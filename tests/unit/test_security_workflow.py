"""Guards for the CodeQL + dependency-review security workflow (F-18).

hpo-link previously shipped no CodeQL / dependency-review coverage. These tests
assert the added ``security.yml`` runs both on pull requests, pins every action
to a commit SHA, keeps least-privilege default permissions, and makes the
dependency review *blocking* at the ``high`` severity threshold.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_SECURITY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "security.yml"
_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$")


def _load() -> dict[str, Any]:
    return yaml.safe_load(_SECURITY.read_text(encoding="utf-8"))


def _triggers(doc: dict[str, Any]) -> Any:
    # PyYAML parses the bare key ``on:`` as the boolean True, not the string "on".
    return doc.get("on", doc.get(True, {}))


def test_security_workflow_exists() -> None:
    assert _SECURITY.is_file(), "security.yml (CodeQL + dependency review) is missing"


def test_codeql_and_dependency_review_jobs_present() -> None:
    jobs = _load()["jobs"]
    assert "codeql" in jobs
    assert "dependency-review" in jobs


def test_runs_on_pull_request() -> None:
    assert "pull_request" in _triggers(_load())


def test_default_permissions_are_least_privilege() -> None:
    assert _load().get("permissions") == {"contents": "read"}


def test_every_action_is_sha_pinned() -> None:
    for job in _load()["jobs"].values():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses is not None:
                assert _SHA_PIN_RE.search(uses), f"action is not SHA-pinned: {uses}"


def test_dependency_review_is_blocking_at_high() -> None:
    """Dependency review must fail the PR (no continue-on-error) on high severity."""
    dep = _load()["jobs"]["dependency-review"]
    saw_action = False
    for step in dep["steps"]:
        assert step.get("continue-on-error") is not True, (
            "dependency review must be blocking (remove continue-on-error)"
        )
        if "dependency-review-action" in str(step.get("uses", "")):
            saw_action = True
            assert step.get("with", {}).get("fail-on-severity") == "high"
    assert saw_action, "dependency-review job must run dependency-review-action"
