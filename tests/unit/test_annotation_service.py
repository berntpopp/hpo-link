"""Tests for AnnotationService — gene/disease/phenotype annotation queries.

TDD: tests were written before the implementation.  Fixture-world facts:
- PAX6 (NCBI: 5080) is annotated to HP:0000479 (Abnormal retinal morphology)
- GLI3 (NCBI: 2737) is annotated to HP:0000478 (Abnormality of the eye)
- HP:0000118 ("Phenotypic abnormality") is a root ancestor of HP:0000479 and HP:0000478
- OMIM:106210 (Aniridia) is annotated to HP:0000479 and is associated with PAX6
- OMIM:146510 (Acrocallosal syndrome) is annotated to HP:0000478 and is associated with GLI3
"""

from __future__ import annotations

import pytest

from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import InvalidInputError, NotFoundError
from hpo_link.services.annotation_service import AnnotationService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def svc(repo: HpoRepository) -> AnnotationService:
    """AnnotationService bound to the fixture repository."""
    return AnnotationService(repo)


# ---------------------------------------------------------------------------
# get_phenotypes_for_gene
# ---------------------------------------------------------------------------


def test_phenotypes_for_gene_pax6(svc: AnnotationService) -> None:
    """PAX6 should return phenotypes including HP:0000479."""
    result = svc.get_phenotypes_for_gene("PAX6")
    hpo_ids = [p["hpo_id"] for p in result["phenotypes"]]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_gene_lowercase(svc: AnnotationService) -> None:
    """pax6 (lowercase) should return same phenotypes (case-insensitive normalisation)."""
    result = svc.get_phenotypes_for_gene("pax6")
    hpo_ids = [p["hpo_id"] for p in result["phenotypes"]]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_gene_ncbi_id(svc: AnnotationService) -> None:
    """NCBI ID '5080' should resolve to PAX6 annotations."""
    result = svc.get_phenotypes_for_gene("5080")
    hpo_ids = [p["hpo_id"] for p in result["phenotypes"]]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_gene_ncbi_curie(svc: AnnotationService) -> None:
    """NCBIGene:5080 CURIE should resolve to PAX6 annotations."""
    result = svc.get_phenotypes_for_gene("NCBIGene:5080")
    hpo_ids = [p["hpo_id"] for p in result["phenotypes"]]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_gene_fields(svc: AnnotationService) -> None:
    """Response must include all required pagination fields."""
    result = svc.get_phenotypes_for_gene("PAX6")
    for field in ("gene", "gene_kind", "gene_value", "phenotypes",
                  "total", "returned", "limit", "offset", "truncated",
                  "hpo_version", "recommended_citation"):
        assert field in result, f"Missing field: {field}"


def test_phenotypes_for_gene_hpo_version(svc: AnnotationService) -> None:
    """Response must carry hpo_version (non-empty)."""
    result = svc.get_phenotypes_for_gene("PAX6")
    assert result["hpo_version"]


def test_phenotypes_for_gene_recommended_citation(svc: AnnotationService) -> None:
    """Response must carry recommended_citation."""
    from hpo_link.constants import RECOMMENDED_CITATION

    result = svc.get_phenotypes_for_gene("PAX6")
    assert result["recommended_citation"] == RECOMMENDED_CITATION


def test_phenotypes_for_gene_invalid_empty(svc: AnnotationService) -> None:
    """Empty gene string should raise InvalidInputError."""
    with pytest.raises(InvalidInputError):
        svc.get_phenotypes_for_gene("")


def test_phenotypes_for_gene_not_found(svc: AnnotationService) -> None:
    """Unknown gene should raise NotFoundError."""
    with pytest.raises(NotFoundError):
        svc.get_phenotypes_for_gene("NOTAREALGENE99999")


def test_phenotypes_for_gene_pagination(svc: AnnotationService) -> None:
    """Limit and offset fields should be present and correct."""
    result = svc.get_phenotypes_for_gene("PAX6", limit=1, offset=0)
    assert result["limit"] == 1
    assert result["offset"] == 0
    assert result["returned"] <= 1


# ---------------------------------------------------------------------------
# get_genes_for_phenotype
# ---------------------------------------------------------------------------


def test_genes_for_phenotype_direct(svc: AnnotationService) -> None:
    """HP:0000479 → genes should include PAX6."""
    result = svc.get_genes_for_phenotype("HP:0000479")
    symbols = {g["gene_symbol"] for g in result["genes"]}
    assert "PAX6" in symbols


def test_genes_for_phenotype_no_descendants(svc: AnnotationService) -> None:
    """HP:0000118 without descendants should NOT include PAX6 (only annotated to child terms)."""
    result = svc.get_genes_for_phenotype("HP:0000118", include_descendants=False)
    symbols = {g["gene_symbol"] for g in result["genes"]}
    assert "PAX6" not in symbols


def test_genes_for_phenotype_with_descendants(svc: AnnotationService) -> None:
    """HP:0000118 with descendants should include PAX6 (via HP:0000479) and GLI3 (via HP:0000478)."""
    result = svc.get_genes_for_phenotype("HP:0000118", include_descendants=True)
    symbols = {g["gene_symbol"] for g in result["genes"]}
    assert "PAX6" in symbols
    assert "GLI3" in symbols


def test_genes_for_phenotype_fields(svc: AnnotationService) -> None:
    """Response must include all required fields."""
    result = svc.get_genes_for_phenotype("HP:0000479")
    for field in ("term", "hpo_id", "genes", "total", "returned", "limit",
                  "offset", "truncated", "include_descendants",
                  "hpo_version", "recommended_citation"):
        assert field in result, f"Missing field: {field}"


def test_genes_for_phenotype_include_descendants_field(svc: AnnotationService) -> None:
    """include_descendants flag is echoed in the response."""
    result_no = svc.get_genes_for_phenotype("HP:0000479", include_descendants=False)
    result_yes = svc.get_genes_for_phenotype("HP:0000479", include_descendants=True)
    assert result_no["include_descendants"] is False
    assert result_yes["include_descendants"] is True


def test_genes_for_phenotype_hpo_version(svc: AnnotationService) -> None:
    """Response must carry hpo_version."""
    result = svc.get_genes_for_phenotype("HP:0000479")
    assert result["hpo_version"]


def test_genes_for_phenotype_recommended_citation(svc: AnnotationService) -> None:
    """Response must carry recommended_citation."""
    from hpo_link.constants import RECOMMENDED_CITATION

    result = svc.get_genes_for_phenotype("HP:0000479")
    assert result["recommended_citation"] == RECOMMENDED_CITATION


# ---------------------------------------------------------------------------
# get_phenotypes_for_disease
# ---------------------------------------------------------------------------


def test_phenotypes_for_disease_omim_106210(svc: AnnotationService) -> None:
    """OMIM:106210 (Aniridia) should return phenotypes including HP:0000479."""
    result = svc.get_phenotypes_for_disease("OMIM:106210")
    hpo_ids = [p["hpo_id"] for p in result["phenotypes"]]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_disease_fields(svc: AnnotationService) -> None:
    """Response must include all required fields."""
    result = svc.get_phenotypes_for_disease("OMIM:106210")
    for field in ("disease_id", "phenotypes", "total", "returned", "limit",
                  "offset", "truncated", "hpo_version", "recommended_citation"):
        assert field in result, f"Missing field: {field}"


def test_phenotypes_for_disease_hpo_version(svc: AnnotationService) -> None:
    """Response must carry hpo_version."""
    result = svc.get_phenotypes_for_disease("OMIM:106210")
    assert result["hpo_version"]


def test_phenotypes_for_disease_recommended_citation(svc: AnnotationService) -> None:
    """Response must carry recommended_citation."""
    from hpo_link.constants import RECOMMENDED_CITATION

    result = svc.get_phenotypes_for_disease("OMIM:106210")
    assert result["recommended_citation"] == RECOMMENDED_CITATION


def test_phenotypes_for_disease_invalid_empty(svc: AnnotationService) -> None:
    """Empty disease_id should raise InvalidInputError."""
    with pytest.raises(InvalidInputError):
        svc.get_phenotypes_for_disease("")


def test_phenotypes_for_disease_normalisation(svc: AnnotationService) -> None:
    """omim:106210 (lowercase prefix) should be normalised to OMIM:106210."""
    result = svc.get_phenotypes_for_disease("omim:106210")
    assert result["disease_id"] == "OMIM:106210"
    hpo_ids = [p["hpo_id"] for p in result["phenotypes"]]
    assert "HP:0000479" in hpo_ids


def test_phenotypes_for_disease_pagination(svc: AnnotationService) -> None:
    """Limit and offset fields must be echoed correctly."""
    result = svc.get_phenotypes_for_disease("OMIM:106210", limit=1, offset=0)
    assert result["limit"] == 1
    assert result["returned"] <= 1


# ---------------------------------------------------------------------------
# get_diseases_for_phenotype
# ---------------------------------------------------------------------------


def test_diseases_for_phenotype_direct(svc: AnnotationService) -> None:
    """HP:0000479 → diseases should include OMIM:106210."""
    result = svc.get_diseases_for_phenotype("HP:0000479")
    ids = {d["database_id"] for d in result["diseases"]}
    assert "OMIM:106210" in ids


def test_diseases_for_phenotype_with_descendants(svc: AnnotationService) -> None:
    """HP:0000118 with descendants should include both OMIM:106210 and OMIM:146510."""
    result = svc.get_diseases_for_phenotype("HP:0000118", include_descendants=True)
    ids = {d["database_id"] for d in result["diseases"]}
    assert "OMIM:106210" in ids
    assert "OMIM:146510" in ids


def test_diseases_for_phenotype_fields(svc: AnnotationService) -> None:
    """Response must include all required fields."""
    result = svc.get_diseases_for_phenotype("HP:0000479")
    for field in ("term", "hpo_id", "diseases", "total", "returned", "limit",
                  "offset", "truncated", "include_descendants",
                  "hpo_version", "recommended_citation"):
        assert field in result, f"Missing field: {field}"


def test_diseases_for_phenotype_hpo_version(svc: AnnotationService) -> None:
    """Response must carry hpo_version."""
    result = svc.get_diseases_for_phenotype("HP:0000479")
    assert result["hpo_version"]


# ---------------------------------------------------------------------------
# get_genes_for_disease
# ---------------------------------------------------------------------------


def test_genes_for_disease_omim_106210(svc: AnnotationService) -> None:
    """OMIM:106210 → genes should include PAX6."""
    result = svc.get_genes_for_disease("OMIM:106210")
    symbols = {g["gene_symbol"] for g in result["genes"]}
    assert "PAX6" in symbols


def test_genes_for_disease_fields(svc: AnnotationService) -> None:
    """Response must include all required fields."""
    result = svc.get_genes_for_disease("OMIM:106210")
    for field in ("disease_id", "genes", "total", "returned", "limit",
                  "offset", "truncated", "hpo_version", "recommended_citation"):
        assert field in result, f"Missing field: {field}"


def test_genes_for_disease_invalid_empty(svc: AnnotationService) -> None:
    """Empty disease_id should raise InvalidInputError."""
    with pytest.raises(InvalidInputError):
        svc.get_genes_for_disease("")


def test_genes_for_disease_hpo_version(svc: AnnotationService) -> None:
    """Response must carry hpo_version."""
    result = svc.get_genes_for_disease("OMIM:106210")
    assert result["hpo_version"]


# ---------------------------------------------------------------------------
# get_diseases_for_gene
# ---------------------------------------------------------------------------


def test_diseases_for_gene_pax6(svc: AnnotationService) -> None:
    """PAX6 → diseases should include OMIM:106210."""
    result = svc.get_diseases_for_gene("PAX6")
    ids = {d["disease_id"] for d in result["diseases"]}
    assert "OMIM:106210" in ids


def test_diseases_for_gene_lowercase(svc: AnnotationService) -> None:
    """pax6 (lowercase) should return same results."""
    result = svc.get_diseases_for_gene("pax6")
    ids = {d["disease_id"] for d in result["diseases"]}
    assert "OMIM:106210" in ids


def test_diseases_for_gene_ncbi_id(svc: AnnotationService) -> None:
    """NCBI ID '5080' → diseases should include OMIM:106210."""
    result = svc.get_diseases_for_gene("5080")
    ids = {d["disease_id"] for d in result["diseases"]}
    assert "OMIM:106210" in ids


def test_diseases_for_gene_fields(svc: AnnotationService) -> None:
    """Response must include all required fields."""
    result = svc.get_diseases_for_gene("PAX6")
    for field in ("gene", "gene_kind", "gene_value", "diseases",
                  "total", "returned", "limit", "offset", "truncated",
                  "hpo_version", "recommended_citation"):
        assert field in result, f"Missing field: {field}"


def test_diseases_for_gene_invalid_empty(svc: AnnotationService) -> None:
    """Empty gene string should raise InvalidInputError."""
    with pytest.raises(InvalidInputError):
        svc.get_diseases_for_gene("")


def test_diseases_for_gene_hpo_version(svc: AnnotationService) -> None:
    """Response must carry hpo_version."""
    result = svc.get_diseases_for_gene("PAX6")
    assert result["hpo_version"]
