# Usage

All tools are read-only and return a JSON envelope: `{success, ...payload,
_meta}` on success, or `{success: false, error_code, message, retryable,
recovery_action, _meta}` on error. `_meta.next_commands` lists ready-to-call
follow-ups — follow them rather than guessing. `response_mode` ∈ `minimal |
compact | standard | full` (default `compact`). Every record payload echoes
`mondo_version` for grounding.

`_meta` verbosity is tiered by `response_mode` to control the per-call token
cost: `minimal` returns only `{tool, request_id}`; `compact` (default) adds
`next_commands` and `capabilities_version` (diff it to skip re-fetching
capabilities while unchanged) but omits `elapsed_ms`; `standard`/`full` add
`elapsed_ms`. Pass `response_mode="minimal"` for the leanest payload once you
know the workflow; widen when you need the guidance or timings.

## Discovery

```
get_server_capabilities(detail="summary")   # tools, signatures, workflows, errors, limits, capabilities_version
get_diagnostics()                            # index_built, mondo_version, counts, build, runtime (p50/p95/p99)
```

Call `get_server_capabilities` first in a cold session, or read the
`mondo://capabilities` / `mondo://tools` resources.

## Resolve a disease

`resolve_disease(query)` normalises a label, synonym, MONDO id, or external
CURIE to one canonical term.

```
resolve_disease(query="Shprintzen-Goldberg syndrome")
→ {mondo_id: "MONDO:0008426", name: "...", match_type: "primary", obsolete: false, mondo_version: "..."}
```

`match_type` ∈ `mondo_id | primary | exact_synonym | related_synonym | xref`
(strongest first). An ambiguous label returns `error_code: "ambiguous_query"`
with `candidates`. An obsolete id returns `not_found` with `replaced_by`.

## Search

`search_diseases(query, limit=25, offset=0, include_obsolete=false)` is FTS over
name, synonyms, and definition. In `compact` (default) each hit is
`{mondo_id, name, score, definition_snippet}` (snippet ≤140 chars); `standard`/
`full` return the complete `definition`.

```
search_diseases(query="marfanoid craniosynostosis")
→ {results: [{mondo_id, name, score, definition_snippet}],
   total, returned, limit, offset, truncated, next_offset?, ...}
```

When `truncated` is true, `_meta.next_commands` includes a forward-page step
(advance `offset`, no rows re-sent) and a widen step.

## The record

`get_disease(term, response_mode=, fields=)` accepts a MONDO id, a label/synonym,
or an external xref (resolved first). Pass `fields=["xrefs.OMIM", ...]` for a
sparse projection (identity anchors are always returned).

```
get_disease(term="MONDO:0008426")
→ {mondo_id, name, definition, synonyms[], xrefs: {OMIM:[...], ORPHA:[...], DOID:[...]},
   parents[], children[], top_groupings[], subsets[], obsolete, replaced_by, mondo_version}
```

A free-text label miss returns `not_found` with the closest hits in `candidates`
and `_meta.next_commands` chaining to `get_disease` on the top hit.

## Hierarchy

```
get_disease_parents(term)        # direct is_a parents
get_disease_children(term)       # direct is_a children
get_disease_ancestors(term, limit=200, offset=0)    # transitive (closure)
get_disease_descendants(term, limit=200, offset=0)  # transitive (closure)
```

Ancestors/descendants carry a pagination block `{total, returned, limit, offset,
truncated, next_offset?}`; page a large closure forward with `offset`.

## Cross-ontology

`resolve_xref(xref_id)` maps an external CURIE back to Mondo, ranked by mapping
predicate. Each matching Mondo term appears **once** (its strongest predicate); a
term reachable via several mapping rows for the same id is not double-counted, so
`returned` never exceeds the distinct-term `total`.

```
resolve_xref(xref_id="OMIM:182212", limit=50, offset=0)
→ {xref_id, normalized: "OMIM:182212", matches: [{mondo_id, name, predicate, origin}],
   total, returned, limit, offset, truncated, next_offset?, ...}
```

`map_cross_ontology(term, prefixes=None, fields=)` lists a term's mappings grouped
by prefix (`fields=["mappings.OMIM"]` for a sparse projection).

```
map_cross_ontology(term="MONDO:0008426", prefixes=["OMIM", "ORPHA"])
→ {mondo_id, name, count, mappings: {OMIM: [{object_id, predicate, origin, source}], ORPHA: [...]}, ...}
```

Predicate ranking: `exactMatch > equivalentTo > closeMatch > narrowMatch >
broadMatch > xref`. `origin` is `obo_xref` or `sssom`.

## Typical workflow

```
resolve_disease("...") → get_disease(mondo_id)
  → get_disease_ancestors / get_disease_descendants   (navigate the DAG)
  → map_cross_ontology(mondo_id)                       (jump to OMIM/Orphanet/DOID/...)
```

## Citation contract

Cite the **MONDO id** and the **Mondo release version** (from `mondo_version` /
`get_diagnostics`) for every claim. Research use only; not for clinical decision
support.
