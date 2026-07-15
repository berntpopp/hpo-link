"""Regression tests for the confirmed defects in issue #28 (MCP fleet audit 2026-07-14).

Each test is written against the CORRECT behaviour and fails against the pre-fix code:

* D1 — ``search_terms`` must rank an exact primary-label / exact-synonym match on
  page 1 (a doc-length/BM25 inversion buries the exact term behind its children).
* D2 — every candidate a resolver returns must carry its (trusted, DB-sourced) ``name``.
* D4 (#4) — a malformed ``disease_id`` / ``gene`` must return an actionable
  ``invalid_input`` whose envelope carries ``allowed_values`` and ``hint``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastmcp.tools.tool import ToolResult

from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import AmbiguousQueryError, NotFoundError
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool


def _env(result: Any) -> dict[str, Any]:
    """Read the flat envelope whether run_mcp_tool returned a dict or a ToolResult."""
    if isinstance(result, ToolResult):
        assert isinstance(result.structured_content, dict)
        return result.structured_content
    assert isinstance(result, dict)
    return result


# --------------------------------------------------------------------------- D1


def _build_seizure_db(path: Path) -> None:
    """A minimal HPO index where the exact match ('Seizure') has the WORST bm25.

    The parent term HP:0001250 'Seizure' carries many synonyms and a long definition,
    so its FTS document is long and bm25 ranks it BELOW its shorter child terms for the
    query 'seizure' — the exact doc-length inversion the audit reproduced live.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE term (
            hpo_id TEXT PRIMARY KEY, name TEXT, name_upper TEXT, definition TEXT,
            is_obsolete INTEGER DEFAULT 0, replaced_by TEXT, consider TEXT,
            alt_ids TEXT, synonyms TEXT, subsets TEXT, comments TEXT
        );
        CREATE VIRTUAL TABLE term_fts USING fts5(hpo_id UNINDEXED, name, synonyms, definition);
        CREATE TABLE term_lookup (lookup_label TEXT, hpo_id TEXT, label_type TEXT);
        """
    )
    long_def = "A seizure is an abnormal " + (
        "synchronous neuronal cortical electrical discharge event " * 20
    )
    syns = "Seizures Epileptic seizure Epilepsy Convulsion Convulsions Ictus Fits " * 4
    children = [
        ("HP:0011153", "Focal motor seizure", "Focal seizures with motor signs."),
        ("HP:0100622", "Maternal seizure", "Seizures occurring in the mother."),
        ("HP:0011167", "Focal tonic seizure", "Focal seizures of tonic type."),
        ("HP:0002266", "Focal clonic seizure", "Focal seizures of clonic type."),
    ]
    conn.execute(
        "INSERT INTO term (hpo_id,name,name_upper,definition,is_obsolete) VALUES (?,?,?,?,0)",
        ("HP:0001250", "Seizure", "SEIZURE", long_def),
    )
    conn.execute(
        "INSERT INTO term_fts (hpo_id,name,synonyms,definition) VALUES (?,?,?,?)",
        ("HP:0001250", "Seizure", syns, long_def),
    )
    conn.execute("INSERT INTO term_lookup VALUES (?,?,?)", ("SEIZURE", "HP:0001250", "primary"))
    conn.execute(
        "INSERT INTO term_lookup VALUES (?,?,?)", ("SEIZURES", "HP:0001250", "exact_synonym")
    )
    for hid, name, definition in children:
        conn.execute(
            "INSERT INTO term (hpo_id,name,name_upper,definition,is_obsolete) VALUES (?,?,?,?,0)",
            (hid, name, name.upper(), definition),
        )
        conn.execute(
            "INSERT INTO term_fts (hpo_id,name,synonyms,definition) VALUES (?,?,?,?)",
            (hid, name, "", definition),
        )
        conn.execute("INSERT INTO term_lookup VALUES (?,?,?)", (name.upper(), hid, "primary"))
    conn.commit()
    conn.close()


def test_search_ranks_the_exact_primary_label_first(tmp_path: Path) -> None:
    """search('Seizure') must return HP:0001250 first, not its more-specific children."""
    db = tmp_path / "seizure.sqlite"
    _build_seizure_db(db)
    repo = HpoRepository(db)
    try:
        hits, total = repo.search("Seizure", limit=30, include_obsolete=False)
    finally:
        repo.close()
    ids = [h["hpo_id"] for h in hits]
    assert total == 5
    assert "HP:0001250" in ids, "the exact term must be in the result set"
    assert ids[0] == "HP:0001250", f"the exact primary-label match must rank first; got {ids[:3]}"


def test_search_ranks_the_exact_synonym_first(tmp_path: Path) -> None:
    """The plural 'Seizures' is a declared exact synonym of HP:0001250 → it must rank first."""
    db = tmp_path / "seizure.sqlite"
    _build_seizure_db(db)
    repo = HpoRepository(db)
    try:
        hits, _ = repo.search("Seizures", limit=30, include_obsolete=False)
    finally:
        repo.close()
    ids = [h["hpo_id"] for h in hits]
    assert ids and ids[0] == "HP:0001250", f"exact-synonym match must rank first; got {ids[:3]}"


# --------------------------------------------------------------------------- D2


async def test_ambiguous_candidates_all_carry_a_name() -> None:
    """AmbiguousQueryError candidates must surface {hpo_id, name}, not bare CURIEs."""

    async def call() -> dict[str, Any]:
        raise AmbiguousQueryError(
            "matches several terms",
            candidates=[
                {"hpo_id": "HP:0002373", "name": "Febrile seizure (within the age range)"},
                {"hpo_id": "HP:0011171", "name": "Complex febrile seizure"},
                {"hpo_id": "HP:0032894", "name": "Simple febrile seizure"},
            ],
        )

    result = await run_mcp_tool(
        "resolve_term", call, context=McpErrorContext("resolve_term", arguments={"query": "x"})
    )
    env = _env(result)
    assert env["error_code"] == "ambiguous_query"
    candidates = env.get("candidates")
    assert candidates, "an ambiguous_query error must carry candidates"
    for cand in candidates:
        assert cand.get("name"), f"every candidate must carry a name; got {cand!r}"


async def test_notfound_suggestions_all_carry_a_name() -> None:
    """NotFoundError suggestions must surface {hpo_id, name}, not bare CURIEs."""

    async def call() -> dict[str, Any]:
        raise NotFoundError(
            "no exact match",
            suggestions=[
                {"hpo_id": "HP:0040292", "name": "Left hemiplegia", "score": 3.2},
                {"hpo_id": "HP:0040293", "name": "Right hemiplegia", "score": 3.1},
            ],
        )

    result = await run_mcp_tool(
        "resolve_term", call, context=McpErrorContext("resolve_term", arguments={"query": "x"})
    )
    env = _env(result)
    assert env["error_code"] == "not_found"
    candidates = env.get("candidates")
    assert candidates, "a not_found with suggestions must carry candidates"
    for cand in candidates:
        assert cand.get("name"), f"every candidate must carry a name; got {cand!r}"


# --------------------------------------------------------------------------- D4 (#4)


async def test_bad_disease_id_error_carries_allowed_values_and_hint() -> None:
    """A malformed disease_id must return invalid_input WITH allowed_values + hint."""
    from hpo_link.mcp.facade import create_hpo_mcp
    from hpo_link.mcp.service_adapters import (
        reset_services,
        set_annotation_service,
    )
    from hpo_link.services.annotation_service import AnnotationService

    reset_services()
    set_annotation_service(AnnotationService(None))
    try:
        mcp = create_hpo_mcp()
        result = await mcp.call_tool("get_phenotypes_for_disease", {"disease_id": "OMIM-607208"})
    finally:
        reset_services()
    env = result.structured_content
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env.get("field") == "disease_id"
    assert env.get("allowed_values"), "the error must state what a valid disease_id looks like"
    assert env.get("hint"), "the error must carry a call hint"


async def test_bad_gene_error_carries_allowed_values_and_hint() -> None:
    """A malformed gene must return invalid_input WITH allowed_values + hint (same class)."""
    from hpo_link.mcp.facade import create_hpo_mcp
    from hpo_link.mcp.service_adapters import (
        reset_services,
        set_annotation_service,
    )
    from hpo_link.services.annotation_service import AnnotationService

    reset_services()
    set_annotation_service(AnnotationService(None))
    try:
        mcp = create_hpo_mcp()
        result = await mcp.call_tool("get_phenotypes_for_gene", {"gene": "BadGene:xyz"})
    finally:
        reset_services()
    env = result.structured_content
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env.get("field") == "gene"
    assert env.get("allowed_values"), "the error must state what a valid gene looks like"
    assert env.get("hint"), "the error must carry a call hint"
