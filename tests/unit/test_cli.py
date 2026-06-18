"""Tests for hpo_link.ingest.cli."""

from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from hpo_link.ingest.cli import app

runner = CliRunner()


def test_status_no_db(tmp_path: Path) -> None:
    """status exits 1 when no database exists."""
    env = {**os.environ, "HPO_LINK_DATA__DATA_DIR": str(tmp_path)}
    result = runner.invoke(app, ["status"], env=env)
    assert result.exit_code == 1
    assert "No HPO database" in result.output or "hpo.sqlite" in result.output


def test_status_with_db(built_test_db: Path) -> None:
    """status prints hpo_version when a database exists."""
    db_dir = built_test_db.parent
    env = {**os.environ, "HPO_LINK_DATA__DATA_DIR": str(db_dir)}
    result = runner.invoke(app, ["status"], env=env)
    assert result.exit_code == 0
    assert "2026-06-06" in result.output
