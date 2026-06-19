# WS-A — Phase 0: Diagnostics & Observability (P0)

**Goal:** `get_diagnostics` reports real volume counts (fixing the only functional
bug, I-1), with a robust fallback, and the withheld `error_rate` is
self-explaining. Lifts `get_diagnostics` 6 → 9 and Observability 7 → 9.

## Files you OWN (touch only these + their tests)

- `hpo_link/mcp/tools/discovery.py`
- `hpo_link/data/repository.py` (the `counts()` method, ~line 277)
- `hpo_link/mcp/metrics.py`
- `hpo_link/ingest/builder.py` (only if a test reveals a real gap — see T0.1)
- Tests: `tests/unit/test_builder.py` (extend), `tests/unit/test_repository_*.py`
  (extend for `counts()`), and NEW files `tests/unit/test_tools_discovery.py`
  and/or `tests/unit/test_metrics.py`.

Do NOT touch `schemas.py`, `capabilities.py`, `annotation_service.py`,
`shaping.py`, `ontology.py` — other workstreams own them.

## Root cause (corrected from the audit)

The audit (I-1, T0.1) claimed "the builder never writes those keys." **That is
wrong.** The `meta` table already has columns `term_count, obsolete_count,
closure_count, xref_count, disease_phenotype_count, gene_phenotype_count,
gene_disease_count`, written by `builder.BuildMeta` / `_insert_meta`, and they ARE
populated (`make data-status` shows real counts). The actual bug is a **key-name
mismatch** in `discovery.py`: it reads `meta.get("num_terms")`, `num_obsolete`,
`num_closure`, `num_xref`, `num_disease_phenotype`, `num_gene_phenotype`,
`num_gene_disease` — none of which are real columns — so every `.get()` returns
`None`. Fix the read keys; do NOT add redundant `num_*` writes.

## Tasks

### T0.1 — Confirm counts are persisted (regression test)

The builder already persists counts. Add/keep a unit test in `test_builder.py`
asserting that a freshly built fixture DB's `meta` row has **positive integer**
counts for all seven `*_count` columns, and an internal-consistency check
(`obsolete_count <= term_count`). If — and only if — a test exposes a genuine
missing write, fix `builder.py`. Otherwise leave `builder.py` unchanged.

### T0.2 — Fix discovery read keys + add `repo.counts()` fallback

1. In `discovery.py`, read the correct meta columns:
   - `counts.terms` ← `meta["term_count"]`
   - `counts.obsolete` ← `meta["obsolete_count"]`
   - `counts.closure` ← `meta["closure_count"]`
   - `counts.xref` ← `meta["xref_count"]`
   - `counts.disease_phenotype` ← `meta["disease_phenotype_count"]`
   - `counts.gene_phenotype` ← `meta["gene_phenotype_count"]`
   - `counts.gene_disease` ← `meta["gene_disease_count"]`
2. **Fallback:** when a meta count column is missing/`None` (e.g. an older DB
   built before a column existed, or a partial build), fall back to
   `Repository.counts()`. **Prefer meta when present.** Implement per-key:
   `meta.get("<col>") if not None else fallback["<key>"]`.
3. `Repository.counts()` (repository.py:277) is **incomplete** — it returns only
   `{terms, obsolete, xrefs, closure}` (note `xrefs` plural) and is missing the
   three annotation counts. Extend it to return all seven with keys EXACTLY
   matching the diagnostics counts dict:
   `{terms, obsolete, closure, xref, disease_phenotype, gene_phenotype,
   gene_disease}` (singular `xref`). Use real `SELECT COUNT(*)` per table
   (`term` with `WHERE is_obsolete=1` for obsolete; tables `hpo_closure`, `xref`,
   `disease_phenotype`, `gene_phenotype`, `gene_disease`). Confirm the real table
   names from `schema.sql`.
4. Keep `discovery.py` readable and ≤ 500 lines. Strongly consider extracting a
   small **pure helper** `def _resolve_counts(meta: dict, repo) -> dict[str,int]`
   (in discovery.py) so it is unit-testable without a live `get_hpo_service()`.

### T0.3 — Self-explaining withheld error_rate

In `metrics.py::_Metrics.snapshot`, when `error_rate` is withheld (i.e.
`requests < _ERROR_RATE_MIN_SAMPLE`, so `error_rate is None`), also emit
`"error_rate_withheld_below": _ERROR_RATE_MIN_SAMPLE` in the snapshot so a
consumer understands the `null` is an intentional small-sample guard, not a bug.
When `error_rate` is reported, you may omit the key (or keep it — your call, but
be consistent and test it).

## Acceptance

- `get_diagnostics` returns positive integers for all seven counts against the
  built DB; `make data-status` and the tool agree.
- A DB whose `meta` row is missing a count column still reports counts via the
  `repo.counts()` fallback (simulate by passing a meta dict missing the keys to
  your pure helper).
- `metrics.snapshot()` carries `error_rate_withheld_below: 20` when `< 20`
  requests have been recorded.

## Tests (TDD — write first)

- `repo.counts()` returns all seven keys with correct values against a fixture DB.
- `_resolve_counts`: (a) prefers meta values when present; (b) falls back to
  `repo.counts()` per-key when a meta value is `None`; (c) internal consistency
  (`obsolete <= terms`).
- `metrics.snapshot()` includes `error_rate_withheld_below` below threshold and
  `error_rate` (a float) once ≥ threshold.
