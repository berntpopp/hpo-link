"""Supply-chain guard: the Docker builder must not bootstrap a floating installer.

The builder previously ran ``pip install --upgrade pip uv``, pulling whatever
uv/pip happened to be newest at build time (unpinned, non-reproducible). Pin uv
by copying it from a digest-pinned image so rebuilds are byte-reproducible.
Research use only; not clinical decision support.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = ROOT / "docker" / "Dockerfile"
_UV_PINNED_COPY = (
    "ghcr.io/astral-sh/uv:0.8.7@sha256:"
    "1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab"
)


def test_dockerfile_pins_uv_and_has_no_floating_pip_upgrade() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert "pip install --upgrade" not in text, "floating pip/uv upgrade must be removed"
    assert _UV_PINNED_COPY in text, "uv must be copied from a digest-pinned image"
