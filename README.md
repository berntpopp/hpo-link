# hpo-link

MCP/API server that grounds disease work in the [Mondo Disease Ontology](https://mondo.monarchinitiative.org/).

`hpo-link` builds a local SQLite index from the Mondo OBO + SSSOM releases
(Monarch PURLs) and serves a **read-only** MCP + REST surface for disease term
lookup, the `is_a` hierarchy (ancestors/descendants via a transitive closure),
and cross-ontology mapping (OMIM ↔ Orphanet ↔ DOID ↔ NCIT ↔ UMLS ↔ MeSH ↔
MONDO …). There is no live API — the local index is the only source, so lookups
are fast and offline. It mirrors the architecture of the sibling `mgi-link`
server.

Every response is grounded in the local index and cites the **MONDO id + Mondo
release version**. Research use only; **not** clinical decision support.

## Tools

| Tool | Signature |
|------|-----------|
| `get_server_capabilities` | `get_server_capabilities(detail=)` — discovery surface (tools, workflows, error taxonomy, limits). |
| `get_diagnostics` | `get_diagnostics()` — index status, loaded Mondo release, counts. |
| `resolve_disease` | `resolve_disease(query, response_mode=)` — label/synonym/MONDO id/xref → canonical term + `match_type`. |
| `search_diseases` | `search_diseases(query, limit=, include_obsolete=, response_mode=)` — FTS over name/synonyms/definition. |
| `get_disease` | `get_disease(term, response_mode=)` — definition, synonyms, grouped xrefs, parents/children, obsolescence. |
| `get_disease_ancestors` | `get_disease_ancestors(term, limit=, response_mode=)` — transitive `is_a` ancestors. |
| `get_disease_descendants` | `get_disease_descendants(term, limit=, response_mode=)` — transitive `is_a` descendants. |
| `get_disease_parents` | `get_disease_parents(term, response_mode=)` — direct `is_a` parents. |
| `get_disease_children` | `get_disease_children(term, response_mode=)` — direct `is_a` children. |
| `resolve_xref` | `resolve_xref(xref_id, limit=, response_mode=)` — external CURIE → MONDO ids, ranked by predicate. |
| `map_cross_ontology` | `map_cross_ontology(term, prefixes=, response_mode=)` — a MONDO term → mappings grouped by prefix. |

Every response carries `_meta.next_commands` (ready-to-call follow-ups). Ids are
normalised to `MONDO:NNNNNNN`. `response_mode` ∈ `minimal | compact | standard |
full` (default `compact`).

Tools are **unprefixed** here (`serverInfo.name` = `hpo-link`); the GeneFoundry
router applies the canonical gateway **namespace token** `mondo` at mount time, so
`resolve_disease` surfaces as `mondo_resolve_disease` behind the federated endpoint.

## Quickstart

```bash
make install        # uv sync --group dev
make data           # download Mondo (OBO + SSSOM) and build the local index
make data-status    # print the loaded Mondo release + counts
make dev            # unified REST + MCP server on http://127.0.0.1:8000
curl -s http://127.0.0.1:8000/health
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

## Data provenance

The index is built from the Mondo OBO release
(`http://purl.obolibrary.org/obo/mondo.obo`) plus the consolidated SSSOM
cross-ontology mappings (from the Mondo repository), fetched via conditional GET
(ETag / Last-Modified). The OBO already carries dbxrefs, so the SSSOM is a
**supplementary, optional** source — if it is unavailable the index still builds
from the OBO (cross-references present, curated SSSOM predicates omitted). The
build is atomic (temp file + `os.replace`) under a lock, and records provenance
in a `meta` table (Mondo release version, source validators, counts).
`get_diagnostics` and `get_server_capabilities` report the loaded release.

## Documentation

- [docs/architecture.md](docs/architecture.md) — the two planes, ingest pipeline, SQLite schema, request lifecycle.
- [docs/usage.md](docs/usage.md) — per-tool examples and workflows.
- [docs/deployment.md](docs/deployment.md) — Docker, environment variables, refresh.
- [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) — contributor + agent guide.

## License & citation

Code: MIT. Data: the Mondo Disease Ontology is distributed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) by the Monarch
Initiative. Cite: Vasilevsky NA, Matentzoglu NA, Toro S, et al. *Mondo:
Unifying diseases for the world, by the world.* medRxiv 2022.04.13.22273750.

Research use only; not for diagnosis, treatment, triage, or patient management.
