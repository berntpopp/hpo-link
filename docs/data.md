# Data & provenance

`hpo-link` has **no live API**. A local SQLite database, built from the upstream HPO
release, is the only source — so lookups are fast and offline, and every response can
cite an exact release.

## Sources

- **HPO ontology** (`hp.json`) — downloaded from the HPO GitHub releases via the OBO
  PURL `http://purl.obolibrary.org/obo/hp.json`. Contains roughly 19,800 active
  phenotype terms (HPO release `2026-06-06` at the time of writing).
- **HPOA annotations** (`phenotype.hpoa`) — the HPO phenotype-to-disease annotation
  file, linking HPO terms to OMIM / Orphanet / DECIPHER diseases. Gene associations are
  derived from those annotations.

## Building the database

The build is a **mandatory pre-run step**: until it completes there is no data to serve.

```bash
make data           # uv run hpo-link-data build   — download + build
make data-status    # uv run hpo-link-data status  — loaded HPO release + counts
make data-refresh   # uv run hpo-link-data refresh — conditional rebuild (cron entry point)
```

`hpo-link-data status` is the operator's freshness check, distinct from the
`get_diagnostics` tool.

## Local authoring freshness

Downloads use a **conditional GET** (`If-None-Match` / `If-Modified-Since`, cached in
`download_cache.json`); a `304` reuses the local file, so `refresh` is cheap and a
no-op when the upstream release has not changed.

`make data-refresh` is for a reviewed local data-authoring workflow. It is not
a serving-time operation and deployed applications never run an in-process
scheduler or a cron-driven refresh.

## Build integrity

The build is **atomic** (temp file + `os.replace`) and serialised by an `fcntl` build
lock (`.build.lock`), which times out into a `DataUnavailableError`. Provenance — HPO
release version, source validators, counts, build time — is written to a single-row
`meta` table. `get_diagnostics` and `get_server_capabilities` report the loaded release.

See [Architecture → ingest pipeline](architecture.md#ingest-pipeline) for the stage
breakdown and the SQLite schema.

## Production immutable artifact

Production uses the exact `db-v2026-06-23` GitHub Release asset and compressed
SHA-256 declared in `container-release.json`. The non-root `hpo-data-init`
sidecar is the only process allowed to fetch it. It bounds the download,
verifies the committed compressed digest, verifies the canonical expanded-tree
digest and HPO metadata, then atomically selects `/data/current` in the named
reference volume. The request-facing app starts only after that sidecar exits
successfully, mounts the same volume read-only, and opens
`current/hpo.sqlite` in SQLite immutable mode.

Changing data is a reviewed promotion: publish a new immutable data release,
update the release tuple and deployment image, then redeploy. Do not set
`PREBUILT_DB_URL`, `AUTO_BOOTSTRAP`, or a mutable release selector in a running
deployment.

## Licence

**Data:** HPO is distributed under a custom licence for **research and educational use**
— see <https://hpo.jax.org/app/license>. **Attribution is required.** This is not an
open-content licence; it does not grant unrestricted redistribution, and it is distinct
from the MIT licence covering this repository's code.

## Citation

Every response cites the HPO id **and** the HPO release version (`hpo_version`). Cite:

> Köhler S, Gargano M, Matentzoglu N, et al. *The Human Phenotype Ontology in 2021.*
> Nucleic Acids Research 2021;49(D1):D1207–D1217. doi:10.1093/nar/gkaa1043.

For the most recent release, cite instead:

> Gargano MA, Matentzoglu N, Coleman B, et al. *The Human Phenotype Ontology in 2024:
> phenotypes around the world.* Nucleic Acids Research 2024;52(D1):D1333–D1346.
> doi:10.1093/nar/gkad1005.

`hpo_version` is the per-call citation anchor and is echoed on every non-`minimal`
payload. The long-form `recommended_citation` is inlined on `standard` / `full` payloads;
`compact` / `minimal` carry `hpo_version` and defer to `get_server_capabilities`, which
is the canonical source of record per the advertised `provenance_policy`.

Research use only; not for diagnosis, treatment, triage, or patient management.
