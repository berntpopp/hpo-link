# AGENTS.md — hpo-link

Guidance for agents and contributors working in this repository.

## What this is

`hpo-link` is an MCP + REST server that grounds phenotype work in the Human
Phenotype Ontology (HPO). It builds a local SQLite database from the HPO OBO
release and HPOA gene/disease annotation files, then serves read-only tools
for phenotype term lookup, the `is_a` hierarchy, cross-ontology mapping, and
gene↔phenotype↔disease association queries. It mirrors the sibling `mgi-link`
stack/architecture.

## Two planes (non-negotiable boundary)

- **Data plane** — `config.py`, `constants.py`, `identifiers.py`, `ingest/`,
  `data/`, `services/`. Downloads the HPO release (conditional GET), atomically
  builds the SQLite database (terms, labels, synonyms, definitions, `is_a`
  closure, cross-references with provenance + predicate, deprecated/`replaced_by`,
  HPOA gene and disease annotations), and **returns plain dicts**. It raises typed
  exceptions from `hpo_link.exceptions`; it never builds error envelopes.
- **MCP plane** — `mcp/`. Domain-agnostic scaffolding shared with siblings.
  `run_mcp_tool` (in `mcp/envelope.py`) owns `success` / `_meta` and converts
  exceptions into **returned** structured errors (never raised to the client).

## Architecture: ingest → data DAO → services → MCP

```
ingest/            download (conditional GET) → lock → parser → builder (schema.sql)
data/              HpoRepository (read-only SQLite DAO)
services/          HpoService, AnnotationService, shaping, pagination, refresh
mcp/               envelope, capabilities, annotations, schemas, next_commands,
                   metrics, middleware, facade, arg_help, resources, tools/
server.py          unified REST + MCP transport (FastAPI + uvicorn)
mcp_server.py      stdio transport (Claude Desktop)
```

## Invariants

- Services return plain dicts; the envelope owns `success`/`_meta` and returns
  structured errors. **7-code error taxonomy**: `invalid_input`, `not_found`,
  `ambiguous_query`, `data_unavailable`, `rate_limited`, `upstream_unavailable`,
  `internal_error`.
- Every `compact` (default) or richer response carries `_meta.next_commands`
  (ready-to-call follow-ups); `minimal` is the explicit opt-out and returns only
  `_meta = {tool, request_id}`. `_meta` verbosity is tiered by `response_mode`
  (`_shape_meta`): `compact` keeps `next_commands` + `capabilities_version` but
  drops the `elapsed_ms` echo; `standard`/`full` add `elapsed_ms`.
- Every tool declares `output_schema` + `READ_ONLY_OPEN_WORLD` annotations, and
  its first description sentence is a discovery summary ending with
  `Signature: tool(args...)`.
- **Every tool's real output (success + error, all response modes) must validate
  against its own `output_schema`** — enforced by `tests/unit/test_output_schemas.py`.
  Grouped-by-prefix payloads (`xrefs`, `mappings`) are objects keyed by prefix, not
  arrays; declare them as objects or the envelope leaks a raw validation error.
- `response_mode` ∈ `minimal | compact | standard | full`. List tools also carry a
  pagination block (`total`/`returned`/`limit`/`offset`/`truncated`/`next_offset`);
  when truncated, `_meta.next_commands` offers a forward-page step (advance `offset`).
- `compact`+ `_meta` echoes `capabilities_version` (a hash of the discovery
  contract) so warm clients can skip re-fetching `get_server_capabilities`
  (omitted in `minimal`).
- Keep `mcp/capabilities.py::TOOLS` in sync with the registered tool set
  (`tests/unit/test_tool_names.py` enforces this).
- Identifiers are normalised in `identifiers.py` (`HP:NNNNNNN`; external
  CURIEs case-folded).
- Ground every claim in the local database and cite the HPO id + HPO release
  version. `hpo_version` is the per-call citation anchor (echoed on every
  non-minimal payload). The long-form `recommended_citation` is inlined only on
  `standard`/`full` payloads — **term and association alike** (one rule across
  both planes); `compact`/`minimal` carry `hpo_version` and defer the full
  citation to `get_server_capabilities`, which is the canonical source of record
  per the advertised `provenance_policy`.
- `structlog` logs to **stderr only** — stdout is reserved for the stdio MCP
  protocol. Never `print` to stdout outside the CLI.
- Files stay under 500 lines (hard cap enforced by `scripts/check_file_size.py`
  in CI).

## Data pipeline + artifact model

1. **Download** (`ingest/downloader.py`) — conditional GET of `hp.json` and
   `phenotype.hpoa` via OBO PURLs / HPO GitHub releases. `If-None-Match` /
   `If-Modified-Since` from a `download_cache.json`; a `304` reuses the local
   file.
2. **Lock** (`ingest/lock.py`) — an `fcntl` build lock (`.build.lock`)
   serialises concurrent builds; times out into `DataUnavailableError`.
3. **Parse** (`ingest/parser.py`) — extracts HPO terms, `is_a` parents,
   synonyms, definitions, xrefs (with provenance and predicate), subsets,
   `is_obsolete`/`replaced_by`/`consider`; computes the transitive `is_a`
   closure; parses HPOA gene/disease annotations.
4. **Build** (`ingest/builder.py`) — writes a temp SQLite via
   `load_schema_sql()`, loads all tables, then `os.replace`s it onto
   `hpo.sqlite` (atomic). Provenance (HPO release, source validators, counts)
   is written to the single-row `meta` table.

**Immutable artifact model:** production Docker deployments use the exact,
pinned GitHub Release bundle configured in `immutable_data`. The `hpo-data-init`
init sidecar is the only production downloader: it verifies the compressed
artifact and the expanded SQLite tree, atomically publishes `/data/current`,
and exits successfully before the application starts. The application mounts
that named volume read-only and never bootstraps or refreshes data in process.
Local `hpo-link-data build` and `refresh` commands remain authoring tools, not
serving startup paths.

## Definition of done

`make ci-local` must be green:

```
format-check   ruff format --check
lint-ci        ruff check
lint-loc       scripts/check_file_size.py   (≤ 500 lines/file, hard cap)
typecheck      mypy --strict
test-fast      pytest -n auto, coverage ≥ 80%
```

`tests/unit/test_output_schemas.py` runs inside `test-fast` and is the gate
against the grouped-payload schema leak. After a redeploy, also run
`make verify-deploy URL=<server>/health`.

## Conventions

- Python 3.12+, `uv`, hatchling. Add deps via `pyproject.toml`, then `uv lock`.
- `structlog` logs to **stderr only** — stdout is reserved for the stdio MCP
  protocol. Never `print` to stdout outside the CLI.
- Files stay under 500 lines; split by responsibility, not layer.
- TDD: write the failing test first. Keep unit tests self-contained (build a
  fixture SQLite from `load_schema_sql()` or `tests/fixtures/`).
- Frozen contracts: `mcp/` scaffolding, `ingest/schema.sql`, and the
  `HpoService` / `HpoRepository` signatures are the seams other modules code
  against — change them deliberately.

## Layout

```
hpo_link/
  config, constants, identifiers, exceptions, logging_config, buildinfo, app
  server_manager                # unified | http | stdio transports
  ingest/  downloader, lock, parser, builder, schema.sql, cli
  data/    repository, annotations_repository
  services/ hpo_service, annotation_service, shaping, pagination, refresh
  mcp/     envelope, capabilities, annotations, schemas, next_commands, metrics,
           middleware, facade, arg_help, resources, service_adapters, tools/
server.py  mcp_server.py  scripts/check_file_size.py
```
