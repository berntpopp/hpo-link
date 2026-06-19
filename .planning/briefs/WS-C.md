# WS-C — Discovery contract & schema/ontology polish (P1.1, P3.1, P3.3, P3.4)

**Goal:** document the absent-entity contract; advertise the `synonyms` schema
polymorphism; fix the broken `resolve_term` example; and (stretch) give
`search_terms` a "did you mean" fallback. Lifts API consistency to 9, `get_term`
8 → 9.5.

## Files you OWN (touch only these + their tests)

- `hpo_link/mcp/capabilities.py`
- `hpo_link/mcp/schemas.py`
- `hpo_link/mcp/tools/ontology.py`
- `hpo_link/services/hpo_service.py` (for T3.4 `search_terms` fallback)
- `hpo_link/services/resolution.py` (you may reuse/extend its helpers for T3.4)
- Tests: `tests/unit/test_tools_ontology.py` (extend),
  `tests/unit/test_hpo_service.py` (extend), and a NEW
  `tests/unit/test_schemas.py` if you add one.

Do NOT touch `annotation_service.py`, `shaping.py`, `discovery.py`, `builder.py`,
`metrics.py`, `identifiers.py`.

## Tasks

### T1.1 — Document the absent-entity contract in capabilities

In `capabilities.build_capabilities()`, add a new key (e.g.
`absent_entity_contract`) — and add its key name to `_SUMMARY_KEYS` so it shows in
the default summary — stating the LOCKED rule verbatim (see SHARED-CONTEXT.md
"The absent-entity contract"):

> Malformed identifier → `invalid_input` (with `field`). A well-formed but unknown
> id (valid shape, no annotations) → an empty 200 page with `total:0` — NOT
> `not_found`. `not_found` is reserved for genuine identity-resolution failure:
> the `resolve_*` tools and phenotype→term lookups where a free-text term cannot
> be resolved to any HPO id. This rule is uniform across the six association tools
> (`get_phenotypes_for_gene/disease`, `get_genes_for_phenotype/disease`,
> `get_diseases_for_phenotype/gene`) and `resolve_xref`.

Keep wording tight. Changing this payload changes `capabilities_version` (a
content hash) — that is expected and fine. If `test_facade.py` or another test
asserts a FROZEN hash value, update it; if it only checks structure, no change
needed.

### T3.1 — Advertise the `synonyms` schema polymorphism

`get_term.synonyms` changes shape by `response_mode`: `standard`/`full` →
`[{text, scope, ...}]`; `compact` (default) & sparse `fields` → `["plain", ...]`
(see `services/shaping._plain_synonyms`). Make this explicit:

1. In `schemas.py`, change `TERM_SCHEMA`'s `synonyms` from bare `_ARR` to an array
   whose items are `oneOf`: a `string`, OR an object
   `{text: string, scope: string, ...}` (keep `additionalProperties: true`). Keep
   the schema permissive overall (the envelope returns errors through the same
   schema). Define a small local constant for the synonyms schema for clarity.
2. In `ontology.py`, extend the `get_term` description to note: "`compact`
   (default) returns synonyms as plain strings; `standard`/`full` return
   `{text, scope}` objects." Keep the `Signature:` sentence intact.

### T3.3 — Fix the broken `resolve_term` example (I-7)

The `resolve_term` description in `ontology.py` uses the example xref
`SNOMEDCT_US:193046000`, which returns `not_found` against the current release.
Replace it with an xref CURIE that ACTUALLY resolves. Verify against the built DB
before choosing — e.g.:

```
uv run python -c "import sqlite3,os; c=sqlite3.connect('data/hpo.sqlite'); \
import sys; \
print(c.execute(\"SELECT x.curie_or_prefix, x.object_id, x.hpo_id FROM xref x \
LIMIT 5\").fetchall())"
```

(Confirm the real `xref` column names from `schema.sql` first.) Pick a real
`UMLS:` or `SNOMEDCT_US:` (or other supported-prefix) CURIE that maps to an HPO
term, and use it in the description. Also fix the same stale example in
`capabilities.py` `id_normalization` if you choose, but at minimum fix the
`resolve_term` tool description. Confirm your chosen example resolves by calling
the resolver or a direct xref query in a test or one-off check.

### T3.4 — (Stretch) `search_terms` "did you mean"

When `search_terms` returns **zero** FTS hits, fall back to the conservative
fuzzy-suggestion logic already in `services/resolution.py`
(`Resolver._search_suggestions` / `_hits_to_suggestions` / token relaxation) to
attach up to ~3 ranked candidate suggestions, so a typo like `"polycstic kidny"`
returns suggestions instead of a bare empty list.

- Implement in `hpo_service.search_terms` (data plane): on 0 results, populate a
  `suggestions: [{hpo_id, name, score}]` field (and leave `results` empty,
  `total:0`). Reuse existing resolution helpers rather than duplicating logic.
- The `search_terms` tool body (`ontology.py`) should, when `suggestions` are
  present and `results` empty, add `next_commands` chaining to `get_term` on the
  top suggestion (in addition to any existing widen step). Keep the existing
  `after_search` behavior for the non-empty case.
- If clean integration proves larger than expected, deliver T1.1/T3.1/T3.3 fully
  and mark T3.4 deferred in your report (it is explicitly a stretch goal).

## Acceptance

- Capabilities summary includes the absent-entity contract text.
- `TERM_SCHEMA.synonyms` expresses both the string and object item shapes; the
  `get_term` description documents the polymorphism.
- The `resolve_term` example CURIE resolves (proven by a test or check), not 404.
- (Stretch) a 0-hit query yields ranked `suggestions` + a chaining `next_command`.

## Tests (TDD — write first)

- A test asserting `build_capabilities()` (and the summary projection) contains
  the absent-entity contract key/text.
- A schema test: `TERM_SCHEMA["properties"]["synonyms"]["items"]` admits both a
  string and an object (assert the `oneOf` structure).
- A resolver test: the new example CURIE resolves to a non-null `hpo_id`.
- (Stretch) `hpo_service.search_terms("<deliberate typo>")` returns
  `results == []` but non-empty `suggestions`.
