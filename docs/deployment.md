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

Production overlays live in `docker/`: `docker-compose.prod.yml` and
`docker-compose.npm.yml` (Nginx Proxy Manager). Both add
`hpo-link.genefoundry.org` to the Host allowlist — the backend is unauthenticated by
design and must be reachable **only** through the reverse proxy / the GeneFoundry
router, never published directly.

## Configuration

Every environment variable — server, data, and the exact Host/Origin/CORS allowlist
semantics — is documented in [Configuration](configuration.md). The two that most often
bite a first deployment:

- `HPO_LINK_ALLOWED_HOSTS` must include the exact public reverse-proxy hostname
  alongside the loopback defaults; wildcards are rejected.
- `HPO_LINK_ALLOWED_ORIGINS` must include every origin `HPO_LINK_CORS_ORIGINS` is
  intended to serve, or a browser request is rejected before CORS applies.

## Data refresh

Two options, mutually compatible:

- **In-process:** set `HPO_LINK_DATA__REFRESH_ENABLED=true`. The server checks
  for a new HPO release on the configured interval and atomically rebuilds.
- **External cron:** keep refresh disabled and run `make data-refresh`
  (`hpo-link-data refresh`) on a schedule. It conditionally downloads (304 →
  no-op) and rebuilds only when the release changed.

`make data-status` (`hpo-link-data status`) prints the loaded HPO release
and counts — use it as a readiness/freshness check.

To serve a prebuilt database instead of building one, see
[Data & provenance → prebuilt artifact distribution](data.md#prebuilt-artifact-distribution).

## Health

`GET /health` returns `{"status": "ok", "service": "hpo-link", ...build}`. The
build provenance (version, git SHA) is included for deploy verification.

After a redeploy, run `make verify-deploy URL=<server>/health` — it fails if the
deployed build's git SHA does not match local `HEAD`.
