# WS-B — Association contract, token efficiency & frequency (P1.2/1.3, P2.1/2.2, P3.2)

**Goal:** uniform absent/invalid semantics across the 6 association tools;
genuinely compact `compact` rows; and gene-path frequency decoded to match the
disease path. Lifts API consistency 7.5 → 9, Token efficiency 7.5 → 9,
`get_phenotypes_for_disease` 7 → 9, `get_phenotypes_for_gene` 8 → 9.5.

## Files you OWN (touch only these + their tests)

- `hpo_link/services/annotation_service.py`
- `hpo_link/services/shaping.py`
- `hpo_link/identifiers.py`
- Tests: `tests/unit/test_annotation_service.py` (extend),
  `tests/unit/test_tools_annotations.py` (extend),
  `tests/unit/test_identifiers.py` (extend).

Do NOT touch `capabilities.py` (WS-C documents the contract there), `schemas.py`,
`discovery.py`, `parser_hpoa.py` (import from it, don't edit), `ontology.py`.

## Tasks

### T1.3 — CURIE/id shape validation → `invalid_input` (do this first)

Add validators to `identifiers.py` (data plane; raise typed exceptions):

- `validate_disease_id(raw: str) -> str`: strip; require a CURIE shape — a single
  `:` with a non-empty prefix AND non-empty body. Reject `notacurie` (no colon),
  `:123` (empty prefix), `OMIM:` (empty body) → raise
  `InvalidInputError(..., field="disease_id")`. On success return the
  normalized id (reuse `normalize_disease_id`).
- `validate_gene(raw: str) -> tuple[str, str]`: strip; if it contains `:` and the
  prefix (case-insensitive) is not `NCBIGene`, raise `InvalidInputError(...,
  field="gene")`. If prefix is `NCBIGene`, the body must be all digits else
  `InvalidInputError`. Otherwise return `normalize_gene(raw)`. A bare symbol or
  bare numeric id is valid.

Keep `InvalidInputError` messages short, actionable, and name the expected shape.
Call these from the service (below). `identifiers.py` may import
`InvalidInputError` from `hpo_link.exceptions`.

### T1.2 — Gene path: empty page, not `not_found`

In `annotation_service.get_phenotypes_for_gene`, **remove** the
`if total == 0: raise NotFoundError(...)` block (lines ~115-118). A well-formed
gene with zero annotations returns an empty 200 page (`total:0`), exactly like
`get_diseases_for_gene` already does. Keep the empty-string `invalid_input` guard
(now superseded by `validate_gene`, which also handles empty → call it and let it
raise). Apply `validate_gene` in all gene-path methods
(`get_phenotypes_for_gene`, `get_diseases_for_gene`). Apply `validate_disease_id`
in all disease-path methods (`get_phenotypes_for_disease`, `get_genes_for_disease`).

Do NOT change the phenotype→X methods' resolver behavior — `_resolve_to_id`
raising `NotFoundError` on an unresolvable term is correct and stays.

### T2.1 — Make `compact` rows actually compact (drop null/empty per row)

Add a row-shaping helper to `shaping.py`, e.g.
`shape_annotation_rows(rows: list[dict], mode: str) -> list[dict]`:

- `standard` / `full`: return rows unchanged (full columns).
- `compact` / `minimal`: drop keys whose value is null/empty (reuse the existing
  `_is_empty` predicate: `None`, `""`, `[]`, `{}`). Always keep `hpo_id` (and for
  rows that have it, `name`) even if a future row had them empty.

Call it in each association service method to shape the `rows`/`phenotypes`/
`genes`/`diseases` list by `response_mode` BEFORE assembling the payload. This is
the big token win for `get_phenotypes_for_disease` (drops `qualifier:""`,
`onset:""`, `sex:""`, `modifier:""`, and null `frequency_*`).

### T2.2 — Move `recommended_citation` out of the `compact` body

The server already ADVERTISES (capabilities `provenance_policy`) that static
provenance "is not repeated per-call to conserve context tokens" — but the code
includes `recommended_citation` (~250 chars) on every association payload. Make
the code match the advertised contract:

- Change `_provenance()` → `_provenance(mode)`:
  - always include `hpo_version`.
  - include `recommended_citation` only when `mode in ("standard", "full")`.
    Omit it in `compact` and `minimal`. (hpo_id + hpo_version satisfy the citation
    invariant at compact.)
- Thread `response_mode` into `_provenance` in all six methods.

Update existing tests that assert `recommended_citation` is always present to be
mode-aware (present at standard/full, absent at compact/minimal).

### T3.2 — Decode gene-path frequency (symmetry with disease path)

In `get_phenotypes_for_gene`, the repository rows carry a raw `frequency`
(an HP code like `HP:0040281`, a ratio `42/163`, or `-`). The disease path
already exposes `frequency_hpo` / `frequency_ratio` / `frequency_percent`. Give
gene rows the same triplet:

- `from hpo_link.ingest.parser_hpoa import parse_frequency` (import only — do NOT
  edit `parser_hpoa.py`).
- For each gene-phenotype row, compute
  `(frequency_hpo, frequency_ratio, frequency_percent) =
  parse_frequency(row.get("frequency"))` and add them to the row. Keep the raw
  `frequency` too (disease path keeps raw `frequency` as well). The T2.1 compact
  shaping then naturally drops the null ones.

If importing `services` → `ingest` feels like a layering concern, it is
acceptable here (one small pure function); do NOT relocate it (that would touch
`builder.py`, owned by WS-A).

## Acceptance

- Parametrized matrix `{malformed, well-formed-absent, present} × {6 tools}`
  yields `invalid_input` | empty-200 | data uniformly.
- A 25-row `get_phenotypes_for_disease` `compact` payload has materially fewer
  bytes (target ≥ 30% smaller) and **no field that is empty/null across all
  rows** survives in `compact`.
- Gene and disease phenotype rows are field-symmetric on the frequency triplet.
- `recommended_citation` present at `standard`/`full`, absent at `compact`/`minimal`;
  `hpo_version` present in all non-minimal modes.

## Tests (TDD — write first)

- `validate_disease_id` / `validate_gene`: valid + each malformed case.
- Matrix test over the 6 tools (use a fixture DB) for the three input classes.
- `shape_annotation_rows`: drops empty in compact, keeps full in standard.
- A size/shape assertion: compact disease rows contain no all-empty column.
- Symmetry test: gene-phenotype row keys ⊇ {frequency_hpo, frequency_ratio,
  frequency_percent} at standard mode, matching disease rows.
- Provenance mode-gating test.
