"""Uniform truncation + forward-pagination contract for list-returning tools.

Every list tool returns ``total`` (matches before the cap), ``returned`` (rows in
this payload), ``limit`` (cap applied), ``offset`` (rows skipped), and
``truncated`` (rows remain beyond this page) so an LLM can never mistake a capped
page for a complete list. When ``truncated`` is true, ``next_offset`` carries the
offset for the next page so a client can advance forward WITHOUT re-sending the
rows it already has (cheaper than widening ``limit``, which re-fetches the head).
"""

from __future__ import annotations


def page_fields(*, total: int, returned: int, limit: int, offset: int = 0) -> dict[str, int | bool]:
    """Return the canonical truncation + pagination block.

    ``truncated`` is true when ``offset + returned < total`` (more rows ahead);
    in that case ``next_offset`` is the offset to pass for the following page.
    """
    consumed = offset + returned
    truncated = consumed < total
    block: dict[str, int | bool] = {
        "total": total,
        "returned": returned,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
    }
    if truncated:
        block["next_offset"] = consumed
    return block
