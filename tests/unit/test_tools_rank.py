"""score_genes_for_phenotypes through the registered FastMCP tool + perf on shipped data."""

from __future__ import annotations

import sqlite3
import statistics
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hpo_link.mcp.service_adapters import reset_services, set_annotation_service

SHIPPED_DB = Path(__file__).resolve().parents[2] / "data" / "hpo.sqlite"


@pytest.fixture()
def service(built_test_db: Path) -> Iterator[Any]:
    from hpo_link.data.repository import HpoRepository
    from hpo_link.services.annotation_service import AnnotationService

    reset_services()
    repo = HpoRepository(built_test_db)
    svc = AnnotationService(repo)
    set_annotation_service(svc)
    try:
        yield svc
    finally:
        repo.close()
        reset_services()


@pytest.fixture()
def mcp(service: Any) -> Any:
    from hpo_link.mcp.facade import create_hpo_mcp

    return create_hpo_mcp()


async def _call(mcp: Any, **args: Any) -> dict[str, Any]:
    result = await mcp.call_tool("score_genes_for_phenotypes", args)
    payload: dict[str, Any] = result.structured_content
    return payload


async def test_ranks_exact_match_first_with_matched_pairs(mcp: Any) -> None:
    payload = await _call(mcp, hpo_ids=["HP:0000479"])
    assert payload["success"] is True
    top = payload["genes"][0]
    assert (top["rank"], top["gene"], top["best_disease"]["disease_id"]) == (
        1,
        "PAX6",
        "OMIM:106210",
    )
    assert top["matched_terms"][0]["mica_hpo_id"] == "HP:0000479"
    assert payload["total"] == 1 and payload["truncated"] is False
    steps = [s["tool"] for s in payload["_meta"]["next_commands"]]
    assert steps == ["get_phenotypes_for_gene", "get_phenotypes_for_disease"]
    assert payload["limitations"] and payload["hpo_version"]
    # issue #130: one ranked gene cannot be a close call; every mode carries the fields.
    assert (payload["rank1_margin"], payload["close_call"], top["matched_count"]) == (
        None,
        False,
        1,
    )
    minimal = await _call(mcp, hpo_ids=["HP:0000479"], response_mode="minimal")
    assert minimal["close_call"] is False and minimal["genes"][0]["top_matches"]


async def test_candidate_filter_reports_unrankable_genes(mcp: Any) -> None:
    # GLI3's only disease is annotated to HP:0000478 alone (IC 0 in the fixture): unrankable.
    payload = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["pax6", "GLI3", "NOPE"])
    assert [(g["gene"], g["input_id"]) for g in payload["genes"]] == [("PAX6", "pax6")]
    assert payload["unranked_candidate_genes"] == [
        {"input_id": "GLI3", "reason": "not_rankable"},
        {"input_id": "NOPE", "reason": "not_rankable"},
    ]
    assert payload["total"] == 1


async def test_foreign_gene_ids_fail_with_accepted_forms_and_remedy(mcp: Any) -> None:
    # Issue #128: hpo-link has no Ensembl/HGNC mapping; say so instead of "see field".
    bad = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["ENSG00000007372"])
    assert (bad["success"], bad["error_code"], bad["field"]) == (
        False,
        "invalid_input",
        "candidate_genes",
    )
    assert bad["allowed_values"] and "translate them to gene symbols" in bad["hint"]
    # router #343: the error hands the rejected ids to the converter, ready to send.
    batch = {"tool": "hgnc_resolve_symbols_batch", "arguments": {"queries": ["ENSG00000007372"]}}
    assert bad["_meta"]["next_commands"][0] == batch
    assert "hgnc_resolve_symbols_batch" in bad["hint"]
    mixed = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["PAX6", "ENSG00000007372"])
    assert [g["input_id"] for g in mixed["genes"]] == ["PAX6"]
    assert mixed["unranked_candidate_genes"] == [
        {"input_id": "ENSG00000007372", "reason": "unsupported_identifier"}
    ]
    assert mixed["_meta"]["next_commands"][0] == batch
    # NCBI gene ids are HPO's own data: ranked, with the caller's spelling echoed.
    for ncbi in ("NCBIGene:5080", "5080"):
        own = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=[ncbi])
        assert [(g["gene"], g["input_id"]) for g in own["genes"]] == [("PAX6", ncbi)]
    # The single-gene tools returned an empty success for an Ensembl id (317 wasted calls).
    for tool in ("get_phenotypes_for_gene", "get_diseases_for_gene"):
        result = await mcp.call_tool(tool, {"gene": "ENSG00000007372"})
        single = result.structured_content
        assert (single["success"], single["error_code"], single["field"]) == (
            False,
            "invalid_input",
            "gene",
        )
        assert "translate them to gene symbols" in single["hint"]
        assert single["_meta"]["next_commands"][0] == {
            "tool": "hgnc_resolve_symbol",
            "arguments": {"query": "ENSG00000007372"},
        }

    # A transcript id is not a gene: no HGNC converter is named (it does not take ENST).
    result = await mcp.call_tool("get_phenotypes_for_gene", {"gene": "ENST00000379132"})
    enst = result.structured_content
    assert (enst["error_code"], enst["field"]) == ("invalid_input", "gene")
    assert "transcript id" in enst["hint"] and "hgnc_" not in enst["hint"]
    assert [s["tool"] for s in enst["_meta"]["next_commands"]] == ["get_server_capabilities"]
    listed = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["ENST00000379132"])
    assert [s["tool"] for s in listed["_meta"]["next_commands"]] == ["get_server_capabilities"]


async def test_disease_id_spellings_are_normalised_and_foreign_ontologies_rejected(
    mcp: Any,
) -> None:
    """Router #343: Orphanet:/MIM: are the same namespace; MONDO is not (no empty success)."""
    for tool, key in (
        ("get_phenotypes_for_disease", "phenotypes"),
        ("get_genes_for_disease", "genes"),
    ):
        ok = (await mcp.call_tool(tool, {"disease_id": "mim:106210"})).structured_content
        assert (ok["success"], ok["disease_id"]) == (True, "OMIM:106210") and ok[key]
        orpha = (await mcp.call_tool(tool, {"disease_id": "Orphanet:648"})).structured_content
        assert (orpha["success"], orpha["disease_id"]) == (True, "ORPHA:648")
        bad = (await mcp.call_tool(tool, {"disease_id": "MONDO:0018997"})).structured_content
        assert (bad["success"], bad["error_code"], bad["field"]) == (
            False,
            "invalid_input",
            "disease_id",
        )
        assert bad["allowed_values"] and "mondo_map_cross_ontology" in bad["hint"]
        assert bad["_meta"]["next_commands"][0] == {
            "tool": "mondo_map_cross_ontology",
            "arguments": {"term": "MONDO:0018997", "prefixes": ["OMIM", "ORPHA"]},
        }
        # a gene id sent as a disease id is not handed to the disease converter
        gene = (await mcp.call_tool(tool, {"disease_id": "NCBIGene:5080"})).structured_content
        assert (gene["error_code"], gene["field"]) == ("invalid_input", "disease_id")
        assert "mondo_" not in gene["hint"]
        assert [s["tool"] for s in gene["_meta"]["next_commands"]] == ["get_server_capabilities"]
        # a correctly understood disease without annotations is still an honest empty page
        empty = (await mcp.call_tool(tool, {"disease_id": "OMIM:0000000"})).structured_content
        assert (empty["success"], empty[key]) == (True, [])


async def test_truncation_and_excluded_conflict_on_toy_index(mcp: Any, service: Any) -> None:
    from tests.unit.test_phenotype_rank import ids, toy

    ix = toy({"d": [("MICRO", 0.95), ("FEB", 0.9)], "e": [("CAT", 0.9)]})
    service._phenotype_index = ix
    plain = await _call(mcp, hpo_ids=ids("FACE", "FEB"), limit=1)
    excl = await _call(mcp, hpo_ids=ids("FACE", "FEB"), excluded_hpo_ids=ids("MICRO"), limit=1)
    assert (excl["returned"], excl["truncated"], excl["next_offset"], excl["total"]) == (
        1,
        True,
        1,
        2,
    )
    assert excl["genes"][0]["score"] == plain["genes"][0]["score"]
    assert excl["genes"][0]["conflicts"][0]["disease_hpo_id"] == ids("MICRO")[0]
    page = excl["_meta"]["next_commands"][0]
    assert page["tool"] == "score_genes_for_phenotypes"
    assert page["arguments"]["offset"] == 1
    assert page["arguments"]["excluded_hpo_ids"] == ids("MICRO")


async def test_close_call_points_to_curations_of_the_tied_genes(mcp: Any, service: Any) -> None:
    from tests.unit.test_phenotype_rank import ids, toy

    service._phenotype_index = toy({"a": [("FEB", 0.9)], "b": [("FEB", 0.88)], "c": [("CAT", 0.9)]})
    close = await _call(mcp, hpo_ids=ids("FEB"))
    assert close["close_call"] is True and close["genes"][0]["other_diseases"] == []
    curations = {"tool": "gencc_get_genes_curations", "arguments": {"genes": ["G_a", "G_b"]}}
    assert close["_meta"]["next_commands"][0] == curations
    assert "gencc_get_genes_curations" in close["close_call_note"]  # minimal has no next_commands
    # a truncated page: the whole tied set, ahead of paging, behind the identifier converter
    for offset in (0, 1):
        page = await _call(mcp, hpo_ids=ids("FEB"), limit=1, offset=offset)
        assert page["_meta"]["next_commands"][0] == curations
    mixed = await _call(
        mcp, hpo_ids=ids("FEB"), candidate_genes=["G_a", "G_b", "G_c", "ENSG00000144285"], limit=1
    )
    assert [s["tool"] for s in mixed["_meta"]["next_commands"]][:3] == [
        "hgnc_resolve_symbols_batch",
        "gencc_get_genes_curations",
        "score_genes_for_phenotypes",
    ]
    clear = await _call(mcp, hpo_ids=ids("FEB"), candidate_genes=["G_a", "G_c"])
    assert "gencc_get_genes_curations" not in [s["tool"] for s in clear["_meta"]["next_commands"]]


async def test_validation_errors_name_the_field(mcp: Any) -> None:
    bad = await _call(mcp, hpo_ids=["not-an-id"])
    assert (bad["success"], bad["error_code"], bad["field"]) == (False, "invalid_input", "hpo_ids")
    # HP:0000478 is reached by every fixture disease (IC 0): nothing informative to score.
    flat = await _call(mcp, hpo_ids=["HP:0000478", "HP:9999999"])
    assert (flat["success"], flat["error_code"]) == (False, "invalid_input")


@pytest.mark.skipif(not SHIPPED_DB.exists(), reason="shipped data/hpo.sqlite not present")
def test_warm_ranking_is_fast_on_shipped_data() -> None:
    from hpo_link.services.phenotype_index import load_index
    from hpo_link.services.phenotype_rank import rank_payload

    conn = sqlite3.connect(f"file:{SHIPPED_DB}?mode=ro&immutable=1", uri=True)
    t0 = time.perf_counter()
    ix = load_index(conn)
    cold = time.perf_counter() - t0
    terms = [
        "HP:0001250",  # seizure
        "HP:0001263",  # global developmental delay
        "HP:0000252",  # microcephaly
        "HP:0001252",  # hypotonia
        "HP:0000486",  # strabismus
        "HP:0002650",  # scoliosis
        "HP:0004322",  # short stature
        "HP:0000365",  # hearing impairment
    ]
    runs = []
    for _ in range(7):  # CPU time: robust to wall-clock noise from parallel test workers
        t = time.process_time()
        payload = rank_payload(ix, terms, None, None, 20, 0, "compact")
        runs.append(time.process_time() - t)
    warm = statistics.median(runs)
    print(f"cold index build {cold:.2f}s, warm 8-term ranking median {warm * 1000:.1f} ms")
    assert payload["total"] > 4000 and payload["genes"][0]["matched_terms"]
    assert warm < 0.050


async def test_symbol_less_gene_is_listed_last_and_never_ranked(mcp: Any) -> None:
    """HPO ships "-" as the symbol of a few genes (fixture: NCBIGene:3653 on OMIM:106210)."""
    result = await mcp.call_tool(
        "get_genes_for_disease", {"disease_id": "OMIM:106210", "response_mode": "standard"}
    )
    assert [g["gene_symbol"] for g in result.structured_content["genes"]] == ["PAX6", "-"]
    ranked = await _call(mcp, hpo_ids=["HP:0000479"])
    assert [g["gene"] for g in ranked["genes"]] == ["PAX6"]
    by_id = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["PAX6", "3653"])
    assert by_id["unranked_candidate_genes"] == [{"input_id": "3653", "reason": "not_rankable"}]


async def test_echoed_input_ids_are_stripped_of_control_characters_and_capped(mcp: Any) -> None:
    hostile = "NO\u202ePE\u0000" + "X" * 100
    payload = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["PAX6", hostile])
    echoed = payload["unranked_candidate_genes"][0]["input_id"]
    assert echoed == "NOPE" + "X" * 60
