"""Resolution cascade: id / xref / label -> canonical HPO id (+ match provenance).

Extracted from :class:`HpoService` to keep that file within the 500-line gate
and to isolate the conservative fuzzy fallback (see ``decide_fuzzy`` /
``_fuzzy_or_not_found``). One cascade backs both entry points: ``resolve_term_id``
is the id-only view (used where provenance is irrelevant, e.g. ``get_term``);
``classify_resolution`` additionally reports how the match was made (``match_type``)
and -- when enabled -- attempts a fuzzy resolve before giving up.

Returns plain data / raises typed exceptions; the MCP envelope owns error shaping.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from hpo_link.exceptions import (
    AmbiguousQueryError,
    InvalidInputError,
    NotFoundError,
)
from hpo_link.identifiers import normalize_hpo_id

if TYPE_CHECKING:
    from hpo_link.data.repository import HpoRepository

#: Maps a lookup ``label_type`` to a resolve ``match_type``.
_LABEL_MATCH_TYPE: dict[str, str] = {
    "primary": "primary",
    "exact_synonym": "exact_synonym",
    "related_synonym": "related_synonym",
    "broad_synonym": "related_synonym",
    "narrow_synonym": "related_synonym",
    "alt_id": "alt_id",
}

#: Deterministic confidence by match_type. Exact identity lookups (id / primary
#: label / alt_id) are 1.0; an exact synonym is near-certain; an xref reverse-map
#: slightly less; a related synonym weaker; a fuzzy FTS fallback is the floor. The
#: numeric form lets a consumer threshold programmatically (match_type is the
#: qualitative twin).
MATCH_CONFIDENCE: dict[str, float] = {
    "hpo_id": 1.0,
    "primary": 1.0,
    "alt_id": 1.0,
    "exact_synonym": 0.95,
    "xref": 0.9,
    "related_synonym": 0.8,
    "fuzzy": 0.6,
}


def confidence_for(match_type: str) -> float:
    """Numeric confidence in [0, 1] for a resolve match_type (conservative default)."""
    return MATCH_CONFIDENCE.get(match_type, 0.6)


#: Fuzzy thresholds (tuned against bm25-derived scores; repo.search returns
#: ``score = round(-bm25, 4)`` where higher = more relevant). A near-miss resolves
#: only when the top hit clears an absolute floor AND dominates the runner-up by a
#: factor -- conservative by design so a tie is never silently collapsed.
FUZZY_MIN_SCORE = 0.5
FUZZY_DOMINANCE = 1.5
FUZZY_MAX_CANDIDATES = 5

#: Fuzzy hits are fetched in a larger pool than the candidate cap so the prior
#: can sink less-relevant terms out of the candidate window entirely.
FUZZY_SEARCH_POOL = FUZZY_MAX_CANDIDATES * 3

#: Distinctive (>=3-char alphabetic) tokens used to relax a multi-token miss into
#: candidate suggestions (so a query like "HP 479" never dead-ends on a bare 404).
_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")


def decide_fuzzy(
    hits: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | list[dict[str, Any]] | None]:
    """Classify FTS hits into a fuzzy decision.

    Returns ``("resolve", top_hit)`` for a clear winner, ``("ambiguous", candidates)``
    when the runner-up is within ``FUZZY_DOMINANCE`` of the top, or ``("none", None)``
    when nothing clears ``FUZZY_MIN_SCORE``. Conservative by design: never returns a
    winner on a near-tie, so a wrong term is never silently substituted.
    """
    if not hits:
        return ("none", None)
    top = hits[0]
    top_score = float(top.get("score") or 0.0)
    if top_score < FUZZY_MIN_SCORE:
        return ("none", None)
    if len(hits) == 1:
        return ("resolve", top)
    second = float(hits[1].get("score") or 0.0)
    if second <= 0.0 or top_score >= FUZZY_DOMINANCE * second:
        return ("resolve", top)
    return ("ambiguous", hits[:FUZZY_MAX_CANDIDATES])


class Resolver:
    """Resolve any id/label/xref to a canonical HPO id with provenance."""

    def __init__(self, repo: HpoRepository) -> None:
        """Bind the resolver to a read-only HPO repository."""
        self._repo = repo

    def resolve_term_id(self, term: str) -> str:
        """Resolve any HP id / label / xref CURIE to a canonical HP id.

        The strict (non-fuzzy) entry point: a free-text miss raises ``NotFoundError``
        (with close-match suggestions) rather than guessing.
        """
        raw = (term or "").strip()
        if not raw:
            raise InvalidInputError("term must be a non-empty HP id, label, or xref.", field="term")
        return self.classify_resolution(raw, fuzzy=False)[1]

    def classify_resolution(self, raw: str, *, fuzzy: bool = True) -> tuple[str, str]:
        """Resolve ``raw`` and report how the match was made (``match_type``).

        Cascade:
        1. HP id -> direct lookup (returns obsolete terms too, obsolete flag is data)
        2. exact label/synonym -> label table lookup
        3. external xref CURIE -> xref reverse lookup
        4. fuzzy FTS (when enabled)

        A multi-term exact label raises ``AmbiguousQueryError``. On an exact-label
        miss: when ``fuzzy`` is set (the ``resolve_term`` entry) a conservative FTS
        fallback runs; otherwise (the strict ``resolve_term_id`` entry)
        ``NotFoundError`` is raised. Assumes ``raw`` is already stripped and
        non-empty (the public entry points validate).
        """
        # Step 1: canonical HP id (primary lookup)
        hpo_id = normalize_hpo_id(raw)
        if hpo_id:
            record = self._repo.get_term(hpo_id)
            if record is not None:
                return "hpo_id", hpo_id
            # Not a primary id — may be an alt_id; fall through to label lookup.

        # Step 2: exact label / synonym
        candidates = self._repo.resolve_label(raw.upper())
        if candidates:
            distinct = {c["hpo_id"] for c in candidates}
            if len(distinct) == 1:
                best = candidates[0]
                match_type = _LABEL_MATCH_TYPE.get(best["label_type"], "primary")
                return match_type, str(best["hpo_id"])
            raise AmbiguousQueryError(
                f"'{raw}' matches {len(distinct)} HPO terms; pick one and call get_term.",
                candidates=self._label_candidates(candidates),
            )

        # Step 3: external xref CURIE
        if ":" in raw:
            matches = self._repo.hpo_for_xref(raw, limit=2, offset=0)
            if matches:
                return "xref", str(matches[0]["hpo_id"])

        # Step 4: fuzzy FTS fallback
        if fuzzy:
            return self._fuzzy_or_not_found(raw)
        raise self._label_not_found(raw)

    def _fuzzy_or_not_found(self, raw: str) -> tuple[str, str]:
        """Exact-label miss: try a conservative FTS-based fuzzy resolution.

        A clear single winner resolves with ``match_type='fuzzy'``; a near-tie
        raises ``AmbiguousQueryError`` with candidates; nothing above the score
        floor raises ``NotFoundError`` (embedding the weak hits as suggestions, so
        the envelope can still chain straight to ``get_term``).
        """
        hits, _ = self._repo.search(raw, limit=FUZZY_SEARCH_POOL, include_obsolete=False)
        kind, payload = decide_fuzzy(hits)
        if kind == "resolve" and isinstance(payload, dict):
            return "fuzzy", str(payload["hpo_id"])
        if kind == "ambiguous" and isinstance(payload, list):
            cands = [
                {"hpo_id": h["hpo_id"], "name": h["name"], "label_type": "fuzzy"} for h in payload
            ]
            raise AmbiguousQueryError(
                f"'{raw}' has no exact match; the closest HPO terms are in candidates.",
                candidates=cands,
            )
        if hits:  # weak (below-floor) hits already in hand -> reuse as suggestions
            raise self._label_not_found(raw, suggestions=_hits_to_suggestions(hits))
        raise self._label_not_found(raw)  # nothing strict -> _search_suggestions relaxes

    def _label_not_found(
        self, raw: str, *, suggestions: list[dict[str, Any]] | None = None
    ) -> NotFoundError:
        """Build a not_found for a free-text miss, with close-match suggestions."""
        if suggestions is None:
            suggestions = self._search_suggestions(raw)
        if suggestions:
            message = (
                f"No exact HPO term matches '{raw}'. The closest search hits are in "
                "candidates; open one with get_term or refine with search_terms."
            )
        else:
            message = (
                f"No HPO term matches '{raw}'. Try an HP id, a phenotype label, or an xref CURIE."
            )
        return NotFoundError(message, suggestions=suggestions)

    def _search_suggestions(self, raw: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Close-match suggestions for a failed lookup (id + name + score), best-effort."""
        hits = self._safe_search(raw, limit)
        if not hits:
            for token in sorted(set(_TOKEN_RE.findall(raw)), key=len, reverse=True):
                hits = self._safe_search(token, limit)
                if hits:
                    break
        return _hits_to_suggestions(hits)

    def _safe_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Run an FTS search, returning [] on any failure (never mask the not_found)."""
        try:
            hits, _ = self._repo.search(query, limit=limit, include_obsolete=False)
        except Exception:  # pragma: no cover - defensive
            return []
        return hits

    def _label_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Build de-duplicated ambiguity candidates with names."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for cand in candidates:
            hid = cand["hpo_id"]
            if hid in seen:
                continue
            seen.add(hid)
            term = self._repo.get_term(hid)
            out.append(
                {
                    "hpo_id": hid,
                    "name": term["name"] if term else hid,
                    "label_type": cand["label_type"],
                }
            )
        return out


def _hits_to_suggestions(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project FTS hits to compact ``{hpo_id, name, score}`` suggestion rows."""
    return [{"hpo_id": h["hpo_id"], "name": h["name"], "score": h.get("score")} for h in hits[:3]]
