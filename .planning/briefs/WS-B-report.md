# WS-B Report — Association contract, token efficiency & frequency

**Date:** 2026-06-19
**Branch:** feat/mcp-audit-improvements
**Status:** DONE

## Summary

WS-B implemented four tasks (T1.2, T1.3, T2.1, T2.2, T3.2) using strict TDD
(failing test written before every production change). All 112 affected tests
pass; mypy --strict is clean; ruff check passes on all touched files.

---

## Files Changed

### Production files

| File | Change |
|------|--------|
| `hpo_link/identifiers.py` | +`validate_disease_id`, +`validate_gene`; added import of `InvalidInputError` |
| `hpo_link/services/shaping.py` | +`shape_annotation_rows` row-shaping helper |
| `hpo_link/services/annotation_service.py` | Full rewrite: removed `NotFoundError` on zero-rows in gene path, switched to `validate_gene`/`validate_disease_id`, added `shape_annotation_rows` calls, `_provenance(mode)` gating, `parse_frequency` decoding for gene rows |

### Test files

| File | Change |
|------|--------|
| `tests/unit/test_identifiers.py` | Added 14 tests for `validate_disease_id` + `validate_gene` (valid and all malformed cases) |
| `tests/unit/test_annotation_service.py` | Updated 8 old tests (recommended_citation now mode-gated; not_found → empty-page contract); added 31 new tests covering T1.2/T1.3/T2.1/T2.2/T3.2 |
| `tests/unit/test_tools_annotations.py` | Updated 1 test (`test_get_phenotypes_for_gene_bad_gene` → `test_get_phenotypes_for_gene_absent_gene_returns_empty`) |
| `tests/unit/test_shaping_annotations.py` | **New file** — 11 unit tests for `shape_annotation_rows` across all 4 modes |

---

## What each change does

### T1.3 — CURIE/id shape validation (`identifiers.py`)

- `validate_disease_id(raw)`: strips, requires `PREFIX:body` (both non-empty),
  raises `InvalidInputError(field="disease_id")` for: no colon, empty prefix,
  empty body, or blank. Returns normalized id (prefix uppercased) on success.
- `validate_gene(raw)`: strips; if colon present and prefix != `ncbigene`
  (case-insensitive) → `InvalidInputError(field="gene")`; if prefix is
  `ncbigene` and body is not all-digits → `InvalidInputError(field="gene")`;
  otherwise delegates to `normalize_gene`. Empty → `InvalidInputError`.

### T1.2 — Gene path returns empty 200 (not `not_found`) (`annotation_service.py`)

Removed the `if total == 0: raise NotFoundError(...)` block from
`get_phenotypes_for_gene`. Both gene-path methods (`get_phenotypes_for_gene`,
`get_diseases_for_gene`) now use `validate_gene` instead of the old empty-string
guard + `normalize_gene`. The phenotype→X and disease→X resolver paths are
unchanged (`not_found` on unresolvable term is correct and preserved).
`validate_disease_id` is now called in `get_phenotypes_for_disease` and
`get_genes_for_disease`, catching malformed CURIEs before the DB query.

### T2.1 — Compact rows drop null/empty (`shaping.py`, `annotation_service.py`)

New `shape_annotation_rows(rows, mode)` function added to `shaping.py`:
- `standard`/`full`: rows returned unchanged.
- `compact`/`minimal`: iterate each row, drop any key whose value satisfies
  `_is_empty()` (None, "", [], {}); always keep `hpo_id` and `name` anchors.

Called in all six association methods before assembling the payload. This gives
the big token win for `get_phenotypes_for_disease` (drops `qualifier:""`,
`onset:""`, `sex:""`, `modifier:""`, and null frequency triplet fields per row).

### T2.2 — `recommended_citation` gated to standard/full (`annotation_service.py`)

`_provenance()` changed to `_provenance(mode: str = "compact")`:
- Always includes `hpo_version`.
- Includes `recommended_citation` only when `mode in ("standard", "full")`.

All six methods now pass `response_mode` to `_provenance(response_mode)`. The
citation invariant is satisfied by `hpo_id` + `hpo_version` at compact.

### T3.2 — Gene-path frequency decoded (`annotation_service.py`)

In `get_phenotypes_for_gene`, each repository row gets the frequency triplet
decoded via `parse_frequency(row.get("frequency"))`:
```python
fhpo, fratio, fpct = parse_frequency(r.get("frequency"))
r["frequency_hpo"] = fhpo
r["frequency_ratio"] = fratio
r["frequency_percent"] = fpct
```
The raw `frequency` field is preserved (matching disease path behavior). The
T2.1 compact shaping then naturally drops the null triplet fields in compact
mode. `parse_frequency` is imported from `hpo_link/ingest/parser_hpoa.py`
without editing that file.

---

## Existing tests updated and why

The following tests asserted OLD behavior that the new contract supersedes:

1. **`test_phenotypes_for_gene_not_found`** → renamed to
   `test_phenotypes_for_gene_absent_returns_empty_page`. WS-B T1.2 changes the
   contract: unknown (well-formed) gene → empty 200, not `not_found`.

2. **`test_phenotypes_for_gene_fields`** — removed `recommended_citation` from
   the required-field list (it is now gated to standard/full per T2.2).

3. **`test_phenotypes_for_gene_recommended_citation`** → renamed to
   `test_phenotypes_for_gene_recommended_citation_at_standard`. Now calls with
   `response_mode="standard"` to match the new contract.

4. **`test_genes_for_phenotype_fields`** — same: removed `recommended_citation`.

5. **`test_genes_for_phenotype_recommended_citation`** → renamed to
   `test_genes_for_phenotype_recommended_citation_at_standard`.

6. **`test_phenotypes_for_disease_fields`** — removed `recommended_citation`.

7. **`test_phenotypes_for_disease_recommended_citation`** → renamed to
   `test_phenotypes_for_disease_recommended_citation_at_standard`.

8. **`test_genes_for_disease_fields`** — removed `recommended_citation`.

9. **`test_diseases_for_gene_fields`** — removed `recommended_citation`.

10. **`test_get_phenotypes_for_gene_bad_gene`** (test_tools_annotations.py) →
    renamed to `test_get_phenotypes_for_gene_absent_gene_returns_empty`. Now
    asserts `success=True`, `total=0`, `phenotypes=[]` (empty 200), not
    `error_code="not_found"`.

All updates are expected and correct per the brief's statement: "Update them to
the new contract as part of TDD — that is expected and correct, not a regression."

---

## Test command and pass counts

```bash
uv run pytest tests/unit/test_annotation_service.py tests/unit/test_tools_annotations.py tests/unit/test_identifiers.py tests/unit/test_shaping_annotations.py -q
# 112 passed in 0.13s

uv run pytest tests -q -m "not integration" --ignore=tests/unit/test_release.py
# 241 passed in 0.49s
```

Note: `test_release.py` has a pre-existing `ModuleNotFoundError: No module named
'zstandard'` that prevents collection. This is unrelated to WS-B.

---

## mypy result

```
uv run mypy --strict hpo_link
Success: no issues found in 47 source files
```

---

## Line counts (all ≤ 500)

| File | Lines |
|------|-------|
| `hpo_link/identifiers.py` | 115 |
| `hpo_link/services/shaping.py` | 160 |
| `hpo_link/services/annotation_service.py` | 340 |

---

## Concerns

None. The implementation matches the spec exactly:
- Malformed → `invalid_input` with `field`.
- Well-formed-but-absent → empty 200 `total:0`.
- `not_found` reserved only for resolver identity failure (phenotype→X paths).
- `recommended_citation` gated to standard/full.
- Gene frequency triplet decoded, raw field preserved.
- Compact rows carry no null/empty fields.
