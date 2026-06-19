# WS-A Report — Diagnostics & Observability

## Status: DONE

## Files Changed

| File | Change |
|------|--------|
| `hpo_link/data/repository.py` | Extended `counts()` from 4 keys to all 7 (fixed `xrefs`→`xref`, added `disease_phenotype`, `gene_phenotype`, `gene_disease`) |
| `hpo_link/mcp/tools/discovery.py` | Added `_resolve_counts()` pure helper; fixed `get_diagnostics` to use it (replaced 7 broken `meta.get("num_*")` reads) |
| `hpo_link/mcp/metrics.py` | Added `error_rate_withheld_below` key in `snapshot()` when `error_rate` is `None` |
| `tests/unit/test_tools_discovery.py` | NEW — 6 tests for `_resolve_counts` (meta-prefer, per-key fallback, absent key, consistency, all-keys, all-fallback) |
| `tests/unit/test_metrics.py` | NEW — 5 tests for `error_rate_withheld_below` (below threshold, zero requests, above threshold, key absent above threshold, float type) |
| `tests/unit/test_builder.py` | Added T0.1 regression: `test_build_database_db_meta_row_has_all_seven_counts` verifies the DB `meta` table row has positive integers for all 7 `*_count` columns |
| `tests/unit/test_repository_ontology.py` | Added 5 new `counts()` tests: all-seven-keys, terms-positive, obsolete-le-terms, closure-positive, annotation-tables-positive |

## Root Cause Confirmed

The audit was correct that `get_diagnostics` returned all-`None` counts, but the cause was a **key-name mismatch** in `discovery.py`: it read `meta.get("num_terms")`, `num_obsolete`, etc. — none of which exist as column names. The actual columns are `term_count`, `obsolete_count`, etc. The builder already wrote correct values. No `builder.py` change was needed.

## What Each Change Does

### T0.1 — `test_builder.py`
Adds a regression test that opens the built SQLite DB and verifies the `meta` table row has non-NULL, non-negative integer values for all 7 `*_count` columns, plus internal consistency (`obsolete_count <= term_count`). Confirms the builder already persists all counts correctly — no builder change needed.

### T0.2 — `repository.py` + `discovery.py`

**`repository.counts()`**: Changed from returning 4 keys (`terms`, `obsolete`, `xrefs`, `closure`) to 7 keys with correct naming:
- `xrefs` → `xref` (singular, matches diagnostics payload)
- Added: `disease_phenotype`, `gene_phenotype`, `gene_disease` (live `SELECT COUNT(*)` per table)

**`discovery.py` — `_resolve_counts()`**: New pure helper (exportable for testing) that:
1. Maps the 7 meta column names → result key names
2. Lazy-calls `repo.counts()` only once if any meta value is `None` or absent
3. Per-key: prefers `meta[col]` when non-None, falls back to `repo.counts()[key]` otherwise

**`get_diagnostics`**: Now calls `_resolve_counts(meta, repo)` when `repo` is available, producing real counts. When no repo (index unavailable), returns `None` for all 7 keys.

### T0.3 — `metrics.py`

In `_Metrics.snapshot()`, when `report_rate` is `False` (i.e. `requests < _ERROR_RATE_MIN_SAMPLE`), now emits `"error_rate_withheld_below": _ERROR_RATE_MIN_SAMPLE` alongside `error_rate: null`. When `report_rate` is `True`, the key is absent. This lets consumers understand the `null` is an intentional small-sample guard, not a bug.

## Test Command + Pass Counts

```
uv run pytest tests/unit/test_tools_discovery.py tests/unit/test_metrics.py tests/unit/test_builder.py tests/unit/test_repository_ontology.py tests/unit/test_repository_annotations.py -q
```

**Result: 64 passed in 0.19s**

## mypy Result

```
uv run mypy --strict hpo_link
Success: no issues found in 47 source files
```

## ruff Result

```
uv run ruff check hpo_link/mcp/tools/discovery.py hpo_link/data/repository.py hpo_link/mcp/metrics.py tests/unit/test_tools_discovery.py tests/unit/test_metrics.py tests/unit/test_builder.py tests/unit/test_repository_ontology.py
All checks passed!
```

## Line Counts (all ≤ 500)

| File | Lines |
|------|-------|
| `discovery.py` | 160 |
| `repository.py` | 324 |
| `metrics.py` | 105 |
| `test_tools_discovery.py` | 177 |
| `test_metrics.py` | 67 |
| `test_builder.py` | 75 |
| `test_repository_ontology.py` | 228 |

## Concerns

None. The implementation is clean:
- `_resolve_counts` is a pure, unit-testable function with no side effects on the tool registration
- The fallback is lazy (one `repo.counts()` call max per `get_diagnostics` invocation)
- No files outside the WS-A owned set were touched
- Pre-existing failures in `test_annotation_service.py` (15 tests, WS-B work) and collection errors in `test_identifiers.py`, `test_release.py`, `test_shaping_annotations.py` (WS-B/C stubs) are unrelated to WS-A
