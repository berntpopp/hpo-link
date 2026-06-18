"""Build/version stamp so a running server can report its own provenance.

Provenance is injected by the Docker image build (``MONDO_LINK_GIT_SHA`` /
``MONDO_LINK_BUILT_AT``). In a source checkout those env vars are absent, so the
git sha is resolved from ``.git`` with a dependency-free reader and ``built_at``
falls back to the package mtime — the server can always say which build answered.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from hpo_link import __version__


def _git_sha_from_dotgit() -> str | None:
    """Resolve the current commit sha by reading ``.git`` (no subprocess)."""
    root = Path(__file__).resolve().parent.parent
    git = root / ".git"
    if not git.exists():
        return None
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head[:12]  # detached HEAD: raw sha
        ref = head[4:].strip()
        loose = git / ref
        if loose.exists():
            return loose.read_text(encoding="utf-8").strip()[:12]
        packed = git / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith(("#", "^")) and line.endswith(ref):
                    return line.split()[0][:12]
        return None
    except OSError:
        return None


def _built_at_fallback() -> str | None:
    """ISO-8601 mtime of the package as a best-effort build timestamp."""
    try:
        mtime = Path(__file__).with_name("__init__.py").stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    except OSError:
        return None


def build_info() -> dict[str, str | None]:
    """Return version + git sha + build time (env-injected, else resolved locally)."""
    return {
        "version": __version__,
        "git_sha": os.environ.get("MONDO_LINK_GIT_SHA") or _git_sha_from_dotgit() or "unknown",
        "built_at": os.environ.get("MONDO_LINK_BUILT_AT") or _built_at_fallback(),
    }
