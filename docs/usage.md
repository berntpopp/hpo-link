# Usage

All tools are read-only and return a JSON envelope: `{success, ...payload,
_meta}` on success, or `{success: false, error_code, message, retryable,
recovery_action, _meta}` on error. `_meta.next_commands` lists ready-to-call
follow-ups — follow them rather than guessing. `response_mode` ∈ `minimal |
compact | standard | full` (default `compact`). Every record payload echoes
`hpo_version` for grounding.

`_meta` verbosity is tiered by `response_mode` to control the per-call token
cost: `minimal` returns only `{tool, request_id}`; `compact` (default) adds
`next_commands` and `capabilities_version` (diff it to skip re-fetching
capabilities while unchanged) but omits `elapsed_ms`; `standard`/`full` add
`elapsed_ms`. Pass `response_mode="minimal"` for the leanest payload once you
know the workflow; widen when you need the guidance or timings.

## Discovery

```
get_server_capabilities(detail="summary")   # tools, signatures, workflows, errors, limits, capabilities_version
get_diagnostics()                            # index_status, hpo_version, hpoa_version, counts, build, runtime (p50/p95/p99)
```

Call `get_server_capabilities` first in a cold session, or read the
`hpo://capabilities` / `hpo://tools` resources. `get_diagnostics` reports the
loaded `hpo_version` / `hpoa_version` and real row counts
(`terms`, `obsolete`, `closure`, `xref`, `disease_phenotype`, `gene_phenotype`,
`gene_disease`) so you can confirm freshness or diagnose a `data_unavailable`.

## Resolve a term

`resolve_term(query)` normalises a phenotype label, synonym, HP id, or external
xref CURIE to one canonical term.

```
resolve_term(query="Renal cyst")
→ {query, hpo_id: "HP:0000107", name: "Renal cyst", match_type: "primary", obsolete: false, hpo_version: "..."}
```

`match_type` ∈ `hpo_id | primary | exact_synonym | related_synonym | alt_id |
xref | fuzzy` (strongest first). An ambiguous label returns `error_code:
"ambiguous_query"` with `candidates`. An obsolete HP id returns `not_found` with
`replaced_by`.

## Search

`search_terms(query, limit=25, offset=0, include_obsolete=false)` is FTS over
name, synonyms, and definition. In `compact` (default) each hit is
`{hpo_id, name, score, definition_snippet}` (snippet ≤140 chars); `standard`/
`full` return the complete `definition`. Obsolete terms are excluded unless
`include_obsolete=true`.

```
search_terms(query="polycystic kidney")
→ {results: [{hpo_id, name, score, definition_snippet}],
   total, returned, limit, offset, truncated, next_offset?, ...}
```

When `truncated` is true, `_meta.next_commands` includes a forward-page step
(advance `offset`, no rows re-sent) and a widen step.

## The record

`get_term(term, response_mode=, fields=)` accepts an HP id, a label/synonym, or
an external xref CURIE (resolved first). Pass `fields=["synonyms", "xrefs.UMLS"]`
for a sparse projection (identity anchors `hpo_id` / `name` / `hpo_version` are
always returned).

```
get_term(term="HP:0000107")
→ {hpo_id, name, definition, synonyms[], alt_ids[], subsets[], xrefs: {UMLS:[...], SNOMEDCT_US:[...], ...},
   parents[], children[], obsolete, replaced_by, hpo_version, recommended_citation}
```

`synonyms` is polymorphic by `response_mode`: `standard`/`full` return
`[{text, scope}]` objects; `compact` (default) and sparse `fields` collapse them
to plain `["string", ...]`. A free-text label miss returns `not_found` with the
closest hits in `candidates` and `_meta.next_commands` chaining to `get_term` on
the top hit.

## Hierarchy

```
get_term_parents(term)        # direct is_a parents
get_term_children(term)       # direct is_a children
get_term_ancestors(term, limit=50, offset=0)    # transitive (closure)
get_term_descendants(term, limit=50, offset=0)  # transitive (closure)
```

Parents/children carry a `count`; ancestors/descendants carry a pagination block
`{total, returned, limit, offset, truncated, next_offset?}` — page a large
closure forward with `offset`. `children ⊆ descendants` and
`parents ⊆ ancestors` always hold.

## Cross-ontology

`resolve_xref(xref_id)` maps an external CURIE back to HPO. Each matching HPO
term appears once, so `returned` never exceeds the distinct-term `total`.

```
resolve_xref(xref_id="UMLS:C0000737", limit=25, offset=0)
→ {xref_id, matches: [{hpo_id, name}],
   total, returned, limit, offset, truncated, next_offset?, hpo_version}
```

`map_cross_ontology(term, prefixes=None, fields=)` lists a term's mappings grouped
by prefix (`fields=["mappings.UMLS"]` for a sparse projection).

```
map_cross_ontology(term="HP:0000107", prefixes=["UMLS", "SNOMEDCT_US"])
→ {hpo_id, name, mappings: {UMLS: [{object_id, predicate, origin, source}], SNOMEDCT_US: [...]}, hpo_version}
```

First-class xref prefixes: `UMLS`, `SNOMEDCT_US`, `NCIT`, `MEDDRA`, `ICD-10`,
`ICD-9`, `ORPHA`, `MONDO`, `DOID`, `EFO`, `MSH`, `MESH`. `origin` is `obo_xref`.

## Gene ↔ phenotype ↔ disease annotations (HPOA)

Six tools join HPO terms to genes and diseases via the HPOA annotation tables.
Genes accept a symbol (`PAX6`), a bare NCBI id (`5080`), or an `NCBIGene:5080`
CURIE; diseases accept a CURIE (`OMIM:154700`, `ORPHA:550`). All take
`limit` / `offset` / `response_mode` and carry the standard pagination block.

```
get_phenotypes_for_gene(gene="PAX6")
→ {gene, gene_kind, gene_value, phenotypes: [{hpo_id, name, frequency,
   frequency_hpo, frequency_ratio, frequency_percent, disease_id}], total, ..., hpo_version}

get_genes_for_phenotype(term="HP:0000107", include_descendants=false)
→ {term, hpo_id, genes: [{ncbi_gene_id, gene_symbol}], include_descendants, total, ...}

get_phenotypes_for_disease(disease_id="OMIM:154700")
→ {disease_id, phenotypes: [{hpo_id, name, aspect, evidence, reference, biocuration,
   frequency_hpo, frequency_ratio, frequency_percent, onset, sex, qualifier, modifier}], total, ...}

get_diseases_for_phenotype(term="HP:0000107", include_descendants=true)
→ {term, hpo_id, diseases: [{database_id, disease_name}], include_descendants, total, ...}

get_genes_for_disease(disease_id="OMIM:154700")
→ {disease_id, genes: [{ncbi_gene_id, gene_symbol, association_type, source}], total, ...}

get_diseases_for_gene(gene="PAX6")
→ {gene, gene_kind, gene_value, diseases: [{ncbi_gene_id, gene_symbol, association_type, source}], total, ...}
```

The `frequency` triplet is decoded uniformly on both phenotype paths:
`frequency_hpo` (an HP frequency code, e.g. `HP:0040283`), `frequency_ratio`
(`42/163`), and `frequency_percent` (computed). `include_descendants=true` on the
phenotype→gene/disease tools unions the term's transitive descendants first, so
annotations on any child term are included (e.g. `HP:0000107` diseases expand
materially once descendants are folded in).

### Absent vs malformed vs unresolved (one contract)

- **Malformed identifier** → `invalid_input` (with `field`): a `disease_id` that
  is not a CURIE (`notacurie`, `:123`, `OMIM:`), or a gene CURIE with a
  non-`NCBIGene` prefix / non-numeric body (`NCBIGene:abc`).
- **Well-formed but unknown id** (valid shape, no annotations) → an empty 200
  page with `total: 0` — **not** `not_found`.
- **`not_found`** is reserved for genuine identity-resolution failure: the
  `resolve_*` tools, and the phenotype→X tools when a free-text term cannot be
  resolved to any HP id.

This rule is uniform across all six association tools, so a consuming agent can
branch identically on "absent" everywhere.

## Typical workflow

```
resolve_term("...") → get_term(hpo_id)
  → get_term_ancestors / get_term_descendants        (navigate the DAG)
  → get_genes_for_phenotype / get_diseases_for_phenotype   (annotations)
  → map_cross_ontology(hpo_id)                        (jump to UMLS/SNOMED/...)
```

## Citation contract

Cite the **HP id** and the **HPO release version** (`hpo_version` /
`get_diagnostics`) for every claim. The long-form `recommended_citation` is
returned on term records and on `standard`/`full` association payloads; the
canonical static provenance lives in `get_server_capabilities`. HPO has a custom
license (https://hpo.jax.org/app/license). Research use only; not for clinical
decision support, diagnosis, treatment, or patient management.
