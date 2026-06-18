"""Post-deploy guard: fail if the live server's build sha != local HEAD.

The deployed sha is read from a diagnostics-shaped JSON (on stdin or a file). The
operator obtains it from the running server -- the REST ``/health`` endpoint (sha
at the top level) or an MCP ``get_diagnostics`` call (sha under ``build``) -- and
pipes it in. Keeping the fetch out of this script makes the comparison pure and
unit-testable; the I/O shell is a thin ``main``.

This is the recurrence guard for the "stale broken build" class of failure: a
green local tree whose fixes never reached the live container. Wire it as a
deploy step (``make verify-deploy URL=<server>/diagnostics``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

#: buildinfo emits this sentinel when no commit sha can be resolved.
_UNKNOWN_SHA = "unknown"


def extract_git_sha(diagnostics: dict[str, Any]) -> str | None:
    """Return the deployed build git sha from a diagnostics payload, or ``None``.

    Handles both live surfaces: the MCP/REST ``get_diagnostics`` payload nests it
    under ``build.git_sha``, while the REST ``/health`` endpoint carries it at the
    top level. Returns ``None`` for a missing/empty sha and for the ``"unknown"``
    sentinel (which buildinfo emits when it cannot resolve a commit), so an
    unresolved build is treated as *not fresh* rather than spuriously matching.
    """
    build = diagnostics.get("build")
    sha = build.get("git_sha") if isinstance(build, dict) else None
    sha = sha or diagnostics.get("git_sha")  # REST /health shape (top-level)
    if sha and str(sha) != _UNKNOWN_SHA:
        return str(sha)
    return None


def local_head_sha() -> str:
    """Return the local repository's short HEAD sha."""
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git resolved from PATH
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def is_fresh(diagnostics: dict[str, Any], local_sha: str) -> bool:
    """True iff the deployed sha matches the local HEAD (prefix-compatible).

    The two shas may be abbreviated to different widths (e.g. a 7-char deployed
    sha vs a longer local one), so a match is accepted when either is a prefix of
    the other. A missing deployed or local sha is never fresh.
    """
    deployed = extract_git_sha(diagnostics)
    if not deployed or not local_sha:
        return False
    return local_sha.startswith(deployed) or deployed.startswith(local_sha)


def main(argv: list[str]) -> int:
    """Read a diagnostics JSON (stdin or ``argv[1]``) and compare to local HEAD."""
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.read()
    diagnostics = json.loads(raw)
    local = local_head_sha()
    if is_fresh(diagnostics, local):
        print(f"OK: deployed sha matches local HEAD ({local}).")
        return 0
    print(
        f"STALE: deployed sha {extract_git_sha(diagnostics)!r} != local HEAD {local!r}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
