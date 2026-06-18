# hpo-link — Design Specification

**Status:** Approved (design) — pending implementation plan
**Date:** 2026-06-18
**Author:** Senior MCP engineer (Claude) with B. Popp
**Repo:** `berntpopp/hpo-link` (new; member of the GeneFoundry `-link` fleet)

---

## 1. Summary

`hpo-link` is a deterministic, offline-first **MCP server** that serves the **Human Phenotype Ontology (HPO)** and its disease/gene annotation layer (HPOA) from a **locally-built SQLite database that is published to GitHub as a versioned release artifact**. It exposes fast graph and association lookups: resolve terms, walk the ontology hierarchy, map cross-references, and connect **genes ↔ phenotypes ↔ diseases**.

It joins the GeneFoundry fleet behind `genefoundry-router` under the namespace `hpo`, following the exact conventions of its sibling `-link` servers (mondo-link, hgnc-link, gtex-link, clinvar-link, …).

### Scope boundary (vs. phentrieve)
`hpo-link` is **deterministic only**: no embeddings, no vector search, no LLM, no free-text extraction. Those are `phentrieve`'s specialty (BioLORD vectors, Chroma, cross-encoder, multilingual LLM extraction, phenopackets). `hpo-link` is the complementary *deterministic backbone* — fast exact/synonym/ID resolution, O(1) hierarchy queries via precomputed closure, and the gene/disease association graph that phentrieve does **not** expose.

---

## 2. Goals & non-goals

### Goals
1. Reproducible local build of an HPO database from canonical, version-pinned sources.
2. Publish the prebuilt DB to GitHub as a versioned Release asset; server fetches+caches it at runtime, with full offline local-build fallback.
3. Fleet-faithful MCP surface: `response_mode`, `_meta` envelope, 7-code error taxonomy, `recommended_citation`, `get_server_capabilities`, `get_diagnostics`.
4. Ontology graph tools (resolve / search / hierarchy / xref) at mondo-link parity.
5. Annotation tools connecting genes, phenotypes, and diseases, with descendant-aware queries via the closure table.

### Non-goals (v1)
- Embeddings / semantic similarity / vector search (phentrieve's domain).
- Information-content / Resnik / Lin term similarity (candidate for a later milestone; schema leaves room).
- Multilingual labels (English only; `hp-international` not ingested).
- Write access of any kind (read-only research server).

---

## 3. Architecture

Layered, identical to the fleet pattern: **ingest → data (DAO) → services → mcp**.

```
hpo_link/
  __init__.py            # __version__
  config.py              # pydantic-settings, env prefix HPO_LINK_
  constants.py           # SCHEMA_VERSION, citation, license, PURLs, xref prefixes
  identifiers.py         # HP CURIE/IRI normalization, gene/disease id normalization
  exceptions.py          # exception hierarchy
  logging_config.py      # structlog -> stderr
  buildinfo.py           # build/git_sha/built_at
  app.py                 # FastAPI create_app(): /health + /mcp mount
  server_manager.py      # unified/http/stdio transport selection
  ingest/
    cli.py               # hpo-link-data: build | refresh | status
    downloader.py        # conditional GET (ETag/Last-Modified) from PURLs
    parser_obo.py        # hp.json obographs -> terms + edges + closure
    parser_hpoa.py       # phenotype.hpoa + 3 gene/phenotype TSVs -> association rows
    builder.py           # build SQLite under lock, atomic replace
    schema.sql           # DDL
    lock.py              # cross-process build lock
    release.py           # fetch prebuilt DB from GitHub Release; version discovery
  data/
    repository.py        # read-only SQLite DAO (mode=ro)
  services/
    hpo_service.py       # resolve/search/hierarchy/xref orchestration
    annotation_service.py# gene/disease association orchestration
  mcp/
    facade.py            # create_hpo_mcp() -> FastMCP
    tools/
      _common.py         # ResponseMode, QueryStr annotated types
      ontology.py        # resolve_term, search_terms, get_term
      hierarchy.py       # parents/children/ancestors/descendants
      xref.py            # resolve_xref, map_cross_ontology
      annotations.py     # gene<->phenotype<->disease tools
    schemas.py           # permissive JSON output schemas (additionalProperties: true)
    envelope.py          # run_mcp_tool(), McpErrorContext, error classification
    next_commands.py     # cmd(), after_* builders, _meta assembly
    capabilities.py      # build_capabilities(), TOOLS list
    resources.py         # HPO_SERVER_INSTRUCTIONS, capability resources
    annotations.py       # READ_ONLY_OPEN_WORLD ToolAnnotations
    errors.py            # error-code taxonomy helpers
server.py                # unified entry (argparse transport)
mcp_server.py            # stdio entry (Claude Desktop)
.github/workflows/
  ci.yml                 # ruff + mypy + pytest + coverage + lint-loc
  build-data.yml         # build & publish DB release artifact
docker/                  # Dockerfile, compose, entrypoint
tests/                   # unit/ integration/ + conftest fixtures
docs/  CLAUDE.md  AGENTS.md  README.md  Makefile  pyproject.toml  uv.lock
```

**Stack:** Python 3.12, `uv`, hatchling build backend, FastMCP (`mcp[cli]>=1.27`, `fastmcp>=3.2`), FastAPI + uvicorn, pydantic v2 + pydantic-settings, httpx, structlog, orjson, typer. ruff (line-length 100), mypy strict, pytest (asyncio auto). Entry points: `hpo-link` (unified), `hpo-link-mcp` (stdio), `hpo-link-data` (ingest CLI). Max 500 lines/file (`scripts/check_file_size.py`).

---

## 4. Data sources (version-pinned, canonical)

Discovery: `GET https://api.github.com/repos/obophenotype/human-phenotype-ontology/releases/latest` → `tag_name` `vYYYY-MM-DD` → build dated PURLs.

| Dataset | Default source (pinned) | Notes |
|---|---|---|
| Ontology | `http://purl.obolibrary.org/obo/hp/releases/{DATE}/hp.json` | **Default = `hp.json`** (main, logically-classified, English). `hp-base.json` switchable via config. |
| Disease→phenotype | `http://purl.obolibrary.org/obo/hp/releases/{DATE}/phenotype.hpoa` | TSV, 4 `#` metadata lines + header. |
| Gene→phenotype | `…/releases/{DATE}/genes_to_phenotype.txt` | TSV. |
| Phenotype→gene | `…/releases/{DATE}/phenotype_to_genes.txt` | TSV (curated reverse). |
| Gene→disease | `…/releases/{DATE}/genes_to_disease.txt` | TSV. |

Latest verified release at design time: **v2026-06-06** (~19.8k active terms, 574 obsolete). Version is detectable from `hp.json` `graphs[0].meta.version` (version IRI) and `phenotype.hpoa` `#version` / `#hpo-version`.

**Licensing:** custom HPO license (`https://hpo.jax.org/app/license`) — must display release version and cite the consortium; relationships must not be altered. Recommended citation: *Köhler S, et al. The Human Phenotype Ontology in 2024. Nucleic Acids Res. 2024;52(D1):D1333–D1346.* HPOA falls under the same project terms.

### hp.json parsing contract (obographs)
- Node `id` is a full IRI (`…/obo/HP_0000118`) → normalize to CURIE `HP:0000118`.
- `lbl` → name; `meta.definition.val` → definition; `meta.synonyms[]` `{pred, val}` with pred ∈ {hasExactSynonym, hasRelatedSynonym, hasBroadSynonym, hasNarrowSynonym} → scoped synonyms; `meta.xrefs[].val` → xrefs; `meta.basicPropertyValues` → `hasAlternativeId` (alt_ids) and `IAO_0100001`/term-replaced-by (replaced_by); `meta.deprecated == true` → obsolete; `meta.subsets`, `meta.comments`.
- `edges[]` `{sub, pred, obj}`: ingest `pred == "is_a"` for the hierarchy. Other relation preds recorded but not used for closure in v1.
- Reuse phentrieve's defensive helpers (`safe_get_nested`, `safe_get_list`, obsolete detection) for schema resilience.

### HPOA parsing contract
- `phenotype.hpoa` columns: `database_id, disease_name, qualifier(NOT|''), hpo_id, reference, evidence(IEA|PCS|TAS), onset, frequency, sex, modifier, aspect(P|C|I|M), biocuration`.
- `genes_to_phenotype.txt`: `ncbi_gene_id, gene_symbol, hpo_id, hpo_name, frequency, disease_id`.
- `phenotype_to_genes.txt`: `hpo_id, hpo_name, ncbi_gene_id, gene_symbol, disease_id`.
- `genes_to_disease.txt`: `ncbi_gene_id(NCBIGene:…), gene_symbol, association_type, disease_id, source`.
- `frequency` retained raw **and** parsed into `{frequency_hpo, frequency_ratio, frequency_percent}` where derivable (HPO frequency term, `n/m` ratio, or `%`).

---

## 5. Database schema (SQLite + FTS5)

`PRAGMA journal_mode = WAL`. Built atomically (temp file → `os.replace`). Read at runtime with `mode=ro`.

```sql
-- Ontology -----------------------------------------------------------------
CREATE TABLE term (
  hpo_id      TEXT PRIMARY KEY,      -- HP:0000118
  name        TEXT NOT NULL,
  name_upper  TEXT NOT NULL,
  definition  TEXT,
  is_obsolete INTEGER NOT NULL DEFAULT 0,
  replaced_by TEXT,
  consider    TEXT,                  -- JSON list
  alt_ids     TEXT,                  -- JSON list
  synonyms    TEXT,                  -- JSON [{text, scope}]
  subsets     TEXT,                  -- JSON list
  comments    TEXT                   -- JSON list
);
CREATE INDEX idx_term_name_upper ON term(name_upper);

CREATE TABLE term_lookup (           -- resolve(): label/synonym/alt_id -> hpo_id
  lookup_label TEXT NOT NULL,        -- uppercased
  hpo_id       TEXT NOT NULL,
  label_type   TEXT NOT NULL         -- primary|exact_synonym|related_synonym|broad_synonym|narrow_synonym|alt_id
);
CREATE INDEX idx_term_lookup ON term_lookup(lookup_label);

CREATE VIRTUAL TABLE term_fts USING fts5(
  hpo_id UNINDEXED, name, synonyms, definition,
  tokenize = 'porter unicode61'
);

CREATE TABLE hpo_parent (hpo_id TEXT NOT NULL, parent_id TEXT NOT NULL);
CREATE INDEX idx_hpo_parent     ON hpo_parent(hpo_id);
CREATE INDEX idx_hpo_parent_rev ON hpo_parent(parent_id);

CREATE TABLE hpo_closure (hpo_id TEXT NOT NULL, ancestor_id TEXT NOT NULL); -- incl. self
CREATE INDEX idx_hpo_closure     ON hpo_closure(hpo_id);
CREATE INDEX idx_hpo_closure_anc ON hpo_closure(ancestor_id);

CREATE TABLE xref (
  hpo_id          TEXT NOT NULL,
  prefix          TEXT NOT NULL,     -- UMLS, SNOMEDCT_US, NCIT, MEDDRA, ICD-10, MONDO, ...
  object_id       TEXT NOT NULL,
  object_id_upper TEXT NOT NULL,
  origin          TEXT NOT NULL      -- 'obo_xref'
);
CREATE INDEX idx_xref_hpo ON xref(hpo_id);
CREATE INDEX idx_xref_obj ON xref(prefix, object_id_upper);

-- Annotations (HPOA) -------------------------------------------------------
CREATE TABLE disease_phenotype (
  database_id  TEXT NOT NULL,        -- OMIM:619340 / ORPHA:.. / DECIPHER:..
  disease_name TEXT,
  hpo_id       TEXT NOT NULL,
  qualifier    TEXT,                 -- '' or 'NOT'
  reference    TEXT,
  evidence     TEXT,
  onset        TEXT,
  frequency    TEXT,                 -- raw
  frequency_hpo     TEXT,
  frequency_ratio   TEXT,
  frequency_percent REAL,
  sex          TEXT,
  modifier     TEXT,
  aspect       TEXT,                 -- P|C|I|M
  biocuration  TEXT
);
CREATE INDEX idx_dp_hpo     ON disease_phenotype(hpo_id);
CREATE INDEX idx_dp_disease ON disease_phenotype(database_id);

CREATE TABLE gene_phenotype (
  ncbi_gene_id     TEXT NOT NULL,
  gene_symbol      TEXT NOT NULL,
  gene_symbol_upper TEXT NOT NULL,
  hpo_id           TEXT NOT NULL,
  frequency        TEXT,
  disease_id       TEXT
);
CREATE INDEX idx_gp_gene ON gene_phenotype(gene_symbol_upper);
CREATE INDEX idx_gp_ncbi ON gene_phenotype(ncbi_gene_id);
CREATE INDEX idx_gp_hpo  ON gene_phenotype(hpo_id);

CREATE TABLE gene_disease (
  ncbi_gene_id      TEXT NOT NULL,
  gene_symbol       TEXT NOT NULL,
  gene_symbol_upper TEXT NOT NULL,
  association_type  TEXT,            -- MENDELIAN|...
  disease_id        TEXT NOT NULL,
  source            TEXT
);
CREATE INDEX idx_gd_gene    ON gene_disease(gene_symbol_upper);
CREATE INDEX idx_gd_ncbi    ON gene_disease(ncbi_gene_id);
CREATE INDEX idx_gd_disease ON gene_disease(disease_id);

-- Provenance ---------------------------------------------------------------
CREATE TABLE meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  schema_version INTEGER,
  hpo_version    TEXT,               -- e.g. 2026-06-06
  hpoa_version   TEXT,
  source_purls       TEXT,           -- JSON
  source_validators  TEXT,           -- JSON {etag,last_modified} per file
  term_count INTEGER, obsolete_count INTEGER, closure_count INTEGER, xref_count INTEGER,
  disease_phenotype_count INTEGER, gene_phenotype_count INTEGER, gene_disease_count INTEGER,
  build_utc TEXT, build_duration_s REAL
);
```

Closure precomputation: iterative BFS over `child→parents` for every term (self-pairs included), mirroring mondo-link's `_load_graph`. Estimated built DB size with annotations: ~150–250 MB (compressed asset materially smaller).

---

## 6. MCP tool surface

All tools: `hpo_`-prefixed, `READ_ONLY_OPEN_WORLD` annotations, `response_mode` (default `compact`), return `_meta.next_commands`, `recommended_citation`, and `hpo_version`. Errors returned as typed dicts (never raised across the MCP boundary).

### Ontology / graph
| Tool | Signature | Returns (compact) |
|---|---|---|
| `hpo_resolve_term` | `(query, response_mode=)` | `{query, hpo_id, name, match_type, obsolete, replaced_by?, hpo_version}` |
| `hpo_search_terms` | `(query, limit=25, offset=0, include_obsolete=false, response_mode=)` | FTS results `[{hpo_id, name, score}]` + pagination |
| `hpo_get_term` | `(term, response_mode=, fields=)` | full record (definition, synonyms, xrefs, alt_ids, parents, children) |
| `hpo_get_term_parents` | `(term, response_mode=)` | immediate `is_a` parents |
| `hpo_get_term_children` | `(term, response_mode=)` | immediate `is_a` children |
| `hpo_get_term_ancestors` | `(term, limit=, offset=, response_mode=)` | transitive ancestors (closure) + pagination |
| `hpo_get_term_descendants` | `(term, limit=, offset=, response_mode=)` | transitive descendants (closure) + pagination |
| `hpo_resolve_xref` | `(xref_id, limit=, offset=, response_mode=)` | external CURIE (UMLS/SNOMED/…) → HPO terms |
| `hpo_map_cross_ontology` | `(term, prefixes=, response_mode=)` | HPO → grouped xrefs by prefix |

### Associations (gene ↔ phenotype ↔ disease)
| Tool | Signature | Returns |
|---|---|---|
| `hpo_get_phenotypes_for_gene` | `(gene, limit=, offset=, response_mode=)` | gene (symbol or `NCBIGene:`) → `[{hpo_id, name, frequency, disease_id}]` |
| `hpo_get_genes_for_phenotype` | `(term, include_descendants=false, limit=, offset=, response_mode=)` | HPO → `[{ncbi_gene_id, gene_symbol, disease_id}]` |
| `hpo_get_phenotypes_for_disease` | `(disease_id, limit=, offset=, response_mode=)` | OMIM/ORPHA/DECIPHER → annotations `[{hpo_id, name, frequency*, onset, evidence, aspect, qualifier}]` |
| `hpo_get_diseases_for_phenotype` | `(term, include_descendants=false, limit=, offset=, response_mode=)` | HPO → `[{database_id, disease_name}]` |
| `hpo_get_genes_for_disease` | `(disease_id, limit=, offset=, response_mode=)` | disease → `[{ncbi_gene_id, gene_symbol, association_type, source}]` |
| `hpo_get_diseases_for_gene` | `(gene, limit=, offset=, response_mode=)` | gene → `[{database_id, association_type, source}]` |

`include_descendants` expands the query HPO term to its closure subtree (e.g. all genes annotated under `HP:0000118 Phenotypic abnormality`).

### Infra
- `get_server_capabilities(detail=summary|full)` — tools, response modes, error codes, workflows, citation.
- `get_diagnostics()` — index status, HPO/HPOA versions, counts, build timestamp, runtime metrics.

**Router entrypoints (pinned):** `hpo_resolve_term`, `hpo_get_phenotypes_for_gene`, `hpo_get_genes_for_phenotype`.

### Error taxonomy
`not_found`, `ambiguous_query` (+candidates), `invalid_input` (+field/allowed_values/hint), `data_unavailable` (index not built/upstream down; retryable), `rate_limited`, `upstream_unavailable`, `internal_error`.

---

## 7. Artifact pipeline (build, publish, consume)

### Build & publish — `.github/workflows/build-data.yml`
- **Triggers:** weekly `schedule` cron + `workflow_dispatch`.
- **Steps:** resolve latest HPO release tag → if no `db-vYYYY-MM-DD` Release exists for it → `uv run hpo-link-data build` → compress to `hpo.sqlite.zst` → compute `sha256` → write `manifest.json` (hpo_version, hpoa_version, counts, checksum, source PURLs) → create GitHub Release `db-vYYYY-MM-DD` with assets `{hpo.sqlite.zst, hpo.sqlite.zst.sha256, manifest.json}`.
- **Idempotent:** skip when a release for the version already exists.

### Consume — `ingest/release.py` + startup `ensure_database()`
1. Local DB present and `meta.hpo_version` matches desired → use it.
2. Else download prebuilt asset from latest `db-*` Release → verify sha256 → decompress → atomic place (fast path; no ontology parsing).
3. Else (offline / asset missing) → local `build` from PURLs.
Config: `prefer_prebuilt` (default true), `auto_bootstrap` (default true), `prebuilt_db_url` override, `data_dir`, `db_filename`.

### CI — `.github/workflows/ci.yml`
`ruff format --check`, `ruff check`, `mypy`, `pytest` (unit, `-m "not integration"`), coverage gate ≥70%, `scripts/check_file_size.py`.

---

## 8. Configuration (`HPO_LINK_*`)

```
HPO_LINK_HOST / PORT / TRANSPORT (unified|http|stdio) / LOG_LEVEL
HPO_LINK_DATA__DATA_DIR / DB_FILENAME / DOWNLOAD_TIMEOUT
HPO_LINK_DATA__ONTOLOGY_EDITION (hp.json|hp-base.json)
HPO_LINK_DATA__PREFER_PREBUILT / AUTO_BOOTSTRAP / PREBUILT_DB_URL / REFRESH_ENABLED
HPO_LINK_CACHE__SIZE / TTL
```

---

## 9. Testing strategy

- **Fixtures:** a synthetic mini-`hp.json` (~10 terms, a small DAG, one obsolete) + mini HPOA TSVs → `conftest` builds a tiny SQLite DB once per session.
- **Unit:** identifiers, parsers (obo + hpoa, incl. frequency parsing + obsolete handling), repository queries (resolve/search/closure/xref/associations), services (match-type classification, descendant expansion), config.
- **MCP functional:** each tool returns correct envelope, `_meta`, error codes for bad input, `response_mode` projection.
- **Integration (marked `integration`, off by default):** hit live PURLs to validate parser against the current real release; validate `release.py` asset discovery.
- Coverage gate ≥70%; markers `unit|integration|mcp|slow`.

---

## 10. Reuse map

| Source | Reused for |
|---|---|
| `mondo-link/ingest/downloader.py`, `lock.py` | conditional download + build lock (URLs swapped) |
| `mondo-link/ingest/builder.py`, `schema.sql` | build orchestration + closure + atomic replace pattern |
| `mondo-link/data/repository.py`, `services/*`, `mcp/*` | DAO + service singleton + MCP scaffolding (envelope, next_commands, capabilities, facade) |
| `mondo-link/config.py`, `server.py`, `mcp_server.py` | settings + entry points |
| `phentrieve/.../hpo_parser.py` | hp.json obographs parsing, safe-get helpers, obsolete detection, closure BFS |
| net-new | `parser_hpoa.py`, `annotation_service.py`, annotation tools, `release.py`, `build-data.yml` |

---

## 11. Implementation approach

Post-plan, build via `subagent-driven-development` with parallel agents on isolated layers whose interfaces the plan fixes:
1. Skeleton + config + constants + identifiers + entry points.
2. Ingest pipeline (downloader, parsers, builder, schema, lock, CLI).
3. Data repository + services.
4. MCP layer + tools + capabilities + resources.
5. CI + artifact workflow + Docker + docs + router registration (`genefoundry-router/servers.yaml`).

Definition of done: `make ci-local` green, coverage ≥70%, ≤500 lines/file, a real local build succeeds against the current HPO release, prebuilt-asset round-trip verified, and the server answers each tool against the built DB.
