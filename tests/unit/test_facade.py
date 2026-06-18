"""Tests for create_hpo_mcp() — facade assembly and tool registration."""

from __future__ import annotations

import pytest


EXPECTED_TOOLS = {
    "get_server_capabilities",
    "hpo_resolve_term",
    "hpo_search_terms",
    "hpo_get_term",
    "hpo_get_term_parents",
    "hpo_get_term_children",
    "hpo_get_term_ancestors",
    "hpo_get_term_descendants",
    "hpo_resolve_xref",
    "hpo_map_cross_ontology",
}


async def test_create_hpo_mcp_registers_expected_tools() -> None:
    """create_hpo_mcp() must register exactly the expected tool set."""
    from hpo_link.mcp.facade import create_hpo_mcp

    mcp = create_hpo_mcp()
    tools = await mcp.list_tools()
    registered = {t.name for t in tools}
    assert registered == EXPECTED_TOOLS


async def test_get_server_capabilities_server_name() -> None:
    """get_server_capabilities includes server == 'hpo-link' in capabilities."""
    from hpo_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["server"] == "hpo-link"
    assert set(caps["tools"]) == EXPECTED_TOOLS
