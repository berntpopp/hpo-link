"""Guard: pyproject -> installed metadata -> __version__ -> serverInfo -> /health are one value.

Regression guard for two fork bugs that let the advertised version drift:
  * ``FastMCP(...)`` was built without ``version=``, so MCP ``initialize`` leaked
    the FastMCP framework version (e.g. ``3.4.2``) as ``serverInfo.version``.
  * ``hpo_link.__version__`` was a second hardcoded literal that drifted below
    ``pyproject.toml`` (``0.1.0`` vs ``0.1.1``).

``pyproject.toml [project].version`` is now the single source of truth;
``__version__`` is derived from the installed distribution metadata, so a
version bump touches exactly one file.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from starlette.testclient import TestClient

from hpo_link import __version__
from hpo_link.app import create_app
from hpo_link.buildinfo import build_info
from hpo_link.mcp.facade import create_hpo_mcp

DIST = "hpo-link"


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def test_pyproject_is_the_single_source() -> None:
    assert version(DIST) == _pyproject_version()


def test_dunder_version_is_metadata_derived() -> None:
    assert __version__ == version(DIST)
    assert build_info()["version"] == version(DIST)


def test_mcp_server_info_version_matches_package() -> None:
    assert create_hpo_mcp().version == version(DIST)


def test_health_version_matches_package() -> None:
    resp = TestClient(create_app()).get("/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == version(DIST)
