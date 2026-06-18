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
first start it bootstraps the Mondo index into the data volume (unless one is
already present). Mount a persistent volume at the data directory so the index
survives restarts.

## Configuration

Settings are read from the environment with the `MONDO_LINK_` prefix; nested
data settings use a `__` delimiter (`pydantic-settings`).

### Server

| Variable | Default | Notes |
|----------|---------|-------|
| `MONDO_LINK_HOST` | `127.0.0.1` | Bind host. |
| `MONDO_LINK_PORT` | `8000` | Bind port. |
| `MONDO_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. |
| `MONDO_LINK_MCP_PATH` | `/mcp` | MCP mount path (must start with `/`). |
| `MONDO_LINK_CORS_ORIGINS` | localhost dev origins | JSON list. |
| `MONDO_LINK_LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL`. |
| `MONDO_LINK_LOG_FORMAT` | `console` | `console` \| `json` (logs go to stderr). |

### Data (`MONDO_LINK_DATA__*`)

| Variable | Default | Notes |
|----------|---------|-------|
| `MONDO_LINK_DATA__DATA_DIR` | `<project>/data` | Index + cache directory. |
| `MONDO_LINK_DATA__DB_FILENAME` | `mondo.sqlite` | SQLite filename. |
| `MONDO_LINK_DATA__OBO_URL` | Monarch PURL | `mondo.obo` source. |
| `MONDO_LINK_DATA__SSSOM_URL` | Monarch PURL | `mondo.sssom.tsv` source. |
| `MONDO_LINK_DATA__DOWNLOAD_TIMEOUT` | `300` | Seconds. |
| `MONDO_LINK_DATA__AUTO_BOOTSTRAP` | `true` | Build the index on first use if absent. |
| `MONDO_LINK_DATA__REFRESH_ENABLED` | `false` | In-process periodic refresh. |
| `MONDO_LINK_DATA__REFRESH_INTERVAL_HOURS` | `168` | Refresh cadence (weekly). |
| `MONDO_LINK_DATA__BUILD_LOCK_TIMEOUT` | `900` | Seconds to wait for the build lock. |

## Data refresh

Two options, mutually compatible:

- **In-process:** set `MONDO_LINK_DATA__REFRESH_ENABLED=true`. The server checks
  for a new Mondo release on the configured interval and atomically rebuilds.
- **External cron:** keep refresh disabled and run `make data-refresh`
  (`mondo-link-data refresh`) on a schedule. It conditionally downloads (304 →
  no-op) and rebuilds only when the release changed.

`make data-status` (`mondo-link-data status`) prints the loaded Mondo release
and counts — use it as a readiness/freshness check.

## Health

`GET /health` returns `{"status": "ok", "service": "mondo-link", ...build}`. The
build provenance (version, git SHA) is included for deploy verification.
