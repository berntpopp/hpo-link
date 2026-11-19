"""Unit tests for the resolution cascade (services/resolution.py).

``decide_fuzzy`` is exercised as a pure function across its three decisions
(resolve / ambiguous / none); the ``Resolver`` cascade is exercised against the
mini fixture repository for the xref branch and the strict free-text miss path.

Fixture-world facts (from the mini fixtures):
  HP:0000479  Abnormal retinal morphology, xref UMLS:C0151888
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hpo_link.exceptions import AmbiguousQueryError, InvalidInputError, NotFoundError
from hpo_link.services.resolution import (
    FUZZY_DOMINANCE,
    FUZZY_MIN_SCORE,
    Resolver,
    confidence_for,
    decide_fuzzy,
)

if TYPE_CHECKING:
    from hpo_link.data.repository import HpoRepository


# ---------------------------------------------------------------------------
# decide_fuzzy — pure decision function
# ---------------------------------------------------------------------------


def test_decide_fuzzy_empty_hits_is_none() -> None:
    """No hits -> ('none', None)."""
    assert decide_fuzzy([]) == ("none", None)


def test_decide_fuzzy_below_floor_is_none() -> None:
    """A top hit under FUZZY_MIN_SCORE is rejected as a non-match."""
    weak = [{"hpo_id": "HP:0000479", "name": "x", "score": FUZZY_MIN_SCORE - 0.01}]
    assert decide_fuzzy(weak) == ("none", None)


def test_decide_fuzzy_single_clear_winner_resolves() -> None:
    """A lone hit above the floor resolves to that hit."""
    top = {"hpo_id": "HP:0000479", "name": "x", "score": FUZZY_MIN_SCORE + 1.0}
    assert decide_fuzzy([top]) == ("resolve", top)


def test_decide_fuzzy_dominant_top_resolves() -> None:
    """A top hit dominating the runner-up by >= FUZZY_DOMINANCE resolves."""
    top = {"hpo_id": "HP:1", "name": "a", "score": 3.0}
    second = {"hpo_id": "HP:2", "name": "b", "score": 3.0 / FUZZY_DOMINANCE - 0.1}
    assert decide_fuzzy([top, second]) == ("resolve", top)


def test_decide_fuzzy_zero_scored_runner_up_resolves() -> None:
    """A runner-up with a non-positive score never blocks a resolve."""
    top = {"hpo_id": "HP:1", "name": "a", "score": FUZZY_MIN_SCORE + 0.1}
    second = {"hpo_id": "HP:2", "name": "b", "score": 0.0}
    assert decide_fuzzy([top, second]) == ("resolve", top)


def test_decide_fuzzy_near_tie_is_ambiguous() -> None:
    """When the runner-up is within FUZZY_DOMINANCE of the top, it is ambiguous."""
    hits = [
        {"hpo_id": "HP:1", "name": "a", "score": 1.0},
        {"hpo_id": "HP:2", "name": "b", "score": 0.95},
        {"hpo_id": "HP:3", "name": "c", "score": 0.9},
    ]
    kind, candidates = decide_fuzzy(hits)
    assert kind == "ambiguous"
    assert isinstance(candidates, list)
    assert candidates == hits  # all within the candidate cap


# ---------------------------------------------------------------------------
# confidence_for
# ---------------------------------------------------------------------------


def test_confidence_for_known_and_unknown() -> None:
    """Known match types map to their tuned confidence; unknown falls to the floor."""
    assert confidence_for("hpo_id") == 1.0
    assert confidence_for("exact_synonym") == 0.95
    assert confidence_for("totally-made-up") == 0.6


# ---------------------------------------------------------------------------
# Resolver cascade — against the mini fixture repository
# ---------------------------------------------------------------------------


def test_resolver_resolves_xref_curie(repo: HpoRepository) -> None:
    """An external xref CURIE reverse-maps to its canonical HP id (match_type='xref')."""
    match_type, hpo_id = Resolver(repo).classify_resolution("UMLS:C0151888", fuzzy=False)
    assert match_type == "xref"
    assert hpo_id == "HP:0000479"


def test_resolver_resolves_primary_id(repo: HpoRepository) -> None:
    """A canonical HP id resolves directly via the primary-id lookup."""
    assert Resolver(repo).classify_resolution("HP:0000479", fuzzy=False) == (
        "hpo_id",
        "HP:0000479",
    )


def test_resolver_term_id_rejects_empty() -> None:
    """resolve_term_id with a blank term raises InvalidInputError before any lookup."""
    with pytest.raises(InvalidInputError):
        Resolver(repo=None).resolve_term_id("   ")  # type: ignore[arg-type]


def test_resolver_strict_miss_raises_not_found(repo: HpoRepository) -> None:
    """A non-matching free-text label with fuzzy disabled raises NotFoundError."""
    with pytest.raises(NotFoundError):
        Resolver(repo).resolve_term_id("zzqqxx-not-a-phenotype-zzqqxx")


class _LabelRepo:
    """Stub repo: one exact-label lookup result + per-id obsolete flags."""

    def __init__(self, rows: list[dict[str, str]], obsolete: frozenset[str] = frozenset()) -> None:
        self._rows, self._obsolete = rows, obsolete

    def get_term(self, hpo_id: str) -> dict[str, object] | None:
        if not hpo_id.startswith("HP:"):
            return None
        return {"hpo_id": hpo_id, "name": hpo_id, "is_obsolete": hpo_id in self._obsolete}

    def resolve_label(self, label: str) -> list[dict[str, str]]:
        return self._rows


def _resolver(rows: list[tuple[str, str]], obsolete: frozenset[str] = frozenset()) -> Resolver:
    repo = _LabelRepo([{"hpo_id": h, "label_type": t} for h, t in rows], obsolete)
    return Resolver(repo)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([("HP:0000002", "exact_synonym"), ("HP:0000001", "primary")], "HP:0000001"),
        ([("HP:0000002", "related_synonym"), ("HP:0000001", "exact_synonym")], "HP:0000001"),
        ([("HP:0000002", "broad_synonym"), ("HP:0000001", "exact_synonym")], "HP:0000001"),
    ],
)
def test_exact_label_strongest_match_type_wins(rows: list[tuple[str, str]], expected: str) -> None:
    """Primary > exact synonym > related synonym: a unique strongest term resolves (#124)."""
    assert _resolver(rows).classify_resolution("x label")[1] == expected


@pytest.mark.parametrize(
    ("rows", "obsolete"),
    [
        ([("HP:0000001", "exact_synonym"), ("HP:0000002", "exact_synonym")], frozenset()),
        ([("HP:0000001", "primary"), ("HP:0000002", "related_synonym")], {"HP:0000001"}),
    ],
)
def test_exact_label_tie_or_obsolete_winner_stays_ambiguous(
    rows: list[tuple[str, str]], obsolete: frozenset[str]
) -> None:
    """A tie at the strongest type, or an obsolete winner, stays ambiguous_query."""
    with pytest.raises(AmbiguousQueryError):
        _resolver(rows, frozenset(obsolete)).classify_resolution("x label")


def test_free_text_miss_carries_static_mondo_hint(repo: HpoRepository) -> None:
    """A free-text miss points disease names at mondo_resolve_disease without echoing them."""
    query = "zzqx Holt-Oram syndrome"
    with pytest.raises(NotFoundError) as exc_info:
        Resolver(repo).resolve_term_id(query)
    hint = exc_info.value.hint
    assert hint and "mondo_resolve_disease" in hint
    assert "Holt" not in hint


def test_absent_hp_id_miss_has_no_disease_hint(repo: HpoRepository) -> None:
    """A well-formed but absent HP id is not a disease name: no mondo hint."""
    with pytest.raises(NotFoundError) as exc_info:
        Resolver(repo).resolve_term_id("HP:9999999")
    assert exc_info.value.hint is None
