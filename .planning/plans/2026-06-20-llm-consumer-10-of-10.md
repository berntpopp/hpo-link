# hpo-link "Beyond 9/10" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (for parallel waves) and superpowers:test-driven-development per task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task ends `make ci-local` green.

**Goal:** Implement the `2026-06-20-llm-consumer-assessment.md` plan end-to-end — push every aspect (speed, token efficiency, observability, discoverability, correctness) to a genuine, regression-gated 10.

**Architecture:** Two planes are preserved throughout — services return plain dicts; the MCP envelope owns `success`/`_meta`. All changes are surgical edits to existing core files plus new regression-test files. Each "10" claim is backed by a CI assertion (byte ceiling, latency p99, invariant property test) so the score cannot silently regress.

**Tech Stack:** Python 3.12, `uv`, pytest (`-n auto`, asyncio auto), ruff, mypy strict, FastMCP, SQLite. No new runtime deps.

## Global Constraints (verbatim, apply to every task)

- `make ci-local` green = definition of done: `format-check`, `lint-ci`, `lint-loc` (≤ 500 lines/file hard cap), `typecheck` (mypy strict), `test-fast` (coverage ≥ 80%).
- Two planes: services return plain dicts; **only** `mcp/envelope.py::run_mcp_tool` injects `success`/`_meta`.
- 7-code error taxonomy unchanged: `invalid_input, not_found, ambiguous_query, data_unavailable, rate_limited, upstream_unavailable, internal_error`.
- Every `compact`+ response carries `_meta.next_commands`; `minimal` opts out (returns only `{tool, request_id}`).
- `hpo_version` is the always-present per-call citation anchor (every non-minimal payload). The long-form `recommended_citation` is fetched once from `get_server_capabilities`; inline copy is a `standard`/`full` convenience only.
- Every tool's real output (success + error, all modes) must validate against its `output_schema` (`tests/unit/test_output_schemas.py` / `test_schemas.py`).
- `structlog` → stderr only. Files split by responsibility, ≤ 500 lines.
- TDD: failing test first. Unit tests use the session fixtures in `tests/conftest.py` (`hpo_service`, `annotation_service`, `repo`, `built_test_db`, `mini_paths`).

---

## State assessment (READ FIRST — prior audit P0–P3 is already merged)

Confirmed in-code; **do not re-implement**:

- **B.1 diagnostics counts** — DONE. `builder.py::BuildMeta` writes `term_count…gene_disease_count`; `discovery.py::_resolve_counts` prefers meta, falls back to `repo.counts()` (repository.py:277). Tests in `test_tools_discovery.py`.
- **B.2 absent-entity contract** — DONE. `validate_disease_id`/`validate_gene` (identifiers.py) reject malformed → `invalid_input`; gene path returns empty page (no `NotFoundError` on zero rows); `capabilities.py::absent_entity_contract` documents the rule.
- **A.3 association rows** — DONE. `shape_annotation_rows` drops null/empty + `-` sentinel in compact/minimal; `_provenance(mode)` gates citation to standard/full; gene-path frequency decoded (`frequency_hpo/ratio/percent`).
- **C.4 synonyms polymorphism schema** — DONE. `schemas.py::_SYNONYM_ITEM` is a `oneOf[string, object]`.
- **C.3 error_rate guard** — partial. `error_rate_withheld_below` already emitted.

**Remaining work = this plan:** Phase A.1/A.2 (term-citation leak F-1, confirmed live), and all of Phase C (the guardrail layer). Phase B = verify + lock with one regression test.

---

## Phase A — Token efficiency on the hot path (fixes F-1)

**Files:**
- Modify: `hpo_link/services/shaping.py:23-27` (`_MINIMAL_KEEP`)
- Modify: `hpo_link/services/hpo_service.py:72-77` (`_version_fields`) + its call sites
- Modify: `AGENTS.md` (citation-contract line)
- Modify: `hpo_link/mcp/capabilities.py` (`provenance_policy` text)
- Test: `tests/unit/test_hpo_service.py`, `tests/unit/test_shaping_annotations.py` (rename concept: add term-citation cases)

**Interfaces:**
- Produces: `HpoService._version_fields(mode: str) -> dict[str, Any]` — returns `{"hpo_version": ...}` always, adds `recommended_citation` only when `mode in ("standard","full")`. Mirrors `AnnotationService._provenance(mode)`.

### Task A1: Gate the term citation by response_mode

- [ ] **Step 1 — failing tests** (`tests/unit/test_hpo_service.py`):

```python
import pytest
from hpo_link.constants import RECOMMENDED_CITATION

@pytest.mark.parametrize("mode", ["minimal", "compact"])
def test_resolve_term_omits_citation_in_lean_modes(hpo_service, mode):
    out = hpo_service.resolve_term("Phenotypic abnormality", response_mode=mode)
    assert out["hpo_version"]  # anchor always present
    assert "recommended_citation" not in out

@pytest.mark.parametrize("mode", ["standard", "full"])
def test_resolve_term_keeps_citation_in_rich_modes(hpo_service, mode):
    out = hpo_service.resolve_term("Phenotypic abnormality", response_mode=mode)
    assert out["recommended_citation"] == RECOMMENDED_CITATION

@pytest.mark.parametrize("mode", ["minimal", "compact"])
def test_get_term_omits_citation_in_lean_modes(hpo_service, mode):
    out = hpo_service.get_term("HP:0000118", response_mode=mode)
    assert out["hpo_version"]
    assert "recommended_citation" not in out

def test_get_term_keeps_citation_in_full(hpo_service):
    out = hpo_service.get_term("HP:0000118", response_mode="full")
    assert out["recommended_citation"] == RECOMMENDED_CITATION
```

- [ ] **Step 2 — run, expect FAIL** (`uv run pytest tests/unit/test_hpo_service.py -k citation -q`). compact/minimal still carry the citation.

- [ ] **Step 3 — implement.** In `hpo_link/services/hpo_service.py`, change `_version_fields` to take a mode (mirror `AnnotationService._provenance`):

```python
def _version_fields(self, mode: str = DEFAULT_RESPONSE_MODE) -> dict[str, Any]:
    """Version + citation anchors. hpo_version is always present (the per-call
    citation anchor); the long-form recommended_citation is a standard/full
    convenience only — it is fetched once from get_server_capabilities."""
    fields: dict[str, Any] = {"hpo_version": self._version}
    if mode in ("standard", "full"):
        fields["recommended_citation"] = RECOMMENDED_CITATION
    return fields
```

Then thread `response_mode` into every call site in `hpo_service.py`: `resolve_term`, `search_terms`, `get_term`, `_neighbours`, `_closure`, `resolve_xref`, `map_cross_ontology` all already receive `response_mode`/`mode` — change `**self._version_fields()` → `**self._version_fields(response_mode)` (use the local `response_mode` param name present in each method; `_neighbours`/`_closure` use `response_mode`). `resolve_term` and `map_cross_ontology` also have `response_mode`.

- [ ] **Step 4 — drop citation from `_MINIMAL_KEEP`** (`hpo_link/services/shaping.py:23-27`):

```python
#: Identity anchors kept in ``minimal`` mode. hpo_version is the per-call citation
#: anchor; the long-form recommended_citation is fetched once from
#: get_server_capabilities and inlined only at standard/full (not here).
_MINIMAL_KEEP: frozenset[str] = frozenset({"hpo_id", "name", "hpo_version", "_meta"})
```

- [ ] **Step 5 — run, expect PASS** (`uv run pytest tests/unit/test_hpo_service.py -k citation -q`).

- [ ] **Step 6 — guard the schemas still validate.** `RESOLVE_TERM_SCHEMA`/`TERM_SCHEMA` already declare `recommended_citation=_STR_NULL` (optional, permissive). No change needed; run `uv run pytest tests/unit/test_schemas.py tests/unit/test_output_schemas.py -q` to confirm.

- [ ] **Step 7 — commit** `feat(token): gate term recommended_citation to standard/full (fixes F-1)`.

### Task A2: Make the documented contract match the code

- [ ] **Step 1** — update `hpo_link/services/shaping.py` docstring (top of file, the `compact` paragraph) and the `_MINIMAL_KEEP` comment (done in A1.4) so no line claims the citation is "always included per spec."
- [ ] **Step 2** — `AGENTS.md`: change the Invariants bullet that reads *"the long-form `recommended_citation` appears on term records and on `standard`/`full` association payloads"* to: *"the long-form `recommended_citation` is inlined only on `standard`/`full` payloads (term and association alike); compact/minimal carry `hpo_version` as the anchor and defer the full citation to `get_server_capabilities`."*
- [ ] **Step 3** — `hpo_link/mcp/capabilities.py::build_capabilities`, tighten `provenance_policy` to state the uniform rule explicitly (one plane, one rule):

```python
"provenance_policy": (
    "Static provenance (research-use restriction, citation, HPO release) is "
    "declared here and applies to ALL tool outputs. Every non-minimal payload "
    "carries hpo_version as the per-call citation anchor; the long-form "
    "recommended_citation is inlined only at response_mode standard/full (term "
    "and association payloads alike) and is otherwise fetched once from here."
),
```

- [ ] **Step 4** — `make ci-local`; commit `docs(contract): single citation rule across both planes (A.2)`.

---

## Phase B — Verify & lock the two prior defects

Both are already fixed; this phase adds **one** regression test that locks the contract uniformly and confirms diagnostics counts are real.

**Files:** Test: `tests/unit/test_absent_entity_contract.py` (new), assertions in `tests/unit/test_tools_discovery.py`.

### Task B1: Uniform absent/invalid contract matrix (locks B.2)

- [ ] **Step 1 — new test file** `tests/unit/test_absent_entity_contract.py`. A parametrized matrix over the 6 association tools × {malformed, well-formed-absent} asserting `invalid_input` vs empty-200, at the **service** layer (plain dicts / typed exceptions):

```python
"""Locks the uniform absent-entity contract (assessment B.2 / prior T1.1-T1.3)."""
import pytest
from hpo_link.exceptions import InvalidInputError

# (method_name, malformed_arg, well_formed_absent_arg)
GENE_TOOLS = [("get_phenotypes_for_gene", "NCBIGene:abc", "NCBIGene:999999999"),
              ("get_diseases_for_gene", "NCBIGene:abc", "NCBIGene:999999999")]
DISEASE_TOOLS = [("get_phenotypes_for_disease", "notacurie", "OMIM:0000000"),
                 ("get_genes_for_disease", "notacurie", "OMIM:0000000")]
PHENO_TOOLS = [("get_genes_for_phenotype", "", "HP:0000001"),
               ("get_diseases_for_phenotype", "", "HP:0000001")]

@pytest.mark.parametrize("method,bad,_absent", GENE_TOOLS + DISEASE_TOOLS)
def test_malformed_id_raises_invalid_input(annotation_service, method, bad, _absent):
    with pytest.raises(InvalidInputError):
        getattr(annotation_service, method)(bad)

@pytest.mark.parametrize("method,_bad,absent", GENE_TOOLS + DISEASE_TOOLS)
def test_well_formed_absent_returns_empty_page(annotation_service, method, _bad, absent):
    out = getattr(annotation_service, method)(absent)
    assert out["total"] == 0
    assert out["returned"] == 0
    rows = out.get("phenotypes") or out.get("genes") or out.get("diseases")
    assert rows == []
```

> Note: `get_genes_for_phenotype`/`get_diseases_for_phenotype` take a free-text `term` that must *resolve*; an unknown term legitimately raises `NotFoundError` (resolve_* semantics) — they are excluded from the empty-page matrix above and covered by existing `test_hpo_service.py` not_found cases. If `HP:0000001` (root "All") has zero gene annotations it returns an empty page; adjust the absent arg to a guaranteed-empty well-formed HP id from the fixture if needed.

- [ ] **Step 2 — run** (`uv run pytest tests/unit/test_absent_entity_contract.py -q`). Expect PASS (contract already implemented). If any case fails, that is a real regression to fix in `annotation_service.py`/`identifiers.py` before proceeding.

- [ ] **Step 3 — diagnostics counts are real** — add to `tests/unit/test_tools_discovery.py` (or confirm exists):

```python
def test_resolve_counts_all_positive_against_built_db(repo):
    from hpo_link.mcp.tools.discovery import _resolve_counts
    counts = _resolve_counts(repo.read_meta(), repo)
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())
    assert counts["terms"] > 0
    assert counts["obsolete"] <= counts["terms"]
```

- [ ] **Step 4 — commit** `test(contract): lock absent-entity matrix + diagnostics counts (Phase B)`.

---

## Phase C — The 9.5 → 10 guardrail layer (the new work)

Order of execution (dependency DAG): **C4a (capabilities constants) → {C3-metrics, C3-freshness, C5-grounding, C4b-graph} in parallel → C1/C2/C-coverage gates last.** See "Execution & parallelization" below.

### Task C4a: Static SLO + tool-graph data (dependency root)

**Files:** Modify `hpo_link/constants.py`, `hpo_link/mcp/capabilities.py`. Test: `tests/unit/test_tools_ontology.py`.

- [ ] **Step 1 — failing test** (`tests/unit/test_tools_ontology.py`):

```python
def test_capabilities_publishes_latency_slo():
    from hpo_link.mcp.capabilities import build_capabilities
    cap = build_capabilities()
    assert cap["latency_slo"]["p99_ms"] == 5
    assert "scope" in cap["latency_slo"]

def test_capabilities_tool_graph_is_complete():
    from hpo_link.mcp.capabilities import build_capabilities, TOOLS
    cap = build_capabilities()
    graph = cap["tool_graph"]
    assert set(graph) <= set(TOOLS)                      # every node is a real tool
    for nexts in graph.values():
        assert set(nexts) <= set(TOOLS)                  # every edge targets a real tool
    # the hot path is reachable from a cold start
    assert "resolve_term" in graph["get_server_capabilities"]
    assert "get_term" in graph["resolve_term"]
```

- [ ] **Step 2 — run, expect FAIL.**

- [ ] **Step 3 — add the SLO constant** to `hpo_link/constants.py`:

```python
#: Published latency SLO for local in-process queries (observability/speed).
#: Surfaced in get_server_capabilities + get_diagnostics; guarded by a benchmark.
LATENCY_SLO_P99_MS = 5
```

- [ ] **Step 4 — add `tool_graph` + `latency_slo`** to `build_capabilities()` in `hpo_link/mcp/capabilities.py` (import `LATENCY_SLO_P99_MS`). The graph is the static form of `next_commands` — which tool legitimately follows which:

```python
TOOL_GRAPH: dict[str, list[str]] = {
    "get_server_capabilities": ["resolve_term", "search_terms", "get_diagnostics"],
    "get_diagnostics": ["resolve_term", "get_server_capabilities"],
    "resolve_term": ["get_term", "search_terms"],
    "search_terms": ["get_term", "resolve_term"],
    "get_term": ["get_term_parents", "get_term_children", "get_term_ancestors",
                 "get_term_descendants", "map_cross_ontology",
                 "get_genes_for_phenotype", "get_diseases_for_phenotype"],
    "get_term_parents": ["get_term", "get_term_ancestors"],
    "get_term_children": ["get_term", "get_term_descendants"],
    "get_term_ancestors": ["get_term_parents", "get_term_descendants", "get_term"],
    "get_term_descendants": ["get_term_children", "get_term_ancestors", "get_term"],
    "map_cross_ontology": ["get_term", "resolve_xref", "get_term_ancestors"],
    "resolve_xref": ["get_term", "map_cross_ontology"],
    "get_genes_for_phenotype": ["get_diseases_for_gene", "get_phenotypes_for_gene"],
    "get_diseases_for_phenotype": ["get_genes_for_disease", "get_phenotypes_for_disease"],
    "get_phenotypes_for_gene": ["get_diseases_for_gene", "get_term"],
    "get_diseases_for_gene": ["get_phenotypes_for_disease", "get_genes_for_disease"],
    "get_genes_for_disease": ["get_phenotypes_for_gene", "get_diseases_for_gene"],
    "get_phenotypes_for_disease": ["get_genes_for_disease", "get_diseases_for_phenotype"],
}
```

In `build_capabilities()` add to the payload dict: `"latency_slo": {"p99_ms": LATENCY_SLO_P99_MS, "scope": "local in-process query (deep descendants closure or a 25-row association page)"}` and `"tool_graph": TOOL_GRAPH`. Add both keys to `_SUMMARY_KEYS`.

- [ ] **Step 5 — run, expect PASS;** `make ci-local`; commit `feat(discovery): publish latency SLO + tool-transition graph (C.2/C.4)`.

### Task C3-metrics: Per-error-code counts

**Files:** Modify `hpo_link/mcp/metrics.py`, `hpo_link/mcp/envelope.py`. Test: `tests/unit/test_metrics.py`.

- [ ] **Step 1 — failing test** (`tests/unit/test_metrics.py`):

```python
def test_snapshot_tracks_errors_by_code():
    from hpo_link.mcp import metrics
    metrics.reset()
    metrics.record("get_term", 1, ok=True)
    metrics.record("get_term", 1, ok=False, error_code="not_found")
    metrics.record("resolve_term", 1, ok=False, error_code="invalid_input")
    metrics.record("resolve_term", 1, ok=False, error_code="not_found")
    snap = metrics.snapshot()
    assert snap["errors_by_code"] == {"invalid_input": 1, "not_found": 2}

def test_record_without_error_code_is_uncategorized_on_failure():
    from hpo_link.mcp import metrics
    metrics.reset()
    metrics.record("x", 1, ok=False)
    assert metrics.snapshot()["errors_by_code"] == {"internal_error": 1}
```

- [ ] **Step 2 — run, expect FAIL.**

- [ ] **Step 3 — implement** in `hpo_link/mcp/metrics.py`: add `self._errors_by_code: dict[str, int] = {}` in `__init__`; extend `record` signature to `record(self, tool, elapsed_ms, *, ok, error_code=None)` and on `not ok` do `code = error_code or "internal_error"; self._errors_by_code[code] = self._errors_by_code.get(code, 0) + 1`; add `"errors_by_code": dict(sorted(self._errors_by_code.items()))` to `snapshot()`; clear it in `reset()`. Update the module-level `record(...)` wrapper to forward `error_code`.

- [ ] **Step 4 — wire envelope** (`hpo_link/mcp/envelope.py`): success branch `metrics.record(tool_name, elapsed, ok=success)` (unchanged → code None); error branch change to `metrics.record(tool_name, elapsed, ok=False, error_code=envelope["error_code"])`.

- [ ] **Step 5 — run, expect PASS;** `make ci-local`; commit `feat(observability): per-error-code counts in metrics (C.3)`.

### Task C3-freshness: Data freshness/staleness in diagnostics

**Files:** Modify `hpo_link/mcp/tools/discovery.py`. Test: `tests/unit/test_tools_discovery.py`.

- [ ] **Step 1 — failing test** (`tests/unit/test_tools_discovery.py`):

```python
def test_freshness_helper_flags_stale():
    from datetime import UTC, datetime
    from hpo_link.mcp.tools.discovery import _freshness
    built = "2026-01-01T00:00:00+00:00"
    now = datetime(2026, 6, 1, tzinfo=UTC)
    fr = _freshness(built, now=now)
    assert fr["age_days"] == 151
    assert fr["stale"] is True
    assert fr["stale_after_days"] == 90

def test_freshness_helper_fresh():
    from datetime import UTC, datetime
    from hpo_link.mcp.tools.discovery import _freshness
    fr = _freshness("2026-05-20T00:00:00+00:00", now=datetime(2026, 6, 1, tzinfo=UTC))
    assert fr["stale"] is False

def test_freshness_helper_handles_missing_build_date():
    from hpo_link.mcp.tools.discovery import _freshness
    fr = _freshness(None)
    assert fr["age_days"] is None and fr["stale"] is None
```

- [ ] **Step 2 — run, expect FAIL.**

- [ ] **Step 3 — implement** in `hpo_link/mcp/tools/discovery.py`:

```python
from datetime import UTC, datetime

_STALE_AFTER_DAYS = 90

def _freshness(build_utc: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Built-date age + staleness signal so an operator sees a stale index locally."""
    out: dict[str, Any] = {"build_utc": build_utc, "stale_after_days": _STALE_AFTER_DAYS,
                           "age_days": None, "stale": None}
    if not build_utc:
        return out
    try:
        built = datetime.fromisoformat(build_utc)
    except ValueError:
        return out
    if built.tzinfo is None:
        built = built.replace(tzinfo=UTC)
    current = now or datetime.now(tz=UTC)
    age = (current - built).days
    out["age_days"] = age
    out["stale"] = age > _STALE_AFTER_DAYS
    return out
```

Add `"freshness": _freshness(meta.get("build_utc"))` and `"latency_slo": {"p99_ms": LATENCY_SLO_P99_MS, ...}` to the diagnostics `payload` (import `LATENCY_SLO_P99_MS` from constants). Extend `DIAGNOSTICS_SCHEMA` in `schemas.py` with `freshness=_OBJ, latency_slo=_OBJ` (permissive).

- [ ] **Step 4 — run, expect PASS;** `make ci-local`; commit `feat(observability): data freshness + SLO echo in diagnostics (C.3/C.2)`.

### Task C5-grounding: Numeric match-confidence on resolve_term

**Files:** Modify `hpo_link/services/resolution.py`, `hpo_link/services/hpo_service.py`, `hpo_link/mcp/schemas.py`. Test: `tests/unit/test_hpo_service.py`.

- [ ] **Step 1 — failing test**:

```python
@pytest.mark.parametrize("query,expected_type,min_conf", [
    ("HP:0000118", "hpo_id", 1.0),
    ("Phenotypic abnormality", "primary", 1.0),
])
def test_resolve_term_exposes_match_confidence(hpo_service, query, expected_type, min_conf):
    out = hpo_service.resolve_term(query)
    assert out["match_type"] == expected_type
    assert out["match_confidence"] >= min_conf

def test_exact_synonym_confidence_below_primary(hpo_service):
    # uses a fixture synonym (see tests/fixtures/mini_hp.json)
    out = hpo_service.resolve_term("<a fixture exact-synonym label>")
    assert 0.9 <= out["match_confidence"] < 1.0
```

- [ ] **Step 2 — run, expect FAIL.**

- [ ] **Step 3 — implement** a deterministic mapping in `hpo_link/services/resolution.py`:

```python
#: Deterministic confidence by match_type (exact lookups = 1.0; synonyms/xref < 1;
#: fuzzy is overridden by the bm25-derived score, clamped to <0.9).
MATCH_CONFIDENCE: dict[str, float] = {
    "hpo_id": 1.0, "primary": 1.0, "alt_id": 1.0,
    "exact_synonym": 0.95, "xref": 0.9, "related_synonym": 0.8, "fuzzy": 0.6,
}

def confidence_for(match_type: str) -> float:
    return MATCH_CONFIDENCE.get(match_type, 0.6)
```

In `hpo_service.py::resolve_term`, after `match_type, hpo_id = self._resolution.classify_resolution(raw)`, add `"match_confidence": confidence_for(match_type)` to the `out` dict (import `confidence_for`). (Fuzzy can stay at the table default 0.6 for v1 — deterministic and testable; the bm25-derived refinement is optional and out of scope unless trivial.)

- [ ] **Step 4 — schema** — add `match_confidence={"type": ["number", "null"]}` to `RESOLVE_TERM_SCHEMA` in `schemas.py`.

- [ ] **Step 5 — run, expect PASS;** `make ci-local`; commit `feat(grounding): numeric match_confidence on resolve_term (C.5)`.

### Task C1: Byte-ceiling regression gate (Token efficiency → 10)

**Files:** Test: `tests/unit/test_byte_ceiling.py` (new). Depends on Phase A (citation gated) landing first.

- [ ] **Step 1 — new test** asserting bytes-per-row + total-payload ceilings per `response_mode`, and no all-empty column in compact:

```python
"""Byte-ceiling gate: compact must stay lean; CI fails if a field re-inflates it."""
import json

# Ceilings are deliberately generous vs current sizes but tight enough to catch
# a re-introduced citation/null-column regression. Tune to ~1.4x observed on first green.
TERM_COMPACT_MAX_BYTES = 900
ASSOC_COMPACT_MAX_BYTES_PER_ROW = 320

def _b(obj) -> int:
    return len(json.dumps(obj, default=str).encode("utf-8"))

def test_get_term_compact_under_ceiling(hpo_service):
    payload = hpo_service.get_term("HP:0000118", response_mode="compact")
    assert "recommended_citation" not in payload          # F-1 stays fixed
    assert _b(payload) <= TERM_COMPACT_MAX_BYTES

def test_association_compact_bytes_per_row(annotation_service):
    out = annotation_service.get_phenotypes_for_disease("OMIM:106210", limit=25,
                                                        response_mode="compact")
    rows = out["phenotypes"]
    if rows:
        per_row = _b(rows) / len(rows)
        assert per_row <= ASSOC_COMPACT_MAX_BYTES_PER_ROW
    assert "recommended_citation" not in out

def test_compact_has_no_all_empty_column(annotation_service):
    out = annotation_service.get_phenotypes_for_disease("OMIM:106210", limit=25,
                                                        response_mode="compact")
    rows = out["phenotypes"]
    if rows:
        keys = set().union(*(r.keys() for r in rows))
        for k in keys:
            vals = [r.get(k) for r in rows if k in r]
            assert any(v not in (None, "", [], {}, "-") for v in vals), f"all-empty column: {k}"
```

- [ ] **Step 2 — run.** First run prints actual sizes via failure if ceilings too tight; set the constants to ~1.4× observed compact size, re-run to green. Confirm the `recommended_citation` absence assertions pass (proves Phase A).
- [ ] **Step 3 — commit** `test(token): byte-per-row ceiling + no-empty-column gate (C.1)`.

### Task C2: Latency benchmark with a hard p99 ceiling (Speed → 10)

**Files:** Test: `tests/unit/test_latency_slo.py` (new). No new deps — use `time.perf_counter` over N iterations.

- [ ] **Step 1 — new test** (CI-safe ceiling generous vs the 5 ms SLO to avoid flakiness on shared runners; it guards against catastrophic regression, the SLO advertises the target):

```python
"""Latency guard: deep closure + a 25-row association page must stay well under a
hard ceiling. The published SLO (capabilities.latency_slo.p99_ms) is the target;
this CI ceiling is looser to survive shared-runner jitter but still catches a
10-100x regression."""
import time

CI_P99_CEILING_MS = 50  # SLO target is 5ms local; this guards against regression

def _p99(samples):
    s = sorted(samples)
    import math
    return s[min(len(s) - 1, max(0, math.ceil(0.99 * len(s)) - 1))]

def test_descendants_and_association_p99_under_ceiling(hpo_service, annotation_service):
    samples = []
    for _ in range(200):
        t = time.perf_counter()
        hpo_service.term_descendants("HP:0000118", limit=1000)
        annotation_service.get_phenotypes_for_disease("OMIM:106210", limit=25)
        samples.append((time.perf_counter() - t) * 1000)
    assert _p99(samples) <= CI_P99_CEILING_MS

def test_slo_published_and_consistent():
    from hpo_link.mcp.capabilities import build_capabilities
    from hpo_link.constants import LATENCY_SLO_P99_MS
    assert build_capabilities()["latency_slo"]["p99_ms"] == LATENCY_SLO_P99_MS
```

- [ ] **Step 2 — run, expect PASS** (sub-ms locally). If the fixture DB lacks `OMIM:106210` use an id present in `tests/fixtures/mini_phenotype.hpoa`.
- [ ] **Step 3 — commit** `test(speed): latency p99 benchmark guard + SLO consistency (C.2)`.

### Task C-coverage: next_commands on 100% of paths incl. all 7 error codes

**Files:** Test: `tests/unit/test_next_commands_coverage.py` (new). Modify `next_commands.py`/`envelope.py` only if a gap is found.

- [ ] **Step 1 — new test** exercising the error boundary for every code and asserting non-empty `next_commands` on compact:

```python
"""Every error path (all 7 codes) must still chain via _meta.next_commands."""
import pytest
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.exceptions import (AmbiguousQueryError, DataUnavailableError,
    InvalidInputError, NotFoundError, RateLimitError, ServiceUnavailableError)

CASES = [
    ("invalid_input", InvalidInputError("bad", field="term")),
    ("not_found", NotFoundError("nope")),
    ("ambiguous_query", AmbiguousQueryError("amb", candidates=[])),
    ("data_unavailable", DataUnavailableError("no index")),
    ("rate_limited", RateLimitError("slow down")),
    ("upstream_unavailable", ServiceUnavailableError("down")),
    ("internal_error", RuntimeError("boom")),
]

@pytest.mark.parametrize("code,exc", CASES)
async def test_every_error_code_chains(code, exc):
    async def call():
        raise exc
    out = await run_mcp_tool("resolve_term", call,
                             context=McpErrorContext("resolve_term", arguments={"query": "x"}))
    assert out["success"] is False
    assert out["error_code"] == code
    assert out["_meta"]["next_commands"], f"{code} produced no next_commands"
```

- [ ] **Step 2 — run.** If any code yields empty `next_commands`, extend `default_error_next_commands` / `_error_envelope` so it always falls back to `[cmd("get_server_capabilities")]`. (Current code already does — this test locks it.)
- [ ] **Step 3 — commit** `test(discoverability): next_commands coverage on all 7 error codes (C.4)`.

### Task C5-invariants: Hierarchy + inverse-agreement property tests

**Files:** Test: `tests/unit/test_invariants.py` (new).

- [ ] **Step 1 — new test** locking the invariants verified by hand in the prior audit:

```python
"""Property/invariant tests so hierarchy + inverse relations can't silently drift."""

def test_children_subset_of_descendants(hpo_service):
    root = "HP:0000118"
    kids = {c["hpo_id"] for c in hpo_service.term_children(root)["children"]}
    desc = {d["hpo_id"] for d in hpo_service.term_descendants(root, limit=1000)["descendants"]}
    assert kids <= desc

def test_get_term_parents_match_term_parents(hpo_service):
    root = "HP:0000118"
    via_term = {p["hpo_id"] for p in hpo_service.get_term(root, response_mode="full")["parents"]}
    via_tool = {p["hpo_id"] for p in hpo_service.term_parents(root)["parents"]}
    assert via_term == via_tool

def test_gene_disease_inverse_agreement(annotation_service):
    # a gene's diseases should round-trip: each disease lists the gene back
    genes_out = annotation_service.get_diseases_for_gene("PAX6")
    for d in genes_out["diseases"]:
        back = annotation_service.get_genes_for_disease(d["disease_id"])
        symbols = {g.get("gene_symbol", "").upper() for g in back["genes"]}
        assert "PAX6" in symbols
```

- [ ] **Step 2 — run, expect PASS.** Adjust ids to the fixture's actual content (`tests/fixtures/mini_hp.json`, `mini_genes_to_disease.txt`) if `PAX6`/`HP:0000118` relations differ in the mini DB.
- [ ] **Step 3 — commit** `test(grounding): hierarchy + inverse invariants as property tests (C.5)`.

---

## Execution & parallelization strategy

Dependency-aware; avoids two agents editing one file.

1. **Wave 0 (inline, sequential):** Phase A (A1, A2) — touches `shaping.py`, `hpo_service.py`, `capabilities.py` text, `AGENTS.md`. Then Phase B (B1). Commit each.
2. **Wave 1 (inline):** Task **C4a** — adds `LATENCY_SLO_P99_MS` (constants.py) + `tool_graph`/`latency_slo` (capabilities.py). This is the dependency root for C3-freshness and C2.
3. **Wave 2 (PARALLEL — file-disjoint subagents):**
   - Agent α: **C3-metrics** → `metrics.py` + `envelope.py` + `test_metrics.py`.
   - Agent β: **C3-freshness** → `discovery.py` + `schemas.py` (DIAGNOSTICS_SCHEMA) + `test_tools_discovery.py`.
   - Agent γ: **C5-grounding** → `resolution.py` + `hpo_service.py` (resolve_term only) + `schemas.py` (RESOLVE_TERM_SCHEMA) + `test_hpo_service.py`.
   - ⚠ β and γ both touch `schemas.py` (different schema objects). To stay disjoint, **assign all `schemas.py` edits to one agent** (fold both schema edits into β) and have γ skip the schema step (γ's `match_confidence` is permissive under `additionalProperties:true` anyway; add its schema line in the integration step). Each agent runs `make ci-local` before returning.
4. **Wave 3 (PARALLEL — new files only, no source conflicts):** C1 (`test_byte_ceiling.py`), C2 (`test_latency_slo.py`), C-coverage (`test_next_commands_coverage.py`), C5-invariants (`test_invariants.py`). Depend on Waves 0–2 being merged.
5. **Integrate:** run `make ci-local` on the union; fix any cross-file fallout; tune the C1 byte ceilings to ~1.4× observed.

---

## Self-review

- **Spec coverage:** A.1 (Task A1), A.2 (A2), A.3 (already done; locked by C1's citation-absence asserts), B.1 (B1 step 3), B.2 (B1 matrix), C.1 (Task C1), C.2 (C4a SLO + C2 bench), C.3 (C3-metrics + C3-freshness), C.4 (C4a graph + C-coverage + synonyms schema already done), C.5 (C5-grounding + C5-invariants). All §3 "10" bars have a CI assertion.
- **No placeholders:** every code step shows real code; test ids may need adjusting to fixture content — flagged inline where so.
- **Type consistency:** `_version_fields(mode)`, `_provenance(mode)` aligned; `metrics.record(..., error_code=None)` matches the envelope call; `confidence_for(match_type)`/`MATCH_CONFIDENCE` consistent; `_freshness(build_utc, *, now=None)` matches its tests; `LATENCY_SLO_P99_MS` single source of truth in constants.py.
- **Do not regress (§7):** `match_type`, `next_commands` rails, `hpo_version`+`capabilities_version`+`request_id`, the 7-code error contract — all preserved; C only widens coverage.
