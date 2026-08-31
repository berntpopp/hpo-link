"""Regression tests for the README Standard checker repository identity."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_checker() -> object:
    script = Path(__file__).parents[2] / "scripts" / "check_readme.py"
    spec = importlib.util.spec_from_file_location("check_readme", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_slug_uses_origin_when_worktree_directory_has_a_different_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An isolated worktree keeps the GitHub repository's badge identity."""
    checker = _load_checker()
    worktree = tmp_path / "fleet-security-20260831"
    worktree.mkdir()
    monkeypatch.setattr(checker, "ROOT", worktree)

    class Result:
        stdout = "https://github.com/berntpopp/hpo-link.git\n"

    monkeypatch.setattr(checker.subprocess, "run", lambda *args, **kwargs: Result())

    assert checker.repo_slug() == "hpo-link"
