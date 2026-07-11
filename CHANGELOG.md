# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-07-11

### Security (defense in depth)

- Caller-visible error messages and structured fields are built from fixed/validated
  values (no exception/upstream prose) and sanitized of control/zero-width/bidi/NUL
  code points; the local DB path, decode failures, unknown tool names, and unknown
  resource URIs are no longer echoed or logged raw. Research use only.

## [0.3.0] - 2026-07-11

### Changed (BREAKING)

- **Response-Envelope Standard v1.1 untrusted-content fencing:** every externally
  sourced HPO free-text field now emits a typed `untrusted_text` object (`kind`,
  `text`, `provenance`, `raw_sha256`) instead of a bare string, so hosts can never
  confuse retrieved HPO ontology prose with instructions. Fenced surfaces:
  `get_term` `/definition` and `/comments/*`, and `search_terms`
  `/results/*/definition` and `/results/*/definition_snippet`. Clients reading
  these fields as plain strings (or a `comments` list of strings) must update to
  read `.text`. Defense in depth; research use only, not clinical decision support.

### Added

- `limit_exceeded` error code: exceeding a v1.1 untrusted-object/byte ceiling now
  returns an explicit typed limit error in the envelope (never a silent omission or
  a generic `internal_error`).

## [0.2.0] - 2026-07-10

### Security

- Enforce exact configurable Host and Origin allowlists across every HTTP
  route, with safe loopback defaults, wildcard rejection, explicit production
  proxy hosts, and native FastMCP protection in depth. FastMCP is upgraded to
  3.4.4 while preserving structured argument-validation error envelopes.

### Changed (BREAKING)

- Host and Origin admission is now default-deny outside the configured
  loopback values. Non-loopback and reverse-proxy deployments must list their
  exact public names in `HPO_LINK_ALLOWED_HOSTS` and browser origins, when
  used, in `HPO_LINK_ALLOWED_ORIGINS`.

## [0.1.4] - 2026-07-10

### Security

- Harden HPO source and prebuilt database acquisition with exact-host validated
  redirects, measured configurable bounds, release-bound manifests, strict
  SHA-256 and size verification, bounded decompression, SQLite validation, and
  atomic preservation of the previous database on failure.

## [0.1.3] - 2026-07-07

### Security

- **CORS credentials disabled on the unauthenticated boundary:** `allow_credentials`
  is now `False` (the backend holds no cookies/session), and a startup guard refuses
  to boot with the `allow_credentials=True` + wildcard-origin footgun.
- **No paths/URLs in log values:** the refresh, ingest builder, downloader, and
  service-adapter log events now emit the file basename / a stable identifier only
  (never the absolute filesystem path or the source URL), closing a
  deployment-layout info-leak surface.
- **`git_sha` is `None`, not the literal `"unknown"`, when unresolved:** `/health`
  and the `get_diagnostics` tool now surface a machine-readable null instead of a
  placeholder string when neither the env stamp nor `.git` resolves the commit.
- Adopt the GeneFoundry Container & Deployment Hardening Standard v1: digest-pinned
  base image, `.dockerignore`, read-only rootfs + tmpfs scratch + writable data
  volume, `cap_drop: ALL`, `no-new-privileges`, `init`, mem/cpu/pids limits on the
  base compose, a new expose-only `docker-compose.prod.yml`, and a CI container
  scan + SBOM workflow (Trivy). Also fetch the HPO OBO release over `https://`
  (scheme only; no checksum infra changes).

### Token-efficiency pass

- **Tiered `_meta` by `response_mode` (token tax):** the per-call `_meta` block is
  now sized to the requested verbosity instead of repeating everything on every
  call. `minimal` returns only `{tool, request_id}`; `compact` (default) keeps
  `next_commands` (workflow guidance) and `capabilities_version` (the warm-client
  cache key) but drops the `elapsed_ms` echo; `standard`/`full` add `elapsed_ms`.
  The universal `next_commands` invariant now holds for `compact` and richer;
  `minimal` is the explicit opt-out (still recorded server-side / via diagnostics).
- **Deduped `map_cross_ontology` targets:** multiple rows for the same target id
  (an OBO xref plus an SSSOM mapping, or two predicates) collapse into **one entry
  per `object_id`** carrying the strongest `predicate`/`origin` and a `predicates`
  list (only when >1) — mirroring the `resolve_xref` fix. The wasteful
  `source: null` of OBO xrefs is dropped. Fewer tokens, same information.
- **Cross-reference target labels:** cross-references now carry the target term's
  human-readable `name` when known (from the SSSOM `object_label`, persisted in a
  new `xref.object_label` column; schema v2). So `map_cross_ontology` /
  `get_disease.xrefs` answer "what *is* OMIM:182212" without a follow-up call;
  OBO-only targets simply omit `name`. The repository reads the column tolerantly,
  so an index built before v2 keeps working (label absent, no crash).
- **Value-vs-name errors disambiguated:** a wrong **type** on a known argument (e.g.
  `prefixes="OMIM"` instead of `["OMIM"]`) now reports the expected type with a
  concrete example (`expects an array, e.g. ["OMIM", "ORPHA"]`) and carries the
  shape in `allowed_values` — no longer dumping the list of valid argument *names*
  (which is reserved for genuinely unknown arguments).
- **`error_rate` noise suppressed:** `get_diagnostics.runtime.error_rate` is
  withheld (`null`) until the sample is meaningful (≥20 requests); raw
  `requests`/`errors` counts are always reported. A single early failure no longer
  reads as an alarming ratio.
- **Acronym resolution (verified + locked):** clinical acronyms that live as HPO
  synonyms resolve via the exact-synonym path regardless of case;
  regression coverage now guards the case-insensitive acronym path.

### Added

- **`_meta.unsafe_for_clinical_use` on every tool response:** every `_meta` block
  now carries `unsafe_for_clinical_use: true` — on both the success and the error
  path, at every `response_mode` including `minimal` (a universal invariant with no
  opt-out, unlike `next_commands`/`capabilities_version`/`elapsed_ms`). Purely
  additive to the response envelope: no restructuring, no version bump. Implements
  the fleet-wide Response-Envelope Standard v1 disclaimer decision (2026-07-03).
- **Acronym / fuzzy resolution:** `hpo_resolve_term` now falls back to a
  conservative FTS match (`match_type: "fuzzy"`) for a near-miss or acronym-like
  label with no exact id/xref/label match. It resolves only a clear single winner
  (absolute score floor + dominance over the runner-up); a near-tie returns
  `ambiguous_query` with candidates, and anything weaker returns `not_found` with
  suggestions. `hpo_get_term` stays strict (non-fuzzy) so record retrieval never
  silently guesses.
- **Batch tools:** resolve and get batch variants resolve/fetch up to 50 items in
  one round trip with **partial success** — each item returns its record or its own
  `ok=false`/`error_code`/`message`, and the call never fails wholesale (an
  over-cap call returns a single `invalid_input`).
- **Deploy-freshness guard:** `scripts/check_deployed_freshness.py` plus
  `make verify-deploy URL=<server>/diagnostics` fail a deploy whose live
  `build.git_sha` does not match local HEAD — the recurrence guard against
  shipping a green local tree whose fixes never reached the container.
- Regression coverage for the `ambiguous_query` path (a label shared by two
  distinct HPO terms), end-to-end through the facade envelope.

### Fixed

- **Output-schema leak (P0):** `hpo_get_term.xrefs` and
  `hpo_map_cross_ontology.mappings` are grouped-by-prefix objects but were
  declared as `array` in their `output_schema`, so FastMCP rejected the tool's
  own valid output and surfaced a raw `{...} is not of type 'array'` string
  instead of an envelope. Schemas now declare the grouped-object shape. A new
  `tests/unit/test_output_schemas.py` round-trips every tool's real output (all
  response modes + error cases) through its declared `output_schema`, so this
  class of drift fails CI.
- `hpo_resolve_xref.total` reported only the returned page size (never the full
  match count), so it could silently truncate without setting `truncated`; it now
  uses a true distinct-term count.
- **`hpo_resolve_xref` row/total mismatch:** a term reachable via several mapping
  rows for the same external id was returned once per row, so `returned` could
  exceed the distinct-term `total` and break a client paging off `total`. The
  reverse lookup now collapses to **one row per distinct HP term** (keeping its
  strongest predicate), so `returned <= total` always holds and offset-paging
  advances by whole terms.
- **`get_server_capabilities` missing `_meta.next_commands`:** the discovery root
  omitted `next_commands`, contradicting both the universal `_meta` invariant and
  its own `per_call_meta` contract (which lists `next_commands` as guaranteed). It
  now chains into the canonical `hpo_resolve_term` → record workflow plus a
  `get_diagnostics` freshness check.

### Changed

- **Documented batch cap:** `capabilities.limits` now advertises
  `max_batch_items` (50) alongside the search/closure/xref limits, sourced from a
  single `constants.MAX_BATCH_ITEMS` shared by the batch tools and the discovery
  surface — previously the cap was discoverable only by tripping it.

### Added

- **Forward pagination (P2):** `hpo_search_terms`, `hpo_get_term_ancestors`,
  `hpo_get_term_descendants`, and `hpo_resolve_xref` accept `offset=` and return
  `offset` + `next_offset`; when truncated, `_meta.next_commands` includes a
  ready-to-call forward-page step that advances `offset` without re-sending rows
  (alongside the existing widen step).
- **`capabilities_version` (P2):** a content hash of the discovery contract is
  echoed in every `_meta` (and in `get_server_capabilities`); a warm client diffs
  it to skip re-fetching capabilities while unchanged.
- **Sparse fieldsets (P2):** `hpo_get_term` and `hpo_map_cross_ontology` accept
  `fields=[...]` (top-level keys, or dotted into a group e.g. `xrefs.OMIM`);
  identity anchors are always returned.
- **Runtime metrics (P3):** `get_diagnostics` now returns a `runtime` block with
  request/error counts and latency percentiles (p50/p95/p99) from an in-process
  collector.

### Changed

- **Slimmer `hpo_search_terms` (P1):** compact (default) now returns
  `hp_id + name + score + definition_snippet` (≤140 chars); the full definition
  is reserved for `standard`/`full`, cutting tokens on the broadest-fan-out tool.
- **Answer-embedding `not_found` (P1):** a free-text label miss now attaches the
  closest search hits as `candidates` and chains `_meta.next_commands` straight to
  `hpo_get_term` on the top hit, instead of merely routing back to the search tool.

## [0.1.2] - 2026-07-03

### Fixed

- **MCP `serverInfo.version` advertises the package version, not FastMCP's.** The
  FastMCP facade was constructed without a `version=` argument, so an `initialize`
  handshake reported the FastMCP framework version (e.g. `3.4.2`) as
  `serverInfo.version` instead of the `hpo-link` package version. The facade now
  passes `version=__version__`, matching what `/health` already reports.
- **Single-source versioning.** `hpo_link.__version__` was a second hardcoded
  literal that had drifted below `pyproject.toml` (`0.1.0` vs `0.1.1`). It is now
  derived from the installed distribution metadata
  (`importlib.metadata.version`), so `pyproject.toml [project].version` is the one
  source of truth and `__version__`, the installed metadata, `/health`,
  `get_diagnostics`, and MCP `serverInfo` can no longer disagree. A new
  `tests/unit/test_version_single_source.py` guard locks the invariant.

## [0.1.0] - 2026-06-16

### Added

- Initial release of `hpo-link`, an MCP + REST server grounding phenotype work
  in the Human Phenotype Ontology (HPO).
- **Data plane:** conditional-GET downloader (ETag / Last-Modified) for the
  HPO OBO (`hp.json`) and HPOA (`phenotype.hpoa`) files via OBO PURLs and HPO
  GitHub releases; `fcntl` build lock; HPO JSON + HPOA parser with transitive
  `is_a` closure and top-grouping derivation; atomic SQLite builder
  (temp + `os.replace`) with a `meta` provenance table; `hpo-link-data`
  CLI (`build` / `refresh` / `status`).
- **Database:** terms, labels, synonyms, definitions, `is_a` closure, top
  groupings, and a cross-reference table with provenance and mapping predicate,
  plus HPOA gene↔phenotype and disease↔phenotype annotation tables, plus
  deprecated / `replaced_by` handling.
- **MCP plane:** 17 read-only tools — `get_server_capabilities`,
  `get_diagnostics`, `hpo_resolve_term`, `hpo_search_terms`, `hpo_get_term`,
  `hpo_get_term_ancestors`, `hpo_get_term_descendants`, `hpo_get_term_parents`,
  `hpo_get_term_children`, `hpo_resolve_xref`, `hpo_map_cross_ontology`,
  `hpo_get_phenotypes_for_gene`, `hpo_get_genes_for_phenotype`,
  `hpo_get_phenotypes_for_disease`, `hpo_get_diseases_for_phenotype`,
  `hpo_get_genes_for_disease`, `hpo_get_diseases_for_gene` — each with
  `output_schema`, `READ_ONLY_OPEN_WORLD` annotations, `response_mode`, and
  `_meta.next_commands`. 7-code structured error taxonomy returned via the
  envelope; `hpo://` discovery resources.
- **Server:** FastAPI + uvicorn unified server (`/health` + `/mcp`) and a stdio
  entry point (`mcp_server.py`) for Claude Desktop.
- Docs, Docker, CI workflow (`.github/workflows/ci.yml`), Makefile, and a
  `make ci-local` gate (ruff format/lint, 500-line budget, mypy strict, pytest
  with ≥80% coverage).
