---
name: fastapi-route-change
description: Use when adding, renaming, or modifying this backend's FastAPI routes, dependencies, middleware, or response behavior.
---

# FastAPI Route Change

Follow `AGENTS.md` first.

## Workflow

1. Inspect neighboring route / service modules under `hpo_link/` and follow their structure.
2. Keep route handlers thin; put behavior in the service / manager layer.
3. Use Pydantic models for public request/response shapes; validate identifiers (gene / variant / HGVS / build / accession) before calling upstream.
4. The upstream base URL is a fixed config constant — never construct it from user input (SSRF).
5. Never log full query payloads or identifiers that may be patient-derived (PHI); log correlation id + route + timings only.
6. Don't pair CORS `allow_origins=*` with `allow_credentials=True`.
7. Add / refresh route tests, then run `make ci-local`.
