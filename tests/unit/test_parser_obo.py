# tests/unit/test_parser_obo.py
from pathlib import Path

from hpo_link.ingest.parser_obo import compute_closure, parse_hp_json

DOC = Path("tests/fixtures/mini_hp.json").read_text()


def test_parses_version_and_terms():
    p = parse_hp_json(DOC)
    assert p.version == "2026-06-06"
    assert p.terms["HP:0000118"].name == "Phenotypic abnormality"


def test_marks_obsolete():
    p = parse_hp_json(DOC)
    obs = [t for t in p.terms.values() if t.is_obsolete]
    assert obs and obs[0].replaced_by is not None


def test_synonyms_and_xrefs():
    p = parse_hp_json(DOC)
    t = p.terms["HP:0000479"]
    assert any(s["scope"] == "exact" for s in t.synonyms)
    assert any(x["prefix"] == "UMLS" for x in t.xrefs)


def test_closure_includes_self_and_ancestors():
    p = parse_hp_json(DOC)
    pairs = set(compute_closure(p.parents))
    assert ("HP:0000479", "HP:0000479") in pairs  # self
    assert ("HP:0000479", "HP:0000118") in pairs  # transitive
    assert ("HP:0000479", "HP:0000001") in pairs  # to root
