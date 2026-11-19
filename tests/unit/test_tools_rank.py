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


async def test_candidate_filter_reports_unrankable_genes(mcp: Any) -> None:
    # GLI3's only disease is annotated to HP:0000478 alone (IC 0 in the fixture): unrankable.
    payload = await _call(mcp, hpo_ids=["HP:0000479"], candidate_genes=["pax6", "GLI3", "NOPE"])
    assert [g["gene"] for g in payload["genes"]] == ["PAX6"]
    assert payload["unranked_candidate_genes"] == ["GLI3", "NOPE"]
    assert payload["total"] == 1


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
