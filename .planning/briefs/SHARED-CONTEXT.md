# Shared context — hpo-link MCP audit implementation

You are a senior MCP engineer implementing improvements to `hpo-link`, an MCP +
REST server over the Human Phenotype Ontology (HPO), backed by a local SQLite DB.
Read this file first, then your workstream brief (`WS-A.md` / `WS-B.md` / `WS-C.md`).

## Non-negotiable architecture (two planes)

- **Data plane** (`config.py`, `identifiers.py`, `ingest/`, `data/`, `services/`):
  returns **plain dicts**, raises typed exceptions from `hpo_link.exceptions`
  (`InvalidInputError`, `NotFoundError`, `AmbiguousQueryError`,
  `DataUnavailableError`, ...). It NEVER builds error envelopes.
- **MCP plane** (`mcp/`): `run_mcp_tool` in `mcp/envelope.py` owns `success` /
  `_meta` and converts exceptions into **returned** structured errors. Tool bodies
  return a plain payload dict; the envelope injects `success`/`_meta`.

## Invariants you must preserve

- 7-code error taxonomy: `invalid_input`, `not_found`, `ambiguous_query`,
  `data_unavailable`, `rate_limited`, `upstream_unavailable`, `internal_error`.
  `InvalidInputError(msg, field=..., allowed=..., hint=...)` carries `field`.
- `response_mode` ∈ `minimal | compact | standard | full` (default `compact`).
  `_meta` is tiered by `response_mode` in `envelope._shape_meta` — do NOT change that.
- Every `compact`+ response carries `_meta.next_commands`; `minimal` opts out.
  Tool bodies set `payload.setdefault("_meta", {})["next_commands"] = [...]`.
- Files stay **≤ 500 lines** (hard CI cap, `scripts/check_file_size.py`).
- Citation: cite HPO id + HPO release (`hpo_version`). `recommended_citation`
  is the long-form string.
- `structlog`/logging → **stderr only**. Never `print` to stdout.

## Definition of done (per workstream)

- TDD: **write the failing test first**, then implement. Keep unit tests
  self-contained (build a fixture SQLite from `load_schema_sql()` or reuse
  fixtures in `tests/conftest.py`).
- Your changes must pass: `uv run pytest <your test files> -q` AND
  `uv run mypy --strict hpo_link` (run mypy on the whole package; it's fast).
- Run `uv run ruff format hpo_link tests` and `uv run ruff check hpo_link tests`
  on the files you touched (fix all lint).
- Touched files ≤ 500 lines.
- **Do NOT run `git commit` or any git mutation** — the controller commits.
  **Do NOT touch files outside your workstream's owned set** (listed in your brief).

## The absent-entity contract (LOCKED — WS-B implements, WS-C documents)

This is the single uniform rule across the 6 association tools
(`get_phenotypes_for_gene`, `get_genes_for_phenotype`, `get_phenotypes_for_disease`,
`get_diseases_for_phenotype`, `get_genes_for_disease`, `get_diseases_for_gene`)
and `resolve_xref`:

1. **Empty / blank id** → `invalid_input` (with `field`). (Already true.)
2. **Malformed identifier** → `invalid_input` (with `field`):
   - disease path: a `disease_id` that is not a CURIE — no `:` (e.g. `notacurie`),
     empty prefix (`:123`), or empty body (`OMIM:`).
   - gene path: an `NCBIGene:` CURIE whose body is not all digits (e.g.
     `NCBIGene:` or `NCBIGene:abc`); or a colon-bearing token whose prefix is not
     `NCBIGene` (genes are bare symbols or NCBI ids). A bare symbol or bare
     numeric id is well-formed.
3. **Well-formed but unknown id** (valid shape, simply no annotations) → **empty
   200 page**: `success:true`, empty list, `total:0`. (NOT `not_found`.)
4. **`not_found`** is reserved for genuine **identity-resolution failure**: the
   `resolve_*` tools and the phenotype→X paths where a free-text term/label
   cannot be resolved to any HPO id (handled by the resolver — unchanged).

Net effect: `get_phenotypes_for_gene("NCBIGene:999999999")` →
empty 200 (was `not_found`). `get_phenotypes_for_disease("notacurie")` →
`invalid_input` (was empty 200). Same input class behaves identically across all
six tools.

## Useful facts (verified against the source)

- `repo.read_meta()` returns a **column-keyed dict** of the single-row `meta`
  table. Count columns ALREADY EXIST and are populated:
  `term_count, obsolete_count, closure_count, xref_count,
  disease_phenotype_count, gene_phenotype_count, gene_disease_count`.
- `parse_frequency(raw)` in `hpo_link/ingest/parser_hpoa.py` decodes a raw HPOA
  frequency string → `(frequency_hpo, frequency_ratio, frequency_percent)`.
- The fuzzy/suggestion logic lives in `hpo_link/services/resolution.py`
  (`decide_fuzzy`, `Resolver._search_suggestions`, `_hits_to_suggestions`).
- Output schemas in `mcp/schemas.py` are permissive metadata (no runtime
  validation test exists); they're consumer-facing documentation.
- A prebuilt DB exists at `data/hpo.sqlite` (HPO 2026-06-06). You may query it
  read-only to verify examples, e.g.
  `uv run python -c "import sqlite3;..."` — but tests must use fixtures.

## Report contract

When done, append your full report to your report file
(`.planning/briefs/WS-X-report.md`) and return ONLY: status
(`DONE` / `DONE_WITH_CONCERNS` / `BLOCKED`), the list of files changed, a
one-line test summary (command + pass count), and any concerns. Keep the returned
message short — the detail goes in the report file.
