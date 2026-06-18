import pytest

from hpo_link.identifiers import (
    iri_to_curie,
    is_hpo_id,
    normalize_disease_id,
    normalize_gene,
    normalize_hpo_id,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HP:0000118", "HP:0000118"),
        ("hp:0000118", "HP:0000118"),
        ("0000118", "HP:0000118"),
        ("118", "HP:0000118"),
        ("HP_0000118", "HP:0000118"),
        ("http://purl.obolibrary.org/obo/HP_0000118", "HP:0000118"),
        ("garbage", None),
    ],
)
def test_normalize_hpo_id(raw, expected):
    assert normalize_hpo_id(raw) == expected


def test_iri_to_curie():
    assert iri_to_curie("http://purl.obolibrary.org/obo/HP_0000003") == "HP:0000003"


def test_is_hpo_id():
    assert is_hpo_id("HP:0000118") is True
    assert is_hpo_id("OMIM:123") is False


def test_normalize_gene():
    assert normalize_gene("NCBIGene:1234") == ("ncbi", "1234")
    assert normalize_gene("1234") == ("ncbi", "1234")
    assert normalize_gene("PAX6") == ("symbol", "PAX6")
    assert normalize_gene("pax6") == ("symbol", "PAX6")


def test_normalize_disease_id():
    assert normalize_disease_id("omim:619340") == "OMIM:619340"
    assert normalize_disease_id("ORPHA:550") == "ORPHA:550"
