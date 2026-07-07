"""Unit tests for the CORS boundary (Fleet Security Remediation Theme C / D4).

hpo-link is unauthenticated and holds no cookies or session, so
``allow_credentials`` is meaningless and a footgun if origins ever widen to
``"*"``. These guards assert credentials stay OFF and that the app refuses to
start with the credentials-plus-wildcard combination, while GET endpoints
(``/health`` and root) keep working.
"""

from __future__ import annotations

import pytest
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from hpo_link.app import _validate_cors, create_app


def _cors_kwargs(app: object) -> dict[str, object]:
    """Return the kwargs the CORSMiddleware was configured with."""
    for mw in app.user_middleware:  # type: ignore[attr-defined]
        if mw.cls is CORSMiddleware:
            return dict(mw.kwargs)
    msg = "CORSMiddleware is not installed on the app"
    raise AssertionError(msg)


def test_cors_credentials_are_disabled() -> None:
    """The backend holds no cookies; credentials must be OFF."""
    kwargs = _cors_kwargs(create_app())
    assert kwargs["allow_credentials"] is False


def test_cors_preserves_method_list() -> None:
    """GET/POST/OPTIONS must stay allowed (root + /health are GET endpoints)."""
    kwargs = _cors_kwargs(create_app())
    assert kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]


def test_health_still_returns_200() -> None:
    """GET /health must still succeed after the CORS change."""
    client = TestClient(create_app(), raise_server_exceptions=True)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_validate_cors_rejects_credentials_with_wildcard() -> None:
    """Startup guard: credentials + wildcard origin must fail closed."""
    with pytest.raises(RuntimeError, match="allow_credentials"):
        _validate_cors(allow_credentials=True, origins=["*"])


def test_validate_cors_allows_credentials_off_with_wildcard() -> None:
    """Credentials off is safe even with a wildcard origin."""
    _validate_cors(allow_credentials=False, origins=["*"])


def test_validate_cors_allows_credentials_on_with_explicit_origins() -> None:
    """Credentials with explicit origins (no wildcard) is permitted."""
    _validate_cors(allow_credentials=True, origins=["http://localhost:3000"])
