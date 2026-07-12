---
name: release-readiness
description: Use when preparing to tag, publish, or promote a hpo-link build.
---

# Release Readiness

Follow `AGENTS.md` first.

## Workflow

1. Confirm the worktree holds only intended release changes.
2. Run `make ci-local`; build/validate the container (`make docker-build` plus any `docker-*-config` validation targets the Makefile exposes).
3. Verify **single-source versioning** (../genefoundry-router/docs/VERSIONING-STANDARD-v1.md): the version comes from package metadata and `serverInfo.version` does not leak the framework version; the version guard test passes.
4. Check README / CHANGELOG, MCP safety language, and deployment docs for drift.
5. Confirm any destructive MCP tools remain opt-in and the container overlays stay hardened (../genefoundry-router/docs/CONTAINER-HARDENING-STANDARD-v1.md).
6. Record residual risks before handoff.
