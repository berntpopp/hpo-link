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
from hpo_link.identifiers import (
    TRANSLATE_GENE_HINT,
    is_foreign_gene_id,
    normalize_gene,
    normalize_hpo_id,
)
from hpo_link.mcp.untrusted_content import sanitize_message
from hpo_link.services.pagination import page_fields
from hpo_link.services.phenotype_index import (
    EXPLAIN_MIN_MATCH,
    F0,
    GAMMA,
    MISSING_F,
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


def _matches(
    ix: PhenotypeIndex, profile: Profile, d: Disease
) -> list[tuple[float, dict[str, Any]]]:
    """(forward contribution, matched pair) per present term that reaches EXPLAIN_MIN_MATCH."""
    matched: list[tuple[float, dict[str, Any]]] = []
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
            (
                best,
                {
                    "hpo_id": p,
                    "label": ix.labels.get(p),
                    "disease_hpo_id": d.terms[arg],
                    "disease_label": ix.labels.get(d.terms[arg]),
                    "mica_hpo_id": mica,
                    "mica_ic": round(ix.ic[mica], 4),
                    "frequency": round(d.f[arg], 4),
                },
            )
        )
    return matched


def explain(ix: PhenotypeIndex, profile: Profile, d: Disease) -> dict[str, list[dict[str, Any]]]:
    """Matched (patient term ↔ disease term, MICA) pairs and excluded-term conflicts."""
    matched = [m for _, m in _matches(ix, profile, d)]
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
# Chosen on the tune split of a published-case evaluation (phenopacket-store 0.1.27, see
# CHANGELOG 0.11.0). With the top two scores closer than this, rank 1 was the wrong gene in
# roughly 40-50% of 16-candidate rankings (it varies with the random distractors) and ~65%
# genome-wide; otherwise in ~1% and ~4%.
CLOSE_CALL_MARGIN = 0.05
TOP_MATCH_ROWS = 5  # minimal mode: ranks that carry top_matches
LIMITATIONS = [
    "Annotation-overlap ranking, not clinical-grade prioritisation; research use only.",
    "Scores correlate with how many phenotypes a gene's diseases are annotated with "
    "(well-annotated genes rank higher).",
    "Only genes linked to an HPO-annotated disease can be ranked.",
    "matched_terms lists pairs sharing at least half of the input term's information content; "
    "weaker matches still add to a score.",
]


def close_call(ranked: list[tuple[str, float, int]]) -> dict[str, Any]:
    """Whether the top ranks are separable; computed on the whole ranking, not the page."""
    if len(ranked) < 2:
        return {"rank1_margin": None, "close_call": False}
    top = ranked[0][1]
    margin = round(top - ranked[1][1], 4)  # flag what is reported: 0.05 is never a close call
    if margin >= CLOSE_CALL_MARGIN:
        return {"rank1_margin": margin, "close_call": False}
    k = sum(1 for _, s, _ in ranked if round(top - s, 4) < CLOSE_CALL_MARGIN)
    return {
        "rank1_margin": margin,
        "close_call": True,
        "close_call_note": (
            f"Ranks 1-{k} are within {CLOSE_CALL_MARGIN} of each other, too close to separate "
            "by score; compare matched terms or check gene-disease evidence before choosing."
        ),
    }


def _pair_text(m: dict[str, Any]) -> str:
    """'<input id> = <label> (f=0.9)': '=' the same term, '~' a related one, 'f=?' not recorded."""
    same = "=" if m["disease_hpo_id"] == m["hpo_id"] else "~"
    # ponytail: "not recorded" is recognised by the placeholder value, which a pooled 2/6 also
    # yields; store a flag on Disease if that ever matters.
    f = "?" if m["frequency"] == MISSING_F else f"{m['frequency']:.2g}"
    return f"{m['hpo_id']} {same} {m['disease_label'] or m['disease_hpo_id']} (f={f})"


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


def _echo(raw: str) -> str:
    """A caller's spelling as echoed in ``input_id``: forbidden code points stripped, capped."""
    return sanitize_message(raw)[:64]


def _account(
    ix: PhenotypeIndex, present: list[str], excluded: list[str], profile: Profile
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Say what happened to every input id that is not scored as given (issue #130).

    Returns ``(replaced, ignored)``: an obsolete id / alt_id scored as its current term, and
    ids left out with a reason (and the scored term that covers them, where one does).
    """
    replaced: list[dict[str, str]] = []
    ignored: list[dict[str, str]] = []
    for ids, kept in ((present, profile.present), (excluded, profile.excluded)):
        for x in dict.fromkeys(ids):
            t = ix.canonical(x)
            if t is None:
                known = x in ix.labels or x in ix.aliases
                reason = "not_a_current_phenotype_term" if known else "unknown_id"
                ignored.append({"input_id": x, "reason": reason})
            elif ix.self_ic[t] <= 0:
                ignored.append({"input_id": x, "reason": "no_disease_annotations"})
            elif t not in kept:  # pruned: a scored term is this term or a descendant of it
                by = next(p for p in profile.present if t in ix.anc[p])
                reason = "ancestor_of_scored_term" if ids is present else "contradicts_present_term"
                ignored.append({"input_id": x, "reason": reason, "covered_by": by})
            elif t != x:
                replaced.append({"input_id": x, "replaced_by": t, "reason": "obsolete_or_alt_id"})
    return replaced, ignored


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
    replaced, ignored = _account(ix, present, excluded, profile)
    pool: list[str] | None = None
    unranked: list[dict[str, str]] = []
    hits: dict[str, str] = {}  # gene -> the caller's spelling; ordered de-duplication
    if candidate_genes is not None:
        upper = {g.upper(): g for g in ix.genes}
        for raw in candidate_genes:
            g = raw.strip()
            kind, value = normalize_gene(g)
            if kind == "ncbi":  # HPO ships the NCBI gene id next to the symbol
                value = ix.gene_ids.get(value, "").upper()
            hit = upper.get(value)
            if hit is not None:
                hits.setdefault(hit, _echo(g))
            elif kind != "ncbi" and is_foreign_gene_id(g):
                unranked.append({"input_id": _echo(g), "reason": "unsupported_identifier"})
            else:  # unknown symbol / NCBI id, or no HPO-annotated disease
                unranked.append({"input_id": _echo(g), "reason": "not_rankable"})
        pool = list(hits)
        if not pool:  # an all-unknown filter must not look like "no gene fits"
            raise InvalidInputError(
                "candidate_genes: none of the entries is a gene with an HPO-annotated "
                f"disease ({', '.join(u['input_id'] for u in unranked[:5])}).",
                "candidate_genes",
                allowed=["<gene symbol> e.g. SCN1A", "NCBIGene:<id> e.g. NCBIGene:6323"],
                hint=(
                    "candidate_genes takes gene symbols (SCN1A) or NCBI gene ids "
                    f"(NCBIGene:6323 or 6323). {TRANSLATE_GENE_HINT}"
                ),
            )
    ranked = rank_genes(ix, profile, pool)
    page = ranked[offset : offset + limit]
    genes: list[dict[str, Any]] = []
    for n, (gene, score, d) in enumerate(page, start=offset + 1):
        disease = ix.diseases[d]
        row: dict[str, Any] = {
            "rank": n,
            "gene": gene,
            **({"input_id": hits[gene]} if pool is not None else {}),
            "score": round(score, 4),
            "best_disease": {"disease_id": disease.id, "disease_name": disease.name},
        }
        if response_mode != "minimal":
            row.update(explain(ix, profile, disease))
            row["matched_count"] = len(row["matched_terms"])
        elif n <= TOP_MATCH_ROWS:  # minimal: why a top row leads, without a second call (#130)
            pairs = sorted(_matches(ix, profile, disease), key=lambda m: -m[0])
            row["matched_count"] = len(pairs)
            row["top_matches"] = [_pair_text(m) for _, m in pairs[:2]]
        genes.append(row)
    return {
        "scored_hpo_ids": profile.present,
        "excluded_hpo_ids": profile.excluded,
        "replaced_hpo_ids": replaced,
        "ignored_hpo_ids": ignored,
        "unranked_candidate_genes": unranked,
        **close_call(ranked),
        "genes": genes,
        **page_fields(total=len(ranked), returned=len(genes), limit=limit, offset=offset),
        "method": METHOD,
        "limitations": LIMITATIONS,
    }
