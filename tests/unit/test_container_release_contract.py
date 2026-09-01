"""Contract tests for the container release trigger and target platform."""

from __future__ import annotations

import json
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
