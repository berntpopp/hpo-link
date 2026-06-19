# tests/unit/test_parser_hpoa.py
from pathlib import Path

from hpo_link.ingest.parser_hpoa import (
    parse_frequency,
    parse_genes_to_phenotype,
    parse_phenotype_hpoa,
)


def test_parse_frequency_variants():
    assert parse_frequency("HP:0040283") == ("HP:0040283", None, None)
    assert parse_frequency("3/5") == (None, "3/5", 60.0)
    assert parse_frequency("25%") == (None, None, 25.0)
    assert parse_frequency("-") == (None, None, None)
    assert parse_frequency("5/0") == (None, None, None)


def test_phenotype_hpoa():
    text = Path("tests/fixtures/mini_phenotype.hpoa").read_text()
    version, rows = parse_phenotype_hpoa(text)
    assert version == "2026-06-06"
    r = rows[0]
    assert r.database_id.startswith(("OMIM:", "ORPHA:", "DECIPHER:"))
    assert r.hpo_id.startswith("HP:")
    assert any(x.qualifier == "NOT" for x in rows)


def test_genes_to_phenotype():
    rows = parse_genes_to_phenotype(Path("tests/fixtures/mini_genes_to_phenotype.txt").read_text())
    assert rows[0].gene_symbol and rows[0].hpo_id.startswith("HP:")
