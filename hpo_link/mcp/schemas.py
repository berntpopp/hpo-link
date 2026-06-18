"""JSON output schemas for the typed Mondo MCP tools (MCP structured output).

The schemas are deliberately **permissive** (``additionalProperties: true``,
nothing ``required``) because ``response_mode`` projects fields out and the error
envelope is returned by the same tool body and must also validate.
"""

from __future__ import annotations

from typing import Any

_META = {"type": "object", "additionalProperties": True}


def _envelope(**properties: Any) -> dict[str, Any]:
    """A permissive object schema carrying the common envelope keys + extras."""
    props: dict[str, Any] = {
        "success": {"type": "boolean"},
        "_meta": _META,
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "recovery_action": {"type": "string"},
        "field": {"type": "string"},
        "allowed_values": {"type": "array"},
        "hint": {"type": "string"},
        "candidates": {"type": "array"},
        **properties,
    }
    return {"type": "object", "additionalProperties": True, "properties": props}


_STR = {"type": "string"}
_STR_NULL = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_ARR = {"type": "array"}
_ARR_NULL = {"type": ["array", "null"]}
_OBJ = {"type": "object", "additionalProperties": True}

#: One cross-reference target within a prefix group: ONE entry per object_id. The
#: primary ``predicate``/``origin`` are the strongest mapping's; ``predicates`` lists
#: all of them (strongest-first) only when a target is asserted more than once;
#: ``name`` is the target term's label (SSSOM only) when known; ``source`` (the
#: mapping justification) is present only when non-null.
_XREF_ENTRY = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "object_id": _STR,
        "name": _STR,
        "predicate": _STR,
        "predicates": _ARR,
        "origin": _STR,
        "source": _STR_NULL,
    },
}

#: Cross-references grouped by target prefix: ``{"OMIM": [entry, ...], ...}``.
#: Declared as an object (NOT an array) so the grouped payload validates against
#: its own schema -- the historical leak was declaring this shape as ``array``.
_GROUPED_XREFS = {
    "type": "object",
    "additionalProperties": {"type": "array", "items": _XREF_ENTRY},
}

CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    capabilities_version=_STR,
    mondo_version=_STR,
    tools=_ARR,
    response_modes=_ARR,
    error_codes=_ARR,
)

DIAGNOSTICS_SCHEMA = _envelope(
    data_available=_BOOL,
    mondo_version=_STR_NULL,
    term_count=_INT,
    obsolete_count=_INT,
    xref_count=_INT,
    mapping_count=_INT,
    schema_version=_INT,
    built_utc=_STR,
    build=_OBJ,
    runtime=_OBJ,
)

RESOLVE_DISEASE_SCHEMA = _envelope(
    query=_STR,
    mondo_id=_STR_NULL,
    name=_STR_NULL,
    definition=_STR_NULL,
    match_type=_STR_NULL,
    obsolete=_BOOL,
    mondo_version=_STR_NULL,
)

_SEARCH_HIT = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "mondo_id": _STR,
        "name": _STR,
        "score": {"type": "number"},
        "definition": _STR_NULL,
        "definition_snippet": _STR,
    },
}

SEARCH_SCHEMA = _envelope(
    query=_STR,
    include_obsolete=_BOOL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    results={"type": "array", "items": _SEARCH_HIT},
)

DISEASE_SCHEMA = _envelope(
    mondo_id=_STR,
    name=_STR,
    definition=_STR_NULL,
    synonyms=_ARR,
    xrefs=_GROUPED_XREFS,
    parents=_ARR,
    children=_ARR,
    top_groupings=_ARR,
    subsets=_ARR,
    obsolete=_BOOL,
    match_type=_STR_NULL,
    mondo_version=_STR_NULL,
)

ANCESTORS_SCHEMA = _envelope(
    mondo_id=_STR,
    name=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    ancestors=_ARR,
)

DESCENDANTS_SCHEMA = _envelope(
    mondo_id=_STR,
    name=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    descendants=_ARR,
)

PARENTS_SCHEMA = _envelope(
    mondo_id=_STR,
    name=_STR_NULL,
    count=_INT,
    parents=_ARR,
)

CHILDREN_SCHEMA = _envelope(
    mondo_id=_STR,
    name=_STR_NULL,
    count=_INT,
    children=_ARR,
)

RESOLVE_XREF_SCHEMA = _envelope(
    xref_id=_STR,
    normalized=_STR_NULL,
    prefix=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    matches=_ARR,
)

CROSS_ONTOLOGY_SCHEMA = _envelope(
    mondo_id=_STR,
    name=_STR_NULL,
    mappings=_GROUPED_XREFS,
    count=_INT,
    prefixes_filter=_ARR_NULL,
    mondo_version=_STR_NULL,
)

#: One result row in a batch response: either a resolved/fetched record (``ok``
#: true, plus the single-tool keys) or a per-item failure (``ok`` false, with its
#: own ``error_code``/``message``). Permissive (``additionalProperties: true``) so
#: a record's projected fields -- including a grouped ``xrefs`` object -- validate.
_BATCH_ITEM = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "query": _STR,
        "term": _STR,
        "ok": _BOOL,
        "mondo_id": _STR_NULL,
        "name": _STR_NULL,
        "match_type": _STR_NULL,
        "error_code": _STR,
        "message": _STR,
    },
}

BATCH_RESOLVE_SCHEMA = _envelope(
    count=_INT,
    results={"type": "array", "items": _BATCH_ITEM},
)

BATCH_DISEASE_SCHEMA = _envelope(
    count=_INT,
    results={"type": "array", "items": _BATCH_ITEM},
)
