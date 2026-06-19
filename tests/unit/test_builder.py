"""Tests for hpo_link.ingest.builder — includes WS-A T0.1 regression."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hpo_link.ingest.builder import BuildMeta, build_database


def _settings(tmp_path: Path) -> object:
    """Create a minimal ServerSettings pointing at tmp_path."""
    from hpo_link.config import HPODataConfig, ServerSettings

    data = HPODataConfig(data_dir=tmp_path)
    return ServerSettings.model_construct(data=data)


def test_build_database(tmp_path: Path, mini_paths: dict[str, Path | None]) -> None:
    meta = build_database(_settings(tmp_path), paths=mini_paths, validators={})  # type: ignore[arg-type]
    db = tmp_path / "hpo.sqlite"
    assert db.exists()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM term").fetchone()[0] >= 4
        assert (
            conn.execute("SELECT count(*) FROM hpo_closure WHERE hpo_id=ancestor_id").fetchone()[0]
            >= 4
        )
        assert conn.execute("SELECT count(*) FROM disease_phenotype").fetchone()[0] >= 1
        assert conn.execute("SELECT count(*) FROM gene_phenotype").fetchone()[0] >= 1
        assert conn.execute("SELECT count(*) FROM gene_disease").fetchone()[0] >= 1
    assert meta.hpo_version == "2026-06-06"
    assert isinstance(meta, BuildMeta)


def test_build_database_meta_counts(tmp_path: Path, mini_paths: dict[str, Path | None]) -> None:
    meta = build_database(_settings(tmp_path), paths=mini_paths, validators={})  # type: ignore[arg-type]
    assert meta.term_count >= 4
    assert meta.closure_count >= 4
    assert meta.disease_phenotype_count >= 1
    assert meta.gene_phenotype_count >= 1
    assert meta.gene_disease_count >= 1


def test_build_database_db_meta_row_has_all_seven_counts(
    tmp_path: Path, mini_paths: dict[str, Path | None]
) -> None:
    """T0.1 — the meta table row must have positive integers for all 7 *_count columns."""
    build_database(_settings(tmp_path), paths=mini_paths, validators={})  # type: ignore[arg-type]
    db = tmp_path / "hpo.sqlite"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    assert row is not None, "meta table must have exactly one row"
    count_columns = [
        "term_count",
        "obsolete_count",
        "closure_count",
        "xref_count",
        "disease_phenotype_count",
        "gene_phenotype_count",
        "gene_disease_count",
    ]
    for col in count_columns:
        val = row[col]
        assert val is not None, f"meta.{col} must not be NULL"
        assert isinstance(val, int), f"meta.{col} must be an integer, got {type(val)}"
        assert val >= 0, f"meta.{col} must be non-negative, got {val}"
    # Internal consistency: obsolete <= total terms
    assert row["obsolete_count"] <= row["term_count"]
    # Sanity: at least some real data
    assert row["term_count"] >= 4
    assert row["disease_phenotype_count"] >= 1
    assert row["gene_phenotype_count"] >= 1
    assert row["gene_disease_count"] >= 1
