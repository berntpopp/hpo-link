# Deployment

## Docker

```bash
make docker-build
make docker-up        # starts the stack on a random free host port
make docker-url       # prints the MCP URL + a `claude mcp add` snippet
make docker-logs
make docker-down
```

The container runs the unified server (FastAPI `/health` + MCP `/mcp`). On
first start it bootstraps the HPO database into the data volume (unless one is
already present). Mount a persistent volume at the data directory so the
database survives restarts.

## Configuration

Settings are read from the environment with the `HPO_LINK_` prefix; nested
data settings use a `__` delimiter (`pydantic-settings`).

### Server

| Variable | Default | Notes |
|----------|---------|-------|
| `HPO_LINK_HOST` | `127.0.0.1` | Bind host. |
| `HPO_LINK_PORT` | `8000` | Bind port. |
| `HPO_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. |
| `HPO_LINK_MCP_PATH` | `/mcp` | MCP mount path (must start with `/`). |
| `HPO_LINK_CORS_ORIGINS` | localhost dev origins | JSON list. |
| `HPO_LINK_LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL`. |
| `HPO_LINK_LOG_FORMAT` | `console` | `console` \| `json` (logs go to stderr). |

### Data (`HPO_LINK_DATA__*`)

| Variable | Default | Notes |
|----------|---------|-------|
| `HPO_LINK_DATA__DATA_DIR` | `<project>/data` | Database + cache directory. |
| `HPO_LINK_DATA__DB_FILENAME` | `hpo.sqlite` | SQLite filename. |
| `HPO_LINK_DATA__ONTOLOGY_EDITION` | `hp.json` | HPO ontology edition to download. |
| `HPO_LINK_DATA__DOWNLOAD_TIMEOUT` | `300` | Seconds. |
| `HPO_LINK_DATA__AUTO_BOOTSTRAP` | `true` | Build the database on first use if absent. |
| `HPO_LINK_DATA__PREFER_PREBUILT` | `true` | Prefer a prebuilt SQLite artifact if available. |
| `HPO_LINK_DATA__PREBUILT_DB_URL` | _(unset)_ | URL of a prebuilt SQLite artifact to download. |
| `HPO_LINK_DATA__REFRESH_ENABLED` | `false` | In-process periodic refresh. |
| `HPO_LINK_DATA__REFRESH_INTERVAL_HOURS` | `168` | Refresh cadence (weekly). |
| `HPO_LINK_DATA__BUILD_LOCK_TIMEOUT` | `900` | Seconds to wait for the build lock. |

## Data refresh

Two options, mutually compatible:

- **In-process:** set `HPO_LINK_DATA__REFRESH_ENABLED=true`. The server checks
  for a new HPO release on the configured interval and atomically rebuilds.
- **External cron:** keep refresh disabled and run `make data-refresh`
  (`hpo-link-data refresh`) on a schedule. It conditionally downloads (304 →
  no-op) and rebuilds only when the release changed.

`make data-status` (`hpo-link-data status`) prints the loaded HPO release
and counts — use it as a readiness/freshness check.

## Health

`GET /health` returns `{"status": "ok", "service": "hpo-link", ...build}`. The
build provenance (version, git SHA) is included for deploy verification.
