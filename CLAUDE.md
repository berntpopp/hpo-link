# CLAUDE.md

This file orients Claude Code (and other agents) in this repository.

**Read [AGENTS.md](AGENTS.md) first** — it is the authoritative contributor and
agent guide (architecture, invariants, conventions, definition of done). This
file only highlights the essentials.

## Essentials

- `hpo-link` is an MCP + REST server over the Human Phenotype Ontology (HPO),
  backed by a locally-built SQLite index. It mirrors the sibling `mgi-link` stack.
- **Two planes:** the data plane (`config`/`constants`/`identifiers`/`ingest`/
  `data`/`services`) builds & reads the index and returns plain dicts; the MCP
  plane (`mcp/`) is domain-agnostic scaffolding where `run_mcp_tool` owns
  `success`/`_meta` and returns structured errors (never raised).
- **Invariants:** every `compact`+ (default) response carries
  `_meta.next_commands` (`minimal` opts out → `_meta` = `{tool, request_id}`);
  7-code error
  taxonomy; each tool has `output_schema` + `READ_ONLY_OPEN_WORLD` and a first
  sentence ending `Signature: tool(args...)`; keep `capabilities.TOOLS` in sync;
  normalise ids in `identifiers.py`; cite the HPO id + HPO release version.
- **Definition of done:** `make ci-local` green (format-check, lint-ci, lint-loc
  ≤500 lines/file, mypy strict, tests ≥80% coverage).
- `structlog` → stderr only; stdout is reserved for the stdio MCP protocol.

## Common commands

```bash
make install        # uv sync --group dev
make data           # build the local Mondo index
make data-status    # print loaded release + counts
make dev            # unified REST + MCP server
make mcp-serve      # stdio MCP server
make ci-local       # the full gate
```

Research use only; not for clinical decision support. HPO data is CC BY 4.0.
