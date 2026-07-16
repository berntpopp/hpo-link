# Docker

```bash
make docker-build       # build the image
make docker-up          # start (prints the MCP URL + Claude Code command)
make docker-logs        # follow logs
make docker-down        # stop
```

`hpo-data-init` is a hardened one-shot writer. It verifies the exact immutable
HPO release into the `hpo-reference` named volume, then exits. `hpo-link`
waits for that success condition and mounts the volume read-only; its default
command only serves HTTP/MCP. Promote data through a reviewed release-pin
change and redeploy — never by scheduling a refresh inside the running stack.

See [`../docs/deployment.md`](../docs/deployment.md) for the deployment contract.

## Ports

The host port defaults to `8000`; override with `HPO_LINK_HOST_PORT` (e.g. in
`docker/.env`). MCP endpoint: `http://127.0.0.1:<port>/mcp`. Health:
`http://127.0.0.1:<port>/health`.
