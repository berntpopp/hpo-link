#!/usr/bin/env bash
# Build the local HPO database before serving so the request path never triggers
# a lazy build, then start the server. Refresh is handled by cron (see
# docs/deployment.md), not the in-app scheduler.
set -euo pipefail

echo "[entrypoint] Ensuring the local HPO database is built/refreshed..."
if hpo-link-data refresh; then
    echo "[entrypoint] HPO database ready."
else
    echo "[entrypoint] WARN: build/refresh failed; the server will lazy-bootstrap on first use."
fi

exec python server.py \
    --transport "${HPO_LINK_TRANSPORT:-unified}" \
    --host "${HPO_LINK_HOST:-0.0.0.0}" \
    --port "${HPO_LINK_PORT:-8000}"
