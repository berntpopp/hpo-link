"""next_commands coverage gate (assessment C.4 — Discoverability -> 10).

The single best discoverability feature is the _meta.next_commands rail. This
locks the invariant that EVERY error path — all 7 error codes — still hands the
client a ready-to-call recovery step, so a failure never dead-ends.
"""

from __future__ import annotations

import pytest

from hpo_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool

# (expected_error_code, exception instance) — one per code in the 7-code taxonomy.
CASES = [
    ("invalid_input", InvalidInputError("bad input", field="term")),
    ("not_found", NotFoundError("no such term")),
    ("ambiguous_query", AmbiguousQueryError("ambiguous")),
    ("data_unavailable", DataUnavailableError("index not built")),
    ("rate_limited", RateLimitError("slow down")),
    ("upstream_unavailable", ServiceUnavailableError("upstream down")),
    ("internal_error", RuntimeError("boom")),
]


@pytest.mark.parametrize("expected_code,exc", CASES, ids=[c[0] for c in CASES])
async def test_every_error_code_populates_next_commands(expected_code: str, exc: Exception) -> None:
    """Each of the 7 error codes returns a non-empty _meta.next_commands rail."""

    async def call() -> dict[str, object]:
        raise exc

    result = await run_mcp_tool(
        "resolve_term",
        call,
        context=McpErrorContext("resolve_term", arguments={"query": "kidney cyst"}),
    )
    assert result["success"] is False
    assert result["error_code"] == expected_code
    steps = result["_meta"]["next_commands"]
    assert steps, f"{expected_code} produced no next_commands"
    assert all("tool" in s for s in steps), f"{expected_code} step missing a tool"


async def test_success_path_has_next_commands() -> None:
    """The success path also carries a next_commands rail at compact (default)."""

    async def call() -> dict[str, object]:
        return {"hpo_id": "HP:0000118", "_meta": {"next_commands": [{"tool": "get_term"}]}}

    result = await run_mcp_tool("resolve_term", call, context=McpErrorContext("resolve_term"))
    assert result["success"] is True
    assert result["_meta"]["next_commands"]
