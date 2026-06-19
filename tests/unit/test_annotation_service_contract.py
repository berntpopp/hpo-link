"""Contract tests for AnnotationService — absent-entity, validation, response-mode behaviour.

Covers:
- T1.2  Absent-entity contract: well-formed but unknown inputs return empty 200 pages (not errors);
         malformed inputs raise InvalidInputError with the correct ``field`` attribute.
- T2.1  Compact rows drop null/empty fields; standard rows preserve all columns.
- T2.2  ``recommended_citation`` is gated to standard / full mode only.
- T3.2  Gene-path frequency triplet (frequency_hpo, frequency_ratio, frequency_percent) decoded
         at standard mode; raw ``frequency`` field preserved; symmetry with disease path.

Fixture-world facts (mini DB, same as test_annotation_service.py):
- PAX6 (NCBI: 5080) is annotated to HP:0000479 (Abnormal retinal morphology)
- GLI3 (NCBI: 2737) is annotated to HP:0000478 (Abnormality of the eye)
- HP:0000118 ("Phenotypic abnormality") is a root ancestor of HP:0000479 and HP:0000478
- OMIM:106210 (Aniridia) is annotated to HP:0000479 and is associated with PAX6
- OMIM:146510 (Acrocallosal syndrome) is annotated to HP:0000478 and is associated with GLI3

The ``annotation_service`` fixture is provided by tests/conftest.py (session-scoped).
"""

from __future__ import annotations

import pytest

from hpo_link.exceptions import InvalidInputError
from hpo_link.services.annotation_service import AnnotationService

# ===========================================================================
# T1.2 absent-entity contract
# ===========================================================================


def test_phenotypes_for_gene_well_formed_absent_returns_empty(
    annotation_service: AnnotationService,
) -> None:
    """Well-formed but unknown gene returns empty 200 page (NOT not_found).

    NCBIGene:999999999 is a valid CURIE shape but has no annotations.
    """
    result = annotation_service.get_phenotypes_for_gene("NCBIGene:999999999")
    assert result["total"] == 0
    assert result["phenotypes"] == []


def test_phenotypes_for_gene_well_formed_absent_bare_symbol(
    annotation_service: AnnotationService,
) -> None:
    """Well-formed but unknown gene symbol returns empty 200 page (NOT not_found)."""
    result = annotation_service.get_phenotypes_for_gene("NOTAREALGENE99999")
    assert result["total"] == 0
    assert result["phenotypes"] == []


def test_phenotypes_for_gene_malformed_ncbi_curie_non_digit(
    annotation_service: AnnotationService,
) -> None:
    """NCBIGene CURIE with non-digit body raises InvalidInputError."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_phenotypes_for_gene("NCBIGene:abc")
    assert exc_info.value.field == "gene"


def test_phenotypes_for_gene_malformed_wrong_curie_prefix(
    annotation_service: AnnotationService,
) -> None:
    """A non-NCBIGene CURIE (e.g. HGNC:1234) raises InvalidInputError."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_phenotypes_for_gene("HGNC:1234")
    assert exc_info.value.field == "gene"


def test_diseases_for_gene_well_formed_absent_returns_empty(
    annotation_service: AnnotationService,
) -> None:
    """Well-formed but unknown gene returns empty page for get_diseases_for_gene."""
    result = annotation_service.get_diseases_for_gene("NOTAREALGENE99999")
    assert result["total"] == 0
    assert result["diseases"] == []


def test_diseases_for_gene_malformed_ncbi_curie(
    annotation_service: AnnotationService,
) -> None:
    """NCBIGene CURIE with non-digit body raises InvalidInputError for get_diseases_for_gene."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_diseases_for_gene("NCBIGene:abc")
    assert exc_info.value.field == "gene"


def test_phenotypes_for_disease_malformed_no_colon(
    annotation_service: AnnotationService,
) -> None:
    """disease_id without colon (e.g. 'notacurie') raises InvalidInputError."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_phenotypes_for_disease("notacurie")
    assert exc_info.value.field == "disease_id"


def test_phenotypes_for_disease_malformed_empty_prefix(
    annotation_service: AnnotationService,
) -> None:
    """disease_id with empty prefix raises InvalidInputError."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_phenotypes_for_disease(":123")
    assert exc_info.value.field == "disease_id"


def test_phenotypes_for_disease_malformed_empty_body(
    annotation_service: AnnotationService,
) -> None:
    """disease_id with empty body (e.g. 'OMIM:') raises InvalidInputError."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_phenotypes_for_disease("OMIM:")
    assert exc_info.value.field == "disease_id"


def test_phenotypes_for_disease_well_formed_absent_returns_empty(
    annotation_service: AnnotationService,
) -> None:
    """Well-formed but unknown disease_id returns empty 200 page."""
    result = annotation_service.get_phenotypes_for_disease("OMIM:9999999")
    assert result["total"] == 0
    assert result["phenotypes"] == []


def test_genes_for_disease_malformed_no_colon(
    annotation_service: AnnotationService,
) -> None:
    """disease_id without colon raises InvalidInputError for get_genes_for_disease."""
    with pytest.raises(InvalidInputError) as exc_info:
        annotation_service.get_genes_for_disease("notacurie")
    assert exc_info.value.field == "disease_id"


def test_genes_for_disease_well_formed_absent_returns_empty(
    annotation_service: AnnotationService,
) -> None:
    """Well-formed but unknown disease_id returns empty 200 page for get_genes_for_disease."""
    result = annotation_service.get_genes_for_disease("OMIM:9999999")
    assert result["total"] == 0
    assert result["genes"] == []


# ===========================================================================
# T2.1 compact rows drop null/empty
# ===========================================================================


def test_compact_disease_phenotype_rows_no_empty_fields(
    annotation_service: AnnotationService,
) -> None:
    """In compact mode, disease phenotype rows should have no null/empty-string fields."""
    result = annotation_service.get_phenotypes_for_disease("OMIM:106210", response_mode="compact")
    phenotypes = result.get("phenotypes", [])
    assert phenotypes, "Expected phenotype rows from OMIM:106210"
    for row in phenotypes:
        for key, val in row.items():
            assert val is not None and val != "" and val != [] and val != {}, (
                f"compact row contains empty field '{key}': {val!r}"
            )


def test_standard_disease_phenotype_rows_preserve_all_fields(
    annotation_service: AnnotationService,
) -> None:
    """In standard mode, disease phenotype rows keep all columns (no trimming)."""
    result_compact = annotation_service.get_phenotypes_for_disease(
        "OMIM:106210", response_mode="compact"
    )
    result_standard = annotation_service.get_phenotypes_for_disease(
        "OMIM:106210", response_mode="standard"
    )
    # Standard should have at least as many keys per row as compact
    if result_compact["phenotypes"] and result_standard["phenotypes"]:
        compact_keys = set(result_compact["phenotypes"][0].keys())
        standard_keys = set(result_standard["phenotypes"][0].keys())
        assert standard_keys >= compact_keys


def test_compact_gene_phenotype_rows_no_empty_fields(
    annotation_service: AnnotationService,
) -> None:
    """In compact mode, gene phenotype rows should have no null/empty-string fields."""
    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="compact")
    phenotypes = result.get("phenotypes", [])
    assert phenotypes, "Expected phenotype rows for PAX6"
    for row in phenotypes:
        for key, val in row.items():
            assert val is not None and val != "" and val != [] and val != {}, (
                f"compact gene row contains empty field '{key}': {val!r}"
            )


# ===========================================================================
# T2.2 recommended_citation gated to standard/full
# ===========================================================================


def test_recommended_citation_present_at_standard(
    annotation_service: AnnotationService,
) -> None:
    """recommended_citation is present in standard mode."""
    from hpo_link.constants import RECOMMENDED_CITATION

    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="standard")
    assert result.get("recommended_citation") == RECOMMENDED_CITATION


def test_recommended_citation_present_at_full(
    annotation_service: AnnotationService,
) -> None:
    """recommended_citation is present in full mode."""
    from hpo_link.constants import RECOMMENDED_CITATION

    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="full")
    assert result.get("recommended_citation") == RECOMMENDED_CITATION


def test_recommended_citation_absent_at_compact(
    annotation_service: AnnotationService,
) -> None:
    """recommended_citation is NOT present in compact mode (token efficiency)."""
    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="compact")
    assert "recommended_citation" not in result


def test_recommended_citation_absent_at_minimal(
    annotation_service: AnnotationService,
) -> None:
    """recommended_citation is NOT present in minimal mode."""
    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="minimal")
    assert "recommended_citation" not in result


def test_hpo_version_always_present(annotation_service: AnnotationService) -> None:
    """hpo_version is present in compact and standard modes."""
    for mode in ("compact", "standard", "full"):
        result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode=mode)
        assert result.get("hpo_version"), f"hpo_version missing in {mode!r} mode"


# ===========================================================================
# T3.2 gene-path frequency decoded
# ===========================================================================


def test_gene_phenotype_rows_have_frequency_triplet_at_standard(
    annotation_service: AnnotationService,
) -> None:
    """Gene phenotype rows at standard mode include frequency_hpo, frequency_ratio, frequency_percent."""
    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="standard")
    phenotypes = result.get("phenotypes", [])
    assert phenotypes, "Expected at least one phenotype row"
    first = phenotypes[0]
    # All three keys must exist (values may be None)
    assert "frequency_hpo" in first, "Missing frequency_hpo"
    assert "frequency_ratio" in first, "Missing frequency_ratio"
    assert "frequency_percent" in first, "Missing frequency_percent"


def test_gene_phenotype_raw_frequency_preserved(
    annotation_service: AnnotationService,
) -> None:
    """Gene phenotype rows at standard mode preserve raw 'frequency' field."""
    result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="standard")
    phenotypes = result.get("phenotypes", [])
    assert phenotypes, "Expected at least one phenotype row"
    # Raw frequency key must remain
    assert "frequency" in phenotypes[0], "Raw frequency field missing"


def test_disease_and_gene_phenotype_rows_frequency_keys_symmetric(
    annotation_service: AnnotationService,
) -> None:
    """Gene and disease phenotype rows have the same frequency triplet keys."""
    gene_result = annotation_service.get_phenotypes_for_gene("PAX6", response_mode="standard")
    disease_result = annotation_service.get_phenotypes_for_disease(
        "OMIM:106210", response_mode="standard"
    )
    gene_phenotypes = gene_result.get("phenotypes", [])
    disease_phenotypes = disease_result.get("phenotypes", [])
    if gene_phenotypes and disease_phenotypes:
        gene_freq_keys = {k for k in gene_phenotypes[0] if "frequency" in k}
        disease_freq_keys = {k for k in disease_phenotypes[0] if "frequency" in k}
        assert gene_freq_keys == disease_freq_keys, (
            f"Frequency key mismatch: gene={gene_freq_keys}, disease={disease_freq_keys}"
        )
