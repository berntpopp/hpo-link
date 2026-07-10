# hpo-link

MCP/API server that grounds phenotype work in the [Human Phenotype Ontology (HPO)](https://hpo.jax.org/).

`hpo-link` builds a local SQLite database from the HPO OBO release and HPOA
gene/disease annotation files (served via OBO PURLs and the HPO GitHub
releases) and serves a **read-only** MCP + REST surface for phenotype term
lookup, the `is_a` hierarchy (ancestors/descendants via a transitive closure),
cross-ontology mapping, and gene↔phenotype↔disease association queries. There
is no live API — the local database is the only source, so lookups are fast
and offline.

Every response is grounded in the local database and cites the **HPO id + HPO
release version**. Research use only; **not** clinical decision support.

## Tools

### Discovery

| Tool | Signature |
|------|-----------|
| `get_server_capabilities` | `get_server_capabilities(detail=)` — discovery surface (tools, workflows, error taxonomy, limits). |
| `get_diagnostics` | `get_diagnostics()` — database status, loaded HPO release, counts. |

### Phenotype term lookup

| Tool | Signature |
|------|-----------|
| `resolve_term` | `resolve_term(query, response_mode=)` — label/synonym/HP id/xref → canonical term + `match_type`. |
| `search_terms` | `search_terms(query, limit=, include_obsolete=, response_mode=)` — FTS over name/synonyms/definition. |
| `get_term` | `get_term(term, response_mode=)` — definition, synonyms, grouped xrefs, parents/children, obsolescence. |

### Hierarchy

| Tool | Signature |
|------|-----------|
| `get_term_ancestors` | `get_term_ancestors(term, limit=, response_mode=)` — transitive `is_a` ancestors. |
| `get_term_descendants` | `get_term_descendants(term, limit=, response_mode=)` — transitive `is_a` descendants. |
| `get_term_parents` | `get_term_parents(term, response_mode=)` — direct `is_a` parents. |
| `get_term_children` | `get_term_children(term, response_mode=)` — direct `is_a` children. |

### Cross-ontology mapping

| Tool | Signature |
|------|-----------|
| `resolve_xref` | `resolve_xref(xref_id, limit=, response_mode=)` — external CURIE → HP ids, ranked by predicate. |
| `map_cross_ontology` | `map_cross_ontology(term, prefixes=, response_mode=)` — an HP term → mappings grouped by prefix. |

### Gene ↔ Phenotype ↔ Disease associations (HPOA)

| Tool | Signature |
|------|-----------|
| `get_phenotypes_for_gene` | `get_phenotypes_for_gene(gene, response_mode=)` — HPO terms annotated to a gene. |
| `get_genes_for_phenotype` | `get_genes_for_phenotype(term, response_mode=)` — genes annotated to an HPO term. |
| `get_phenotypes_for_disease` | `get_phenotypes_for_disease(disease_id, response_mode=)` — HPO terms annotated to a disease. |
| `get_diseases_for_phenotype` | `get_diseases_for_phenotype(term, response_mode=)` — diseases annotated to an HPO term. |
| `get_genes_for_disease` | `get_genes_for_disease(disease_id, response_mode=)` — genes associated with a disease. |
| `get_diseases_for_gene` | `get_diseases_for_gene(gene, response_mode=)` — diseases associated with a gene. |

Every response carries `_meta.next_commands` (ready-to-call follow-ups). Ids are
normalised to `HP:NNNNNNN`. `response_mode` ∈ `minimal | compact | standard |
full` (default `compact`).

Tools are **unprefixed** here (`serverInfo.name` = `hpo-link`); the GeneFoundry
router applies the canonical gateway **namespace token** `hpo` at mount time.

## Quickstart

```bash
uv sync --group dev           # install dependencies
uv run hpo-link-data build    # download HPO (OBO + HPOA) and build the local database
uv run hpo-link-data status   # print the loaded HPO release + counts
uv run hpo-link-mcp           # stdio MCP server (for Claude Desktop)
uv run hpo-link               # unified REST + MCP server on http://127.0.0.1:8000
```

Or via `make`:

```bash
make install        # uv sync --group dev
make data           # build the local HPO database
make data-status    # print loaded release + counts
make dev            # unified REST + MCP server
make mcp-serve      # stdio MCP server
```

## MCP client setup

HTTP (unified server exposes `/mcp` alongside `/health`):

```bash
claude mcp add --transport http hpo-link --scope user http://127.0.0.1:8000/mcp
```

stdio (Claude Desktop and similar):

```bash
make mcp-serve      # runs mcp_server.py on stdio (stdout is reserved for the protocol)
```

## HTTP boundary configuration

`HPO_LINK_ALLOWED_HOSTS` is a JSON list of exact Host values and defaults to
`["localhost","127.0.0.1","::1"]`; production Compose also permits
`hpo-link.genefoundry.org`. Write IPv6 entries bare, without brackets. Wildcard
patterns are rejected. `HPO_LINK_ALLOWED_ORIGINS` defaults to `[]` and is the
browser-origin admission gate: include every origin that `HPO_LINK_CORS_ORIGINS`
is intended to serve. Requests without an Origin header remain valid.

## Data provenance

The database is built from:

- **HPO ontology** (`hp.json`) — downloaded from the HPO GitHub releases via
  the OBO PURL (`http://purl.obolibrary.org/obo/hp.json`). Contains ~19,800
  active phenotype terms (HPO v2026-06-06). Fetched via conditional GET
  (ETag / Last-Modified); a `304` reuses the local file.
- **HPOA annotations** (`phenotype.hpoa`) — the HPO phenotype-to-disease
  annotation file linking HPO terms to OMIM/Orphanet/DECIPHER diseases, and
  gene associations derived from those annotations.

The build is atomic (temp file + `os.replace`) under a lock, and records
provenance in a `meta` table (HPO release version, source validators, counts).
`get_diagnostics` and `get_server_capabilities` report the loaded release.

### Prebuilt artifact distribution

To skip the build step, set `HPO_LINK_DATA__PREBUILT_DB_URL` to the URL of a
prebuilt SQLite artifact (e.g., from a GitHub Release). The entrypoint will
download and verify it before serving. If absent, the server builds from
source automatically (`HPO_LINK_DATA__AUTO_BOOTSTRAP=true`).

## Documentation

- [docs/architecture.md](docs/architecture.md) — the two planes, ingest pipeline, SQLite schema, request lifecycle.
- [docs/usage.md](docs/usage.md) — per-tool examples and workflows.
- [docs/deployment.md](docs/deployment.md) — Docker, environment variables, refresh.
- [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) — contributor + agent guide.

## License & citation

**Code:** MIT.

**Data:** HPO is distributed under a custom license for research and educational
use. See [https://hpo.jax.org/app/license](https://hpo.jax.org/app/license)
for details. Attribution required.

**Citation:** Köhler S, Gargano M, Matentzoglu N, et al. *The Human Phenotype
Ontology in 2021.* Nucleic Acids Research 2021;49(D1):D1207–D1217.
doi:10.1093/nar/gkaa1043.

For the most recent release cite: Gargano MA, Matentzoglu N, Coleman B, et al.
*The Human Phenotype Ontology in 2024: phenotypes around the world.*
Nucleic Acids Research 2024;52(D1):D1333–D1346. doi:10.1093/nar/gkad1005.

Research use only; not for diagnosis, treatment, triage, or patient management.
