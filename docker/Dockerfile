# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for hpo-link.

# Base image pinned by digest (manifest-list) for byte-reproducible rebuilds —
# Container & Deployment Hardening Standard v1, rule 2. Bump via Renovate/Dependabot.
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

# Pin uv by digest for byte-reproducible builds instead of bootstrapping a
# floating pip-based uv upgrade — Container & Deployment Hardening Standard v1.
# Bump the tag+digest together via Renovate/Dependabot.
COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab /uv /usr/local/bin/uv

RUN uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS prepared


# Release identity is supplied by the central container-release workflow.
ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="HPO Link" \
      org.opencontainers.image.description="MCP/API server for Human Phenotype Ontology research data" \
      org.opencontainers.image.source="https://github.com/berntpopp/hpo-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/hpo-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/hpo-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry"
ENV VCS_REF="${VCS_REF}" \
    HPO_LINK_GIT_SHA="${VCS_REF}" \
    HPO_LINK_BUILT_AT="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    HPO_LINK_HOST=0.0.0.0 \
    HPO_LINK_PORT=8000 \
    HPO_LINK_TRANSPORT=unified \
    HPO_LINK_MCP_PATH=/mcp \
    HPO_LINK_DATA__DATA_DIR=/data \
    # The entrypoint builds the index before the server starts. Refresh is owned
    # by cron (see docs/deployment.md), so the in-app scheduler stays OFF.
    HPO_LINK_DATA__AUTO_BOOTSTRAP=true \
    HPO_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /data && \
    chown -R app:app /data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./hpo_link ./hpo_link
COPY --chown=app:app ./server.py ./mcp_server.py ./pyproject.toml ./README.md ./
COPY --chown=app:app ./docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN /opt/venv/bin/pip install . --no-deps && chmod +x /usr/local/bin/entrypoint.sh

RUN rm -rf /root/.cache/pip \
           /usr/local/lib/python*/ensurepip \
           /usr/local/lib/python*/site-packages/pip \
           /usr/local/lib/python*/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.* \
    && find / -xdev -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find / -xdev -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
RUN find / -xdev -perm /6000 -exec chmod a-s '{}' + \
    && test -z "$(find / -xdev -perm /6000 -print -quit)"
RUN actual="$(find / -xdev -type f -links +1 -printf '%i %p\n' | sort -k2,2)" \
    && expected="$(printf '%s %s\n%s %s\n' \
         "$(stat -c '%i' /usr/bin/perl)" /usr/bin/perl \
         "$(stat -c '%i' /usr/bin/perl5.40.1)" /usr/bin/perl5.40.1 | sort -k2,2)" \
    && { test "$actual" = "$expected" || { printf 'unexpected hardlinks:\n%s\n' "$actual"; exit 1; }; } \
    && rm -f /usr/bin/perl5.40.1

FROM scratch AS production
COPY --from=prepared / /

ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="HPO Link" \
      org.opencontainers.image.description="MCP/API server for Human Phenotype Ontology research data" \
      org.opencontainers.image.source="https://github.com/berntpopp/hpo-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/hpo-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/hpo-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry"
ENV VCS_REF="${VCS_REF}" \
    HPO_LINK_GIT_SHA="${VCS_REF}" \
    HPO_LINK_BUILT_AT="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    HPO_LINK_HOST=0.0.0.0 \
    HPO_LINK_PORT=8000 \
    HPO_LINK_TRANSPORT=unified \
    HPO_LINK_MCP_PATH=/mcp \
    HPO_LINK_DATA__DATA_DIR=/data \
    # The entrypoint builds the index before the server starts. Refresh is owned
    # by cron (see docs/deployment.md), so the in-app scheduler stays OFF.
    HPO_LINK_DATA__AUTO_BOOTSTRAP=true \
    HPO_LINK_DATA__REFRESH_ENABLED=false \
    TMPDIR=/tmp
WORKDIR /home/app/web

USER app

EXPOSE 8000

# The built SQLite index lives under HPO_LINK_DATA__DATA_DIR (/data).
# Mount a volume there so the index persists across container restarts.
VOLUME ["/data"]

# start-period covers the entrypoint's first build (download + build).
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
