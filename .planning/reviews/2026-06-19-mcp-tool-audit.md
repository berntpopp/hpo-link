# hpo-link MCP — Tool & Aspect Audit + Improvement Plan

- **Date:** 2026-06-19
- **HPO release under test:** 2026-06-06 (`capabilities_version: ce93d6ee51337b99`)
- **Scope:** all 17 MCP tools, exercised across 31 live calls (happy-path, error taxonomy, feature flags, edge cases), with root causes traced to source.
- **Verdict:** **8.7 / 10** — strong, ship-quality. One real bug, one real consistency gap, the rest efficiency/polish.
- **Goal of this plan:** lift **every tool ≥ 9** and **every aspect ≥ 9**, in priority order.

> Two earlier "findings" were retracted after reading the source — they are correct-by-design:
> - `runtime_metrics.error_rate: null` is **intentional** — `_ERROR_RATE_MIN_SAMPLE = 20` (`hpo_link/mcp/metrics.py:23`) withholds the ratio below 20 calls as noise. The test made only 3 calls.
> - `synonyms` collapsing to plain strings in `compact` is **documented** in `hpo_link/services/shaping.py:54-56`. The gap is that consumers can't see this from the tool's output schema (see I-3).

---

## 1. Current scorecard

### Per tool

| Tool | Now | Target | Blocking item(s) |
|---|---|---|---|
| `get_server_capabilities` | 10 | 10 | — hold |
| `resolve_term` | 10 | 10 | — hold (fix docstring example, P3) |
| `get_term_parents` | 10 | 10 | — hold |
| `get_term_children` | 10 | 10 | — hold |
| `get_term_ancestors` | 10 | 10 | — hold |
| `get_term_descendants` | 10 | 10 | — hold |
| `resolve_xref` | 9 | 9+ | absent-entity contract (I-2) |
| `map_cross_ontology` | 9 | 9+ | — hold |
| `get_genes_for_phenotype` | 9 | 9+ | absent-entity contract (I-2) |
| `get_diseases_for_phenotype` | 9 | 9+ | absent-entity contract (I-2) |
| `get_genes_for_disease` | 9 | 9+ | absent-entity contract (I-2) |
| `get_diseases_for_gene` | 9 | 9+ | absent-entity contract (I-2) |
| `get_term` | 8 | 9.5 | synonyms schema polymorphism (I-3) |
| `get_phenotypes_for_gene` | 8 | 9.5 | frequency encoding (I-5) + absent-entity (I-2) |
| `get_phenotypes_for_disease` | 7 | 9.5 | compact verbosity (I-4) |
| `get_diagnostics` | **6** | 9.5 | **null counts bug (I-1)** |

### Per aspect

| Aspect | Now | Target | Lever |
|---|---|---|---|
| Correctness / data integrity | 9.5 | 9.5 | hold |
| Error handling | 9.5 | 9.5 | hold |
| Discoverability | 9.5 | 9.5 | hold |
| Performance | 10 | 10 | hold (sub-ms, local SQLite) |
| Provenance / citation | 9.5 | 9.5 | hold |
| **API consistency** | **7.5** | 9 | I-2 + I-3 |
| **Observability** | **7** | 9 | I-1 |
| **Token efficiency** | **7.5** | 9 | I-4 + I-6 |

---

## 2. Findings (root-caused)

### I-1 — `get_diagnostics.counts.*` are all `null` *(BUG — the only functional defect)*

- **Observed:** `counts: {terms:null, obsolete:null, closure:null, xref:null, disease_phenotype:null, gene_phenotype:null, gene_disease:null}` while `index_status:"available"` and every query works.
- **Root cause:** `hpo_link/mcp/tools/discovery.py:92-100` pulls counts from the meta KV table via `meta.get("num_terms")` etc., but the builder never writes those keys, so each `.get()` returns `None`. Meanwhile a working `Repository.counts()` (`hpo_link/data/repository.py:277`) computes real row counts and is **unused** here.
- **Impact:** the tool's stated purpose ("confirm freshness / diagnose `data_unavailable`") is defeated — an operator can't tell whether the index is full or empty.
- **Severity:** Medium (functional, but isolated to one diagnostic tool).

### I-2 — Inconsistent absent-entity semantics across the 6 association tools *(CONSISTENCY)*

Confirmed with well-formed-but-nonexistent and malformed ids:

| Call | Result |
|---|---|
| `get_phenotypes_for_gene("NCBIGene:999999999")` (well-formed, absent) | `not_found` (404) |
| `get_phenotypes_for_gene("NOTAGENE123")` (unresolvable symbol) | `not_found` (404) |
| `get_genes_for_disease("OMIM:0000000")` (well-formed, absent) | `success:true`, empty list |
| `get_phenotypes_for_disease("OMIM:0000000")` (well-formed, absent) | `success:true`, empty list |
| `get_phenotypes_for_disease("notacurie")` (**malformed**, no colon) | `success:true`, empty list |
| `resolve_xref("UMLS:C9999999")` (absent) | `success:true`, empty list |

- **Root cause:** gene path raises `NotFoundError` on zero rows (`hpo_link/services/annotation_service.py:116`); disease/xref paths return an empty page. Disease path also performs **no CURIE-shape validation** — `notacurie` should be `invalid_input`.
- **Impact:** a consuming agent cannot branch uniformly on "absent." Same conceptual case ("valid id, no annotations") yields a 404 on one tool and an empty 200 on another.
- **Severity:** Medium.

### I-3 — `synonyms` field changes shape across `response_mode` is not advertised *(CONSISTENCY / schema)*

- **Observed:** `standard` → `[{text, scope}]`; `compact` (default) & sparse-`fields` → `["Kidney cyst", ...]`. Code doing `synonyms[].text` silently breaks at the default rung.
- **Root cause:** intentional and documented in `hpo_link/services/shaping.py:54-66` (`_plain_synonyms`), but the `get_term` `output_schema` / description does not express the polymorphism, so a typed consumer can't anticipate it.
- **Severity:** Low (by-design; documentation/schema-expressiveness gap).

### I-4 — "compact" association rows aren't compact *(TOKEN EFFICIENCY)*

- **Observed:** `get_phenotypes_for_disease` in `compact` ships ~13 fields/row, many empty/null (`qualifier:""`, `onset:""`, `sex:""`, `modifier:""`, `frequency_hpo:null`, `frequency_ratio:null`, `frequency_percent:null`).
- **Root cause:** term shaping drops null/empty in `compact` (`shaping.py:54`), but annotation-row shaping (`hpo_link/services/annotation_service.py` / `hpo_link/mcp/annotations.py`) does not apply the same rule.
- **Severity:** Low.

### I-5 — `get_phenotypes_for_gene` frequency encoding is mixed and under-decoded *(CONSISTENCY / usability)*

- **Observed:** `frequency` is sometimes an HP code (`HP:0040281`), sometimes a ratio (`42/163`), sometimes `-`. The disease path already decodes into `frequency_hpo` / `frequency_ratio` / `frequency_percent`; the gene path does not.
- **Severity:** Low.

### I-6 — `recommended_citation` (~250 chars) repeats on every non-`minimal` response *(TOKEN EFFICIENCY)*

- `minimal` correctly drops it (and `next_commands`), so the lever exists; it's just not used at `compact`.
- **Severity:** Nit.

### I-7 — `resolve_term` docstring example `SNOMEDCT_US:193046000` returns `not_found` *(DOC)*

- Recovery routing to `resolve_xref` is correct; only the documented example is wrong.
- **Severity:** Nit.

### Retracted (correct-by-design)
- ~~`error_rate: null`~~ — intentional `<20`-sample guard (`metrics.py:23`).
- ~~`synonyms` flattening is a bug~~ — documented behavior (`shaping.py:54-56`); reframed as I-3.

---

## 3. Phased plan

Priority order is **P0 → P3**. Each phase is independently shippable and gated by `make ci-local` (format-check, lint, lint-loc, mypy strict, tests; coverage ≥ 80%; files ≤ 500 lines).

### Phase 0 — Correctness: fix the one bug *(P0, ~0.5 day)*

**Objective:** `get_diagnostics` reports real volume counts. Lifts `get_diagnostics` 6 → 9 and Observability 7 → 9.

- **T0.1** Persist counts at build time: have `hpo_link/ingest/builder.py` write `num_terms`, `num_obsolete`, `num_closure`, `num_xref`, `num_disease_phenotype`, `num_gene_phenotype`, `num_gene_disease` into the meta table (authoritative, reflects the built artifact — no runtime query).
- **T0.2** Back-compat fallback: in `discovery.py:92-100`, when a meta count key is absent, fall back to `Repository.counts()` (`repository.py:277`) so already-built DBs still report. Prefer meta when present.
- **T0.3** Optional clarity: when `error_rate` is withheld, emit `"error_rate_withheld_below": 20` (or a note) so the `null` is self-explaining rather than ambiguous.
- **Acceptance:** `get_diagnostics` returns positive integers for all seven counts against a freshly built DB; `make data-status` and the tool agree; a DB built before T0.1 still returns counts via the fallback.
- **Tests:** unit test asserting non-null, internally consistent counts (e.g., `obsolete ≤ terms`); a test simulating a meta table missing the new keys to exercise the fallback.

### Phase 1 — API consistency contract *(P1, ~1 day)*

**Objective:** uniform absent/invalid semantics across all 6 association tools + documented contract. Lifts API consistency 7.5 → 9 and unblocks the four 9-tools and `get_phenotypes_for_gene`.

- **T1.1** Decide and document the contract in `get_server_capabilities` (e.g.: *malformed id → `invalid_input`; well-formed but unknown id → empty 200 page with `total:0`; only `resolve_*` returns `not_found` because identity resolution genuinely failed*).
- **T1.2** Make the gene path conform: `get_phenotypes_for_gene` / (and gene side of `get_diseases_for_gene`) should return an empty page for a well-formed-but-unannotated gene id instead of `not_found` (`annotation_service.py:116`). Keep `not_found` only when the symbol/id cannot be resolved to any identity, and document that distinction.
- **T1.3** Add CURIE/id shape validation to the disease and gene paths so `notacurie` → `invalid_input` (with `field`), matching the quality of the existing `resolve_term("")` → `invalid_input` path.
- **Acceptance:** the I-2 evidence table collapses to one rule; identical "absent vs malformed" inputs behave identically across all 6 tools; capabilities documents the rule.
- **Tests:** a parametrized matrix (`{malformed, well-formed-absent, present}` × `{6 tools}`) asserting `invalid_input | empty-200 | data`.

### Phase 2 — Token efficiency / verbosity ladder *(P2, ~1 day)*

**Objective:** make `compact` genuinely compact for association tools. Lifts Token efficiency 7.5 → 9, `get_phenotypes_for_disease` 7 → 9.

- **T2.1** Apply the term-shaping drop-null/empty rule (`shaping.py:54`) to annotation rows so `compact` omits `qualifier:""`, `onset:""`, `sex:""`, `modifier:""`, and `*:null` frequency fields.
- **T2.2** Move `recommended_citation` out of every `compact` body into `_meta` (or emit once per response, not per row context) — keep it inline at `standard`/`full`. `hpo_id` + `hpo_version` already satisfy the citation contract at `compact`.
- **T2.3** (Optional) Add the sparse `fields=[...]` projection (already on `get_term`) to the high-volume association tools.
- **Acceptance:** measured payload bytes for a 25-row `get_phenotypes_for_disease` `compact` response drop materially (target ≥ 30%); no field present in `compact` carries only empty/null across all rows.
- **Tests:** golden-size assertion (bytes/row ceiling) per response_mode; assert no all-empty columns survive in `compact`.

### Phase 3 — Schema expressiveness & polish *(P3, ~1 day)*

**Objective:** push remaining sub-9.5 tools to 9.5. Lifts `get_term` 8 → 9.5 and `get_phenotypes_for_gene` → 9.5.

- **T3.1** Advertise the `synonyms` polymorphism (I-3): express both shapes in `get_term`'s `output_schema` and note in the description that `compact` returns plain strings, `standard`/`full` return `{text, scope}`.
- **T3.2** Decode gene-path frequency (I-5): give `get_phenotypes_for_gene` rows the same `frequency_hpo` / `frequency_ratio` / `frequency_percent` triplet the disease path produces.
- **T3.3** Fix the `resolve_term` docstring example (I-7) — replace `SNOMEDCT_US:193046000` with a CURIE that actually resolves (e.g., a real HPO xref), or change it to a label example.
- **T3.4** (Stretch) `search_terms` "did you mean": on a 0-hit FTS query, fall back to the same fuzzy candidate logic `resolve_term` already uses (it returned 5 ranked candidates for `"cyst"`), so a typo like `"polycstic kidny"` returns suggestions instead of an empty list.
- **Acceptance:** `get_term` schema validates both synonym shapes; gene & disease phenotype rows are field-symmetric; docstring example resolves; (stretch) a typo query yields candidates.
- **Tests:** schema-conformance test for both synonym shapes; symmetry test comparing gene vs disease frequency fields; a doctest/asserted call for the corrected example.

---

## 4. Target scorecard after each phase

| | After P0 | After P1 | After P2 | After P3 |
|---|---|---|---|---|
| `get_diagnostics` | 9 | 9 | 9 | 9.5 |
| 6 association tools | 8–9 | **9** | **9–9.5** | 9.5 |
| `get_phenotypes_for_disease` | 7 | 8 | **9** | 9.5 |
| `get_phenotypes_for_gene` | 8 | 8.5 | 9 | **9.5** |
| `get_term` | 8 | 8 | 8.5 | **9.5** |
| API consistency (aspect) | 7.5 | **9** | 9 | 9.5 |
| Observability (aspect) | **9** | 9 | 9 | 9.5 |
| Token efficiency (aspect) | 7.5 | 7.5 | **9** | 9.5 |
| **Overall** | ~9.0 | ~9.2 | ~9.4 | **~9.6** |

**Every tool ≥ 9 and every aspect ≥ 9 is reached at the end of Phase 2.** Phase 3 is the polish pass to clear 9.5 across the board.

---

## 5. Definition of done (per phase)

1. `make ci-local` green (format-check, lint, lint-loc, mypy strict, tests).
2. New behavior covered by unit tests; coverage ≥ 80% holds.
3. Touched files ≤ 500 lines.
4. Capability/version surfaces updated where contracts changed (`get_server_capabilities`, `output_schema`, `hpo://capabilities`).
5. Data-plane returns plain dicts; MCP plane owns `success`/`_meta` (invariant preserved).
6. Every `compact`+ response still carries `_meta.next_commands`; `minimal` still opts out.

---

## 6. What is already excellent (do not regress)

- **Error contract** — every error carries `error_code` + `retryable` + `recovery_action` + `field` (when applicable) + `next_commands`. Best-in-class; the Phase 1 work must preserve it.
- **`next_commands` rails** on every response — keep populating them on new/changed paths.
- **Internal consistency** — children ⊂ descendants (11 ⊂ 12, grandchild `HP:0004734`); `get_term.parents` == `get_term_parents`; gene↔disease inverses agree; `include_descendants` expansion verified (`HP:0000107` diseases 121 → 315).
- **Performance** — sub-millisecond (`elapsed_ms:0`, latency p50/p95/p99 = 0), local SQLite.
- **Provenance** — `origin`, `source`, `evidence`, `biocuration`, `association_type`, computed `frequency_percent`.
