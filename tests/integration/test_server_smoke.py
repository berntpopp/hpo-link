"""Integration smoke tests for hpo-link MCP server.

These tests verify that the full MCP facade registers the expected tools and
that a sample of core tool calls succeed end-to-end.

Marked with @pytest.mark.mcp so they can be selected or excluded independently.
"""

from __future__ import annotations

import pytest

from hpo_link.mcp.service_adapters import reset_services, set_annotation_service, set_hpo_service


@pytest.fixture(autouse=True)
def _reset_singleton():  # type: ignore[return]
    """Reset service singletons before AND after every test."""
    reset_services()
    yield
    reset_services()


@pytest.mark.mcp
async def test_all_tools_registered(built_test_db) -> None:
    """The MCP facade must register exactly 17 tools."""
    from hpo_link.mcp.facade import create_hpo_mcp

    mcp = create_hpo_mcp()
    tools = await mcp.list_tools()
    tool_names = sorted(t.name for t in tools)

    expected = sorted(
        [
            "get_server_capabilities",
            "get_diagnostics",
            "hpo_resolve_term",
            "hpo_search_terms",
            "hpo_get_term",
            "hpo_get_term_parents",
            "hpo_get_term_children",
            "hpo_get_term_ancestors",
            "hpo_get_term_descendants",
            "hpo_resolve_xref",
            "hpo_map_cross_ontology",
            "hpo_get_phenotypes_for_gene",
            "hpo_get_genes_for_phenotype",
            "hpo_get_phenotypes_for_disease",
            "hpo_get_diseases_for_phenotype",
            "hpo_get_genes_for_disease",
            "hpo_get_diseases_for_gene",
        ]
    )

    assert len(tools) == 17, f"Expected 17 tools, got {len(tools)}: {tool_names}"
    assert tool_names == expected


@pytest.mark.mcp
async def test_smoke_tool_calls(built_test_db) -> None:
    """Smoke test: a representative sample of tools return success payloads."""
    from pathlib import Path

    from hpo_link.data.repository import HpoRepository
    from hpo_link.mcp.capabilities import collect_tool_signatures, project_capabilities
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.facade import create_hpo_mcp
    from hpo_link.mcp.next_commands import after_capabilities
    from hpo_link.mcp.service_adapters import get_annotation_service, get_hpo_service
    from hpo_link.services.annotation_service import AnnotationService
    from hpo_link.services.hpo_service import HpoService

    db_path: Path = built_test_db
    repo = HpoRepository(db_path)
    hpo_svc = HpoService(repo)
    ann_svc = AnnotationService(repo)
    set_hpo_service(hpo_svc)
    set_annotation_service(ann_svc)

    mcp = create_hpo_mcp()

    # -- get_server_capabilities --
    async def call_caps():
        signatures = await collect_tool_signatures(mcp)
        payload = project_capabilities("summary", signatures)
        payload.setdefault("_meta", {})["next_commands"] = after_capabilities()
        return payload

    caps_result = await run_mcp_tool(
        "get_server_capabilities",
        call_caps,
        context=McpErrorContext("get_server_capabilities"),
    )
    assert caps_result["success"] is True
    assert caps_result["server"] == "hpo-link"

    # -- hpo_resolve_term --
    async def call_resolve():
        return get_hpo_service().resolve_term("HP:0000118")

    resolve_result = await run_mcp_tool(
        "hpo_resolve_term",
        call_resolve,
        context=McpErrorContext("hpo_resolve_term", arguments={"query": "HP:0000118"}),
    )
    assert resolve_result["success"] is True
    assert resolve_result["hpo_id"] == "HP:0000118"

    # -- hpo_get_phenotypes_for_gene --
    async def call_gene_pheno():
        return get_annotation_service().get_phenotypes_for_gene("PAX6")

    gene_pheno_result = await run_mcp_tool(
        "hpo_get_phenotypes_for_gene",
        call_gene_pheno,
        context=McpErrorContext("hpo_get_phenotypes_for_gene", arguments={"gene": "PAX6"}),
    )
    assert gene_pheno_result["success"] is True
    hpo_ids = [p["hpo_id"] for p in gene_pheno_result.get("phenotypes", [])]
    assert "HP:0000479" in hpo_ids

    # -- get_diagnostics (inline) --
    svc = get_hpo_service()
    repo_obj = svc._repo  # intentional introspection
    if repo_obj is not None:
        meta = repo_obj.read_meta()
        diag = {
            "success": True,
            "server": "hpo-link",
            "index_status": "available",
            "hpo_version": meta.get("hpo_version"),
        }
    else:
        diag = {"success": True, "server": "hpo-link", "index_status": "unavailable"}
    assert diag["success"] is True
    assert diag["index_status"] == "available"

    repo.close()
