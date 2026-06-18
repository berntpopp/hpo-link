# AGENTS.md — hpo-link

Guidance for agents and contributors working in this repository.

## What this is

`hpo-link` is an MCP + REST server that grounds phenotype work in the Human
Phenotype Ontology (HPO). It builds a local SQLite index from the HPO OBO
releases and serves read-only tools for phenotype term lookup, the `is_a`
hierarchy, and cross-ontology mapping. It mirrors the sibling `mgi-link` stack/architecture.

## Two planes (non-negotiable boundary)

- **Data plane** — `config.py`, `constants.py`, `identifiers.py`, `ingest/`,
  `data/`, `services/`. Downloads the HPO release (conditional GET), atomically
  builds the SQLite index (terms, labels, synonyms, definitions, `is_a` closure,
  cross-references with provenance + predicate, deprecated/`replaced_by`), and
  **returns plain dicts**. It raises typed exceptions from `hpo_link.exceptions`;
  it never builds error envelopes.
- **MCP plane** — `mcp/`. Domain-agnostic scaffolding shared with siblings.
  `run_mcp_tool` (in `mcp/envelope.py`) owns `success` / `_meta` and converts
  exceptions into **returned** structured errors (never raised to the client).

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
- Ground every claim in the local index and cite the HPO id + HPO release
  version (`hpo_version` is echoed in record payloads).

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
against the grouped-payload schema leak (every tool's real output — success and
error, all response modes — must validate against its own `output_schema`). After
a redeploy, also run `make verify-deploy URL=<server>/health`: it pipes the live
`/health` (or a `get_diagnostics`) payload into
`scripts/check_deployed_freshness.py` and exits non-zero unless the build
`git_sha` matches local HEAD — the guard against shipping a green local tree whose
fixes never reached the running container.

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
  data/    repository           # read-only SQLite
  services/ mondo_service, shaping, pagination, refresh
  mcp/     envelope, capabilities, annotations, schemas, next_commands, metrics,
           middleware, facade, arg_help, resources, service_adapters, tools/
server.py  mcp_server.py  scripts/check_file_size.py
```
