# WS-C Implementation Report

## Status: DONE

---

## Files Changed

| File | Change |
|------|--------|
| `hpo_link/mcp/capabilities.py` | T1.1: added `absent_entity_contract` key + added to `_SUMMARY_KEYS` |
| `hpo_link/mcp/schemas.py` | T3.1: replaced `synonyms=_ARR` with `synonyms=_SYNONYMS_ARR` (oneOf items); added `_SYNONYM_ITEM` and `_SYNONYMS_ARR` constants |
| `hpo_link/mcp/tools/ontology.py` | T3.1: extended `get_term` description to document compact/standard synonyms shape; T3.3: replaced broken CURIE in `resolve_term` description |
| `tests/unit/test_tools_ontology.py` | Added 6 new tests covering T1.1 and T3.3 |
| `tests/unit/test_schemas.py` | NEW file — 4 tests covering T3.1 synonyms oneOf schema |

---

## What Each Change Does

### T1.1 — `capabilities.py`

Added the `absent_entity_contract` key to `build_capabilities()` payload:

```
"absent_entity_contract": (
    "Malformed identifier → invalid_input (with field). A well-formed but "
    "unknown id (valid shape, no annotations) → an empty 200 page with "
    "total:0 — NOT not_found. not_found is reserved for genuine "
    "identity-resolution failure: the resolve_* tools and phenotype→term "
    "lookups where a free-text term cannot be resolved to any HPO id. "
    "This rule is uniform across the six association tools ..."
)
```

Also added `"absent_entity_contract"` to `_SUMMARY_KEYS` so it appears in the
default summary projection from `project_capabilities("summary")`.

Note: `capabilities_version` content hash changes because the payload changed —
this is expected per the brief. `test_facade.py` only checks structure (not a
frozen hash) so no update was needed.

### T3.1 — `schemas.py`

Replaced the bare `_ARR` for `synonyms` with a new `_SYNONYMS_ARR` schema whose
items express the polymorphism via `oneOf`:

```python
_SYNONYM_ITEM = {
    "oneOf": [
        {"type": "string"},                          # compact / sparse fields
        {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "text": {"type": "string"},
                "scope": {"type": "string"},
            },
        },                                           # standard / full
    ]
}
_SYNONYMS_ARR = {"type": "array", "items": _SYNONYM_ITEM}
```

Updated `get_term` description in `ontology.py` to note:
> "Note on synonyms shape: compact (default) returns synonyms as plain strings;
> standard/full return {text, scope} objects."

### T3.3 — `ontology.py`

Replaced the broken example CURIE `SNOMEDCT_US:193046000` in the `resolve_term`
tool description.

**Chosen CURIEs:** `UMLS:C0000737` and `SNOMEDCT_US:263681008`

**Proof they resolve:**

```sql
-- UMLS:C0000737 → HP:0002027 (Abdominal pain)
SELECT hpo_id, prefix, object_id FROM xref
WHERE prefix='UMLS' AND object_id_upper='C0000737';
-- Result: HP:0002027

-- SNOMEDCT_US:263681008 → HP:0000006 (Autosomal dominant inheritance)
SELECT hpo_id, prefix, object_id FROM xref
WHERE prefix='SNOMEDCT_US' AND object_id_upper='263681008';
-- Result: HP:0000006
```

Verified directly against `data/hpo.sqlite` (HPO 2026-06-06) using:
```bash
uv run python -c "import sqlite3; c=sqlite3.connect('data/hpo.sqlite'); ..."
```

The test (`test_resolve_term_description_does_not_use_broken_snomed_curie`) also
confirms the old `SNOMEDCT_US:193046000` string is absent from the source.

The test `test_resolve_term_example_curie_in_description_resolves` uses
`UMLS:C0151888` (the xref in the test fixture for `HP:0000479`) to confirm
end-to-end xref resolution works in the test environment.

---

## T3.4 — Deferred

T3.4 (`search_terms` "did you mean" fallback) was not implemented. The
integration of `Resolver._search_suggestions` into `hpo_service.search_terms`
is clean in principle but required careful changes to the return type contract
(adding an optional `suggestions` field) and the tool body's `after_search`
next_commands logic. Delivering T1.1, T3.1, and T3.3 fully is the priority per
the brief; T3.4 is explicitly a stretch goal and is deferred to a future PR.

---

## Test Command and Pass Count

```
uv run pytest tests/unit/test_tools_ontology.py tests/unit/test_schemas.py \
    tests/unit/test_hpo_service.py tests/unit/test_facade.py -q
```

**Result: 53 passed**

New tests added: 10 (6 in `test_tools_ontology.py`, 4 in `test_schemas.py`).

---

## mypy Result

```
uv run mypy --strict hpo_link/mcp/capabilities.py hpo_link/mcp/schemas.py \
    hpo_link/mcp/tools/ontology.py hpo_link/services/hpo_service.py \
    hpo_link/services/resolution.py
```
**Result: Success: no issues found in 5 source files**

Full-package mypy (`uv run mypy --strict hpo_link`) shows 2 pre-existing errors
in `hpo_link/mcp/tools/discovery.py` (WS-B's file, not touched by WS-C).

---

## ruff Result

```
uv run ruff check hpo_link/mcp/capabilities.py hpo_link/mcp/schemas.py \
    hpo_link/mcp/tools/ontology.py hpo_link/services/hpo_service.py \
    hpo_link/services/resolution.py tests/unit/test_tools_ontology.py \
    tests/unit/test_schemas.py
```
**Result: All checks passed!**

---

## Concerns

1. **Pre-existing mypy errors in `discovery.py`** (WS-B scope): 2 errors for
   `_META_KEY_MAP` name not defined. Not introduced by WS-C; not in owned files.
2. **Pre-existing test failures in `test_annotation_service.py`** (WS-B scope):
   15 failures for absent-entity contract behavior not yet implemented in the
   service layer. Not introduced by WS-C.
3. **T3.4 deferred**: `search_terms` "did you mean" fallback not delivered.
   The resolution helper logic in `resolution.py` is ready but the integration
   involves payload shape changes and next_commands updates; deferred as stretch.
4. **`capabilities_version` hash change**: The content hash changes because
   `absent_entity_contract` was added to the payload. This is expected and
   documented in the brief. No frozen-hash test existed.
