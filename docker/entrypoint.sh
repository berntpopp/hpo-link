#!/usr/bin/env bash
# The hpo-data-init sidecar has already materialized the exact digest-verified
# snapshot. The served process only opens that selected database read-only.
set -euo pipefail

exec python server.py \
    --transport "${HPO_LINK_TRANSPORT:-unified}" \
    --host "${HPO_LINK_HOST:-0.0.0.0}" \
    --port "${HPO_LINK_PORT:-8000}"
