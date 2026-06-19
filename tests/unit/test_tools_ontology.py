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
# resolve_term
# ---------------------------------------------------------------------------


async def test_resolve_term_success(live_hpo_service) -> None:
    """resolve_term('Phenotypic abnormality') -> payload with hpo_id HP:0000118."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.next_commands import after_resolve_term
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        svc = get_hpo_service()
        payload = svc.resolve_term("Phenotypic abnormality")
        payload.setdefault("_meta", {})["next_commands"] = after_resolve_term(payload)
        return payload

    result = await run_mcp_tool(
        "resolve_term",
        call,
        context=McpErrorContext("resolve_term", arguments={"query": "Phenotypic abnormality"}),
    )
    assert result["success"] is True
    assert result["hpo_id"] == "HP:0000118"
    assert "_meta" in result
    assert "next_commands" in result["_meta"]
    assert "hpo_version" in result
    assert "recommended_citation" in result


async def test_resolve_term_not_found(live_hpo_service) -> None:
    """resolve_term with a bad id returns error envelope with error_code='not_found'."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        svc = get_hpo_service()
        return svc.resolve_term("HP:9999999")  # does not exist

    result = await run_mcp_tool(
        "resolve_term",
        call,
        context=McpErrorContext("resolve_term", arguments={"query": "HP:9999999"}),
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
        "resolve_term",
        call,
        context=McpErrorContext("resolve_term", arguments={"query": ""}),
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
    assert "resolve_term" in caps["tools"]
    assert "get_server_capabilities" in caps["tools"]
    assert "_meta" not in caps  # not a tool call — no envelope


# ---------------------------------------------------------------------------
# get_term
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T1.1 — absent-entity contract in capabilities
# ---------------------------------------------------------------------------


def test_capabilities_has_absent_entity_contract_key() -> None:
    """build_capabilities() must include 'absent_entity_contract' key."""
    from hpo_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert "absent_entity_contract" in caps, (
        "'absent_entity_contract' key missing from capabilities payload"
    )


def test_capabilities_absent_entity_contract_text_mentions_invalid_input() -> None:
    """absent_entity_contract text must mention 'invalid_input'."""
    from hpo_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    text = caps["absent_entity_contract"]
    assert "invalid_input" in text, "absent_entity_contract must mention 'invalid_input'"


def test_capabilities_absent_entity_contract_text_mentions_not_found() -> None:
    """absent_entity_contract text must mention 'not_found'."""
    from hpo_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    text = caps["absent_entity_contract"]
    assert "not_found" in text, "absent_entity_contract must mention 'not_found'"


def test_capabilities_summary_includes_absent_entity_contract() -> None:
    """project_capabilities summary projection must include absent_entity_contract."""
    from hpo_link.mcp.capabilities import project_capabilities

    summary = project_capabilities("summary")
    assert "absent_entity_contract" in summary, (
        "'absent_entity_contract' must appear in the summary projection "
        "(it must be in _SUMMARY_KEYS)"
    )


# ---------------------------------------------------------------------------
# T3.3 — resolve_term example CURIE resolves against the test fixture
# ---------------------------------------------------------------------------


def test_resolve_term_example_curie_in_description_resolves(live_hpo_service) -> None:  # type: ignore[return]
    """The CURIE mentioned in the resolve_term description resolves to a real HPO term.

    The fixture includes UMLS:C0151888 -> HP:0000479 (Abnormal retinal morphology).
    We confirm the xref lookup works so the example is not a dead link.
    """
    from hpo_link.services.hpo_service import HpoService

    svc: HpoService = live_hpo_service
    result = svc.resolve_xref("UMLS:C0151888")
    assert result["total"] >= 1, "UMLS:C0151888 should resolve to at least one HPO term"
    hpo_ids = [m["hpo_id"] for m in result["matches"]]
    assert "HP:0000479" in hpo_ids, (
        "UMLS:C0151888 should map to HP:0000479 (Abnormal retinal morphology)"
    )


def test_resolve_term_description_does_not_use_broken_snomed_curie() -> None:
    """The resolve_term description must NOT use SNOMEDCT_US:193046000 (known broken)."""
    import inspect

    from hpo_link.mcp.tools.ontology import register_ontology_tools

    src = inspect.getsource(register_ontology_tools)
    assert "SNOMEDCT_US:193046000" not in src, (
        "SNOMEDCT_US:193046000 is a broken example — it should have been replaced"
    )


def test_broken_snomed_curie_absent_from_all_client_surfaces() -> None:
    """The broken example CURIE must not reach clients via ANY discovery surface.

    I-7's intent is that no dead example reaches a client; the CURIE shipped in
    four surfaces, not just the resolve_term description.
    """
    import json

    from hpo_link.mcp.capabilities import build_capabilities
    from hpo_link.mcp.resources import HPO_SERVER_INSTRUCTIONS
    from hpo_link.mcp.tools._common import XrefIdStr

    broken = "SNOMEDCT_US:193046000"
    assert broken not in HPO_SERVER_INSTRUCTIONS, "stale CURIE in server instructions"
    assert broken not in json.dumps(build_capabilities()), "stale CURIE in capabilities"
    xref_meta = XrefIdStr.__metadata__[0]
    assert broken not in str(getattr(xref_meta, "examples", "")), "stale CURIE in xref examples"
    assert broken not in (getattr(xref_meta, "description", "") or ""), "stale CURIE in xref desc"


# ---------------------------------------------------------------------------
# get_term
# ---------------------------------------------------------------------------


async def test_get_term_success(live_hpo_service) -> None:
    """get_term returns hpo_id, name, definition."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.next_commands import after_get_term
    from hpo_link.mcp.service_adapters import get_hpo_service

    async def call():
        payload = get_hpo_service().get_term("HP:0000118")
        payload.setdefault("_meta", {})["next_commands"] = after_get_term(payload)
        return payload

    result = await run_mcp_tool(
        "get_term",
        call,
        context=McpErrorContext("get_term", arguments={"term": "HP:0000118"}),
    )
    assert result["success"] is True
    assert result["hpo_id"] == "HP:0000118"
    assert "name" in result
    assert "_meta" in result
    assert "next_commands" in result["_meta"]
