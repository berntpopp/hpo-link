# hpo-link MCP — LLM-Consumer Assessment & "Beyond 9/10" Plan

- **Date:** 2026-06-20
- **HPO release under test:** 2026-06-06 (`capabilities_version: a27e70c63bcf0820`)
- **Author's vantage:** the LLM *consuming* the MCP, grading from a live session
  (`resolve_term("kidney cyst")` → `HP:0000107` → `get_term_children`, plus the
  server instructions and tool schemas as seen by the client).
- **Companion to:** [`2026-06-19-mcp-tool-audit.md`](2026-06-19-mcp-tool-audit.md)
  (17-tool, 31-call audit; verdict 8.7/10; P0–P3 plan to ~9.6). **This doc does not
  re-run that audit.** It (a) re-grades the *felt* experience from live use, (b)
  corrects the scope of one prior finding (I-6), and (c) adds the **9.5 → 10**
  "prove-and-guardrail" phase the prior plan stops short of.
- **Goal (as asked):** push **every aspect and every tool to a genuine 10**, in
  priority order, with each step gated by `make ci-local`.

---

## 1. LLM-consumer scorecard (what it felt like to use)

| Aspect | Live score | Prior audit | Ceiling lever |
|---|---|---|---|
| **Speed** | 9 | 10 | Prove it (SLO + benchmark), don't just feel it → §Phase C |
| **Token efficiency** | **6** | 7.5 | Citation tax on the hot path (F-1) + compact rows + byte gate |
| **Observability** | 9 | 7→9 (after P0) | Counts bug (I-1) + per-error-code counts + freshness signal |
| **Discoverability** | 9 | 9.5 | Machine-readable tool graph + 100% `next_commands` coverage |
| **Correctness / grounding** | 9 | 9.5 | Absent-entity contract (I-2) + match-confidence + invariant tests |
| **Overall (felt)** | **~8.5** | 8.7 | — |

**Why my token-efficiency grade is below the prior audit's (6 vs 7.5).** The prior
audit scored token efficiency as a weighted whole and filed the citation repeat as a
"nit" (I-6) on the assumption that *"minimal correctly drops it."* From the client
seat, the felt cost lands on the **most common hot path** — `resolve_term` →
hierarchy walk — and on that path **the citation is not dropped, even at `minimal`**
(see F-1). Both of my compact calls this session carried the full ~250-char
`recommended_citation`. A consumer doing a 5–10 hop ontology walk pays that tax on
every hop. That is a recurring, structural cost, not a nit — hence 6.

**What is genuinely excellent (and made the rest feel like a 9).** `match_type:
"exact_synonym"` told me *why* "kidney cyst" → "Renal cyst" without a guess;
`_meta.next_commands` handed me the exact next call; every payload pinned
`hpo_version` + `capabilities_version` + `request_id`. These are the features I'd
copy to other servers. Do not regress them.

---

## 2. Finding (live-confirmed correction to prior I-6)

### F-1 — `recommended_citation` is hard-wired into the **term** family at *every* mode, including `minimal` *(TOKEN EFFICIENCY — corrects I-6 scope)*

The prior audit's I-6 says the `minimal` lever already drops the citation and is
"just not used at `compact`." That is true for **annotation rows** but **false for
term/ontology/hierarchy/xref payloads** — the exact tools a phenotype walk uses most.

- **Two service planes disagree:**
  - **Annotation plane (already correct):** `AnnotationService._provenance`
    (`hpo_link/services/annotation_service.py:76-86`) emits `recommended_citation`
    **only** at `standard`/`full`; `hpo_version` is the anchor at `compact`/`minimal`.
  - **Term plane (the leak):** `_MINIMAL_KEEP`
    (`hpo_link/services/shaping.py:24-27`) **explicitly lists**
    `recommended_citation` — comment: *"always included per spec"* — so it survives
    even at `minimal`. At `compact`, `shape_term` only drops *empty* values
    (`shaping.py:67-77`), and the citation is non-empty, so it always survives there
    too. It is seeded onto term payloads at `hpo_link/services/hpo_service.py:76` and
    declared in `hpo_link/mcp/schemas.py:75,114,186`.
- **Live evidence:** `resolve_term("kidney cyst")` (compact) and
  `get_term_children("HP:0000107")` (compact) both returned the full citation string.
- **The canonical citation already lives where a client can fetch it once** —
  `get_server_capabilities` carries `RECOMMENDED_CITATION`
  (`hpo_link/mcp/capabilities.py:128`), and the envelope design already states
  static provenance *"lives ONLY in get_server_capabilities"* for `_meta`
  (`hpo_link/mcp/envelope.py:36-39`). The term **body** simply didn't get the memo.
- **Impact:** structural per-hop token tax on the highest-fan-out workflow; also a
  cross-plane inconsistency (a consumer can't assume citation-presence is uniform).
- **Severity:** Medium for token efficiency (was filed Nit). The fix is small and
  mechanical.

---

## 3. The bar: what "10" means per aspect

A 10 is not "no open findings" — it is **provably optimal and guarded against
regression**. Concretely:

- **Speed = 10** — a published latency SLO (e.g. p99 < 5 ms local) with a CI/bench
  check, so sub-ms survives DB growth. (Today it *is* sub-ms — `elapsed_ms:0`,
  p50/p95/p99 = 0 — but unproven against growth.)
- **Token efficiency = 10** — no field in `compact`/`minimal` carries constant or
  all-empty content; a **byte-per-row ceiling test per `response_mode`** fails CI on
  regression.
- **Observability = 10** — an operator can fully self-diagnose from the tools alone:
  real volume counts, per-tool latency percentiles, **per-error-code** counts, and a
  data-freshness/staleness signal.
- **Discoverability = 10** — a *cold* client can plan an entire workflow from
  `get_server_capabilities` (a machine-readable tool-transition graph), without trial
  calls; `next_commands` present on **100%** of responses incl. every error path.
- **Correctness = 10** — one uniform absent/invalid contract across all tools,
  match-confidence exposed on fuzzy resolves, and hierarchy invariants locked by
  property tests.

---

## 4. Phased plan (priority order, each independently shippable)

> Phases A–B mostly **adopt** the prior audit's P0–P2 work; Phase C is the **new**
> 9.5 → 10 layer. Where a task already exists in the prior plan it is cited as
> `[prior Tx.y]` rather than restated.

### Phase A — Token efficiency on the hot path *(P0 · ~0.5 day · biggest felt win)*

**Objective:** make the term/ontology/hierarchy/xref family as lean as the
annotation family already is. Lifts **Token efficiency 6 → 9** and removes the
cross-plane inconsistency.

- **A.1 — Gate the term citation (fixes F-1).** Remove `recommended_citation` from
  `_MINIMAL_KEEP` (`shaping.py:24-27`) and drop it from term bodies at
  `compact`/`minimal`, mirroring `AnnotationService._provenance`
  (`annotation_service.py:76-86`). Keep it inline at `standard`/`full`. Keep
  `hpo_version` as the always-present per-call citation anchor.
- **A.2 — Update the spec line, not just the code.** The `shaping.py:24` comment
  (*"always included per spec"*) encodes the old rule — change it so the single
  documented contract becomes: *full citation is fetched once from
  `get_server_capabilities`; every payload carries `hpo_version` as the anchor;
  inline citation is a `standard`/`full` convenience only.* Update `get_term`'s
  `output_schema` / `hpo://capabilities` to match.
- **A.3 — Adopt prior token-efficiency tasks for the association rows** —
  `[prior T2.1]` (drop null/empty columns in `compact`) and `[prior T2.2]` (citation
  out of `compact` bodies). A.1 makes the rule uniform across both planes.
- **Acceptance:** a `compact` `resolve_term` / `get_term*` body contains **no**
  `recommended_citation`; `hpo_version` still present; `standard`/`full` unchanged;
  `get_server_capabilities` remains the citation source of record.
- **Tests:** assert citation absent at `compact`/`minimal` and present at
  `standard`/`full` for one term tool **and** one annotation tool (locks both planes
  to one rule).

### Phase B — Correctness & observability gaps *(P1 · ~1.5 days · adopt prior P0+P1)*

**Objective:** clear the two real defects the prior audit root-caused. Lifts
**Observability 7 → 9** and **Correctness/consistency** to 9.

- **B.1 — Fix the diagnostics counts bug** `[prior T0.1–T0.3]`: `get_diagnostics`
  must report real volume counts (root cause `discovery.py:92-100` reads meta keys
  the builder never writes; `Repository.counts()` exists and is unused).
- **B.2 — Unify the absent-entity contract** `[prior T1.1–T1.3]`: malformed id →
  `invalid_input`; well-formed-but-unknown → empty 200 page; only `resolve_*` returns
  `not_found`. Document it in `get_server_capabilities`.
- **Acceptance / tests:** per the prior plan's Phase 0 + Phase 1 acceptance criteria.

### Phase C — The 9.5 → 10 guardrail layer *(P2 · ~2 days · NEW — this is the "beyond 9" work)*

**Objective:** convert "currently good" into "provably optimal and regression-gated"
for every aspect. This is the delta beyond the prior plan's 9.5 ceiling.

- **C.1 — Byte-ceiling regression gate (Token efficiency → 10).** Golden test
  asserting bytes-per-row and total-payload ceilings **per `response_mode`** for a
  representative term call and a 25-row association call. CI fails if a future field
  re-inflates `compact`. Add an assertion that **no column is all-empty/constant**
  across rows in `compact`.
- **C.2 — Latency SLO + benchmark (Speed → 10).** Publish a latency SLO in
  `get_server_capabilities`/`get_diagnostics`; add a bench (e.g. a deep
  `get_term_descendants` + a 25-row association page) with a hard p99 ceiling so
  sub-ms is *guaranteed*, not just observed. (`metrics` already records p50/p95/p99 —
  surface the SLO alongside.)
- **C.3 — Self-diagnosis completeness (Observability → 10).** Add to
  `get_diagnostics`: **per-error-code** counts (confirm or extend `mcp/metrics.py`;
  today only an aggregate `<20`-sample-gated `error_rate` exists) and a
  **freshness/staleness** field (built date vs. HPO release age) so an operator sees
  "stale index" without external tools.
- **C.4 — Cold-start workflow planning (Discoverability → 10).** Emit a
  machine-readable **tool-transition graph** in `get_server_capabilities` (which tool
  legitimately follows which — the static form of `next_commands`), and audit that
  **every** response path, **including all 7 error codes**, populates
  `next_commands`. Advertise the `synonyms` shape polymorphism in `get_term`'s
  `output_schema` `[prior T3.1]` so a typed client never breaks on the
  `compact`→plain-string collapse.
- **C.5 — Grounding hardening (Correctness → 10).** Expose a numeric
  **match-confidence** on fuzzy/ambiguous `resolve_term` results (exact synonym vs.
  fuzzy is currently only qualitative via `match_type`); lock hierarchy invariants
  (children ⊆ descendants; `get_term.parents == get_term_parents`; gene↔disease
  inverse agreement — all verified by hand in the prior audit) as **property tests**
  so they can't silently drift.
- **Acceptance:** every aspect's "10" bar in §3 is met **and** backed by a CI check;
  a cold client can construct the kidney-cyst walk from capabilities alone.

---

## 5. Target scorecard

| Aspect | Now (felt) | After A | After B | After C |
|---|---|---|---|---|
| Speed | 9 | 9 | 9 | **10** |
| Token efficiency | 6 | **9** | 9 | **10** |
| Observability | 9 | 9 | **9.5** | **10** |
| Discoverability | 9 | 9 | 9 | **10** |
| Correctness / grounding | 9 | 9 | **9.5** | **10** |
| **Overall** | ~8.5 | ~9.1 | ~9.4 | **~10** |

Every aspect reaches **9 after Phase A+B**; the **10** across the board is what
**Phase C** buys — and, crucially, *guards* (regression gates, not one-time fixes).
Per-tool: Phases A–B carry the prior audit's tools to ≥9.5; Phase C's byte-gate +
invariant tests + `next_commands` coverage are what move them the last half-point to
10.

---

## 6. Definition of done (per phase)

Inherits the prior audit's §5 verbatim — `make ci-local` green (format-check, lint,
lint-loc, mypy strict, tests; coverage ≥ 80%; files ≤ 500 lines); data plane returns
plain dicts, MCP plane owns `success`/`_meta`; every `compact`+ response still carries
`_meta.next_commands` and `minimal` still opts out. **Phase C adds:** each "10" claim
must be backed by a CI assertion (byte ceiling, latency p99, invariant property test),
so the score cannot silently regress.

## 7. Do not regress (the reasons the felt score was already 8.5)

- `match_type` transparency on `resolve_term` — *why* a label matched, not just the id.
- `_meta.next_commands` rails on every success path — the single best discoverability
  feature; Phase C only widens coverage, never removes.
- Per-call grounding triple: `hpo_version` + `capabilities_version` + `request_id`.
- The 7-code error contract (`error_code` + `retryable` + `recovery_action` +
  `field`) — best-in-class; Phases A–C must preserve it.
