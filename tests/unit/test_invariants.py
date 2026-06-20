"""Hierarchy + inverse-agreement invariants (assessment C.5 — Correctness -> 10).

These relations were verified by hand in the prior audit; locking them as
property/invariant tests means the hierarchy and the gene<->disease inverse
cannot silently drift on a future data or query change.

Fixture-world facts (tests/fixtures):
  HP:0000118 -> HP:0000478 -> HP:0000479 (is_a chain)
  PAX6 (NCBIGene:5080) <-> OMIM:106210
"""

from __future__ import annotations

from hpo_link.services.annotation_service import AnnotationService
from hpo_link.services.hpo_service import HpoService


def test_children_subset_of_descendants(hpo_service: HpoService) -> None:
    """Immediate children are always a subset of the transitive descendants."""
    root = "HP:0000118"
    children = {c["hpo_id"] for c in hpo_service.term_children(root)["children"]}
    descendants = {
        d["hpo_id"] for d in hpo_service.term_descendants(root, limit=1000)["descendants"]
    }
    assert children, "fixture root should have at least one child"
    assert children <= descendants


def test_get_term_parents_match_term_parents(hpo_service: HpoService) -> None:
    """get_term().parents agrees with the dedicated get_term_parents tool."""
    term = "HP:0000479"
    via_term = {p["hpo_id"] for p in hpo_service.get_term(term, response_mode="full")["parents"]}
    via_tool = {p["hpo_id"] for p in hpo_service.term_parents(term)["parents"]}
    assert via_term == via_tool
    assert "HP:0000478" in via_tool


def test_gene_disease_inverse_agreement(annotation_service: AnnotationService) -> None:
    """A gene's diseases round-trip: each disease lists the gene back."""
    genes_out = annotation_service.get_diseases_for_gene("PAX6")
    disease_ids = [d["disease_id"] for d in genes_out["diseases"]]
    assert disease_ids, "PAX6 should have at least one associated disease in the fixture"
    for disease_id in disease_ids:
        back = annotation_service.get_genes_for_disease(disease_id)
        symbols = {g.get("gene_symbol", "").upper() for g in back["genes"]}
        assert "PAX6" in symbols, f"{disease_id} did not list PAX6 back (inverse broke)"
