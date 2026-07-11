"""Unit tests for the error-message sanitize primitive (code-point backstop).

``sanitize_message`` strips the fence's forbidden control/zero-width/bidi/NUL code
points and length-caps the result. It is a backstop for server-authored strings; it
does NOT neutralize injection prose (that is handled by fixed-message severing in the
envelope classifier). These tests lock the code-point + length behaviour.
"""

from __future__ import annotations

from hpo_link.mcp.untrusted_content import (
    FORBIDDEN_CODEPOINTS,
    MAX_MESSAGE_CHARS,
    sanitize_message,
)


def test_sanitize_strips_forbidden_codepoints() -> None:
    """NUL, ZWJ, BOM, and RTL-override are removed; ordinary text survives."""
    hostile = "boom\x00zero‍width﻿bidi‮end"
    cleaned = sanitize_message(hostile)
    for bad in ("\x00", "‍", "﻿", "‮"):
        assert bad not in cleaned
    # The ordinary prose between the code points is preserved verbatim.
    assert cleaned == "boomzerowidthbidiend"


def test_sanitize_preserves_ordinary_prose() -> None:
    """A clean server-authored message passes through unchanged."""
    msg = "No matching HPO term was found."
    assert sanitize_message(msg) == msg


def test_sanitize_length_caps_at_max() -> None:
    """Output never exceeds the fleet 280-char message cap."""
    assert MAX_MESSAGE_CHARS == 280
    assert len(sanitize_message("x" * 5000)) == 280


def test_sanitize_covers_the_whole_forbidden_set() -> None:
    """Every code point in the fence's forbidden set is stripped."""
    blob = "".join(chr(cp) for cp in sorted(FORBIDDEN_CODEPOINTS))
    assert sanitize_message(blob) == ""
