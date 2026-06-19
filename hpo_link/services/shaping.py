"""Response-mode projection for HPO term payloads.

``standard`` / ``full`` are the identity (the complete record, with structured
synonyms carrying scope/type/sources). ``compact`` (the default) drops null/empty
values and collapses synonyms to plain strings. ``minimal`` keeps only the
identity anchors (``hpo_id`` + ``name``).
"""

from __future__ import annotations

from typing import Any

RESPONSE_MODES: list[str] = ["minimal", "compact", "standard", "full"]
DEFAULT_RESPONSE_MODE = "compact"

#: Default cap for the compact search snippet (chars). search_terms is the
#: broadest-fan-out tool, so its default page must stay token-cheap: identity +
#: score + a short snippet, with the full definition reserved for standard/full.
SEARCH_SNIPPET_CHARS = 140

_PRESERVE_KEYS: frozenset[str] = frozenset({"_meta", "success"})

#: Identity anchors kept in ``minimal`` mode.
#: hpo_version and recommended_citation are always included per spec.
_MINIMAL_KEEP: frozenset[str] = frozenset(
    {"hpo_id", "name", "hpo_version", "recommended_citation", "_meta"}
)

#: Identity/grounding anchors a sparse fieldset always retains.
_FIELD_ANCHORS: frozenset[str] = frozenset({"hpo_id", "name", "hpo_version", "_meta", "success"})


def _is_empty(value: Any) -> bool:
    """True for the null/empty values compact mode drops."""
    return value is None or value == [] or value == "" or value == {}


#: HPOA "no value" placeholders that annotation-row compact shaping drops as noise
#: (the source TSV uses ``-`` where a value is absent, e.g. an unparseable frequency).
_DROP_SENTINELS: frozenset[str] = frozenset({"-"})


def _plain_synonyms(synonyms: Any) -> list[str]:
    """Collapse a structured-synonym list to de-duplicated plain strings."""
    out: list[str] = []
    seen: set[str] = set()
    for syn in synonyms or []:
        text = syn.get("text") if isinstance(syn, dict) else syn
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def shape_term(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a term record to the requested verbosity.

    - ``minimal``: ``hpo_id`` + ``name`` (and any preserved keys).
    - ``compact``: drop null/empty, collapse synonyms to plain strings,
      truncate definition to snippet.
    - ``standard`` / ``full``: the complete record incl. structured synonyms.
    """
    if mode == "minimal":
        return {k: v for k, v in record.items() if k in _MINIMAL_KEEP}
    if mode in ("standard", "full"):
        return dict(record)
    # compact
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == "synonyms":
            value = _plain_synonyms(value)
        if key == "definition" and isinstance(value, str):
            value = _snippet(value, SEARCH_SNIPPET_CHARS)
        if key not in _PRESERVE_KEYS and _is_empty(value):
            continue
        out[key] = value
    return out


def select_fields(payload: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """Project a payload to a caller-requested sparse fieldset.

    Identity/grounding anchors (``hpo_id``, ``name``, ``hpo_version``, plus the
    preserved ``_meta``/``success``) are always retained. Supports top-level keys
    and ONE level of dotting into a grouped object -- e.g. ``"xrefs.UMLS"`` keeps
    only the UMLS group under ``xrefs``. Unknown fields are skipped (open-world).
    Returns the payload unchanged when ``fields`` is falsy.
    """
    if not fields:
        return payload
    out: dict[str, Any] = {k: v for k, v in payload.items() if k in _FIELD_ANCHORS}
    for field in fields:
        top, _, sub = field.partition(".")
        if sub:
            container = payload.get(top)
            if isinstance(container, dict) and sub in container:
                nested = out.setdefault(top, {})
                if isinstance(nested, dict):
                    nested[sub] = container[sub]
        elif top in payload:
            out[top] = payload[top]
    return out


def shape_annotation_rows(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Project annotation rows (phenotype/gene/disease) to the requested verbosity.

    - ``standard`` / ``full``: rows are returned unchanged (all columns preserved).
    - ``compact`` / ``minimal``: drop keys whose value is null/empty
      (``None``, ``""``, ``[]``, ``{}``) using the ``_is_empty`` predicate.
      ``hpo_id`` and ``name`` are always retained when present.

    Args:
        rows: List of annotation row dicts from the repository.
        mode: One of ``minimal``, ``compact``, ``standard``, ``full``.

    Returns:
        New list of dicts shaped to the requested mode.
    """
    if mode in ("standard", "full"):
        return [dict(r) for r in rows]
    # compact / minimal — drop null/empty values and the HPOA "-" no-data sentinel
    # (e.g. an undecodable raw ``frequency``), which is semantically empty but would
    # otherwise survive as token noise in the token-efficient modes.
    _always_keep: frozenset[str] = frozenset({"hpo_id", "name"})
    shaped: list[dict[str, Any]] = []
    for row in rows:
        out: dict[str, Any] = {}
        for key, value in row.items():
            if key in _always_keep or (not _is_empty(value) and value not in _DROP_SENTINELS):
                out[key] = value
        shaped.append(out)
    return shaped


def _snippet(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars on a word boundary (adds ``…``)."""
    text = " ".join(text.split())  # normalise whitespace runs
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    head, _, _ = cut.rpartition(" ")
    return (head or cut) + "…"


def shape_search_hit(
    hit: dict[str, Any], mode: str, *, snippet_chars: int = SEARCH_SNIPPET_CHARS
) -> dict[str, Any]:
    """Project a search hit, keeping the hot path token-cheap.

    - ``minimal`` / ``compact``: ``{hpo_id, name, score}`` -- compact adds a
      ``definition_snippet`` (truncated to ``snippet_chars``) when a definition
      exists, but never the full paragraph.
    - ``standard`` / ``full``: identity + score + the complete ``definition``.
    """
    out: dict[str, Any] = {
        "hpo_id": hit.get("hpo_id"),
        "name": hit.get("name"),
        "score": hit.get("score"),
    }
    definition = hit.get("definition")
    if mode in ("standard", "full"):
        if definition:
            out["definition"] = definition
    elif mode == "compact" and definition:
        out["definition_snippet"] = _snippet(definition, snippet_chars)
    return out
