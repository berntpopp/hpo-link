"""In-process phenotype index for disease-level Resnik ranking (issue #126).

Ported from VarLens ``src/shared/phenotype/{resnik,phenotype-index,hpo-sources}.ts``
and ``src/shared/config/hpo-scoring.config.ts`` at commit ``779a6d25``. Built once
per process from tables hpo-link already ships (``hpo_parent``, ``hpo_closure``,
``disease_phenotype``, ``gene_disease``); no schema change, no new data source.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

PHENOTYPE_ROOT = "HP:0000118"

# VarLens HPO_SCORING_CONFIG (779a6d25), the shipped defaults.
ALPHA_F = 0.25  # share of a forward match that depends on the annotation frequency
F0 = 1.0  # reverse-score shrinkage prior
GAMMA = 0.55  # forward weight; reverse weight is 1 - GAMMA = 0.45
FRACTION_PRIOR = (0.8, 1.2)  # f = (m + a) / (n + a + b) = (m + 0.8) / (n + 2)
FREQUENCY_TERMS = {
    "HP:0040280": 1.0,  # obligate
    "HP:0040281": 0.895,  # very frequent
    "HP:0040282": 0.545,  # frequent
    "HP:0040283": 0.17,  # occasional
    "HP:0040284": 0.025,  # very rare
}
MISSING_F = 0.35
EXPLAIN_MIN_MATCH = 0.5  # a present term counts as "matched" from this relative match r(p, d)
# Terms with more annotated descendants than this get a precomputed per-disease forward
# column (IC * best factor), so one query never loops in Python over their annotations.
BROAD_ANNOTATIONS = 2000


def fraction_frequency(m: float, n: float) -> float:
    """Smoothed fraction m/n (``1/1`` -> 0.6, not 1)."""
    a, b = FRACTION_PRIOR
    return (m + a) / (n + a + b)


@dataclass
class Disease:
    """One disease: id, name, positive annotations ``terms`` with frequencies ``f``."""

    id: str
    name: str
    terms: tuple[str, ...]
    f: tuple[float, ...]
    fac: tuple[float, ...] = field(init=False)  # forward factor 1 - a + a*f
    fsum: float = field(init=False)

    def __post_init__(self) -> None:
        """Derive the forward factors and the reverse denominator."""
        self.fac = tuple(1 - ALPHA_F + ALPHA_F * x for x in self.f)
        self.fsum = sum(self.f)


@dataclass
class PhenotypeIndex:
    """Ancestor sets, IC, diseases and gene->disease links (all plain Python)."""

    ic: dict[str, float]  # raw annotation IC (0 for unreached terms)
    self_ic: dict[str, float]  # sim(t, t) = max IC over Anc(t)
    anc: dict[str, frozenset[str]]  # ancestors incl. self, phenotype subtree only
    desc: dict[str, frozenset[str]]  # annotated descendants incl. self
    by_ic: dict[str, tuple[str, ...]]  # Anc(t) with IC > 0, most informative first
    aliases: dict[str, str]
    labels: dict[str, str]
    diseases: list[Disease]
    genes: dict[str, list[int]]  # gene symbol -> disease indices
    ann_terms: frozenset[str]
    inv: dict[str, list[tuple[int, float]]]  # term -> (disease, forward factor)
    icf: dict[str, list[float]]  # broad term -> per-disease IC(a) * max factor under a
    gene_ids: dict[str, str] = field(default_factory=dict)  # bare NCBI gene id -> symbol

    def canonical(self, hpo_id: str) -> str | None:
        """Return the current term for an id or alias, or None when unknown."""
        t = self.aliases.get(hpo_id, hpo_id)
        return t if t in self.anc else None


def ancestor_sets(
    terms: Iterable[str], parents: Mapping[str, Iterable[str]]
) -> dict[str, frozenset[str]]:
    """Anc(t) = {t} | union of Anc(parent) for every term (parents outside ``terms`` ignored)."""
    known = set(terms)
    out: dict[str, frozenset[str]] = {}

    def visit(t: str, path: frozenset[str]) -> frozenset[str]:
        if t in out:
            return out[t]
        if t in path:
            raise ValueError(f"is_a cycle at {t}")
        acc = {t}
        for p in parents.get(t, ()):
            if p in known:
                acc |= visit(p, path | {t})
        out[t] = frozenset(acc)
        return out[t]

    for t in known:
        visit(t, frozenset())
    return out


def information_content(
    disease_terms: Mapping[str, Iterable[str]], anc: Mapping[str, frozenset[str]]
) -> dict[str, float]:
    """IC(t) = -ln(n(t)/N): n(t) diseases annotated to t or a descendant, N annotated diseases."""
    counts: dict[str, int] = {}
    total = 0
    for terms in disease_terms.values():
        reached: set[str] = set()
        for t in terms:
            reached |= anc.get(t, frozenset())
        if not reached:
            continue
        total += 1
        for a in reached:
            counts[a] = counts.get(a, 0) + 1
    return {t: -math.log(n / total) for t, n in counts.items()}


def build_index(
    *,
    ic: Mapping[str, float],
    parents: Mapping[str, Iterable[str]],
    diseases: Iterable[tuple[str, str, Iterable[tuple[str, float]]]],
    gene_diseases: Iterable[tuple[str, str]],
    aliases: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> PhenotypeIndex:
    """Build the index from IC, ``is_a`` parents, (id, name, [(term, f)]) and (gene, disease)."""
    terms = set(ic) | set(parents)
    anc = ancestor_sets(terms, parents)
    raw = {t: float(ic.get(t, 0.0)) for t in anc}
    self_ic = {t: max(raw[a] for a in anc[t]) for t in anc}
    alias = {k: v for k, v in (aliases or {}).items() if v in anc}
    links = list(gene_diseases)
    linked = {did for _, did in links}
    kept: list[Disease] = []
    index: dict[str, int] = {}
    for did, name, ann in diseases:
        if did not in linked:  # only gene-linked diseases can rank a gene (IC uses all)
            continue
        best: dict[str, float] = {}
        for t0, f in ann:
            t = alias.get(t0, t0)
            if self_ic.get(t, 0.0) > 0 and f > best.get(t, -1.0):
                best[t] = f
        if best:
            index[did] = len(kept)
            kept.append(Disease(did, name, tuple(best), tuple(best.values())))
    genes: dict[str, list[int]] = {}
    for gene, did in links:
        di = index.get(did)
        if di is not None and di not in genes.setdefault(gene, []):
            genes[gene].append(di)
    for g in [g for g, ds in genes.items() if not ds]:
        del genes[g]
    ann_terms = frozenset(t for d in kept for t in d.terms)
    desc_sets: dict[str, set[str]] = {}
    for t in ann_terms:
        for a in anc[t]:
            desc_sets.setdefault(a, set()).add(t)
    inv: dict[str, list[tuple[int, float]]] = {}
    for i, d in enumerate(kept):
        for t, fac in zip(d.terms, d.fac, strict=True):
            inv.setdefault(t, []).append((i, fac))
    icf: dict[str, list[float]] = {}
    for a, under in desc_sets.items():
        if raw[a] > 0 and sum(len(inv[t]) for t in under) > BROAD_ANNOTATIONS:
            col = [0.0] * len(kept)
            for t in under:
                for i, fac in inv[t]:
                    col[i] = max(col[i], raw[a] * fac)
            icf[a] = col
    by_ic = {
        t: tuple(sorted((a for a in anc[t] if raw[a] > 0), key=lambda a: -raw[a])) for t in anc
    }
    return PhenotypeIndex(
        ic=raw,
        self_ic=self_ic,
        anc=anc,
        desc={a: frozenset(s) for a, s in desc_sets.items()},
        by_ic=by_ic,
        aliases=alias,
        labels=dict(labels or {}),
        diseases=kept,
        genes=genes,
        ann_terms=ann_terms,
        inv=inv,
        icf=icf,
    )


def annotation_frequency(
    rows: Iterable[tuple[str | None, str | None, float | None]],
) -> float | None:
    """Frequency of one (disease, term) from its evidence rows (ratio, hpo term, percent).

    Pooled fractions win (``(M + 0.8)/(N + 2)``); otherwise a percentage, then the
    highest HPO frequency-term midpoint, else the "missing" default. ``None`` drops
    the annotation (only zero frequencies were recorded).
    """
    m = n = 0.0
    pct: float | None = None
    cat: float | None = None
    any_zero = False
    for ratio, freq_hpo, percent in rows:
        if ratio:
            num, den = (float(x) for x in ratio.split("/"))
            m, n = m + num, n + den
            any_zero = any_zero or num == 0
        elif freq_hpo in FREQUENCY_TERMS:
            cat = max(cat or 0.0, FREQUENCY_TERMS[freq_hpo])
        elif percent is not None:
            pct = max(pct or 0.0, percent / 100)
            any_zero = any_zero or percent == 0
    if m > 0:
        return fraction_frequency(m, n)
    if pct:
        return pct
    if cat is not None:
        return cat
    return None if any_zero else MISSING_F


def load_index(conn: sqlite3.Connection) -> PhenotypeIndex:
    """Build the index from the shipped hpo-link SQLite tables."""
    subtree = {
        r[0]
        for r in conn.execute(
            "SELECT hpo_id FROM hpo_closure WHERE ancestor_id = ?", (PHENOTYPE_ROOT,)
        )
    }
    parents: dict[str, list[str]] = {}
    for child, parent in conn.execute("SELECT hpo_id, parent_id FROM hpo_parent"):
        if child in subtree and parent in subtree:
            parents.setdefault(child, []).append(parent)
    for t in subtree:
        parents.setdefault(t, [])
    labels = dict(conn.execute("SELECT hpo_id, name FROM term"))
    aliases = dict(
        conn.execute("SELECT lookup_label, hpo_id FROM term_lookup WHERE label_type = 'alt_id'")
    )
    aliases.update(
        conn.execute(
            "SELECT hpo_id, replaced_by FROM term WHERE is_obsolete = 1 AND replaced_by IS NOT NULL"
        )
    )
    # One evidence row per distinct (term, reference, onset, frequency, sex, modifier):
    # HPOA repeats a row that differs only by biocuration (VarLens "pooled once").
    rows = conn.execute(
        "SELECT DISTINCT database_id, disease_name, hpo_id, reference, onset, frequency, sex, "
        "modifier, frequency_ratio, frequency_hpo, frequency_percent FROM disease_phenotype "
        "WHERE aspect = 'P' AND coalesce(qualifier, '') <> 'NOT'"
    )
    names: dict[str, str] = {}
    evidence: dict[str, dict[str, list[tuple[str | None, str | None, float | None]]]] = {}
    for did, name, t, *_, ratio, fhpo, pct in rows:
        names.setdefault(did, name or did)
        evidence.setdefault(did, {}).setdefault(aliases.get(t, t), []).append((ratio, fhpo, pct))
    ann: dict[str, list[tuple[str, float]]] = {}
    for did, per_term in evidence.items():
        for t, ev in per_term.items():
            f = annotation_frequency(ev)
            if f is not None and t in subtree:
                ann.setdefault(did, []).append((t, f))
    anc = ancestor_sets(subtree, parents)
    ic = information_content({d: [t for t, _ in a] for d, a in ann.items()}, anc)
    ix = build_index(
        ic=ic,
        parents=parents,
        diseases=((d, names[d], a) for d, a in ann.items()),
        # "-" is HPO's no-symbol sentinel (a few genes): not one gene, so never ranked.
        gene_diseases=conn.execute(
            "SELECT gene_symbol, disease_id FROM gene_disease WHERE gene_symbol <> '-'"
        ),
        aliases=aliases,
        labels=labels,
    )
    ix.gene_ids = {
        i.removeprefix("NCBIGene:"): s
        for i, s in conn.execute(
            "SELECT DISTINCT ncbi_gene_id, gene_symbol FROM gene_disease WHERE gene_symbol <> '-'"
        )
    }
    return ix
