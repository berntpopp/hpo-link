# CLAUDE.md

This file orients Claude Code (and other agents) in this repository.

**Read [AGENTS.md](AGENTS.md) first** — it is the authoritative contributor and
agent guide (architecture, invariants, conventions, definition of done). This
file only highlights the essentials.

## Role

`hpo-link` is an MCP + REST server over the Human Phenotype Ontology (HPO),
backed by a locally-built SQLite database. It serves phenotype term lookup,
`is_a` hierarchy traversal, cross-ontology mapping, and gene↔phenotype↔disease
association queries (HPOA). It mirrors the sibling `mgi-link` stack.

## Directory layout

```
hpo_link/          # core package (config, ingest, data, services, mcp)
server.py          # unified REST + MCP server entry point
mcp_server.py      # stdio MCP entry point (Claude Desktop)
scripts/           # CI helpers (check_file_size.py, check_deployed_freshness.py)
tests/             # unit + integration tests
docker/            # Dockerfile, docker-compose.yml, entrypoint.sh
docs/              # architecture.md, deployment.md, usage.md
```

See [AGENTS.md](AGENTS.md) for the full layout and architecture.

## Key `make` commands

```bash
make install        # uv sync --group dev
make data           # build the local HPO database
make data-status    # print loaded HPO release + counts
make dev            # unified REST + MCP server on http://127.0.0.1:8000
make mcp-serve      # stdio MCP server
make ci-local       # the full gate (format-check, lint, lint-loc, mypy, test)
make format         # auto-format with ruff
make typecheck      # mypy strict
make test           # unit tests (not integration)
```

## TL;DR lint / test / build

```bash
make ci-local        # must be green before any commit
make format          # fix formatting issues flagged by ci-local
uv run pytest tests -q -m "not integration"  # fast unit tests
```

## Invariants (summary)

- **Two planes:** data plane returns plain dicts; MCP plane owns `success`/`_meta`.
- Every `compact`+ response carries `_meta.next_commands`; `minimal` opts out.
- 7-code error taxonomy; every tool has `output_schema` + `READ_ONLY_OPEN_WORLD`.
- `structlog` → stderr only; stdout is reserved for the stdio MCP protocol.
- Files ≤ 500 lines; coverage ≥ 80%; `make ci-local` is the definition of done.
- Cite HPO id + HPO release version (`hpo_version`) in every payload.

Research use only; not for clinical decision support. HPO data: see
[https://hpo.jax.org/app/license](https://hpo.jax.org/app/license).
