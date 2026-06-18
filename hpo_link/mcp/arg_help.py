"""Argument ergonomics for MCP tools: aliases, did-you-mean, signatures.

Pure functions with no FastMCP dependency so they unit-test in isolation. The
middleware and the discovery surface both consume them, keeping one source of
truth for what a "valid argument" looks like.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable, Mapping
from typing import Any

# Curated synonym -> canonical map, scoped to this server's parameter space. An
# alias only ever resolves to a canonical name that is a *real* parameter of the
# tool being called (see ``normalize_alias_args``), so a shared map is safe.
ARG_ALIASES: dict[str, str] = {
    "disease": "query",
    "term": "query",
    "mondo": "query",
    "mondo_id": "query",
    "label": "query",
    "id": "xref_id",
    "curie": "xref_id",
    "xref": "xref_id",
    "max": "limit",
    "mode": "response_mode",
    "prefix": "prefixes",
}


def normalize_alias_args(
    valid_params: Iterable[str], arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Rewrite known alias keys to their canonical parameter names.

    An alias is applied only when (a) the alias key is present, (b) the canonical
    target is a real parameter of the called tool, and (c) the canonical key is not
    already supplied explicitly. Returns ``(new_arguments, applied_pairs)``.
    """
    valid = set(valid_params)
    result = dict(arguments)
    applied: list[tuple[str, str]] = []
    for alias, canonical in ARG_ALIASES.items():
        if alias in result and canonical in valid:
            if canonical in result:
                result.pop(alias)  # explicit canonical wins; drop the alias
            else:
                result[canonical] = result.pop(alias)
                applied.append((alias, canonical))
    return result, applied


def did_you_mean(unknown: str, valid: Iterable[str]) -> str | None:
    """Best canonical suggestion for an unknown argument name, or ``None``."""
    valid_list = list(valid)
    aliased = ARG_ALIASES.get(unknown)
    if aliased is not None and aliased in valid_list:
        return aliased
    matches = difflib.get_close_matches(unknown, valid_list, n=1, cutoff=0.6)
    return matches[0] if matches else None


def describe_constraints(field_schema: Mapping[str, Any]) -> tuple[list[str], str] | None:
    """Surface a field's enum/range for an invalid-*value* error.

    Returns ``(allowed_values, human_phrase)`` for an ``enum`` or a bounded
    numeric field (digging through ``anyOf``/``allOf``/``oneOf``), or ``None`` for
    a field with no value constraint (so the caller falls back to a name error).
    """
    nodes: list[Any] = [field_schema]
    for key in ("anyOf", "allOf", "oneOf"):
        nodes.extend(field_schema.get(key, []))
    for node in nodes:
        if isinstance(node, Mapping) and node.get("enum"):
            vals = [str(v) for v in node["enum"]]
            return vals, "must be one of: " + ", ".join(vals)
    lo: Any = None
    hi: Any = None
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        lo = node.get("minimum", node.get("exclusiveMinimum", lo))
        hi = node.get("maximum", node.get("exclusiveMaximum", hi))
    if lo is not None or hi is not None:
        lo_s = str(int(lo)) if lo is not None else "?"
        hi_s = str(int(hi)) if hi is not None else "?"
        return [f"{lo_s}..{hi_s}"], f"must be between {lo_s} and {hi_s}"
    min_items: Any = None
    max_items: Any = None
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        min_items = node.get("minItems", min_items)
        max_items = node.get("maxItems", max_items)
    if min_items is not None or max_items is not None:
        lo_s = str(int(min_items)) if min_items is not None else "0"
        hi_s = str(int(max_items)) if max_items is not None else "?"
        return [f"{lo_s}..{hi_s} items"], f"must have between {lo_s} and {hi_s} items"
    return None


#: JSON type -> human phrase ("expects {phrase}") for a type-mismatch error.
_TYPE_PHRASE: dict[str, str] = {
    "array": "an array",
    "string": "a string",
    "integer": "an integer",
    "number": "a number",
    "boolean": "a boolean (true/false)",
    "object": "an object",
}


def _primary_type(field_schema: Mapping[str, Any]) -> tuple[str | None, Mapping[str, Any]]:
    """First non-null JSON type of a field (digging ``anyOf``/``oneOf`` for ``T | None``)."""
    declared = field_schema.get("type")
    if isinstance(declared, str) and declared != "null":
        return declared, field_schema
    for key in ("anyOf", "oneOf", "allOf"):
        for node in field_schema.get(key, []):
            if isinstance(node, Mapping):
                node_type = node.get("type")
                if isinstance(node_type, str) and node_type != "null":
                    return node_type, node
    return None, field_schema


def _first_example(field_schema: Mapping[str, Any]) -> Any:
    """A representative ``examples[0]`` from the field (or its ``anyOf`` branches)."""
    examples = field_schema.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]
    for key in ("anyOf", "oneOf", "allOf"):
        for node in field_schema.get(key, []):
            if isinstance(node, Mapping):
                branch = node.get("examples")
                if isinstance(branch, list) and branch:
                    return branch[0]
    return None


def describe_type_expectation(field_schema: Mapping[str, Any]) -> tuple[list[str], str] | None:
    """Expected JSON type (+ a concrete example) for a wrong-*type* error on a known arg.

    Reserved for the case where the argument name is valid but its value has the
    wrong type and no enum/range constraint applies (see :func:`describe_constraints`).
    Returns ``(allowed, human_phrase)`` where ``allowed`` carries the shape/example --
    NOT the list of argument names -- so the envelope never conflates a bad value with
    an unknown argument. ``None`` when no JSON type can be determined.
    """
    json_type, node = _primary_type(field_schema)
    if json_type is None:
        return None
    phrase = _TYPE_PHRASE.get(json_type, f"a {json_type}")
    if json_type == "array":
        items = node.get("items")
        item_type = items.get("type") if isinstance(items, Mapping) else None
        if isinstance(item_type, str):
            phrase = f"an array of {item_type}s"
    example = _first_example(field_schema)
    if example is not None:
        rendered = json.dumps(example)
        return [rendered], f"expects {phrase}, e.g. {rendered}"
    return [json_type], f"expects {phrase}"


def tool_signature(name: str, schema: Mapping[str, Any]) -> str:
    """Render ``name(req, opt=, ...)`` from a JSON input schema."""
    props = list(schema.get("properties", {}).keys())
    required = set(schema.get("required") or [])
    parts = [p for p in props if p in required]
    parts += [f"{p}=" for p in props if p not in required]
    return f"{name}(" + ", ".join(parts) + ")"
