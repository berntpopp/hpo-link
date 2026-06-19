import pytest

from hpo_link.exceptions import InvalidInputError
from hpo_link.identifiers import (
    iri_to_curie,
    is_hpo_id,
    normalize_disease_id,
    normalize_gene,
    normalize_hpo_id,
    validate_disease_id,
    validate_gene,
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


# ---------------------------------------------------------------------------
# validate_disease_id (T1.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("OMIM:106210", "OMIM:106210"),
        ("omim:106210", "OMIM:106210"),
        ("ORPHA:123", "ORPHA:123"),
        ("DECIPHER:42", "DECIPHER:42"),
    ],
)
def test_validate_disease_id_valid(raw, expected):
    """Well-formed disease CURIEs pass validation and are normalized."""
    assert validate_disease_id(raw) == expected


@pytest.mark.parametrize(
    "malformed",
    [
        "notacurie",  # no colon
        ":123",  # empty prefix
        "OMIM:",  # empty body
        "  ",  # blank
        "",  # empty
    ],
)
def test_validate_disease_id_malformed(malformed):
    """Malformed disease_id raises InvalidInputError with field='disease_id'."""
    with pytest.raises(InvalidInputError) as exc_info:
        validate_disease_id(malformed)
    assert exc_info.value.field == "disease_id"


# ---------------------------------------------------------------------------
# validate_gene (T1.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_kind,expected_value",
    [
        ("PAX6", "symbol", "PAX6"),
        ("pax6", "symbol", "PAX6"),
        ("5080", "ncbi", "5080"),
        ("NCBIGene:5080", "ncbi", "5080"),
        ("ncbigene:5080", "ncbi", "5080"),
    ],
)
def test_validate_gene_valid(raw, expected_kind, expected_value):
    """Well-formed gene ids pass validation and return (kind, value)."""
    kind, value = validate_gene(raw)
    assert kind == expected_kind
    assert value == expected_value


@pytest.mark.parametrize(
    "malformed",
    [
        "NCBIGene:",  # empty body
        "NCBIGene:abc",  # non-digit body
        "HGNC:1234",  # wrong prefix with colon
        "OMIM:12345",  # wrong prefix with colon
    ],
)
def test_validate_gene_malformed(malformed):
    """Malformed gene id raises InvalidInputError with field='gene'."""
    with pytest.raises(InvalidInputError) as exc_info:
        validate_gene(malformed)
    assert exc_info.value.field == "gene"


def test_validate_gene_empty():
    """Empty gene raises InvalidInputError with field='gene'."""
    with pytest.raises(InvalidInputError) as exc_info:
        validate_gene("")
    assert exc_info.value.field == "gene"
