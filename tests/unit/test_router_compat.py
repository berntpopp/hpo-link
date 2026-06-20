"""Router-compatibility tests for FastMCP argument schemas and middleware."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hpo_link.mcp.service_adapters import reset_services, set_annotation_service, set_hpo_service


@pytest.fixture()
def router_mcp(built_test_db: Path) -> Iterator[Any]:
    """Return a fully registered FastMCP facade backed by the fixture DB."""
    from hpo_link.data.repository import HpoRepository
    from hpo_link.mcp.facade import create_hpo_mcp
    from hpo_link.services.annotation_service import AnnotationService
    from hpo_link.services.hpo_service import HpoService

    reset_services()
    repo = HpoRepository(built_test_db)
    set_hpo_service(HpoService(repo))
    set_annotation_service(AnnotationService(repo))
    try:
        yield create_hpo_mcp()
    finally:
        repo.close()
        reset_services()


async def test_post_resolve_tool_schemas_expose_hpo_id(router_mcp: Any) -> None:
    """Post-resolve tools must advertise canonical hpo_id at the FastMCP schema boundary."""
    tool_names = {
        "get_term",
        "get_term_parents",
        "get_term_children",
        "get_term_ancestors",
        "get_term_descendants",
        "get_genes_for_phenotype",
        "get_diseases_for_phenotype",
        "map_cross_ontology",
    }
    tools = {tool.name: tool for tool in await router_mcp.list_tools()}

    for name in tool_names:
        properties = tools[name].parameters["properties"]
        assert "hpo_id" in properties, f"{name} must expose hpo_id"


@pytest.mark.parametrize(
    ("tool_name", "arguments", "result_key"),
    [
        ("get_term", {"hpo_id": "HP:0000479"}, "name"),
        ("get_term_parents", {"hpo_id": "HP:0000479"}, "parents"),
        ("get_term_children", {"hpo_id": "HP:0000478"}, "children"),
        ("get_term_ancestors", {"hpo_id": "HP:0000479"}, "ancestors"),
        ("get_term_descendants", {"hpo_id": "HP:0000118"}, "descendants"),
        ("get_genes_for_phenotype", {"hpo_id": "HP:0000479"}, "genes"),
        ("get_diseases_for_phenotype", {"hpo_id": "HP:0000479"}, "diseases"),
        ("map_cross_ontology", {"hpo_id": "HP:0000479"}, "mappings"),
    ],
)
async def test_post_resolve_tools_accept_hpo_id_via_fastmcp(
    router_mcp: Any, tool_name: str, arguments: dict[str, Any], result_key: str
) -> None:
    """FastMCP calls using hpo_id must bind and reach the tool body."""
    result = await router_mcp.call_tool(tool_name, arguments)
    payload = result.structured_content

    assert payload is not None
    assert payload["success"] is True
    assert payload["hpo_id"] == arguments["hpo_id"]
    assert result_key in payload


async def test_map_cross_ontology_fields_projects_mapping_groups(router_mcp: Any) -> None:
    """map_cross_ontology(fields=...) must keep identity anchors and dotted mapping groups."""
    result = await router_mcp.call_tool(
        "map_cross_ontology",
        {
            "term": "HP:0000479",
            "fields": ["mappings.UMLS"],
            "response_mode": "compact",
        },
    )
    payload = result.structured_content

    assert payload is not None
    assert payload["success"] is True
    assert set(payload) >= {"hpo_id", "name", "hpo_version", "mappings", "_meta", "success"}
    assert payload["mappings"] == {"UMLS": [{"object_id": "C0151888", "origin": "obo_xref"}]}


@pytest.mark.parametrize(
    ("arguments", "field"),
    [
        ({"limit": "many"}, "query"),
        ({"query": "retina", "limit": "many"}, "limit"),
    ],
)
@pytest.mark.parametrize(
    ("response_mode", "expected_keys", "forbidden_keys"),
    [
        (
            "minimal",
            {"tool", "request_id"},
            {"next_commands", "capabilities_version", "elapsed_ms"},
        ),
        (
            "compact",
            {"tool", "request_id", "next_commands", "capabilities_version"},
            {"elapsed_ms"},
        ),
        (
            "standard",
            {"tool", "request_id", "next_commands", "capabilities_version", "elapsed_ms"},
            set(),
        ),
    ],
)
async def test_middleware_argument_errors_shape_meta_by_response_mode(
    router_mcp: Any,
    arguments: dict[str, Any],
    field: str,
    response_mode: str,
    expected_keys: set[str],
    forbidden_keys: set[str],
) -> None:
    """FastMCP argument-binding errors must preserve the normal _meta mode contract."""
    call_args = {**arguments, "response_mode": response_mode}
    result = await router_mcp.call_tool(
        "search_terms",
        call_args,
    )
    payload = result.structured_content

    assert payload is not None
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_input"
    assert payload["field"] == field
    meta = payload["_meta"]
    assert expected_keys <= set(meta)
    assert forbidden_keys.isdisjoint(meta)
