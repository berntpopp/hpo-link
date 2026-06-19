# Docker

```bash
make docker-build       # build the image
make docker-up          # start (prints the MCP URL + Claude Code command)
make docker-logs        # follow logs
make docker-down        # stop
```

The entrypoint downloads the HPO ontology and builds the local SQLite database
before the server starts. The database is persisted in the `hpo-data` named
volume across restarts.

## Refresh

The in-app scheduler is **off**; refresh is owned by cron. To refresh the
running stack's data, run the one-shot `refresh` service (under the `tools`
profile) from host cron:

```cron
17 3 * * *  docker compose -f /opt/hpo-link/docker/docker-compose.yml run --rm refresh
```

See [`../docs/deployment.md`](../docs/deployment.md) for crontab / systemd timer
options on bare-metal installs.

## Ports

The host port defaults to `8000`; override with `HPO_LINK_HOST_PORT` (e.g. in
`docker/.env`). MCP endpoint: `http://127.0.0.1:<port>/mcp`. Health:
`http://127.0.0.1:<port>/health`.
