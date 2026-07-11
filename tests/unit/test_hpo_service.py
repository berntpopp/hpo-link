"""Unit tests for HpoService — the HPO ontology service layer.

Fixture-world facts (from mini_hp.json):
  HP:0000001  All
  HP:0000118  Phenotypic abnormality  (parent of HP:0000478)
  HP:0000478  Abnormality of the eye  (parent of HP:0000479)
  HP:0000479  Abnormal retinal morphology
              exact_synonym: "Abnormal retina"
              related_synonym: "Retinal abnormality"
              xref: UMLS:C0151888
  HP:0000489  obsolete Abnormal electroretinogram
"""

from __future__ import annotations

import pytest

from hpo_link.exceptions import InvalidInputError, NotFoundError
from hpo_link.services.hpo_service import HpoService

# ---------------------------------------------------------------------------
# resolve_term
# ---------------------------------------------------------------------------


def test_resolve_term_by_primary_label(hpo_service: HpoService) -> None:
    """resolve_term('Phenotypic abnormality') -> HP:0000118, match_type=primary."""
    result = hpo_service.resolve_term("Phenotypic abnormality")
    assert result["hpo_id"] == "HP:0000118"
    assert result["match_type"] == "primary"
    assert result["query"] == "Phenotypic abnormality"
    assert "hpo_version" in result
    assert "recommended_citation" not in result  # compact gates the long citation (F-1)


def test_resolve_term_by_hpo_id(hpo_service: HpoService) -> None:
    """resolve_term('HP:0000479') -> HP:0000479, match_type=hpo_id."""
    result = hpo_service.resolve_term("HP:0000479")
    assert result["hpo_id"] == "HP:0000479"
    assert result["match_type"] == "hpo_id"


def test_resolve_term_by_exact_synonym(hpo_service: HpoService) -> None:
    """resolve_term('Abnormal retina') -> HP:0000479, match_type=exact_synonym."""
    result = hpo_service.resolve_term("Abnormal retina")
    assert result["hpo_id"] == "HP:0000479"
    assert result["match_type"] == "exact_synonym"


def test_resolve_term_not_found_raises(hpo_service: HpoService) -> None:
    """resolve_term on a totally unknown term raises NotFoundError."""
    with pytest.raises(NotFoundError):
        hpo_service.resolve_term("nonexistent_zzz99")


def test_resolve_term_result_has_name(hpo_service: HpoService) -> None:
    """resolve_term result carries a non-empty 'name' field."""
    result = hpo_service.resolve_term("HP:0000118")
    assert result["name"] == "Phenotypic abnormality"


def test_resolve_term_obsolete_flag(hpo_service: HpoService) -> None:
    """resolve_term for a non-obsolete term has obsolete=False."""
    result = hpo_service.resolve_term("HP:0000479")
    assert result["obsolete"] is False


def test_resolve_term_by_related_synonym(hpo_service: HpoService) -> None:
    """resolve_term('Retinal abnormality') -> HP:0000479, match_type=related_synonym."""
    result = hpo_service.resolve_term("Retinal abnormality")
    assert result["hpo_id"] == "HP:0000479"
    assert result["match_type"] == "related_synonym"


def test_resolve_term_by_alt_id(hpo_service: HpoService) -> None:
    """resolve_term('HP:0001098') -> HP:0000479, match_type=alt_id (HP:0001098 is an alt_id)."""
    result = hpo_service.resolve_term("HP:0001098")
    assert result["hpo_id"] == "HP:0000479"
    assert result["match_type"] == "alt_id"


# ---------------------------------------------------------------------------
# search_terms
# ---------------------------------------------------------------------------


def test_search_terms_returns_results(hpo_service: HpoService) -> None:
    """search_terms('retina') returns a dict with a non-empty results list."""
    result = hpo_service.search_terms("retina")
    assert "results" in result
    assert isinstance(result["results"], list)
    assert len(result["results"]) >= 1


def test_search_terms_contains_hp0000479(hpo_service: HpoService) -> None:
    """search_terms('retina') contains HP:0000479."""
    result = hpo_service.search_terms("retina")
    hpo_ids = [r["hpo_id"] for r in result["results"]]
    assert "HP:0000479" in hpo_ids


def test_search_terms_pagination_fields(hpo_service: HpoService) -> None:
    """search_terms result has pagination fields: total, returned, limit, offset, truncated."""
    result = hpo_service.search_terms("retina")
    for key in ("total", "returned", "limit", "offset", "truncated"):
        assert key in result, f"Missing key: {key}"


def test_search_terms_version_and_citation_gated(hpo_service: HpoService) -> None:
    """search_terms (compact) carries hpo_version but gates the long citation."""
    result = hpo_service.search_terms("retina")
    assert "hpo_version" in result
    assert "recommended_citation" not in result
    rich = hpo_service.search_terms("retina", response_mode="full")
    assert "recommended_citation" in rich


def test_search_terms_full_page_of_200_definitions_does_not_raise() -> None:
    """A full 200-hit page, each with a fenced definition, must not trip the limit.

    ``search_terms`` caps ``limit`` at 200 (``mcp/tools/ontology.py`` ``le=200``),
    and full mode fences one ``untrusted_text`` object per definition. The default
    untrusted-object ceiling is 128, so the search enforce call must raise its
    ceiling to the recorded 200 cap; otherwise a legitimate ``limit=200`` full-mode
    search would error with ``UntrustedTextLimitError``.
    """

    class _StubRepo:
        def read_meta(self) -> dict[str, str]:
            return {"hpo_version": "2026-01-01"}

        def search(
            self, query: str, *, limit: int, include_obsolete: bool, offset: int = 0
        ) -> tuple[list[dict[str, object]], int]:
            hits = [
                {
                    "hpo_id": f"HP:{i:07d}",
                    "name": f"Term {i}",
                    "definition": f"Definition prose for term {i}.",
                    "score": -float(i),
                }
                for i in range(limit)
            ]
            return hits, 1000

    svc = HpoService(_StubRepo())  # type: ignore[arg-type]
    result = svc.search_terms("phenotype", limit=200, response_mode="full")

    assert len(result["results"]) == 200
    # every hit's definition is the fenced typed object, not a bare string
    fenced = result["results"][0]["definition"]
    assert fenced["kind"] == "untrusted_text"


def test_search_terms_empty_query_raises(hpo_service: HpoService) -> None:
    """search_terms with empty query raises InvalidInputError."""
    with pytest.raises(InvalidInputError):
        hpo_service.search_terms("")


def test_search_terms_whitespace_query_raises(hpo_service: HpoService) -> None:
    """search_terms with whitespace-only query raises InvalidInputError."""
    with pytest.raises(InvalidInputError):
        hpo_service.search_terms("   ")


# ---------------------------------------------------------------------------
# get_term
# ---------------------------------------------------------------------------


def test_get_term_minimal_mode_no_definition(hpo_service: HpoService) -> None:
    """get_term('HP:0000118', response_mode='minimal') has no 'definition' key."""
    result = hpo_service.get_term("HP:0000118", response_mode="minimal")
    assert "definition" not in result


def test_get_term_minimal_mode_has_hpo_id_and_name(hpo_service: HpoService) -> None:
    """get_term minimal mode keeps hpo_id and name."""
    result = hpo_service.get_term("HP:0000118", response_mode="minimal")
    assert result["hpo_id"] == "HP:0000118"
    assert result["name"] == "Phenotypic abnormality"
    assert "hpo_version" in result, "minimal mode must include hpo_version per spec"
    assert "recommended_citation" not in result, (
        "minimal gates the long citation (fetched once from get_server_capabilities)"
    )


def test_get_term_compact_has_required_fields(hpo_service: HpoService) -> None:
    """get_term('HP:0000479') compact returns hpo_id, name, hpo_version; gates the citation."""
    result = hpo_service.get_term("HP:0000479")
    assert result["hpo_id"] == "HP:0000479"
    assert "name" in result
    assert "hpo_version" in result
    assert "recommended_citation" not in result


def test_get_term_by_label(hpo_service: HpoService) -> None:
    """get_term resolves by label, not just direct HP id."""
    result = hpo_service.get_term("Phenotypic abnormality")
    assert result["hpo_id"] == "HP:0000118"


def test_get_term_compact_has_parents_and_children(hpo_service: HpoService) -> None:
    """get_term compact mode includes parents and children lists."""
    result = hpo_service.get_term("HP:0000478")
    assert "parents" in result
    assert "children" in result
    assert isinstance(result["parents"], list)
    assert isinstance(result["children"], list)


def test_get_term_not_found_raises(hpo_service: HpoService) -> None:
    """get_term for unknown term raises NotFoundError."""
    with pytest.raises(NotFoundError):
        hpo_service.get_term("HP:9999999")


# ---------------------------------------------------------------------------
# term_parents / term_children
# ---------------------------------------------------------------------------


def test_term_parents_returns_list(hpo_service: HpoService) -> None:
    """term_parents('HP:0000479') returns dict with parents list."""
    result = hpo_service.term_parents("HP:0000479")
    assert "parents" in result
    assert isinstance(result["parents"], list)
    assert result["hpo_id"] == "HP:0000479"
    assert "count" in result


def test_term_parents_content(hpo_service: HpoService) -> None:
    """term_parents('HP:0000479') includes HP:0000478 as a parent."""
    result = hpo_service.term_parents("HP:0000479")
    parent_ids = [p["hpo_id"] for p in result["parents"]]
    assert "HP:0000478" in parent_ids


def test_term_children_returns_list(hpo_service: HpoService) -> None:
    """term_children('HP:0000478') returns dict with children list."""
    result = hpo_service.term_children("HP:0000478")
    assert "children" in result
    assert isinstance(result["children"], list)


def test_term_children_content(hpo_service: HpoService) -> None:
    """term_children('HP:0000478') includes HP:0000479."""
    result = hpo_service.term_children("HP:0000478")
    child_ids = [c["hpo_id"] for c in result["children"]]
    assert "HP:0000479" in child_ids


def test_term_parents_has_version(hpo_service: HpoService) -> None:
    """term_parents (compact) carries hpo_version; gates the long citation."""
    result = hpo_service.term_parents("HP:0000479")
    assert "hpo_version" in result
    assert "recommended_citation" not in result


# ---------------------------------------------------------------------------
# term_ancestors / term_descendants
# ---------------------------------------------------------------------------


def test_term_ancestors_returns_dict(hpo_service: HpoService) -> None:
    """term_ancestors('HP:0000118', limit=10) returns paginated result."""
    result = hpo_service.term_ancestors("HP:0000118", limit=10)
    assert "ancestors" in result
    assert isinstance(result["ancestors"], list)
    assert result["hpo_id"] == "HP:0000118"


def test_term_ancestors_pagination_fields(hpo_service: HpoService) -> None:
    """term_ancestors result includes all pagination fields."""
    result = hpo_service.term_ancestors("HP:0000118", limit=10)
    for key in ("total", "returned", "limit", "offset", "truncated"):
        assert key in result, f"Missing pagination key: {key}"


def test_term_ancestors_has_version(hpo_service: HpoService) -> None:
    """term_ancestors (compact) carries hpo_version; gates the long citation."""
    result = hpo_service.term_ancestors("HP:0000118", limit=10)
    assert "hpo_version" in result
    assert "recommended_citation" not in result


def test_term_descendants_returns_dict(hpo_service: HpoService) -> None:
    """term_descendants('HP:0000118') returns paginated result with descendants."""
    result = hpo_service.term_descendants("HP:0000118", limit=10)
    assert "descendants" in result
    assert isinstance(result["descendants"], list)


def test_term_descendants_content(hpo_service: HpoService) -> None:
    """term_descendants('HP:0000118') includes HP:0000479 (transitive)."""
    result = hpo_service.term_descendants("HP:0000118", limit=50)
    desc_ids = [d["hpo_id"] for d in result["descendants"]]
    assert "HP:0000479" in desc_ids


# ---------------------------------------------------------------------------
# resolve_xref
# ---------------------------------------------------------------------------


def test_resolve_xref_returns_matches(hpo_service: HpoService) -> None:
    """resolve_xref('UMLS:C0151888') returns matches containing HP:0000479."""
    result = hpo_service.resolve_xref("UMLS:C0151888")
    assert "matches" in result
    hpo_ids = [m["hpo_id"] for m in result["matches"]]
    assert "HP:0000479" in hpo_ids


def test_resolve_xref_pagination_fields(hpo_service: HpoService) -> None:
    """resolve_xref result has xref_id + pagination fields."""
    result = hpo_service.resolve_xref("UMLS:C0151888")
    assert result["xref_id"] == "UMLS:C0151888"
    for key in ("total", "returned", "limit", "offset", "truncated"):
        assert key in result


def test_resolve_xref_has_version(hpo_service: HpoService) -> None:
    """resolve_xref (compact) carries hpo_version; gates the long citation."""
    result = hpo_service.resolve_xref("UMLS:C0151888")
    assert "hpo_version" in result
    assert "recommended_citation" not in result


# ---------------------------------------------------------------------------
# map_cross_ontology
# ---------------------------------------------------------------------------


def test_map_cross_ontology_returns_mappings(hpo_service: HpoService) -> None:
    """map_cross_ontology('HP:0000118') returns dict with hpo_id and mappings."""
    result = hpo_service.map_cross_ontology("HP:0000118")
    assert "hpo_id" in result
    assert "mappings" in result
    assert result["hpo_id"] == "HP:0000118"


def test_map_cross_ontology_with_xref_term(hpo_service: HpoService) -> None:
    """map_cross_ontology('HP:0000479') returns UMLS mapping."""
    result = hpo_service.map_cross_ontology("HP:0000479")
    assert "mappings" in result
    assert isinstance(result["mappings"], dict)
    # HP:0000479 has UMLS:C0151888 xref
    assert "UMLS" in result["mappings"]


def test_map_cross_ontology_has_version(hpo_service: HpoService) -> None:
    """map_cross_ontology (compact) carries hpo_version; gates the long citation."""
    result = hpo_service.map_cross_ontology("HP:0000118")
    assert "hpo_version" in result
    assert "recommended_citation" not in result


# ---------------------------------------------------------------------------
# citation gating across response modes (assessment F-1 / Phase A.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["minimal", "compact"])
def test_resolve_term_omits_citation_in_lean_modes(hpo_service: HpoService, mode: str) -> None:
    """resolve_term keeps hpo_version but drops the long citation at minimal/compact."""
    out = hpo_service.resolve_term("Phenotypic abnormality", response_mode=mode)
    assert out["hpo_version"]
    assert "recommended_citation" not in out


@pytest.mark.parametrize("mode", ["standard", "full"])
def test_resolve_term_keeps_citation_in_rich_modes(hpo_service: HpoService, mode: str) -> None:
    """resolve_term inlines the long citation at standard/full."""
    from hpo_link.constants import RECOMMENDED_CITATION

    out = hpo_service.resolve_term("Phenotypic abnormality", response_mode=mode)
    assert out["recommended_citation"] == RECOMMENDED_CITATION


@pytest.mark.parametrize("mode", ["minimal", "compact"])
def test_get_term_omits_citation_in_lean_modes(hpo_service: HpoService, mode: str) -> None:
    """get_term keeps hpo_version but drops the long citation at minimal/compact."""
    out = hpo_service.get_term("HP:0000118", response_mode=mode)
    assert out["hpo_version"]
    assert "recommended_citation" not in out


def test_get_term_keeps_citation_in_full(hpo_service: HpoService) -> None:
    """get_term inlines the long citation at full."""
    from hpo_link.constants import RECOMMENDED_CITATION

    out = hpo_service.get_term("HP:0000118", response_mode="full")
    assert out["recommended_citation"] == RECOMMENDED_CITATION


# ---------------------------------------------------------------------------
# match_confidence (assessment C.5 — numeric grounding signal)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_type,expected_conf",
    [
        ("HP:0000118", "hpo_id", 1.0),
        ("Phenotypic abnormality", "primary", 1.0),
        ("Abnormal retina", "exact_synonym", 0.95),
        ("Retinal abnormality", "related_synonym", 0.8),
    ],
)
def test_resolve_term_match_confidence(
    hpo_service: HpoService, query: str, expected_type: str, expected_conf: float
) -> None:
    """resolve_term exposes a deterministic numeric match_confidence per match_type."""
    out = hpo_service.resolve_term(query)
    assert out["match_type"] == expected_type
    assert out["match_confidence"] == expected_conf


def test_resolve_term_match_confidence_in_unit_range(hpo_service: HpoService) -> None:
    """match_confidence is a float in [0, 1]."""
    out = hpo_service.resolve_term("HP:0000479")
    assert isinstance(out["match_confidence"], float)
    assert 0.0 <= out["match_confidence"] <= 1.0


def test_confidence_for_unknown_match_type_is_low_default() -> None:
    """confidence_for() returns a conservative default for an unknown match type."""
    from hpo_link.services.resolution import confidence_for

    assert confidence_for("something_unexpected") == 0.6
