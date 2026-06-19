"""Tests for MCP output schemas in hpo_link.mcp.schemas.

Covers T3.1: TERM_SCHEMA.synonyms must express the polymorphism (string OR
object) via a oneOf in items, reflecting that response_mode changes the shape
of synonyms from plain strings (compact) to {text, scope, ...} objects
(standard/full).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# T3.1 — synonyms schema polymorphism
# ---------------------------------------------------------------------------


def test_term_schema_synonyms_is_array() -> None:
    """TERM_SCHEMA synonyms property must be an array schema."""
    from hpo_link.mcp.schemas import TERM_SCHEMA

    synonyms = TERM_SCHEMA["properties"]["synonyms"]
    assert synonyms.get("type") == "array", "synonyms must have type='array'"


def test_term_schema_synonyms_items_has_oneof() -> None:
    """TERM_SCHEMA synonyms items must use oneOf to express the polymorphism."""
    from hpo_link.mcp.schemas import TERM_SCHEMA

    synonyms = TERM_SCHEMA["properties"]["synonyms"]
    items = synonyms.get("items")
    assert items is not None, "synonyms must have an 'items' schema"
    assert "oneOf" in items, (
        "synonyms items must use 'oneOf' to document the string/object polymorphism"
    )


def test_term_schema_synonyms_oneof_includes_string() -> None:
    """synonyms items oneOf must include a string variant."""
    from hpo_link.mcp.schemas import TERM_SCHEMA

    items = TERM_SCHEMA["properties"]["synonyms"]["items"]
    one_of = items["oneOf"]
    types = [alt.get("type") for alt in one_of]
    assert "string" in types, "synonyms items oneOf must include a string variant (compact mode)"


def test_term_schema_synonyms_oneof_includes_object() -> None:
    """synonyms items oneOf must include an object variant with text property."""
    from hpo_link.mcp.schemas import TERM_SCHEMA

    items = TERM_SCHEMA["properties"]["synonyms"]["items"]
    one_of = items["oneOf"]
    obj_variants = [alt for alt in one_of if alt.get("type") == "object"]
    assert obj_variants, "synonyms items oneOf must include an object variant (standard/full mode)"
    obj = obj_variants[0]
    assert "properties" in obj, "object variant must declare properties"
    assert "text" in obj["properties"], "object variant must have a 'text' property"
    assert "scope" in obj["properties"], "object variant must have a 'scope' property"
