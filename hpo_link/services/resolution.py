"""Resolution cascade: id / xref / label -> canonical MONDO id (+ match provenance).

Extracted from :class:`HpoService` to keep that file within the 500-line gate
and to isolate the conservative fuzzy fallback (see ``decide_fuzzy`` /
``_fuzzy_or_not_found``). One cascade backs both entry points: ``resolve_term_id``
is the id-only view (used where provenance is irrelevant, e.g. ``get_disease``);
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
    WithdrawnEntryError,
)
from hpo_link.identifiers import infer_xref_source, normalize_mondo_id, normalize_xref

if TYPE_CHECKING:
    from hpo_link.data.repository import MondoRepository

#: Maps a lookup ``label_type`` to a resolve ``match_type``.
_LABEL_MATCH_TYPE = {
    "primary": "primary",
    "exact_synonym": "exact_synonym",
    "related_synonym": "related_synonym",
    "broad_synonym": "related_synonym",
    "narrow_synonym": "related_synonym",
}

#: Fuzzy thresholds (tuned against bm25-derived scores; repo.search returns
#: ``score = round(-bm25, 4)`` where higher = more relevant). A near-miss resolves
#: only when the top hit clears an absolute floor AND dominates the runner-up by a
#: factor -- conservative by design so a tie is never silently collapsed.
FUZZY_MIN_SCORE = 0.5
FUZZY_DOMINANCE = 1.5
FUZZY_MAX_CANDIDATES = 5

#: Fuzzy hits are fetched in a larger pool than the candidate cap so the human-disease
#: prior can sink non-human-animal terms out of the candidate window entirely, rather
#: than merely below a thin human head.
FUZZY_SEARCH_POOL = FUZZY_MAX_CANDIDATES * 3

#: Distinctive (>=3-char alphabetic) tokens used to relax a multi-token miss into
#: candidate suggestions (so a query like "ADPKD 1" never dead-ends on a bare 404).
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


def rerank_human_first(hits: list[dict[str, Any]], non_human_ids: set[str]) -> list[dict[str, Any]]:
    """Apply a human-disease prior: sink non-human-animal terms below human terms.

    A query like "Marfan syndrom" must not be led by veterinary terms ("..., pig") that
    score higher in raw FTS. The sort is two-level and STABLE (bm25 order preserved
    within each bucket): relevance first -- a hit clearing ``FUZZY_MIN_SCORE`` outranks
    one below it, so the prior never resurrects an irrelevant hit above a relevant one
    -- then human before non-human. A no-op when nothing in ``hits`` is non-human.
    """
    if not non_human_ids:
        return hits

    def _key(hit: dict[str, Any]) -> tuple[bool, bool]:
        below_floor = float(hit.get("score") or 0.0) < FUZZY_MIN_SCORE
        return (below_floor, hit["mondo_id"] in non_human_ids)

    return sorted(hits, key=_key)


class Resolver:
    """Resolve any id/label/xref to a canonical MONDO id with provenance."""

    def __init__(self, repo: MondoRepository) -> None:
        """Bind the resolver to a read-only Mondo repository."""
        self._repo = repo

    def resolve_term_id(self, term: str) -> str:
        """Resolve any MONDO id / label / xref CURIE to a canonical MONDO id.

        The strict (non-fuzzy) entry point: a free-text miss raises ``NotFoundError``
        (with close-match suggestions) rather than guessing.
        """
        raw = (term or "").strip()
        if not raw:
            raise InvalidInputError(
                "term must be a non-empty MONDO id, label, or xref.", field="term"
            )
        return self.classify_resolution(raw, fuzzy=False)[1]

    def classify_resolution(self, raw: str, *, fuzzy: bool = True) -> tuple[str, str]:
        """Resolve ``raw`` and report how the match was made (``match_type``).

        Cascade: MONDO id (obsolete -> ``WithdrawnEntryError``) -> external xref
        CURIE -> exact label/synonym. A multi-term exact label raises
        ``AmbiguousQueryError``. On an exact-label miss: when ``fuzzy`` is set (the
        ``resolve_disease`` entry) a conservative FTS fallback runs; otherwise (the
        strict ``resolve_term_id`` entry) ``NotFoundError`` is raised. Assumes ``raw``
        is already stripped and non-empty (the public entry points validate).
        """
        mondo_id = normalize_mondo_id(raw)
        if mondo_id:
            record = self._repo.get_term(mondo_id)
            if record is None:
                raise NotFoundError(f"No Mondo term for {mondo_id}.")
            if record["is_obsolete"]:
                raise WithdrawnEntryError(
                    mondo_id, status="obsolete", replaced_by=self._replacement_records(record)
                )
            return "mondo_id", mondo_id
        if infer_xref_source(raw):
            normalized = normalize_xref(raw)
            if normalized:
                matches = self._repo.mondo_for_xref(normalized.upper(), limit=2)
                if matches:
                    return "xref", str(matches[0]["mondo_id"])
                raise NotFoundError(f"No Mondo term cross-references {normalized}.")
        candidates = self._repo.resolve_label(raw.upper())
        if not candidates:
            if fuzzy:
                return self._fuzzy_or_not_found(raw)
            raise self._label_not_found(raw)
        distinct = {c["mondo_id"] for c in candidates}
        if len(distinct) == 1:
            best = candidates[0]
            return _LABEL_MATCH_TYPE.get(best["label_type"], "primary"), str(best["mondo_id"])
        raise AmbiguousQueryError(
            f"'{raw}' matches {len(distinct)} Mondo terms; pick one and call get_disease.",
            candidates=self._label_candidates(candidates),
        )

    def _fuzzy_or_not_found(self, raw: str) -> tuple[str, str]:
        """Exact-label miss: try a conservative FTS-based fuzzy resolution.

        A clear single winner resolves with ``match_type='fuzzy'``; a near-tie
        raises ``AmbiguousQueryError`` with candidates; nothing above the score
        floor raises ``NotFoundError`` (embedding the weak hits as suggestions, so
        the envelope can still chain straight to ``get_disease``).
        """
        hits, _ = self._repo.search(raw, limit=FUZZY_SEARCH_POOL, include_obsolete=False)
        hits = self._demote_non_human(hits)
        kind, payload = decide_fuzzy(hits)
        if kind == "resolve" and isinstance(payload, dict):
            return "fuzzy", str(payload["mondo_id"])
        if kind == "ambiguous" and isinstance(payload, list):
            cands = [
                {"mondo_id": h["mondo_id"], "name": h["name"], "label_type": "fuzzy"}
                for h in payload
            ]
            raise AmbiguousQueryError(
                f"'{raw}' has no exact match; the closest Mondo terms are in candidates.",
                candidates=cands,
            )
        if hits:  # weak (below-floor) hits already in hand -> reuse as suggestions
            raise self._label_not_found(raw, suggestions=_hits_to_suggestions(hits))
        raise self._label_not_found(raw)  # nothing strict -> _search_suggestions relaxes

    def _demote_non_human(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply the human-disease prior to fuzzy hits (no-op when ``<2`` or all human)."""
        if len(hits) < 2:
            return hits
        non_human = self._repo.non_human_animal_ids([h["mondo_id"] for h in hits])
        return rerank_human_first(hits, non_human)

    def _label_not_found(
        self, raw: str, *, suggestions: list[dict[str, Any]] | None = None
    ) -> NotFoundError:
        """Build a not_found for a free-text miss, with close-match suggestions.

        Best practice is to embed the *answer* (top search hits) rather than route
        the client back to the search tool, so the envelope chains to get_disease.
        ``suggestions`` may be supplied by a caller that already ran the search.
        """
        if suggestions is None:
            suggestions = self._search_suggestions(raw)
        if suggestions:
            message = (
                f"No exact Mondo term matches '{raw}'. The closest search hits are in "
                "candidates; open one with get_disease or refine with search_diseases."
            )
        else:
            message = (
                f"No Mondo term matches '{raw}'. Try a MONDO id, a disease label, or an xref CURIE."
            )
        return NotFoundError(message, suggestions=suggestions)

    def _search_suggestions(self, raw: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Close-match suggestions for a failed lookup (id + name + score), best-effort.

        Tries the strict FTS query first; if it finds nothing (a multi-token query
        where the AND/prefix match fails, e.g. "ADPKD 1"), it relaxes to the most
        distinctive single token so the not_found still carries ranked candidates
        rather than dead-ending. Relaxed hits inform *suggestions only* -- they are
        never auto-resolved.
        """
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

    def _replacement_records(self, record: dict[str, Any]) -> list[dict[str, str]]:
        """Build replacement records (replaced_by + consider) for an obsolete term."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        targets: list[str] = []
        replaced_by = record.get("replaced_by")
        if replaced_by:
            targets.append(replaced_by)
        targets.extend(record.get("consider") or [])
        for target in targets:
            canon = normalize_mondo_id(target) or target
            if canon in seen:
                continue
            seen.add(canon)
            successor = self._repo.get_term(canon)
            out.append({"mondo_id": canon, "name": successor["name"] if successor else canon})
        return out

    def _label_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Build de-duplicated ambiguity candidates with names."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for cand in candidates:
            mid = cand["mondo_id"]
            if mid in seen:
                continue
            seen.add(mid)
            term = self._repo.get_term(mid)
            out.append(
                {
                    "mondo_id": mid,
                    "name": term["name"] if term else mid,
                    "label_type": cand["label_type"],
                }
            )
        return out


def _hits_to_suggestions(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project FTS hits to compact ``{mondo_id, name, score}`` suggestion rows."""
    return [
        {"mondo_id": h["mondo_id"], "name": h["name"], "score": h.get("score")} for h in hits[:3]
    ]
