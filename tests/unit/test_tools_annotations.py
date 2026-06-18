"""Tests for HPO annotation MCP tools via the service adapter.

Fixture-world facts (from mini fixtures):
  Gene:    PAX6  (NCBIGene:5080)
  Disease: OMIM:106210  (Aniridia)
  Phenotype annotated to PAX6 and OMIM:106210: HP:0000479 (Abnormal retinal morphology)
  HP:0000118 (Phenotypic abnormality) is a root term, ancestor of HP:0000479
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hpo_link.mcp.service_adapters import reset_services, set_annotation_service, set_hpo_service


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:  # type: ignore[return]
    """Reset service singletons before AND after every test."""
    reset_services()
    yield
    reset_services()


@pytest.fixture()
def live_annotation_service(built_test_db: Path):  # type: ignore[return]
    """Inject a real AnnotationService backed by the test SQLite fixture."""
    from hpo_link.data.repository import HpoRepository
    from hpo_link.services.annotation_service import AnnotationService

    repo = HpoRepository(built_test_db)
    svc = AnnotationService(repo)
    set_annotation_service(svc)
    yield svc
    repo.close()


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
# hpo_get_phenotypes_for_gene
# ---------------------------------------------------------------------------


async def test_get_phenotypes_for_gene_pax6(live_annotation_service) -> None:
    """get_phenotypes_for_gene('PAX6') -> success, HP:0000479 in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.next_commands import cmd
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        payload = get_annotation_service().get_phenotypes_for_gene("PAX6")
        phenotypes = payload.get("phenotypes", [])
        steps = [cmd("hpo_get_diseases_for_gene", gene="PAX6")]
        if phenotypes and phenotypes[0].get("hpo_id"):
            steps.append(cmd("hpo_get_term", term=phenotypes[0]["hpo_id"]))
        payload.setdefault("_meta", {})["next_commands"] = steps
        return payload

    result = await run_mcp_tool(
        "hpo_get_phenotypes_for_gene",
        call,
        context=McpErrorContext("hpo_get_phenotypes_for_gene", arguments={"gene": "PAX6"}),
    )
    assert result["success"] is True
    assert "_meta" in result
    assert "next_commands" in result["_meta"]
    assert "hpo_version" in result
    hpo_ids = [p["hpo_id"] for p in result.get("phenotypes", [])]
    assert "HP:0000479" in hpo_ids


async def test_get_phenotypes_for_gene_bad_gene(live_annotation_service) -> None:
    """get_phenotypes_for_gene with unknown gene -> error_code='not_found'."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        return get_annotation_service().get_phenotypes_for_gene("NOTAREALGENE99999")

    result = await run_mcp_tool(
        "hpo_get_phenotypes_for_gene",
        call,
        context=McpErrorContext(
            "hpo_get_phenotypes_for_gene", arguments={"gene": "NOTAREALGENE99999"}
        ),
    )
    assert result["success"] is False
    assert result["error_code"] == "not_found"
    assert "_meta" in result


# ---------------------------------------------------------------------------
# hpo_get_genes_for_phenotype
# ---------------------------------------------------------------------------


async def test_get_genes_for_phenotype_with_descendants(live_annotation_service) -> None:
    """get_genes_for_phenotype('HP:0000118', include_descendants=True) -> PAX6 in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        payload = get_annotation_service().get_genes_for_phenotype(
            "HP:0000118", include_descendants=True
        )
        payload.setdefault("_meta", {})["next_commands"] = []
        return payload

    result = await run_mcp_tool(
        "hpo_get_genes_for_phenotype",
        call,
        context=McpErrorContext("hpo_get_genes_for_phenotype", arguments={"term": "HP:0000118"}),
    )
    assert result["success"] is True
    gene_symbols = [g["gene_symbol"] for g in result.get("genes", []) if "gene_symbol" in g]
    assert "PAX6" in gene_symbols


async def test_get_genes_for_phenotype_no_descendants(live_annotation_service) -> None:
    """get_genes_for_phenotype('HP:0000118', include_descendants=False) -> PAX6 NOT in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    # HP:0000118 is an ancestor of HP:0000479 (which is annotated to PAX6),
    # but not directly annotated to PAX6 itself — so without descendants, PAX6 should not appear.
    async def call():
        return get_annotation_service().get_genes_for_phenotype(
            "HP:0000118", include_descendants=False
        )

    result = await run_mcp_tool(
        "hpo_get_genes_for_phenotype",
        call,
        context=McpErrorContext("hpo_get_genes_for_phenotype", arguments={"term": "HP:0000118"}),
    )
    # Either not_found (no direct annotations) or success with PAX6 absent
    if result["success"]:
        gene_symbols = [g["gene_symbol"] for g in result.get("genes", []) if "gene_symbol" in g]
        assert "PAX6" not in gene_symbols
    else:
        assert result["error_code"] in ("not_found", "data_unavailable")


# ---------------------------------------------------------------------------
# hpo_get_phenotypes_for_disease
# ---------------------------------------------------------------------------


async def test_get_phenotypes_for_disease(live_annotation_service) -> None:
    """get_phenotypes_for_disease('OMIM:106210') -> success, HP:0000479 in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        payload = get_annotation_service().get_phenotypes_for_disease("OMIM:106210")
        payload.setdefault("_meta", {})["next_commands"] = []
        return payload

    result = await run_mcp_tool(
        "hpo_get_phenotypes_for_disease",
        call,
        context=McpErrorContext(
            "hpo_get_phenotypes_for_disease", arguments={"disease_id": "OMIM:106210"}
        ),
    )
    assert result["success"] is True
    hpo_ids = [p["hpo_id"] for p in result.get("phenotypes", [])]
    assert "HP:0000479" in hpo_ids


# ---------------------------------------------------------------------------
# hpo_get_diseases_for_phenotype
# ---------------------------------------------------------------------------


async def test_get_diseases_for_phenotype(live_annotation_service) -> None:
    """get_diseases_for_phenotype('HP:0000479') -> success, OMIM:106210 in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        payload = get_annotation_service().get_diseases_for_phenotype("HP:0000479")
        payload.setdefault("_meta", {})["next_commands"] = []
        return payload

    result = await run_mcp_tool(
        "hpo_get_diseases_for_phenotype",
        call,
        context=McpErrorContext("hpo_get_diseases_for_phenotype", arguments={"term": "HP:0000479"}),
    )
    assert result["success"] is True
    # The repository returns database_id (HPOA column name)
    disease_ids = [d.get("database_id") or d.get("disease_id") for d in result.get("diseases", [])]
    assert "OMIM:106210" in disease_ids


# ---------------------------------------------------------------------------
# hpo_get_genes_for_disease
# ---------------------------------------------------------------------------


async def test_get_genes_for_disease(live_annotation_service) -> None:
    """get_genes_for_disease('OMIM:106210') -> success, PAX6 in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        payload = get_annotation_service().get_genes_for_disease("OMIM:106210")
        payload.setdefault("_meta", {})["next_commands"] = []
        return payload

    result = await run_mcp_tool(
        "hpo_get_genes_for_disease",
        call,
        context=McpErrorContext(
            "hpo_get_genes_for_disease", arguments={"disease_id": "OMIM:106210"}
        ),
    )
    assert result["success"] is True
    gene_symbols = [g["gene_symbol"] for g in result.get("genes", []) if "gene_symbol" in g]
    assert "PAX6" in gene_symbols


# ---------------------------------------------------------------------------
# hpo_get_diseases_for_gene
# ---------------------------------------------------------------------------


async def test_get_diseases_for_gene(live_annotation_service) -> None:
    """get_diseases_for_gene('PAX6') -> success, OMIM:106210 in results."""
    from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from hpo_link.mcp.service_adapters import get_annotation_service

    async def call():
        payload = get_annotation_service().get_diseases_for_gene("PAX6")
        payload.setdefault("_meta", {})["next_commands"] = []
        return payload

    result = await run_mcp_tool(
        "hpo_get_diseases_for_gene",
        call,
        context=McpErrorContext("hpo_get_diseases_for_gene", arguments={"gene": "PAX6"}),
    )
    assert result["success"] is True
    disease_ids = [d["disease_id"] for d in result.get("diseases", []) if "disease_id" in d]
    assert "OMIM:106210" in disease_ids
