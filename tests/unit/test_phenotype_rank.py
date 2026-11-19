"""Disease-level Resnik ranking: VarLens parity fixtures (issue #126).

Cases transcribed from VarLens ``tests/shared/phenotype/{phenotype-score,resnik}.test.ts``
at commit 779a6d25 (toy ontology, IC given). Skipped there-only cases: penalty-mode /
key-term / organ-system load / NOT-annotation load (hpo-link ships conflicts-only and has
no key terms), background-null and z-mode (correction is off), the seeded fuzz against
the TS naive scorer (no shared RNG), Beta-quantile f_excl (no exclusion penalty).
"""

from __future__ import annotations

import math

import pytest

from hpo_link.exceptions import InvalidInputError
from hpo_link.services.phenotype_index import (
    MISSING_F,
    PhenotypeIndex,
    ancestor_sets,
    annotation_frequency,
    build_index,
    fraction_frequency,
    information_content,
)
from hpo_link.services.phenotype_rank import prepare_profile, rank_genes, rank_payload

ROOT = "HP:0000118"
# ROOT > HEAD(1) > SIZE(2) > {MICRO(4), MACRO(4)}; ROOT > NEURO(1) > SEIZ(2) > FEB(4);
# ROOT > EYE(1) > CAT(4); NEURO > HYPO(3); HEAD > FACE(2).
TERMS = {
    "HEAD": 1,
    "SIZE": 2,
    "MICRO": 4,
    "MACRO": 4,
    "NEURO": 1,
    "SEIZ": 2,
    "FEB": 4,
    "EYE": 1,
    "CAT": 4,
    "HYPO": 3,
    "FACE": 2,
}
PARENTS = {
    "HEAD": [ROOT],
    "SIZE": ["HEAD"],
    "MICRO": ["SIZE"],
    "MACRO": ["SIZE"],
    "NEURO": [ROOT],
    "SEIZ": ["NEURO"],
    "FEB": ["SEIZ"],
    "EYE": [ROOT],
    "CAT": ["EYE"],
    "HYPO": ["NEURO"],
    "FACE": ["HEAD"],
    ROOT: [],
}
GAMMA, F0 = 0.55, 1.0
H = {name: f"HP:{9000 + i:07d}" for i, name in enumerate(TERMS)}  # toy name -> HP-shaped id
H["ALIAS_FEB"] = "HP:0009999"
H[ROOT] = ROOT


def ids(*names: str) -> list[str]:
    return [H.get(n, n) for n in names]


def toy(
    diseases: dict[str, list[tuple[str, float]]],
    gene_diseases: list[tuple[str, str]] | None = None,
) -> PhenotypeIndex:
    return build_index(
        ic={ROOT: 0.0, **{H[t]: v for t, v in TERMS.items()}},
        parents={H[c]: [H[p] for p in ps] for c, ps in PARENTS.items()},
        diseases=[(d, f"name {d}", [(H[t], f) for t, f in ann]) for d, ann in diseases.items()],
        gene_diseases=gene_diseases or [(f"G_{d}", d) for d in diseases],
        aliases={H["ALIAS_FEB"]: H["FEB"]},
        labels={H[t]: f"label {t}" for t in TERMS},
    )


def scores(
    ix: PhenotypeIndex, present: list[str], excluded: list[str] | None = None
) -> dict[str, float]:
    profile = prepare_profile(ix, ids(*present), ids(*(excluded or [])))
    assert profile is not None
    return {g[2:]: s for g, s, _ in rank_genes(ix, profile)}


def test_one_term_exact_match_with_f0_shrinkage() -> None:
    # fwd = 4*1/4 = 1 (f = 1 -> factor 1); rev = 1*(4/4)/(f0 + 1) = 0.5.
    s = scores(toy({"d": [("FEB", 1.0)]}), ["FEB"])
    assert s["d"] == pytest.approx(GAMMA + (1 - GAMMA) / (F0 + 1), abs=1e-12)


def test_tau_one_reference_value() -> None:
    # VarLens 'lowers a disease whose key-term match ...' plain arm: 0.790636.
    s = scores(toy({"d": [("EYE", 0.35), ("MICRO", 1.0)]}), ["EYE", "MICRO"])
    assert s["d"] == pytest.approx(0.790636, abs=1e-6)


def test_present_ancestor_is_pruned() -> None:
    ix = toy({"d": [("FEB", 0.9)], "e": [("CAT", 0.9)]})
    assert scores(ix, ["SEIZ", "FEB", "CAT"]) == scores(ix, ["FEB", "CAT"])


def test_excluded_term_never_changes_a_score_and_is_a_conflict() -> None:
    ix = toy({"d": [("MICRO", 0.95), ("FEB", 0.9)]})
    assert scores(ix, ["FACE"])["d"] > 0
    assert scores(ix, ["FACE", "FEB"], ["MICRO"]) == scores(ix, ["FACE", "FEB"])
    row = rank_payload(ix, ids("FACE", "FEB"), ids("MICRO"), None, 10, 0, "compact")["genes"][0]
    assert [(c["excluded_hpo_id"], c["disease_hpo_id"]) for c in row["conflicts"]] == [
        tuple(ids("MICRO", "MICRO"))
    ]


def test_excluded_ancestor_of_present_is_dropped_and_aliases_canonicalised() -> None:
    ix = toy({"d": [("FEB", 0.9)]})
    profile = prepare_profile(ix, ids("ALIAS_FEB"), ids("SEIZ", "FEB"))
    assert profile is not None and profile.present == ids("FEB") and profile.excluded == []
    assert scores(ix, ["ALIAS_FEB"], ["SEIZ", "FEB"]) == scores(ix, ["FEB"])


def test_inactive_without_a_present_term() -> None:
    ix = toy({"d": [("FEB", 0.9)]})
    assert prepare_profile(ix, [], ids("FEB")) is None
    assert prepare_profile(ix, ["UNKNOWN", ROOT], []) is None


def test_explains_best_disease_with_matched_pairs_and_conflicts() -> None:
    ix = toy(
        {"a": [("FEB", 0.9), ("MICRO", 0.9)], "b": [("CAT", 0.5)]},
        [("G1", "a"), ("G1", "b"), ("G2", "b")],
    )
    payload = rank_payload(ix, ids("FEB", "HYPO"), ids("SIZE"), ["G1"], 10, 0, "compact")
    g1 = payload["genes"][0]
    assert g1["best_disease"] == {"disease_id": "a", "disease_name": "name a"}
    # HYPO's best match (MICA NEURO, IC 1 of 3) is below the 0.5 explain threshold.
    assert [(m["hpo_id"], m["disease_hpo_id"], m["mica_hpo_id"]) for m in g1["matched_terms"]] == [
        tuple(ids("FEB", "FEB", "FEB"))
    ]
    assert g1["matched_terms"][0]["mica_ic"] == 4
    assert [(c["excluded_hpo_id"], c["disease_hpo_id"]) for c in g1["conflicts"]] == [
        tuple(ids("SIZE", "MICRO"))
    ]


# -- resnik.test.ts: IC and frequency parsing --------------------------------------


def test_information_content_counts_a_diamond_descendant_once() -> None:
    anc = ancestor_sets(["P", "A", "B", "F"], {"A": ["P"], "B": ["P"], "F": ["A", "B"]})
    ic = information_content({"d1": ["F"], "d2": ["A"], "d3": ["B"], "d4": ["B"]}, anc)
    assert ic["P"] == pytest.approx(0.0, abs=1e-12)
    assert ic["A"] == pytest.approx(math.log(2), abs=1e-12)
    assert ic["B"] == pytest.approx(math.log(4 / 3), abs=1e-12)
    assert ic["F"] == pytest.approx(math.log(4), abs=1e-12)


def test_frequency_pools_fractions_and_maps_terms_and_percentages() -> None:
    assert annotation_frequency(
        [("1/4", None, 25.0), ("2/6", None, 33.3), (None, "HP:0040281", None)]
    ) == (fraction_frequency(3, 10))
    assert annotation_frequency([(None, "HP:0040283", None), (None, "HP:0040282", None)]) == 0.545
    assert annotation_frequency([(None, None, 25.0)]) == 0.25
    assert annotation_frequency([("0/3", None, 0.0), (None, "HP:0040284", None)]) == 0.025
    assert annotation_frequency([(None, None, None)]) == MISSING_F
    assert annotation_frequency([("0/5", None, 0.0)]) is None
    assert fraction_frequency(6, 14) == pytest.approx(0.425, abs=1e-12)


def test_cycle_is_refused() -> None:
    with pytest.raises(ValueError, match="cycle"):
        ancestor_sets(["A", "B"], {"A": ["B"], "B": ["A"]})


# -- payload contract -------------------------------------------------------------


def test_payload_validation_and_honest_counts() -> None:
    ix = toy({"d": [("FEB", 0.9)], "e": [("CAT", 0.9)]})
    with pytest.raises(InvalidInputError) as empty:
        rank_payload(ix, [], None, None, 10, 0, "compact")
    assert empty.value.field == "hpo_ids"
    with pytest.raises(InvalidInputError) as bad:
        rank_payload(ix, ["HP:0001250", "BOGUS"], None, None, 10, 0, "compact")
    assert bad.value.field == "hpo_ids" and "BOGUS" in str(bad.value)
    with pytest.raises(InvalidInputError) as bad_excl:
        rank_payload(ix, ids("FEB"), ["nope"], None, 10, 0, "compact")
    assert bad_excl.value.field == "excluded_hpo_ids"
    page = rank_payload(ix, ids("FEB"), None, ["g_d", "G_E", "NOPE"], 1, 0, "minimal")
    assert [g["gene"] for g in page["genes"]] == ["G_d"]
    assert page["unranked_candidate_genes"] == ["NOPE"]
    assert (page["total"], page["returned"], page["truncated"], page["next_offset"]) == (
        2,
        1,
        True,
        1,
    )
    assert "matched_terms" not in page["genes"][0]
    assert page["limitations"]
