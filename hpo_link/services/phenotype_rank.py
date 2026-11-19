"""Disease-level Resnik gene ranking (issue #126), ported from VarLens ``779a6d25``.

sim(a, b) = IC of the most informative common ancestor (MICA). Per disease d:
``Fwd = sum_p max_t sim(p, t) * (1 - alpha + alpha * f) / sum_p IC(p)`` (IC-weighted
mean, tau = 1) and ``Rev = sum_t f * max_p sim(p, t) / IC(t) / (f0 + sum_t f)``;
``S = gamma * Fwd + (1 - gamma) * Rev``. A gene takes its best disease. Excluded terms
are reported as conflicts only and NEVER change a score (VarLens ``conflictsOnly``);
no background correction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from hpo_link.exceptions import InvalidInputError
from hpo_link.identifiers import normalize_hpo_id
from hpo_link.services.pagination import page_fields
from hpo_link.services.phenotype_index import (
    EXPLAIN_MIN_MATCH,
    F0,
    GAMMA,
    Disease,
    PhenotypeIndex,
)


@dataclass
class Profile:
    """A canonical query: pruned present terms and the excluded terms that still count."""

    present: list[str]
    excluded: list[str]


def prepare_profile(ix: PhenotypeIndex, present: list[str], excluded: list[str]) -> Profile | None:
    """Canonicalise, drop uninformative terms and present ancestors of other present terms.

    Excluded terms that are an ancestor-or-self of a present term are dropped (a
    patient with focal seizures cannot lack seizures). ``None`` without a present term.
    """
    keep = {t for t in (ix.canonical(x) for x in present) if t is not None and ix.self_ic[t] > 0}
    pruned = sorted(p for p in keep if not any(p in ix.anc[q] for q in keep if q != p))
    if not pruned:
        return None
    union = frozenset().union(*(ix.anc[p] for p in pruned))
    excl = {t for t in (ix.canonical(x) for x in excluded) if t is not None and ix.self_ic[t] > 0}
    return Profile(pruned, sorted(excl - union))


def _sim_map(ix: PhenotypeIndex, ancestors: tuple[str, ...]) -> dict[str, float]:
    """sim(·, t) for every annotated term t, given the query's ancestors (most informative first)."""
    sim = dict.fromkeys(ix.ann_terms, 0.0)
    seen: set[str] = set()
    for a in ancestors:
        new = ix.desc.get(a, frozenset()) - seen
        if new:
            sim.update(dict.fromkeys(new, ix.ic[a]))
            seen |= new
    return sim


def _forward_lane(ix: PhenotypeIndex, p: str) -> list[float]:
    """max_t sim(p, t)·factor(d, t) for every disease d (exact).

    A term's best value comes from its MICA with ``p``: a broad MICA reads the
    precomputed column ``icf``; a specific one loops over that term's annotations.
    """
    cols = [ix.icf[a] for a in ix.by_ic[p] if a in ix.icf]
    if not cols:
        lane = [0.0] * len(ix.diseases)
    else:
        lane = list(map(max, *cols, strict=True)) if len(cols) > 1 else list(cols[0])
    seen: set[str] = set()
    for a in ix.by_ic[p]:  # most informative first, so the first hit is the MICA
        new = ix.desc.get(a, frozenset()) - seen
        if a not in ix.icf:
            s = ix.ic[a]
            for t in new:
                for i, fac in ix.inv[t]:
                    v = s * fac
                    if v > lane[i]:
                        lane[i] = v
        seen |= new
    return lane


def score_diseases(ix: PhenotypeIndex, profile: Profile) -> list[float]:
    """S(d) for every disease index d."""
    w = 1 / sum(ix.self_ic[p] for p in profile.present)
    fwd = list(map(sum, zip(*(_forward_lane(ix, p) for p in profile.present), strict=True)))
    union = set().union(*(ix.anc[p] for p in profile.present))
    best_any = _sim_map(
        ix, tuple(sorted((a for a in union if ix.ic[a] > 0), key=lambda a: -ix.ic[a]))
    )
    rev_t = {t: v / ix.self_ic[t] for t, v in best_any.items()}
    rev = [math.sumprod(map(rev_t.__getitem__, d.terms), d.f) for d in ix.diseases]
    return [
        GAMMA * fw * w + (1 - GAMMA) * rv / (F0 + d.fsum)
        for fw, rv, d in zip(fwd, rev, ix.diseases, strict=True)
    ]


def _mica(ix: PhenotypeIndex, p: str, t: str) -> str | None:
    common = ix.anc[t]
    return next((a for a in ix.by_ic[p] if a in common), None)


def explain(ix: PhenotypeIndex, profile: Profile, d: Disease) -> dict[str, list[dict[str, Any]]]:
    """Matched (patient term ↔ disease term, MICA) pairs and excluded-term conflicts."""
    matched: list[dict[str, Any]] = []
    for p in profile.present:
        best, arg, mica = 0.0, -1, None
        for j, t in enumerate(d.terms):
            m = _mica(ix, p, t)
            v = ix.ic[m] * d.fac[j] if m else 0.0
            if v > best:
                best, arg, mica = v, j, m
        if arg < 0 or mica is None or best / ix.self_ic[p] < EXPLAIN_MIN_MATCH:
            continue
        matched.append(
            {
                "hpo_id": p,
                "label": ix.labels.get(p),
                "disease_hpo_id": d.terms[arg],
                "disease_label": ix.labels.get(d.terms[arg]),
                "mica_hpo_id": mica,
                "mica_ic": round(ix.ic[mica], 4),
                "frequency": round(d.f[arg], 4),
            }
        )
    conflicts: list[dict[str, Any]] = []
    for e in profile.excluded:
        hits = [j for j, t in enumerate(d.terms) if e in ix.anc[t]]
        if hits:
            j = max(hits, key=lambda k: d.f[k])
            conflicts.append(
                {
                    "excluded_hpo_id": e,
                    "label": ix.labels.get(e),
                    "disease_hpo_id": d.terms[j],
                    "disease_label": ix.labels.get(d.terms[j]),
                    "frequency": round(d.f[j], 4),
                }
            )
    return {"matched_terms": matched, "conflicts": conflicts}


def rank_genes(
    ix: PhenotypeIndex, profile: Profile, genes: list[str] | None = None
) -> list[tuple[str, float, int]]:
    """(gene, score, best disease index), best first; ties by gene symbol."""
    pool = list(ix.genes) if genes is None else genes
    scores = score_diseases(ix, profile)
    ranked = []
    for g in pool:
        best = max(ix.genes[g], key=lambda d: (scores[d], -d))  # first disease wins a tie
        ranked.append((g, scores[best], best))
    ranked.sort(key=lambda r: (-r[1], r[0]))
    return ranked


METHOD = (
    "Disease-level Resnik similarity (MICA information content over HPO is_a, annotation IC "
    "from phenotype.hpoa): S = 0.55*forward + 0.45*reverse, frequency-weighted; a gene takes "
    "its best-scoring disease. Excluded terms are reported as conflicts and never change a score."
)
LIMITATIONS = [
    "Annotation-overlap ranking, not clinical-grade prioritisation; research use only.",
    "Scores correlate with how many phenotypes a gene's diseases are annotated with "
    "(well-annotated genes rank higher).",
    "Only genes linked to an HPO-annotated disease can be ranked.",
]


def _parse_ids(raw: list[str] | None, field: str, *, required: bool) -> list[str]:
    ids = [x.strip() for x in raw or [] if x and x.strip()]
    if required and not ids:
        raise InvalidInputError(f"{field} must contain at least one HP id.", field)
    bad = [x for x in ids if normalize_hpo_id(x) is None]
    if bad:
        raise InvalidInputError(
            f"{field} has malformed HP ids: {', '.join(bad[:10])}.",
            field,
            hint="Use HP:NNNNNNN ids; resolve free text with resolve_term first.",
        )
    return [str(normalize_hpo_id(x)) for x in ids]


def rank_payload(
    ix: PhenotypeIndex,
    hpo_ids: list[str],
    excluded_hpo_ids: list[str] | None,
    candidate_genes: list[str] | None,
    limit: int,
    offset: int,
    response_mode: str,
) -> dict[str, Any]:
    """Validate the query, rank genes, explain the returned page."""
    present = _parse_ids(hpo_ids, "hpo_ids", required=True)
    excluded = _parse_ids(excluded_hpo_ids, "excluded_hpo_ids", required=False)
    profile = prepare_profile(ix, present, excluded)
    if profile is None:
        raise InvalidInputError(
            "None of hpo_ids is an informative phenotype term with disease annotations.",
            "hpo_ids",
            hint="Use specific terms under Phenotypic abnormality (HP:0000118).",
        )
    # Unknown, obsolete-without-replacement or uninformative (IC 0) ids are reported, not scored.
    ignored = sorted(
        {x for x in present + excluded if ix.self_ic.get(ix.canonical(x) or "", 0) <= 0}
    )
    pool: list[str] | None = None
    unranked: list[str] = []
    if candidate_genes is not None:
        upper = {g.upper(): g for g in ix.genes}
        hits: dict[str, None] = {}  # ordered de-duplication
        for g in candidate_genes:
            hit = upper.get(g.strip().upper())
            if hit is None:
                unranked.append(g)  # unknown symbol or no HPO-annotated disease
            else:
                hits[hit] = None
        pool = list(hits)
        if not pool:  # an all-unknown filter must not look like "no gene fits"
            raise InvalidInputError(
                "candidate_genes: none of the symbols is a gene with an HPO-annotated disease "
                f"({', '.join(unranked[:5])}). Use HGNC symbols, e.g. SCN1A.",
                "candidate_genes",
            )
    ranked = rank_genes(ix, profile, pool)
    page = ranked[offset : offset + limit]
    genes: list[dict[str, Any]] = []
    for n, (gene, score, d) in enumerate(page, start=offset + 1):
        disease = ix.diseases[d]
        row: dict[str, Any] = {
            "rank": n,
            "gene": gene,
            "score": round(score, 4),
            "best_disease": {"disease_id": disease.id, "disease_name": disease.name},
        }
        if response_mode != "minimal":
            row.update(explain(ix, profile, disease))
        genes.append(row)
    return {
        "scored_hpo_ids": profile.present,
        "excluded_hpo_ids": profile.excluded,
        "ignored_hpo_ids": ignored,
        "unranked_candidate_genes": unranked,
        "genes": genes,
        **page_fields(total=len(ranked), returned=len(genes), limit=limit, offset=offset),
        "method": METHOD,
        "limitations": LIMITATIONS,
    }
