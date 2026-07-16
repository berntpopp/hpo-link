# Deployment

## Docker

```bash
make docker-build
make docker-up        # starts the stack on a random free host port
make docker-url       # prints the MCP URL + a `claude mcp add` snippet
make docker-logs
make docker-down
```

The container runs the unified server (FastAPI `/health` + MCP `/mcp`). A
separate non-root `hpo-data-init` service first fetches and verifies the exact
HPO release pin into the `hpo-reference` named volume. The application waits
for successful completion, mounts that volume read-only, and serves only
`/data/current/hpo.sqlite`; it never downloads, builds, or refreshes HPO data.

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

## Data promotion

Data freshness is a release-promotion concern, not a runtime setting. Publish
and review a new immutable data artifact, update its tag and digests in the
repository release tuple, release a new application image, and redeploy. The
running application has no bootstrap, prebuilt-URL, or refresh configuration.
For local authoring only, `make data-status` and `make data-refresh` inspect or
rebuild a developer-owned SQLite database.

## Health

`GET /health` returns `{"status": "ok", "service": "hpo-link", ...build}`. The
build provenance (version, git SHA) is included for deploy verification.

After a redeploy, run `make verify-deploy URL=<server>/health` — it fails if the
deployed build's git SHA does not match local `HEAD`.
