"""Tests for HPO ontology MCP tools via the service adapter.

Fixture-world facts (from mini_hp.json):
  HP:0000001  All
  HP:0000118  Phenotypic abnormality  (parent of HP:0000478)
  HP:0000478  Abnormality of the eye  (parent of HP:0000479)
  HP:0000479  Abnormal retinal morphology
              exact_synonym: "Abnormal retina"
              related_synonym: "Retinal abnormality"
              xref: UMLS:C0151888
  HP:0000489  obsolete Abnormal electroretinogram
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hpo_link.mcp.service_adapters import reset_services, set_hpo_service


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:  # type: ignore[return]
    """Reset service singleton before AND after every test."""
    reset_services()
    yield
    reset_services()


@pytest.fixture()
def live_hpo_service(built_test_db: Path):  # type: ignore[return]
    """Inject a real HpoService backed by the test SQLite fixture."""
    from hpo_link.data.repository import HpoRepository
    from hpo_link.services.hpo_service import HpoService

    repo = HpoRepository(built_test_db)
    svc = HpoService(repo)
    set_hpo_service(svc)
    yield svc
    repo.close()


# ---------------------------------------------------------------------------
# hpo_resolve_term
# ---------------------------------------------------------------------------


async def test_resolve_term_success(live_hpo_service) -> None:
    """hpo_resolve_term('Phenotypic abnormality') -> payload with hpo_id HP:0000118."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.next_commands import after_resolve_term
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        svc = get_hpo_service()
        payload = svc.resolve_term("Phenotypic abnormality")
        payload.setdefault("_meta", {})["next_commands"] = after_resolve_term(payload)
        return payload

    result = await run_mcp_tool(
        "hpo_resolve_term",
        call,
        context=McpErrorContext("hpo_resolve_term", arguments={"query": "Phenotypic abnormality"}),
    )
    assert result["success"] is True
    assert result["hpo_id"] == "HP:0000118"
    assert "_meta" in result
    assert "next_commands" in result["_meta"]
    assert "hpo_version" in result
    assert "recommended_citation" in result


async def test_resolve_term_not_found(live_hpo_service) -> None:
    """hpo_resolve_term with a bad id returns error envelope with error_code='not_found'."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        svc = get_hpo_service()
        return svc.resolve_term("HP:9999999")  # does not exist

    result = await run_mcp_tool(
        "hpo_resolve_term",
        call,
        context=McpErrorContext("hpo_resolve_term", arguments={"query": "HP:9999999"}),
    )
    assert result["success"] is False
    assert result["error_code"] == "not_found"
    assert "_meta" in result


async def test_resolve_term_empty_query(live_hpo_service) -> None:
    """Empty query returns invalid_input error (not an exception)."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        return get_hpo_service().resolve_term("")

    result = await run_mcp_tool(
        "hpo_resolve_term",
        call,
        context=McpErrorContext("hpo_resolve_term", arguments={"query": ""}),
    )
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"


# ---------------------------------------------------------------------------
# get_server_capabilities
# ---------------------------------------------------------------------------


def test_get_server_capabilities_server_name() -> None:
    """build_capabilities() returns server='hpo-link' and correct tool list."""
    from hpo_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["server"] == "hpo-link"
    assert "hpo_resolve_term" in caps["tools"]
    assert "get_server_capabilities" in caps["tools"]
    assert "_meta" not in caps  # not a tool call — no envelope


# ---------------------------------------------------------------------------
# hpo_get_term
# ---------------------------------------------------------------------------


async def test_get_term_success(live_hpo_service) -> None:
    """hpo_get_term returns hpo_id, name, definition."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.next_commands import after_get_term
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        payload = get_hpo_service().get_term("HP:0000118")
        payload.setdefault("_meta", {})["next_commands"] = after_get_term(payload)
        return payload

    result = await run_mcp_tool(
        "hpo_get_term",
        call,
        context=McpErrorContext("hpo_get_term", arguments={"term": "HP:0000118"}),
    )
    assert result["success"] is True
    assert result["hpo_id"] == "HP:0000118"
    assert "name" in result
    assert "_meta" in result
    assert "next_commands" in result["_meta"]
