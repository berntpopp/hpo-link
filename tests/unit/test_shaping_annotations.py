"""Tests for shape_annotation_rows in hpo_link.services.shaping (WS-B T2.1).

TDD: these tests are written BEFORE the implementation.
"""

from __future__ import annotations

from hpo_link.services.shaping import shape_annotation_rows

# ---------------------------------------------------------------------------
# Basic shape_annotation_rows tests
# ---------------------------------------------------------------------------


def _make_row(**kwargs) -> dict:
    """Helper to build a sample annotation row dict."""
    base = {
        "hpo_id": "HP:0000479",
        "name": "Abnormal retinal morphology",
        "qualifier": "",
        "onset": None,
        "sex": "",
        "modifier": "",
        "frequency": "-",
        "frequency_hpo": None,
        "frequency_ratio": None,
        "frequency_percent": None,
    }
    base.update(kwargs)
    return base


def test_shape_annotation_rows_compact_drops_empty_strings():
    """Compact mode drops keys with empty-string values."""
    row = _make_row(qualifier="", onset=None, sex="", modifier="")
    result = shape_annotation_rows([row], mode="compact")
    assert result, "Expected at least one row"
    shaped = result[0]
    assert "qualifier" not in shaped, "Empty string 'qualifier' should be dropped"
    assert "sex" not in shaped, "Empty string 'sex' should be dropped"
    assert "modifier" not in shaped, "Empty string 'modifier' should be dropped"
    assert "onset" not in shaped, "None 'onset' should be dropped"


def test_shape_annotation_rows_compact_drops_none():
    """Compact mode drops keys with None values."""
    row = _make_row(frequency_hpo=None, frequency_ratio=None, frequency_percent=None)
    result = shape_annotation_rows([row], mode="compact")
    shaped = result[0]
    assert "frequency_hpo" not in shaped
    assert "frequency_ratio" not in shaped
    assert "frequency_percent" not in shaped


def test_shape_annotation_rows_compact_keeps_hpo_id():
    """Compact mode always keeps hpo_id even if non-empty."""
    row = _make_row()
    result = shape_annotation_rows([row], mode="compact")
    assert result[0]["hpo_id"] == "HP:0000479"


def test_shape_annotation_rows_compact_keeps_non_empty_values():
    """Compact mode retains fields that have actual content."""
    row = _make_row(qualifier="NOT", onset="HP:0003577", frequency_hpo="HP:0040281")
    result = shape_annotation_rows([row], mode="compact")
    shaped = result[0]
    assert shaped.get("qualifier") == "NOT"
    assert shaped.get("onset") == "HP:0003577"
    assert shaped.get("frequency_hpo") == "HP:0040281"


def test_shape_annotation_rows_minimal_drops_empty():
    """Minimal mode also drops null/empty values."""
    row = _make_row(qualifier="", onset=None)
    result = shape_annotation_rows([row], mode="minimal")
    shaped = result[0]
    assert "qualifier" not in shaped
    assert "onset" not in shaped


def test_shape_annotation_rows_standard_preserves_all_fields():
    """Standard mode returns rows unchanged (all columns preserved)."""
    row = _make_row(qualifier="", onset=None, sex="", modifier="")
    result = shape_annotation_rows([row], mode="standard")
    shaped = result[0]
    # Standard keeps every key, even empty ones
    assert "qualifier" in shaped
    assert "onset" in shaped
    assert "sex" in shaped
    assert "modifier" in shaped


def test_shape_annotation_rows_full_preserves_all_fields():
    """Full mode returns rows unchanged."""
    row = _make_row(qualifier="", onset=None)
    result = shape_annotation_rows([row], mode="full")
    shaped = result[0]
    assert "qualifier" in shaped
    assert "onset" in shaped


def test_shape_annotation_rows_empty_input():
    """Empty row list returns empty list."""
    assert shape_annotation_rows([], mode="compact") == []


def test_shape_annotation_rows_multiple_rows():
    """All rows in the list are shaped."""
    rows = [
        _make_row(hpo_id="HP:0000479", qualifier="", onset=None),
        _make_row(hpo_id="HP:0000478", qualifier="NOT", onset="HP:0003577"),
    ]
    result = shape_annotation_rows(rows, mode="compact")
    assert len(result) == 2
    assert "qualifier" not in result[0], "Row 0 empty qualifier should be dropped"
    assert result[1]["qualifier"] == "NOT"
    assert result[1]["onset"] == "HP:0003577"


def test_shape_annotation_rows_compact_drops_empty_list():
    """Compact mode drops keys with empty list values."""
    row = _make_row(some_list=[])
    result = shape_annotation_rows([row], mode="compact")
    assert "some_list" not in result[0]


def test_shape_annotation_rows_compact_drops_empty_dict():
    """Compact mode drops keys with empty dict values."""
    row = _make_row(some_dict={})
    result = shape_annotation_rows([row], mode="compact")
    assert "some_dict" not in result[0]


def test_shape_annotation_rows_compact_drops_dash_frequency_sentinel():
    """Compact drops the HPOA '-' no-data sentinel (e.g. an undecodable frequency)."""
    row = _make_row(frequency="-")
    result = shape_annotation_rows([row], mode="compact")
    assert "frequency" not in result[0], "'-' frequency sentinel should be dropped in compact"


def test_shape_annotation_rows_standard_keeps_dash_frequency():
    """Standard mode preserves the raw '-' frequency verbatim (no shaping)."""
    row = _make_row(frequency="-")
    result = shape_annotation_rows([row], mode="standard")
    assert result[0]["frequency"] == "-"
