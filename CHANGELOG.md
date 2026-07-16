# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-07-15

MCP contract-hardening (issue #28 — a fleet audit reproduced five confirmed defects
twice each against the live public endpoint; a Codex review of PR #29 found two more live
silent-empty / false-mapping defects). Against the hardened Behaviour Conformance v1 gate
(router `791363c`, which now sees that a grouped payload with no count field is still a
collection), the fixed server is **CONFORMANT — 187 pass / 0 fail / 0 UNGATED /
2 inconclusive**, and `map_cross_ontology` is now actually exercised (no longer skipped).
Tool surface: **8,894t → 5,342t** (outputSchema 39% → 0%), `doc%` stays 100.

### Security

- **Production materializes HPO data in a hardened init sidecar (issue #23).** The sidecar
  downloads one reviewed immutable bundle, verifies its compressed digest, canonical expanded
  tree hash, and database metadata, then atomically selects it. The serving process waits for
  that success, mounts the reference read-only, and has no bootstrap, refresh, egress, or data
  write path.

### Fixed

- **Every error envelope now sets the MCP `isError: true` protocol flag (D3, the fleet's
  most widespread violation).** A returned dict can never set it, so every `success:false`
  envelope was delivered to the model as a *successful* call — a client branching on
  `isError`, as the protocol tells it to, saw nothing wrong. All 32 gate failures were this
  one bug. Fixed at the single envelope-construction chokepoint: `run_mcp_tool` now returns
  `ToolResult(structured_content=envelope, is_error=True)` on the error path (never a bare
  dict; never a `raise`, which would discard the structured envelope), and the three
  argument-binding error builders in the middleware set `is_error=True` too.
- **`search_terms` now ranks an exact primary-label / exact-synonym match on page 1 (D1).**
  BM25 document-length normalisation buried the exact term (e.g. HP:0001250 "Seizure", with
  many synonyms and a long definition) below its shorter, more-specific children; an agent
  taking the top hit annotated a proband with an over-specific/wrong HPO term. Both search
  paths now boost an exact `primary`/`exact_synonym` match above partial ones (relevance
  order preserved within each tier). "Seizure" now ranks #1 of 343.
- **Resolver candidates carry their `name` (D2).** `resolve_term` returned `ambiguous_query`
  / `not_found` candidates as bare HP ids with no label, at every response mode — forcing N
  extra `get_term` round trips to disambiguate. Candidates now carry `{hpo_id, name}`; the
  label is a trusted, DB-sourced provenance string (the same source every other tool
  surfaces `name` from) and is still code-point-scrubbed, so no injection vector is
  reintroduced.
- **`get_diseases_for_gene` now carries `disease_name` (D3/#3).** It returned bare disease
  CURIEs in every mode; the name is now LEFT-JOINed from the HPOA disease table.
- **Malformed `disease_id` / `gene` errors carry `allowed_values` and `hint` (D4/#4),** so
  the model learns what a valid value looks like without a capabilities round trip.
- **`resolve_term`'s obsolete-id documentation now matches its behaviour (D5):** an obsolete
  HP id resolves with `success:true`, `obsolete:true`, and its successor in `replaced_by`
  (the description previously promised `not_found`).
- **`map_cross_ontology` no longer silently zeroes on an unrecognised `prefixes`/`fields`
  value (PR #29 review).** An unknown prefix returned `mappings:{}` with `success:true`
  (a silent-empty), AND the filter uppercased the value while the DB stores mixed-case
  prefixes (`Fyler`, `ICD-10`) — so even a valid `prefixes=['Fyler']` matched nothing. Both
  `prefixes` and `fields` are now validated against the data-derived vocabulary and rejected
  with `invalid_input` (naming the valid values); a known prefix is canonicalised
  case-insensitively to its actual DB case, never uppercased. The same field-projection guard
  applies to `get_term`.
- **`resolve_xref` no longer fabricates a cross-ontology mapping from a foreign namespace
  (PR #29 review).** It matched only the object id and ignored the namespace, so
  `resolve_xref('__NONSENSE__:C0036572')` returned the real `UMLS:C0036572` term. A CURIE is
  now matched *within* its namespace; an unknown namespace is rejected with `invalid_input`,
  and `resolve_term`'s xref-resolution step no longer resolves a foreign-namespace CURIE.

### Changed

- Re-vendored the behaviour conformance gate from genefoundry-router `56db958`
  (`docs/conformance/behaviour.py` blob `c69801687`) so live MCP contract checks
  treat not-found example probes as inconclusive and keep empty auxiliary objects from hiding counted rows.

- **`error_code` is now the closed Response-Envelope v1 enum** (`invalid_input`, `not_found`,
  `ambiguous_query`, `upstream_unavailable`, `rate_limited`, `internal`). `data_unavailable`
  → `upstream_unavailable`, `internal_error` → `internal`, and the untrusted-text ceiling
  breach → `internal`. `McpToolError` is typed to the enum and its code is re-checked at
  runtime (severed to `internal` if off-contract). Capabilities/discovery prose updated to
  match.
- **`outputSchema` is suppressed on every tool** (`output_schema=None`) and
  `FastMCP(dereference_schemas=False)` — the discovery surface drops ~40% with no loss of
  `structuredContent` (every tool returns a dict envelope). `outputSchema` is optional in
  MCP and no model reads it.

### Added

- Vendored the Behaviour Conformance v1 gate (`tests/conformance/behaviour.py` +
  `test_behaviour_v1.py`, byte-identical from router `feat/mcp-contract-hardening-v1` at
  `791363c`) and wired the "Run behaviour probe" step into
  `.github/workflows/conformance.yml`. `tests/conformance/` is exempt from the per-file line
  budget (vendored files must stay byte-identical).

## [0.3.6] - 2026-07-14

### Changed

- **The NPM deployment pulls the released image instead of building from source.**
  `docker/docker-compose.npm.yml` carried `build:`, so a deploy rebuilt the image on the
  server even though CI had already published an attested, digest-addressable image to
  GHCR. It now requires `HPO_LINK_IMAGE` pinned to a digest and fails closed when it is
  unset. Nothing else in the overlay changed: `container_name`, the Compose project name,
  the healthcheck (including the long first-boot `start_period`), networks and volumes are
  all preserved, so the deployed topology and the persisted HPO SQLite database are
  untouched.

## [0.3.5] - 2026-07-13

### Fixed

- **Signed release evidence now states the data contract this service actually declares.**
  The reusable release workflow hardcoded `--contract data-independent` and a fixed
  `data_requirements: {"mode":"none"}`, so every published manifest claimed the image binds
  to no data at all — while `container-release.json` declares `data-bound` /
  `external-reference` against the immutable HPO database bundle (`db-v2026-06-23`,
  `sha256:d677a96efd8c274045241934c33b25dfb6fc9a6414c27bed7ae3334d05d4c9f6`). Because the
  evidence assembler returns early for a data-independent contract, the strongest assertion
  in the chain — that the definition evidence binds to the exact pinned artifact — was
  silently skipped. Re-pinning the container-release standard to
  `86b11f7ed062ed84dfddcbd309e34da88f3dae5b` sources the contract and the exact data
  identity from `container-release.json`, so the manifest states the real binding and the
  assertion runs. The v0.3.4 image and its attestations are sound; only its evidence
  understated the binding, and regenerating that evidence requires this patch re-release.

## [0.3.4] - 2026-07-13

### Fixed

- Re-pin the reusable container CI and container release callers to the
  corrected GeneFoundry router release standard
  (`58d011d9c72efe90337244342fdec703f2b5b4b9`), which repairs seven latent
  defects in the previously pinned revision that prevented the container
  release workflow from completing. Research use only.

## [0.3.3] - 2026-07-13

### Added

- Adopt the GeneFoundry router container-release standard with SHA-pinned
  reusable container CI/release callers, digest-only production image
  configuration, code-only Docker context controls, and complete OCI image
  labels.

## [0.3.2] - 2026-07-11

### Security (defense in depth)

- Guard FastMCP-core not-found reflection: the caller's own requested tool name,
  resource URI, and prompt name can no longer reflect caller-supplied prose (or
  control/zero-width/bidi/NUL code points) into any caller-visible error frame or
  server log. Adds a protocol-handler backstop (unknown-tool return path + unknown
  prompt `prompts/get`, which FastMCP core echoed as `Unknown prompt: '<name>'`) and
  extends the log-scrub filter to the `mcp.shared.session` request-validation records
  (root logger) that echoed a malformed/forbidden resource URI. Caller-visible
  responses were already fixed; this closes the residual prompt-name caller echo and
  the request-validation log leak. Research use only.

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
