"""Locks the uniform absent-entity contract across the 6 association tools.

Assessment B.2 (prior T1.1-T1.3): one rule, uniform across every association tool —
  * malformed identifier            -> InvalidInputError (invalid_input)
  * well-formed but unknown id       -> empty 200 page (total:0), NOT not_found
  * not_found is reserved for genuine identity-resolution failure (resolve_*).

This contract is already implemented; this file is the regression gate that keeps
the six tools collapsed to a single rule.

Fixture-world facts (tests/fixtures): PAX6 <-> HP:0000479 <-> OMIM:106210.
HP:0000001 ("All") resolves but has no direct gene/disease annotations.
"""

from __future__ import annotations

import pytest

from hpo_link.exceptions import InvalidInputError
from hpo_link.services.annotation_service import AnnotationService

# (method, malformed_arg, well_formed_absent_arg, rows_key)
GENE_TOOLS = [
    ("get_phenotypes_for_gene", "NCBIGene:abc", "NCBIGene:999999999", "phenotypes"),
    ("get_diseases_for_gene", "NCBIGene:abc", "NCBIGene:999999999", "diseases"),
]
DISEASE_TOOLS = [
    ("get_phenotypes_for_disease", "notacurie", "OMIM:0000000", "phenotypes"),
    ("get_genes_for_disease", "notacurie", "OMIM:0000000", "genes"),
]
PHENO_TOOLS = [
    ("get_genes_for_phenotype", "", "HP:0000001", "genes"),
    ("get_diseases_for_phenotype", "", "HP:0000001", "diseases"),
]
ALL_TOOLS = GENE_TOOLS + DISEASE_TOOLS + PHENO_TOOLS


@pytest.mark.parametrize("method,bad,_absent,_key", ALL_TOOLS)
def test_malformed_id_raises_invalid_input(
    annotation_service: AnnotationService, method: str, bad: str, _absent: str, _key: str
) -> None:
    """A malformed/empty identifier raises InvalidInputError on every association tool."""
    with pytest.raises(InvalidInputError):
        getattr(annotation_service, method)(bad)


@pytest.mark.parametrize("method,_bad,absent,key", ALL_TOOLS)
def test_well_formed_absent_returns_empty_page(
    annotation_service: AnnotationService, method: str, _bad: str, absent: str, key: str
) -> None:
    """A well-formed-but-unknown id returns an empty 200 page (total:0), not not_found."""
    out = getattr(annotation_service, method)(absent)
    assert out["total"] == 0
    assert out["returned"] == 0
    assert out[key] == []
