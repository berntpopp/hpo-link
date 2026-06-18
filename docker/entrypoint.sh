#!/usr/bin/env bash
# Build the local Mondo index before serving so the request path never triggers
# a lazy build, then start the server. Refresh is handled by cron (see
# docs/deployment.md), not the in-app scheduler.
set -euo pipefail

echo "[entrypoint] Ensuring the local Mondo index is built/refreshed..."
if hpo-link-data refresh; then
    echo "[entrypoint] Mondo index ready."
else
    echo "[entrypoint] WARN: build/refresh failed; the server will lazy-bootstrap on first use."
fi

exec python server.py \
    --transport "${MONDO_LINK_TRANSPORT:-unified}" \
    --host "${MONDO_LINK_HOST:-0.0.0.0}" \
    --port "${MONDO_LINK_PORT:-8000}"
