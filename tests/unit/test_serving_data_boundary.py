"""Ensure only the init-sidecar command can materialize HPO reference data."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from hpo_link.ingest.cli import app

ROOT = Path(__file__).resolve().parents[2]


def test_server_start_modules_do_not_bootstrap_or_refresh_data() -> None:
    """Serving paths are unable to start a download, build, or refresh operation."""
    forbidden = (
        "bootstrap_data",
        "start_refresh_scheduler",
        "stop_refresh_scheduler",
        "ensure_database",
        "download_bulk",
        "build_database",
        "materialize_immutable_data",
    )
    for relative in ("hpo_link/app.py", "hpo_link/server_manager.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(name not in source for name in forbidden), relative


def test_materialize_data_is_an_explicit_init_command(monkeypatch: object) -> None:
    """The sidecar invokes a dedicated command rather than the server entrypoint."""
    import hpo_link.immutable_data

    selected = Path("/data/current/hpo.sqlite")
    monkeypatch.setattr(hpo_link.immutable_data, "materialize_immutable_data", lambda _: selected)

    result = CliRunner().invoke(app, ["materialize-data"])

    assert result.exit_code == 0
    assert "Materialized immutable HPO data: hpo.sqlite" in result.stdout
