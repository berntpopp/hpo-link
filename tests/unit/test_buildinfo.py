"""Tests for build/identity provenance (de-Mondo: the env vars and self-description).

These guard a fork bug: the Dockerfile/compose stamp HPO_LINK_GIT_SHA /
HPO_LINK_BUILT_AT, but buildinfo previously read the sibling stack's
MONDO_LINK_* names, so the provenance feature silently never worked.
"""

from __future__ import annotations

import pathlib

import pytest

from hpo_link import __version__
from hpo_link.buildinfo import build_info

# ---------------------------------------------------------------------------
# build_info() reads the HPO_LINK_* env vars the image actually injects
# ---------------------------------------------------------------------------


def test_build_info_reads_hpo_link_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_info() must honour HPO_LINK_GIT_SHA / HPO_LINK_BUILT_AT (image-injected)."""
    monkeypatch.setenv("HPO_LINK_GIT_SHA", "abc1234")
    monkeypatch.setenv("HPO_LINK_BUILT_AT", "2026-06-20T07:00:00Z")
    info = build_info()
    assert info["git_sha"] == "abc1234"
    assert info["built_at"] == "2026-06-20T07:00:00Z"
    assert info["version"] == __version__


def test_build_info_ignores_legacy_mondo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy MONDO_LINK_* names must NOT be honoured (they are dead)."""
    monkeypatch.delenv("HPO_LINK_GIT_SHA", raising=False)
    monkeypatch.setenv("MONDO_LINK_GIT_SHA", "deadbee")
    info = build_info()
    # falls back to .git resolution / "unknown" — never the legacy env value
    assert info["git_sha"] != "deadbee"


def test_build_info_git_sha_falls_back_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env stamp, git_sha is resolved locally (never None)."""
    monkeypatch.delenv("HPO_LINK_GIT_SHA", raising=False)
    monkeypatch.delenv("MONDO_LINK_GIT_SHA", raising=False)
    info = build_info()
    assert isinstance(info["git_sha"], str) and info["git_sha"]


# ---------------------------------------------------------------------------
# No MONDO_LINK_ env-var name survives anywhere in the shipped source
# ---------------------------------------------------------------------------


def test_no_mondo_link_env_var_leftovers() -> None:
    """No module may reference a MONDO_LINK_* env var (de-Mondo, anti-rot)."""
    root = pathlib.Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    targets = list((root / "hpo_link").rglob("*.py"))
    targets += [root / "server.py", root / "mcp_server.py"]
    for path in targets:
        if path.exists() and "MONDO_LINK" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"MONDO_LINK leftovers (should be HPO_LINK): {offenders}"


# ---------------------------------------------------------------------------
# The server describes itself as an HPO phenotype server, not a Mondo one
# ---------------------------------------------------------------------------


def test_app_description_is_hpo_not_mondo() -> None:
    """The FastAPI app must not describe itself as a Mondo disease server."""
    from hpo_link.app import create_app

    app = create_app()
    assert "Mondo Disease Ontology" not in (app.description or "")
    assert "HPO" in (app.description or "") or "Human Phenotype" in (app.description or "")


def test_package_docstring_is_hpo_not_mondo() -> None:
    """The top-level package docstring must not claim to be a Mondo server."""
    import hpo_link

    assert "Mondo Disease Ontology" not in (hpo_link.__doc__ or "")
