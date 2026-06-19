#!/usr/bin/env bash
# Bootstrap the local HPO database before serving so the request path never
# triggers a lazy build. Prefers the prebuilt DB artifact published to GitHub
# Releases (fast, sha256-verified — see hpo_link/ingest/release.py); falls back
# to a local build from the OBO PURLs when offline or no asset matches.
# Day-to-day refresh is owned by host cron (see docs/deployment.md), not the
# in-app scheduler.
set -euo pipefail

echo "[entrypoint] Bootstrapping HPO database (prefers prebuilt GitHub Release artifact)..."
if python -c "from hpo_link.config import settings; from hpo_link.ingest.builder import ensure_database; print('[entrypoint] HPO database ready at', ensure_database(settings))"; then
    :
else
    echo "[entrypoint] WARN: bootstrap failed; the server will lazy-bootstrap on first use."
fi

exec python server.py \
    --transport "${HPO_LINK_TRANSPORT:-unified}" \
    --host "${HPO_LINK_HOST:-0.0.0.0}" \
    --port "${HPO_LINK_PORT:-8000}"
