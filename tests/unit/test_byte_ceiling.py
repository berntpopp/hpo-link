"""Byte-ceiling regression gate (assessment C.1 — Token efficiency -> 10).

Locks the compact contract so a future field cannot silently re-inflate the hot
path. Asserts (a) a per-payload / per-row byte ceiling per response_mode, (b) the
F-1 citation stays out of compact, and (c) compact never keeps an empty value.

Ceilings are ~1.4x the observed compact size — tight enough to catch a
re-introduced citation or a null-column leak, loose enough to absorb fixture
churn. The assert messages print the actual size so a legitimate growth is a
one-line retune, not a mystery.
"""

from __future__ import annotations

import json
from typing import Any

from hpo_link.services.annotation_service import AnnotationService
from hpo_link.services.hpo_service import HpoService

#: Tuned to ~1.4x observed compact sizes against the mini fixture (term 234B,
#: assoc 329B/row). A re-introduced ~250-char recommended_citation would blow both
#: ceilings, which is exactly the F-1 regression this gate exists to catch.
TERM_COMPACT_MAX_BYTES = 330
ASSOC_COMPACT_MAX_BYTES_PER_ROW = 460
_EMPTY = (None, "", [], {}, "-")


def _nbytes(obj: Any) -> int:
    return len(json.dumps(obj, default=str).encode("utf-8"))


def test_get_term_compact_under_ceiling(hpo_service: HpoService) -> None:
    """A compact get_term payload stays under the byte ceiling and omits the citation."""
    payload = hpo_service.get_term("HP:0000118", response_mode="compact")
    assert "recommended_citation" not in payload  # F-1 stays fixed
    size = _nbytes(payload)
    assert size <= TERM_COMPACT_MAX_BYTES, (
        f"compact get_term grew to {size}B (ceiling {TERM_COMPACT_MAX_BYTES}B) — "
        "a field re-inflated the hot path; investigate before raising the ceiling"
    )


def test_association_compact_bytes_per_row(annotation_service: AnnotationService) -> None:
    """A compact association page stays under the per-row byte ceiling and omits the citation."""
    out = annotation_service.get_phenotypes_for_disease(
        "OMIM:106210", limit=25, response_mode="compact"
    )
    assert "recommended_citation" not in out
    rows = out["phenotypes"]
    assert rows, "fixture should yield at least one disease-phenotype row"
    per_row = _nbytes(rows) / len(rows)
    assert per_row <= ASSOC_COMPACT_MAX_BYTES_PER_ROW, (
        f"compact row grew to {per_row:.0f}B/row (ceiling {ASSOC_COMPACT_MAX_BYTES_PER_ROW}B)"
    )


def test_compact_rows_have_no_empty_values(annotation_service: AnnotationService) -> None:
    """compact must genuinely be compact: no row keeps a null/empty/sentinel value."""
    out = annotation_service.get_phenotypes_for_disease("OMIM:106210", response_mode="compact")
    for row in out["phenotypes"]:
        for key, value in row.items():
            assert value not in _EMPTY, f"compact kept empty value for {key!r}"


def test_compact_has_no_all_empty_column(annotation_service: AnnotationService) -> None:
    """No column survives in compact that is empty across every row (token noise)."""
    out = annotation_service.get_phenotypes_for_disease(
        "OMIM:106210", limit=25, response_mode="compact"
    )
    rows = out["phenotypes"]
    if not rows:
        return
    keys = set().union(*(r.keys() for r in rows))
    for key in keys:
        values = [r.get(key) for r in rows if key in r]
        assert any(v not in _EMPTY for v in values), f"all-empty column survived compact: {key!r}"
