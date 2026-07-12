"""Static-safety guards for the contents-write build-data workflow (F-02).

The ``build-data`` workflow resolves an upstream-controlled release tag and
publishes a GitHub Release with ``contents: write``. These tests are the
regression anchor proving that an attacker-influenceable value can never reach a
privileged shell: no step-output expression is interpolated into ``run:`` script
bodies (the tag must arrive via an ``env:`` mapping), and every third-party
action is pinned to a full commit SHA rather than a floating tag.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_BUILD_DATA = _WORKFLOW_DIR / "build-data.yml"
_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$")
_EXPRESSION_RE = re.compile(r"\$\{\{")


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for job in doc["jobs"].values():
        steps.extend(job.get("steps", []))
    return steps


def test_build_data_workflow_parses() -> None:
    doc = _load(_BUILD_DATA)
    assert doc["jobs"], "build-data must define at least one job"


def test_every_action_is_sha_pinned() -> None:
    """Floating action tags (``@v4``) are mutable supply-chain risk; require SHAs."""
    for step in _steps(_load(_BUILD_DATA)):
        uses = step.get("uses")
        if uses is not None:
            assert _SHA_PIN_RE.search(uses), f"action is not SHA-pinned: {uses}"


def test_no_expression_interpolated_into_run() -> None:
    """No ``${{ ... }}`` may appear inside a ``run:`` body.

    Upstream-derived values (e.g. the release tag) reaching a shell via
    expression interpolation are a command-injection vector; they must be passed
    through an ``env:`` mapping and referenced as a shell variable instead.
    """
    for step in _steps(_load(_BUILD_DATA)):
        run = step.get("run")
        if run is not None:
            assert not _EXPRESSION_RE.search(run), (
                f"run: body interpolates a ${{{{ }}}} expression (injection risk):\n{run}"
            )
            assert "steps.ver.outputs" not in run, (
                "the resolved release tag must reach run: via env:, not step-output interpolation"
            )


def test_release_tag_flows_through_env_mapping() -> None:
    """Any step whose script references ``$DATE`` must declare it under ``env:``."""
    for step in _steps(_load(_BUILD_DATA)):
        run = step.get("run", "")
        if "${DATE}" in run or "$DATE" in run:
            env = step.get("env", {})
            assert "DATE" in env, "step uses $DATE but does not map it under env:"


def test_all_workflows_parse() -> None:
    """Every workflow file (both extensions Actions loads) must be valid YAML."""
    files = (*_WORKFLOW_DIR.glob("*.yml"), *_WORKFLOW_DIR.glob("*.yaml"))
    assert files, "no workflow files found"
    for path in files:
        yaml.safe_load(path.read_text(encoding="utf-8"))
