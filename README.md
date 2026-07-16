# hpo-link

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/hpo-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/hpo-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/hpo-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/hpo-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An **MCP server** (Streamable HTTP or stdio) that grounds phenotype work in the
[Human Phenotype Ontology (HPO)](https://hpo.jax.org/): term lookup, the `is_a`
hierarchy, cross-ontology mapping, and gene↔phenotype↔disease associations, served
read-only from a local index of the HPO release and its HPOA annotations.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

## Why

HPO ships as bulk artifacts — an OBO/JSON ontology graph (`hp.json`) and a flat
annotation table (`phenotype.hpoa`). Neither answers a question. *"Which genes are
annotated to seizure, including its subtypes?"* needs the transitive `is_a` closure over
a multi-parent DAG, a synonym/xref index to get from free text to `HP:0001250`, and a
join against HPOA — plumbing every consumer otherwise rebuilds, badly.

`hpo-link` builds that once into a read-only SQLite index (closure table, FTS over
names/synonyms/definitions, xrefs ranked by mapping predicate) and serves it as MCP
tools. No upstream call sits in the request path, so lookups are offline and
deterministic, and every response cites the HPO id **and** the HPO release it came from.

## Quick start

Hosted — no install:

```bash
claude mcp add --transport http hpo-link https://hpo-link.genefoundry.org/mcp
```

Local (Python 3.12+, [uv](https://github.com/astral-sh/uv)):

```bash
uv sync --group dev   # install
make data             # REQUIRED: download HPO + HPOA and build the local database
make data-status      # loaded HPO release + counts
make dev              # unified REST + MCP on http://127.0.0.1:8000 (/mcp, /health)
```

There is no data until `make data` (`uv run hpo-link-data build`) has run once.

```bash
claude mcp add --transport http hpo-link --scope user http://127.0.0.1:8000/mcp
make mcp-serve        # stdio instead, for Claude Desktop (stdout is the protocol)
```

Three console scripts: `hpo-link` (unified server), `hpo-link-mcp` (stdio),
`hpo-link-data` (`build` / `refresh` / `status` for data authoring, and
`materialize-data` for the hardened deployment init sidecar).

## Tools

| Tool | Purpose |
|------|---------|
| `get_server_capabilities` | Discovery surface — tools, workflows, error taxonomy, limits |
| `get_diagnostics` | Database status, loaded HPO release, counts |
| `resolve_term` | Label, synonym, HP id or xref → one canonical term + `match_type` |
| `search_terms` | Full-text search over names, synonyms and definitions |
| `get_term` | The record — definition, synonyms, grouped xrefs, parents/children, obsolescence |
| `get_term_ancestors` | Transitive `is_a` ancestors |
| `get_term_descendants` | Transitive `is_a` descendants — a phenotype and all its subtypes |
| `get_term_parents` | Direct `is_a` parents |
| `get_term_children` | Direct `is_a` children |
| `resolve_xref` | External CURIE (`UMLS:`, `SNOMEDCT_US:`, `ORPHA:`, …) → HP ids, ranked by predicate |
| `map_cross_ontology` | An HP term → its mappings, grouped by target prefix |
| `get_phenotypes_for_gene` | HPO terms annotated to a gene |
| `get_genes_for_phenotype` | Genes annotated to an HPO term |
| `get_phenotypes_for_disease` | HPO terms annotated to a disease |
| `get_diseases_for_phenotype` | Diseases annotated to an HPO term |
| `get_genes_for_disease` | Genes associated with a disease |
| `get_diseases_for_gene` | Diseases associated with a gene |

Every response carries `_meta.next_commands` (ready-to-call follow-ups). Ids are
normalised to `HP:NNNNNNN`. `response_mode` ∈ `minimal | compact | standard | full`
(default `compact`) trades detail for tokens. Worked examples: [docs/usage.md](docs/usage.md).

Leaf names are **unprefixed** per
[Tool-Naming Standard v1](https://github.com/berntpopp/genefoundry-router/blob/main/docs/TOOL-NAMING-STANDARD-v1.md)
(`serverInfo.name` = `hpo-link`); behind
[genefoundry-router](https://github.com/berntpopp/genefoundry-router) the gateway applies
the canonical namespace token `hpo`, so they surface as `hpo_<tool>` — e.g.
`hpo_resolve_term`.

## Data & provenance

Built from two upstream artifacts: the **HPO ontology** (`hp.json`, via the OBO PURL
`http://purl.obolibrary.org/obo/hp.json`) and the **HPOA annotations**
(`phenotype.hpoa`), which link HPO terms to OMIM / Orphanet / DECIPHER diseases and,
derived from those, to genes.

Local data authoring can refresh from upstream with conditional GET (ETag /
`Last-Modified`), but deployed servers do not. Production uses the immutable,
digest-pinned release declared in `container-release.json`: `hpo-data-init`
materializes it before the application starts, then the application reads the
selected snapshot only. Details: [docs/data.md](docs/data.md).

**Data licence:** HPO is distributed under a custom licence for research and educational
use (<https://hpo.jax.org/app/license>) — **attribution required**.

**Cite:** Köhler S, Gargano M, Matentzoglu N, et al. *The Human Phenotype Ontology in
2021.* Nucleic Acids Research 2021;49(D1):D1207–D1217. doi:10.1093/nar/gkaa1043. For the
most recent release cite instead: Gargano MA, Matentzoglu N, Coleman B, et al. *The Human
Phenotype Ontology in 2024: phenotypes around the world.* Nucleic Acids Research
2024;52(D1):D1333–D1346. doi:10.1093/nar/gkad1005.

## Documentation

- [Usage](docs/usage.md) — per-tool examples, the citation contract, typical workflows.
- [Architecture](docs/architecture.md) — the two planes, ingest pipeline, SQLite schema, request lifecycle.
- [Data & provenance](docs/data.md) — sources, freshness, build integrity, prebuilt artifacts, licence.
- [Configuration](docs/configuration.md) — every `HPO_LINK_*` variable and the Host/Origin/CORS allowlists.
- [Deployment](docs/deployment.md) — Docker init sidecar, health and deploy verification.
- [AGENTS.md](AGENTS.md) — engineering conventions, invariants, definition of done.

## Contributing

See [AGENTS.md](AGENTS.md) for the invariants and conventions. `make ci-local` is the
definition-of-done gate: format, lint, line budget, README standard, mypy, and tests.
Write the failing test first.

## License

[MIT](LICENSE) © Bernt Popp — code only. The HPO **data** is licensed separately for
research and educational use with required attribution
(<https://hpo.jax.org/app/license>); see [Data & provenance](#data--provenance).
