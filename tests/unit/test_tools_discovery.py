"""Tests for hpo_link.mcp.tools.discovery — WS-A (TDD, written before implementation)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hpo_link.mcp.tools.discovery import _resolve_counts

# ---------------------------------------------------------------------------
# _resolve_counts — pure helper (no live DB needed)
# ---------------------------------------------------------------------------


def _fake_repo(counts: dict[str, int]) -> MagicMock:
    """Return a mock HpoRepository whose counts() returns *counts*."""
    repo = MagicMock()
    repo.counts.return_value = counts
    return repo


# T0.2-a: when all seven meta keys are present and non-None, use meta values
def test_resolve_counts_prefers_meta_values() -> None:
    """_resolve_counts should return meta values when all seven keys are present."""
    meta: dict[str, Any] = {
        "term_count": 10,
        "obsolete_count": 2,
        "closure_count": 50,
        "xref_count": 30,
        "disease_phenotype_count": 100,
        "gene_phenotype_count": 200,
        "gene_disease_count": 80,
    }
    repo = _fake_repo(
        {
            "terms": 999,
            "obsolete": 999,
            "closure": 999,
            "xref": 999,
            "disease_phenotype": 999,
            "gene_phenotype": 999,
            "gene_disease": 999,
        }
    )
    result = _resolve_counts(meta, repo)
    assert result["terms"] == 10
    assert result["obsolete"] == 2
    assert result["closure"] == 50
    assert result["xref"] == 30
    assert result["disease_phenotype"] == 100
    assert result["gene_phenotype"] == 200
    assert result["gene_disease"] == 80
    repo.counts.assert_not_called()


# T0.2-b: when a meta value is None, fall back to repo.counts() for that key
def test_resolve_counts_falls_back_per_key_when_meta_none() -> None:
    """_resolve_counts falls back per-key when a meta value is None."""
    meta: dict[str, Any] = {
        "term_count": 10,
        "obsolete_count": None,  # missing — must fall back
        "closure_count": 50,
        "xref_count": 30,
        "disease_phenotype_count": None,  # missing — must fall back
        "gene_phenotype_count": 200,
        "gene_disease_count": 80,
    }
    fallback = {
        "terms": 999,
        "obsolete": 3,
        "closure": 999,
        "xref": 999,
        "disease_phenotype": 7,
        "gene_phenotype": 999,
        "gene_disease": 999,
    }
    repo = _fake_repo(fallback)
    result = _resolve_counts(meta, repo)
    # meta values used where present
    assert result["terms"] == 10
    assert result["closure"] == 50
    assert result["xref"] == 30
    assert result["gene_phenotype"] == 200
    assert result["gene_disease"] == 80
    # fallback used for None meta values
    assert result["obsolete"] == 3
    assert result["disease_phenotype"] == 7
    # repo.counts() was called (once, lazily or not) since some keys needed fallback
    repo.counts.assert_called()


# T0.2-c: when a meta key is absent (not just None), fall back too
def test_resolve_counts_falls_back_when_meta_key_absent() -> None:
    """_resolve_counts falls back when a meta key is completely absent."""
    meta: dict[str, Any] = {
        "term_count": 5,
        # obsolete_count key absent entirely
        "closure_count": 20,
        "xref_count": 10,
        "disease_phenotype_count": 50,
        "gene_phenotype_count": 100,
        "gene_disease_count": 40,
    }
    fallback = {
        "terms": 999,
        "obsolete": 1,
        "closure": 999,
        "xref": 999,
        "disease_phenotype": 999,
        "gene_phenotype": 999,
        "gene_disease": 999,
    }
    repo = _fake_repo(fallback)
    result = _resolve_counts(meta, repo)
    assert result["obsolete"] == 1  # fell back because key absent
    assert result["terms"] == 5  # from meta


# T0.2-d: internal consistency — obsolete <= terms
def test_resolve_counts_consistency_obsolete_le_terms() -> None:
    """_resolve_counts result must have obsolete <= terms (internal consistency)."""
    meta: dict[str, Any] = {
        "term_count": 100,
        "obsolete_count": 5,
        "closure_count": 500,
        "xref_count": 300,
        "disease_phenotype_count": 1000,
        "gene_phenotype_count": 2000,
        "gene_disease_count": 800,
    }
    repo = _fake_repo({})
    result = _resolve_counts(meta, repo)
    assert result["obsolete"] <= result["terms"]


# T0.2-e: all seven keys are present in result
def test_resolve_counts_returns_all_seven_keys() -> None:
    """_resolve_counts must return all seven expected keys."""
    meta: dict[str, Any] = {
        "term_count": 10,
        "obsolete_count": 2,
        "closure_count": 50,
        "xref_count": 30,
        "disease_phenotype_count": 100,
        "gene_phenotype_count": 200,
        "gene_disease_count": 80,
    }
    repo = _fake_repo({})
    result = _resolve_counts(meta, repo)
    expected_keys = {
        "terms",
        "obsolete",
        "closure",
        "xref",
        "disease_phenotype",
        "gene_phenotype",
        "gene_disease",
    }
    assert set(result.keys()) == expected_keys


# T0.2-g: a legitimate meta value of 0 is preserved, NOT treated as missing.
# This pins the load-bearing `is None` check — a truthiness check (`if not ...`)
# would silently re-break the bug for any genuinely-zero count.
def test_resolve_counts_preserves_legitimate_zero() -> None:
    """A meta count of exactly 0 is kept and does NOT trigger the fallback."""
    meta: dict[str, Any] = {
        "term_count": 10,
        "obsolete_count": 0,  # genuinely zero — must be preserved, not fallback
        "closure_count": 50,
        "xref_count": 30,
        "disease_phenotype_count": 100,
        "gene_phenotype_count": 200,
        "gene_disease_count": 80,
    }
    repo = _fake_repo(
        dict.fromkeys(
            (
                "terms",
                "obsolete",
                "closure",
                "xref",
                "disease_phenotype",
                "gene_phenotype",
                "gene_disease",
            ),
            999,
        )
    )
    result = _resolve_counts(meta, repo)
    assert result["obsolete"] == 0
    repo.counts.assert_not_called()


# T0.2-f: when meta is completely empty, all values come from repo.counts()
def test_resolve_counts_empty_meta_uses_all_fallback() -> None:
    """When meta is empty, all counts come from repo.counts()."""
    meta: dict[str, Any] = {}
    fallback = {
        "terms": 1,
        "obsolete": 0,
        "closure": 5,
        "xref": 3,
        "disease_phenotype": 7,
        "gene_phenotype": 9,
        "gene_disease": 4,
    }
    repo = _fake_repo(fallback)
    result = _resolve_counts(meta, repo)
    assert result == fallback


# B.1: end-to-end — _resolve_counts against the real built fixture DB returns
# real, internally-consistent volume counts (locks the diagnostics-counts fix).
def test_resolve_counts_all_positive_against_built_db(repo: Any) -> None:
    """Against a freshly built DB every count is a real non-negative integer."""
    counts = _resolve_counts(repo.read_meta(), repo)
    expected_keys = {
        "terms",
        "obsolete",
        "closure",
        "xref",
        "disease_phenotype",
        "gene_phenotype",
        "gene_disease",
    }
    assert set(counts) == expected_keys
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())
    assert counts["terms"] > 0
    assert counts["obsolete"] <= counts["terms"]
