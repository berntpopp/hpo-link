"""Tests for HpoRepository annotation queries (gene/disease/phenotype)."""

from __future__ import annotations

from hpo_link.data.repository import HpoRepository

# -- gene -> phenotype -------------------------------------------------------


def test_phenotypes_for_gene_by_symbol(repo: HpoRepository) -> None:
    """phenotypes_for_gene('symbol', 'PAX6') should include HP:0000479."""
    rows = repo.phenotypes_for_gene("symbol", "PAX6", 100)
    hpo_ids = [r["hpo_id"] for r in rows]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_gene_by_ncbi(repo: HpoRepository) -> None:
    """phenotypes_for_gene('ncbi', '5080') should include HP:0000479."""
    rows = repo.phenotypes_for_gene("ncbi", "5080", 100)
    hpo_ids = [r["hpo_id"] for r in rows]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_gene_symbol_case_insensitive(repo: HpoRepository) -> None:
    """Gene symbol lookup is case-insensitive (uppercased internally)."""
    rows_upper = repo.phenotypes_for_gene("symbol", "PAX6", 100)
    rows_lower = repo.phenotypes_for_gene("symbol", "pax6", 100)
    assert {r["hpo_id"] for r in rows_upper} == {r["hpo_id"] for r in rows_lower}


def test_count_phenotypes_for_gene(repo: HpoRepository) -> None:
    """count_phenotypes_for_gene('symbol', 'PAX6') should be at least 1."""
    count = repo.count_phenotypes_for_gene("symbol", "PAX6")
    assert count >= 1


def test_phenotypes_for_gene_gli3(repo: HpoRepository) -> None:
    """phenotypes_for_gene('symbol', 'GLI3') should include HP:0000478."""
    rows = repo.phenotypes_for_gene("symbol", "GLI3", 100)
    hpo_ids = [r["hpo_id"] for r in rows]
    assert "HP:0000478" in hpo_ids


# -- phenotype -> gene -------------------------------------------------------


def test_genes_for_phenotype(repo: HpoRepository) -> None:
    """genes_for_phenotype should return both PAX6 and GLI3 for the given HPO ids."""
    rows = repo.genes_for_phenotype(["HP:0000118", "HP:0000478", "HP:0000479"], 100)
    symbols = {r["gene_symbol"] for r in rows}
    assert "PAX6" in symbols
    assert "GLI3" in symbols


def test_count_genes_for_phenotype(repo: HpoRepository) -> None:
    """count_genes_for_phenotype should be at least 1 for HP:0000479."""
    count = repo.count_genes_for_phenotype(["HP:0000479"])
    assert count >= 1


def test_genes_for_phenotype_empty_ids(repo: HpoRepository) -> None:
    """genes_for_phenotype with empty list should return empty list."""
    assert repo.genes_for_phenotype([], 100) == []


def test_count_genes_for_phenotype_empty(repo: HpoRepository) -> None:
    """count_genes_for_phenotype with empty list should return 0."""
    assert repo.count_genes_for_phenotype([]) == 0


# -- disease -> phenotype ----------------------------------------------------


def test_phenotypes_for_disease(repo: HpoRepository) -> None:
    """phenotypes_for_disease('OMIM:106210') should include HP:0000479."""
    rows = repo.phenotypes_for_disease("OMIM:106210", 100)
    hpo_ids = [r["hpo_id"] for r in rows]
    assert "HP:0000479" in hpo_ids


def test_count_phenotypes_for_disease(repo: HpoRepository) -> None:
    """count_phenotypes_for_disease('OMIM:106210') should be at least 1."""
    count = repo.count_phenotypes_for_disease("OMIM:106210")
    assert count >= 1


def test_phenotypes_for_disease_includes_not_qualifier(repo: HpoRepository) -> None:
    """OMIM:106210 has a NOT-qualified entry for HP:0000118; it should be returned."""
    rows = repo.phenotypes_for_disease("OMIM:106210", 100)
    not_rows = [r for r in rows if r["qualifier"] == "NOT"]
    hpo_ids = [r["hpo_id"] for r in not_rows]
    assert "HP:0000118" in hpo_ids


def test_phenotypes_for_disease_146510(repo: HpoRepository) -> None:
    """phenotypes_for_disease('OMIM:146510') should include HP:0000478."""
    rows = repo.phenotypes_for_disease("OMIM:146510", 100)
    hpo_ids = [r["hpo_id"] for r in rows]
    assert "HP:0000478" in hpo_ids


# -- phenotype -> disease ----------------------------------------------------


def test_diseases_for_phenotype(repo: HpoRepository) -> None:
    """diseases_for_phenotype(['HP:0000479']) should include OMIM:106210."""
    rows = repo.diseases_for_phenotype(["HP:0000479"], 100)
    ids = {r["database_id"] for r in rows}
    assert "OMIM:106210" in ids


def test_count_diseases_for_phenotype(repo: HpoRepository) -> None:
    """count_diseases_for_phenotype(['HP:0000478']) should be at least 1."""
    count = repo.count_diseases_for_phenotype(["HP:0000478"])
    assert count >= 1


def test_diseases_for_phenotype_empty_ids(repo: HpoRepository) -> None:
    """diseases_for_phenotype with empty list should return empty list."""
    assert repo.diseases_for_phenotype([], 100) == []


def test_count_diseases_for_phenotype_empty(repo: HpoRepository) -> None:
    """count_diseases_for_phenotype with empty list should return 0."""
    assert repo.count_diseases_for_phenotype([]) == 0


# -- disease -> gene ---------------------------------------------------------


def test_genes_for_disease(repo: HpoRepository) -> None:
    """genes_for_disease('OMIM:106210') should include PAX6."""
    rows = repo.genes_for_disease("OMIM:106210", 100)
    symbols = {r["gene_symbol"] for r in rows}
    assert "PAX6" in symbols


def test_count_genes_for_disease(repo: HpoRepository) -> None:
    """count_genes_for_disease('OMIM:106210') should be at least 1."""
    count = repo.count_genes_for_disease("OMIM:106210")
    assert count >= 1


def test_genes_for_disease_146510(repo: HpoRepository) -> None:
    """genes_for_disease('OMIM:146510') should include GLI3."""
    rows = repo.genes_for_disease("OMIM:146510", 100)
    symbols = {r["gene_symbol"] for r in rows}
    assert "GLI3" in symbols


# -- gene -> disease ---------------------------------------------------------


def test_diseases_for_gene_by_symbol(repo: HpoRepository) -> None:
    """diseases_for_gene('symbol', 'PAX6') should include OMIM:106210."""
    rows = repo.diseases_for_gene("symbol", "PAX6", 100)
    ids = {r["disease_id"] for r in rows}
    assert "OMIM:106210" in ids


def test_count_diseases_for_gene(repo: HpoRepository) -> None:
    """count_diseases_for_gene('symbol', 'PAX6') should be at least 1."""
    count = repo.count_diseases_for_gene("symbol", "PAX6")
    assert count >= 1


def test_diseases_for_gene_by_ncbi(repo: HpoRepository) -> None:
    """diseases_for_gene('ncbi', '5080') should include OMIM:106210."""
    rows = repo.diseases_for_gene("ncbi", "5080", 100)
    ids = {r["disease_id"] for r in rows}
    assert "OMIM:106210" in ids


def test_diseases_for_gene_gli3(repo: HpoRepository) -> None:
    """diseases_for_gene('symbol', 'GLI3') should include OMIM:146510."""
    rows = repo.diseases_for_gene("symbol", "GLI3", 100)
    ids = {r["disease_id"] for r in rows}
    assert "OMIM:146510" in ids
