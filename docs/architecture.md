# Architecture

`hpo-link` is split into two planes that meet at a thin envelope boundary.

## Data plane

Builds and reads a local SQLite database; returns plain dicts; raises typed
exceptions.

```
config / constants / identifiers
ingest/  downloader → lock → parser → builder (schema.sql) → cli
data/    repository (read-only SQLite)
services/ hpo_service, annotation_service, shaping, pagination, refresh
```

### Ingest pipeline

1. **Download** (`ingest/downloader.py`) — conditional GET of `hp.json` and
   `phenotype.hpoa` from the HPO OBO PURLs / GitHub releases, using
   `If-None-Match` / `If-Modified-Since` from a `download_cache.json`. A `304`
   reuses the local file.
2. **Lock** (`ingest/lock.py`) — an `fcntl` build lock (`.build.lock`) serialises
   concurrent builds; it times out into a `DataUnavailableError`.
3. **Parse** (`ingest/parser.py`) — `parse_hpo_json` extracts terms, `is_a`
   parents, synonyms (scope/type/sources), definitions, xrefs (with provenance
   and a derived predicate), subsets, and `is_obsolete`/`replaced_by`/`consider`.
   `hpo_closure_pairs` computes the transitive `is_a` closure (cycle-guarded
   recursion over the multi-parent DAG, including the self-pair).
   `hpo_top_groupings` derives the direct children of `HP:0000001`.
   `parse_hpoa` reads the HPOA gene/disease annotations.
4. **Build** (`ingest/builder.py`) — writes a temp SQLite via
   `load_schema_sql()`, loads all tables, then `os.replace`s it onto
   `hpo.sqlite` (atomic). Provenance (HPO release, source validators, counts)
   is written to the single-row `meta` table.

### SQLite schema (`ingest/schema.sql`)

| table | purpose |
|-------|---------|
| `term` | one row per HPO class (name, definition, obsolete, replaced_by, consider, synonyms JSON, subsets JSON). |
| `term_lookup` | uppercased label/synonym → hp_id (+ `label_type`) for `resolve_term`. |
| `term_fts` | FTS5 over name/synonyms/definition for `search_terms`. |
| `hpo_parent` | direct `is_a` edges. |
| `hpo_closure` | transitive `is_a` (`hp_id`, `ancestor_id`), incl. self-pair. |
| `hpo_top_grouping` | direct children of `HP:0000001` (orientation/roll-up). |
| `xref` | **merged** OBO `xref:` rows, tagged `origin`, `predicate`, `source`. |
| `hpoa_gene_phenotype` | HPOA gene↔phenotype associations. |
| `hpoa_disease_phenotype` | HPOA disease↔phenotype associations. |
| `meta` | single-row provenance: schema/HPO version, validators, counts, build time. |

### Cross-reference model

OBO `xref:` lines are indexed per row carrying a mapping **predicate** and
ranked for resolution:
`exactMatch > equivalentTo > closeMatch > narrowMatch > broadMatch > xref`.
`resolve_xref` walks external → HP using this ranking;
`map_cross_ontology` groups a term's mappings by target prefix.

### Services

`HpoRepository` opens the database read-only (`file:…?mode=ro`) and exposes the
row-level queries. `HpoService` composes them into tool payloads (plain
dicts), resolving a `term` argument that may be an HP id, a label/synonym, or
an external xref. `AnnotationService` wraps the annotation repository.
`shaping.py` projects payloads to the requested `response_mode`;
`pagination.py` adds the truncation block. `refresh.py` bootstraps the
database at startup and can run a periodic refresh.

## MCP plane (`mcp/`)

Domain-agnostic scaffolding shared with sibling `-link` servers.

```
facade.create_hpo_mcp()    →  FastMCP
  register_discovery_tools   (get_server_capabilities, get_diagnostics)
  register_ontology_tools    (resolve_term, search_terms, get_term)
  register_hierarchy_tools   (ancestors, descendants, parents, children)
  register_xref_tools        (resolve_xref, map_cross_ontology)
  register_annotation_tools  (gene↔phenotype↔disease association tools)
  register_capability_resources  (hpo://capabilities|tools|usage|reference|…)
  ArgValidationMiddleware
```

### Request lifecycle

1. **Middleware** (`mcp/middleware.py`) normalises argument aliases
   (e.g. `phenotype`/`term`/`hp_id` → `query`) and converts binding failures
   into an `invalid_input` envelope with a did-you-mean.
2. **Tool** (`mcp/tools/*`) calls the service via `get_hpo_service()`, attaches
   `_meta.next_commands` (from `mcp/next_commands.py`), and wraps the call in
   `run_mcp_tool(...)`.
3. **Envelope** (`mcp/envelope.py`) injects `success`/`_meta` on success, or
   classifies an exception into one of the 7 error codes and returns a structured
   error (with `retryable`, `recovery_action`, and recovery `next_commands`). An
   obsolete term becomes a `not_found`-class error carrying `replaced_by` and
   chaining to the successor.

## Transports

`server_manager.UnifiedServerManager` selects the transport: `unified`
(FastAPI `/health` + mounted MCP at `/mcp`), `http` (REST only), or `stdio`
(`mcp_server.py`, for Claude Desktop). `structlog` logs to stderr so stdout
stays clean for the stdio protocol.
