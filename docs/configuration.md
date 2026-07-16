# Configuration

Settings are read from the environment with the `HPO_LINK_` prefix; nested data
settings use a `__` delimiter (`pydantic-settings`). See [`.env.example`](../.env.example)
for a minimal local file and [`.env.docker.example`](../.env.docker.example) for the
container variant.

## Server

| Variable | Default | Notes |
|----------|---------|-------|
| `HPO_LINK_HOST` | `127.0.0.1` | Bind host. |
| `HPO_LINK_PORT` | `8000` | Bind port. |
| `HPO_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. |
| `HPO_LINK_MCP_PATH` | `/mcp` | MCP mount path (must start with `/`). |
| `HPO_LINK_CORS_ORIGINS` | localhost dev origins | JSON list. |
| `HPO_LINK_LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL`. |
| `HPO_LINK_LOG_FORMAT` | `console` | `console` \| `json` (logs go to stderr). |

`unified` serves FastAPI `/health` plus the MCP endpoint at `/mcp`; `http` is REST
only; `stdio` is the Claude Desktop transport (`mcp_server.py`). `structlog` writes to
**stderr only** — stdout is reserved for the stdio MCP protocol.

## Data (`HPO_LINK_DATA__*`)

| Variable | Default | Notes |
|----------|---------|-------|
| `HPO_LINK_DATA__DATA_DIR` | `<project>/data` | Database + cache directory. |
| `HPO_LINK_DATA__DB_FILENAME` | `hpo.sqlite` | SQLite filename; production sets `current/hpo.sqlite`. |
| `HPO_LINK_DATA__ONTOLOGY_EDITION` | `hp.json` | HPO ontology edition to download. |
| `HPO_LINK_DATA__DOWNLOAD_TIMEOUT` | `300` | Seconds. |
| `HPO_LINK_DATA__AUTO_BOOTSTRAP` | `true` | Local authoring helper only; production sets `false` and never bootstraps in-process. |
| `HPO_LINK_DATA__PREFER_PREBUILT` | `true` | Local authoring helper only; not a production deployment input. |
| `HPO_LINK_DATA__PREBUILT_DB_URL` | _(unset)_ | Local authoring helper only; production uses the reviewed immutable bundle pin. |
| `HPO_LINK_DATA__REFRESH_ENABLED` | `false` | Local authoring helper only; serving paths never schedule refresh. |
| `HPO_LINK_DATA__REFRESH_INTERVAL_HOURS` | `168` | Refresh cadence (weekly). |
| `HPO_LINK_DATA__BUILD_LOCK_TIMEOUT` | `900` | Seconds to wait for the build lock. |

See [Data & provenance](data.md) for what these knobs actually do to the database.

## Immutable deployment data (`HPO_LINK_IMMUTABLE_DATA__*`)

Production Compose supplies these values only to `hpo-data-init`, never to the
request-facing application. They identify one exact HTTPS GitHub Release asset
(`release_tag`, `bundle_url`, compressed digest, canonical expanded-tree digest,
schema/HPO/HPOA identities, and byte ceilings). The sidecar verifies and
atomically selects it under `/data/current`; the app mounts `/data` read-only
and opens `current/hpo.sqlite` with SQLite immutable read semantics. Treat the
reviewed values in `container-release.json` and Compose as one release tuple;
do not substitute `latest` or an unverified URL.

## HTTP boundary (Host / Origin / CORS)

Every HTTP route is gated by **exact** Host and browser-Origin allowlists. Wildcard
patterns are rejected.

| Variable | Default | Notes |
|----------|---------|-------|
| `HPO_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | JSON list of exact `Host` values. |
| `HPO_LINK_ALLOWED_ORIGINS` | `[]` | JSON list; the browser-origin admission gate. |
| `HPO_LINK_CORS_ORIGINS` | localhost dev origins | JSON list; CORS **response** headers. |

- `HPO_LINK_ALLOWED_HOSTS` must carry the exact public reverse-proxy hostname alongside
  the loopback defaults. Production Compose (`docker/docker-compose.prod.yml`,
  `docker/docker-compose.npm.yml`) also permits `hpo-link.genefoundry.org`.
- Write IPv6 entries **bare**, without brackets (`::1`, not `[::1]`).
- Origin *request* admission (`HPO_LINK_ALLOWED_ORIGINS`) is separate from CORS
  *response* headers (`HPO_LINK_CORS_ORIGINS`): include in `ALLOWED_ORIGINS` every
  origin `CORS_ORIGINS` is intended to serve, or the browser request is rejected before
  CORS is ever considered.
- Requests **without** an `Origin` header remain valid — non-browser MCP clients do not
  send one.
