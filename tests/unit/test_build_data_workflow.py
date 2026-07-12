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


def _resolver_step(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the step that resolves the upstream tag into ``steps.ver.outputs.date``."""
    for step in _steps(doc):
        if step.get("id") == "ver":
            return step
    raise AssertionError("no step with id 'ver' found in build-data workflow")


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
    """Any consuming step whose script references ``$DATE`` must declare it under ``env:``.

    The resolver step (``id: ver``) is exempt: it *defines* ``DATE`` locally from
    the validated resolver output, it does not consume the upstream-derived
    step-output expression, so it needs no ``env:`` mapping.
    """
    for step in _steps(_load(_BUILD_DATA)):
        if step.get("id") == "ver":
            continue
        run = step.get("run", "")
        if "${DATE}" in run or "$DATE" in run:
            env = step.get("env", {})
            assert "DATE" in env, "step uses $DATE but does not map it under env:"


def test_resolver_does_not_swallow_failure_into_echo() -> None:
    """The resolver must not wrap the command substitution inside ``echo "date=$(...)"``.

    Under ``bash -e`` a failing command substitution nested inside a successful
    ``echo`` does NOT fail the step (the echo exits 0), so a hostile/invalid tag
    or a raising validator would silently write an empty ``date=`` to
    ``$GITHUB_OUTPUT`` and the release would publish ``db-v`` / ``hpo-.sqlite.zst``
    (F-02). The resolver's exit code must be observable: assignment first, then
    output on a separate line.
    """
    run = _resolver_step(_load(_BUILD_DATA))["run"]
    assert not re.search(r'echo\s+"date=\$\(', run), (
        "resolver swallows the substitution's exit code inside echo (F-02 bypass); "
        "assign DATE=$(...) on its own line so a non-zero exit fails the step"
    )
    assert re.search(r'^\s*DATE="?\$\(', run, re.MULTILINE), (
        "resolver must assign the resolved tag to DATE=$(...) on its own line"
    )
    assert re.search(r'echo\s+"date=\$DATE"\s*>>\s*"\$GITHUB_OUTPUT"', run), (
        "resolver must echo the already-validated $DATE variable to $GITHUB_OUTPUT"
    )


def test_resolver_has_shell_level_empty_and_grammar_guard() -> None:
    """The resolver run block must fail-closed on an empty or off-grammar DATE.

    Defense in depth: even though ``validate_release_version`` rejects hostile
    tags in Python, the shell must independently refuse to emit an empty or
    non-ISO-date value, and the block must run under ``set -euo pipefail`` so an
    unset variable or a failing command aborts the step.
    """
    run = _resolver_step(_load(_BUILD_DATA))["run"]
    assert "set -euo pipefail" in run, "resolver run block must start with 'set -euo pipefail'"
    assert re.search(r'\[\[\s+"\$DATE"\s+=~\s+\^\[0-9\]\{4\}-\[0-9\]\{2\}-\[0-9\]\{2\}\$', run), (
        "resolver must re-validate $DATE against the strict ISO-date grammar in shell"
    )
    assert "exit 1" in run, "resolver must exit non-zero when $DATE fails the guard"


def test_all_workflows_parse() -> None:
    """Every workflow file (both extensions Actions loads) must be valid YAML."""
    files = (*_WORKFLOW_DIR.glob("*.yml"), *_WORKFLOW_DIR.glob("*.yaml"))
    assert files, "no workflow files found"
    for path in files:
        yaml.safe_load(path.read_text(encoding="utf-8"))
