"""Contract tests for the container release trigger and target platform."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "container-release.yml"
MANIFEST = ROOT / "container-release.json"


def _workflow() -> dict[str, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_container_release_runs_only_for_strict_semver_tags() -> None:
    """A release must require vMAJOR.MINOR.PATCH, not any v-prefixed tag."""
    triggers = _workflow().get("on", _workflow().get(True, {}))
    assert triggers["push"]["tags"] == ["v*.*.*"]


def test_container_release_manifest_declares_linux_amd64_platform() -> None:
    """The release contract must make its single supported image platform explicit."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["platform"] == "linux/amd64"


def test_release_gate_rejects_tags_outside_central_stable_semver_contract() -> None:
    """Invalid tag pushes must stop before invoking the reusable release workflow."""
    workflow = _workflow()
    gate = workflow["jobs"]["validate-tag"]
    gate_run = gate["steps"][0]["run"]
    stable_ref = re.compile(r"^refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$")

    for tag in ("v1.2", "v1.2.3-rc.1", "v1.2.3+build", "v1.two.3"):
        assert stable_ref.fullmatch(f"refs/tags/{tag}") is None

    assert '"$EVENT_REF"' in gate_run
    assert "refs/tags/v[0-9]+\\.[0-9]+\\.[0-9]+" in gate_run
    assert "exit 1" in gate_run
    assert workflow["jobs"]["container-release"]["needs"] == "validate-tag"
