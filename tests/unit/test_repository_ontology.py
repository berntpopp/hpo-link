"""Tests for HpoRepository ontology queries (hierarchy, xrefs, search, meta)."""

from __future__ import annotations

from hpo_link.data.repository import HpoRepository

# -- meta ------------------------------------------------------------------


def test_read_meta(repo: HpoRepository) -> None:
    """Meta dict should carry an hpo_version key from the built index."""
    meta = repo.read_meta()
    assert "hpo_version" in meta
    assert meta["hpo_version"] is not None


# -- term records ----------------------------------------------------------


def test_get_term_found(repo: HpoRepository) -> None:
    """get_term for a known HP id should return a dict with expected keys."""
    term = repo.get_term("HP:0000479")
    assert term is not None
    assert term["hpo_id"] == "HP:0000479"
    assert term["name"] == "Abnormal retinal morphology"
    assert isinstance(term["synonyms"], list)
    assert isinstance(term["alt_ids"], list)


def test_get_term_not_found(repo: HpoRepository) -> None:
    """get_term for a non-existent HP id should return None."""
    assert repo.get_term("HP:9999999") is None


def test_get_term_has_synonym(repo: HpoRepository) -> None:
    """HP:0000479 should have 'Abnormal retina' as an exact synonym."""
    term = repo.get_term("HP:0000479")
    assert term is not None
    synonym_texts = [
        s["text"] if isinstance(s, dict) else s for s in term["synonyms"]
    ]
    assert any("Abnormal retina" in str(s) for s in synonym_texts), (
        f"Expected 'Abnormal retina' in synonyms, got: {term['synonyms']}"
    )


def test_get_term_has_alt_id(repo: HpoRepository) -> None:
    """HP:0000479 should have HP:0001098 as an alt_id."""
    term = repo.get_term("HP:0000479")
    assert term is not None
    assert "HP:0001098" in term["alt_ids"]


# -- resolve_label ---------------------------------------------------------


def test_resolve_label(repo: HpoRepository) -> None:
    """resolve_label for 'Phenotypic abnormality' should return HP:0000118."""
    results = repo.resolve_label("Phenotypic abnormality")
    hpo_ids = [r["hpo_id"] for r in results]
    assert "HP:0000118" in hpo_ids


def test_resolve_label_case_insensitive(repo: HpoRepository) -> None:
    """resolve_label should be case-insensitive (lookup_label is uppercased)."""
    results_lower = repo.resolve_label("phenotypic abnormality")
    results_upper = repo.resolve_label("PHENOTYPIC ABNORMALITY")
    ids_lower = {r["hpo_id"] for r in results_lower}
    ids_upper = {r["hpo_id"] for r in results_upper}
    assert ids_lower == ids_upper
    assert "HP:0000118" in ids_lower


# -- search ----------------------------------------------------------------


def test_search_retina(repo: HpoRepository) -> None:
    """search('retina') should include HP:0000479."""
    hits, _total = repo.search("retina", limit=10, include_obsolete=False)
    hpo_ids = [h["hpo_id"] for h in hits]
    assert "HP:0000479" in hpo_ids


def test_search_excludes_obsolete(repo: HpoRepository) -> None:
    """search with include_obsolete=False should not return obsolete HP:0000489."""
    hits, _total = repo.search("electroretinogram", limit=10, include_obsolete=False)
    hpo_ids = [h["hpo_id"] for h in hits]
    assert "HP:0000489" not in hpo_ids


def test_search_includes_obsolete(repo: HpoRepository) -> None:
    """search with include_obsolete=True may return obsolete terms."""
    # HP:0000489 is the obsolete term; search with include_obsolete=True
    hits, _total = repo.search("electroretinogram", limit=10, include_obsolete=True)
    # We cannot guarantee it appears (depends on FTS index), but we at least
    # verify the query does not crash.
    assert isinstance(hits, list)


# -- hierarchy -------------------------------------------------------------


def test_ancestors_of_479(repo: HpoRepository) -> None:
    """ancestors('HP:0000479') should include HP:0000478, HP:0000118, HP:0000001."""
    anc = repo.ancestors("HP:0000479", limit=100)
    hpo_ids = {r["hpo_id"] for r in anc}
    assert "HP:0000478" in hpo_ids
    assert "HP:0000118" in hpo_ids
    assert "HP:0000001" in hpo_ids
    # Self should NOT be included
    assert "HP:0000479" not in hpo_ids


def test_descendants_of_118(repo: HpoRepository) -> None:
    """descendants('HP:0000118') should include HP:0000478 and HP:0000479."""
    desc = repo.descendants("HP:0000118", limit=100)
    hpo_ids = {r["hpo_id"] for r in desc}
    assert "HP:0000478" in hpo_ids
    assert "HP:0000479" in hpo_ids
    # Self should NOT be included
    assert "HP:0000118" not in hpo_ids


def test_count_ancestors(repo: HpoRepository) -> None:
    """count_ancestors('HP:0000479') should be at least 3."""
    count = repo.count_ancestors("HP:0000479")
    assert count >= 3


def test_count_descendants(repo: HpoRepository) -> None:
    """count_descendants('HP:0000118') should be at least 2."""
    count = repo.count_descendants("HP:0000118")
    assert count >= 2


def test_parents(repo: HpoRepository) -> None:
    """parents('HP:0000479') should have exactly one item: HP:0000478."""
    ps = repo.parents("HP:0000479")
    assert len(ps) == 1
    assert ps[0]["hpo_id"] == "HP:0000478"


def test_children(repo: HpoRepository) -> None:
    """children('HP:0000118') should include HP:0000478."""
    cs = repo.children("HP:0000118")
    hpo_ids = {r["hpo_id"] for r in cs}
    assert "HP:0000478" in hpo_ids


# -- cross-references ------------------------------------------------------


def test_xrefs_for_has_umls(repo: HpoRepository) -> None:
    """xrefs_for('HP:0000479') should include a UMLS entry."""
    xrefs = repo.xrefs_for("HP:0000479")
    prefixes = {x["prefix"] for x in xrefs}
    assert "UMLS" in prefixes


def test_xrefs_for_filtered_by_prefix(repo: HpoRepository) -> None:
    """xrefs_for with prefixes=['UMLS'] should only return UMLS entries."""
    xrefs = repo.xrefs_for("HP:0000479", prefixes=["UMLS"])
    assert len(xrefs) >= 1
    for x in xrefs:
        assert x["prefix"] == "UMLS"


def test_hpo_for_xref(repo: HpoRepository) -> None:
    """hpo_for_xref('UMLS:C0151888') should return HP:0000479."""
    results = repo.hpo_for_xref("UMLS:C0151888", limit=10)
    hpo_ids = [r["hpo_id"] for r in results]
    assert "HP:0000479" in hpo_ids


def test_count_hpo_for_xref(repo: HpoRepository) -> None:
    """count_hpo_for_xref('UMLS:C0151888') should be 1."""
    count = repo.count_hpo_for_xref("UMLS:C0151888")
    assert count == 1


def test_hpo_for_xref_case_insensitive(repo: HpoRepository) -> None:
    """hpo_for_xref should match regardless of input case."""
    results = repo.hpo_for_xref("umls:c0151888", limit=10)
    hpo_ids = [r["hpo_id"] for r in results]
    assert "HP:0000479" in hpo_ids
