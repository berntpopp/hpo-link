"""JSON output schemas for the typed HPO MCP tools (MCP structured output).

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

# Synonyms are polymorphic: compact/sparse -> ["plain string", ...]
# standard/full -> [{text, scope, type, ...}, ...]
_SYNONYM_ITEM = {
    "oneOf": [
        {"type": "string"},
        {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "text": {"type": "string"},
                "scope": {"type": "string"},
            },
        },
    ]
}
_SYNONYMS_ARR = {"type": "array", "items": _SYNONYM_ITEM}

# Response-Envelope Standard v1.1: externally sourced free text is fenced as a
# typed object (kind/text/provenance/raw_sha256), never a bare string, so hosts
# never confuse retrieved HPO prose with instructions.
_UNTRUSTED_TEXT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "untrusted_text"},
        "text": _STR,
        "provenance": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source": _STR,
                "record_id": _STR,
                "retrieved_at": _STR,
            },
        },
        "raw_sha256": _STR,
    },
}
_UNTRUSTED_TEXT_NULL = {"oneOf": [_UNTRUSTED_TEXT, {"type": "null"}]}

CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    capabilities_version=_STR,
    hpo_version=_STR_NULL,
    tools=_ARR,
    response_modes=_ARR,
    error_codes=_ARR,
)

RESOLVE_TERM_SCHEMA = _envelope(
    query=_STR,
    hpo_id=_STR_NULL,
    name=_STR_NULL,
    match_type=_STR_NULL,
    match_confidence={"type": ["number", "null"]},
    obsolete=_BOOL,
    hpo_version=_STR_NULL,
    recommended_citation=_STR_NULL,
)

_SEARCH_HIT = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "hpo_id": _STR,
        "name": _STR,
        "score": {"type": "number"},
        "definition": _UNTRUSTED_TEXT_NULL,
        "definition_snippet": _UNTRUSTED_TEXT,
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
    hpo_version=_STR_NULL,
)

TERM_SCHEMA = _envelope(
    hpo_id=_STR,
    name=_STR,
    definition=_UNTRUSTED_TEXT_NULL,
    synonyms=_SYNONYMS_ARR,
    alt_ids=_ARR,
    subsets=_ARR,
    parents=_ARR,
    children=_ARR,
    obsolete=_BOOL,
    hpo_version=_STR_NULL,
    recommended_citation=_STR_NULL,
)

ANCESTORS_SCHEMA = _envelope(
    hpo_id=_STR,
    name=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    ancestors=_ARR,
    hpo_version=_STR_NULL,
)

DESCENDANTS_SCHEMA = _envelope(
    hpo_id=_STR,
    name=_STR_NULL,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    descendants=_ARR,
    hpo_version=_STR_NULL,
)

PARENTS_SCHEMA = _envelope(
    hpo_id=_STR,
    name=_STR_NULL,
    count=_INT,
    parents=_ARR,
    hpo_version=_STR_NULL,
)

CHILDREN_SCHEMA = _envelope(
    hpo_id=_STR,
    name=_STR_NULL,
    count=_INT,
    children=_ARR,
    hpo_version=_STR_NULL,
)

RESOLVE_XREF_SCHEMA = _envelope(
    xref_id=_STR,
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    matches=_ARR,
    hpo_version=_STR_NULL,
)

CROSS_ONTOLOGY_SCHEMA = _envelope(
    hpo_id=_STR,
    name=_STR_NULL,
    mappings=_OBJ,
    hpo_version=_STR_NULL,
)

ANNOTATION_SCHEMA = _envelope(
    total=_INT,
    returned=_INT,
    limit=_INT,
    offset=_INT,
    next_offset=_INT,
    truncated=_BOOL,
    hpo_version=_STR_NULL,
    recommended_citation=_STR_NULL,
)

DIAGNOSTICS_SCHEMA = _envelope(
    server=_STR,
    index_status=_STR,
    hpo_version=_STR_NULL,
    hpoa_version=_STR_NULL,
    counts=_OBJ,
    build_utc=_STR_NULL,
    freshness=_OBJ,
    latency_slo=_OBJ,
    runtime_metrics=_OBJ,
)
