"""Typed structural fencing for externally sourced prose at the MCP boundary."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

FORBIDDEN_CODEPOINTS = frozenset(
    {
        *range(0x0000, 0x0009),
        *range(0x000B, 0x000D),
        *range(0x000E, 0x0020),
        *range(0x007F, 0x00A0),
        0x200B,
        0x200C,
        0x200D,
        0x2060,
        0xFEFF,
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
    }
)


class UntrustedTextProvenance(BaseModel):
    """Source identity for one fenced external text object."""

    source: str
    record_id: str
    retrieved_at: datetime


class UntrustedText(BaseModel):
    """External prose represented as typed data with digest and provenance."""

    kind: Literal["untrusted_text"] = "untrusted_text"
    text: str
    provenance: UntrustedTextProvenance
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def fence_untrusted_text(raw: str, *, source: str, record_id: str) -> UntrustedText:
    """Normalize external prose and remove only the ratified control characters."""
    normalized = unicodedata.normalize("NFC", raw)
    clean = "".join(char for char in normalized if ord(char) not in FORBIDDEN_CODEPOINTS)
    return UntrustedText(
        text=clean,
        provenance=UntrustedTextProvenance(
            source=source,
            record_id=record_id,
            retrieved_at=datetime.now(UTC),
        ),
        raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


DEFAULT_MAX_TEXT_BYTES = 2_097_152
DEFAULT_MAX_OBJECTS = 128
DEFAULT_MAX_TOTAL_TEXT_BYTES = 8_388_608


class UntrustedTextLimitError(ValueError):
    """A fenced object or response exceeded a Response-Envelope v1.1 ceiling.

    Raised as an explicit, typed execution error — the standard forbids silent
    omission when a limit is exceeded.
    """


def enforce_untrusted_text_limits(
    objects: list[UntrustedText],
    *,
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES,
    max_objects: int = DEFAULT_MAX_OBJECTS,
    max_total_text_bytes: int = DEFAULT_MAX_TOTAL_TEXT_BYTES,
) -> None:
    """Raise UntrustedTextLimitError if the fenced objects exceed any v1.1 ceiling.

    Depth is satisfied structurally: a fenced `text` is a leaf string, so the
    untrusted subtree never nests. Callers pass every UntrustedText they emit in
    one response.
    """
    if len(objects) > max_objects:
        raise UntrustedTextLimitError(
            f"untrusted object count {len(objects)} exceeds ceiling {max_objects}"
        )
    total = 0
    for obj in objects:
        n = len(obj.text.encode("utf-8"))
        if n > max_text_bytes:
            raise UntrustedTextLimitError(
                f"untrusted text {n} bytes exceeds per-object ceiling {max_text_bytes}"
            )
        total += n
    if total > max_total_text_bytes:
        raise UntrustedTextLimitError(
            f"untrusted total {total} bytes exceeds ceiling {max_total_text_bytes}"
        )
