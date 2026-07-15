"""next_commands coverage gate (assessment C.4 — Discoverability -> 10).

The single best discoverability feature is the _meta.next_commands rail. This
locks the invariant that EVERY error path — every code in the closed enum — still
hands the client a ready-to-call recovery step, so a failure never dead-ends.
"""

from __future__ import annotations

import pytest
from fastmcp.tools.tool import ToolResult

from hpo_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool

# (id, expected_error_code, exception) — one row per closed-enum code, plus a second
# exception that also maps onto upstream_unavailable (DataUnavailableError → the local
# index being unavailable) to prove the remap.
CASES = [
    ("invalid_input", "invalid_input", InvalidInputError("bad input", field="term")),
    ("not_found", "not_found", NotFoundError("no such term")),
    ("ambiguous_query", "ambiguous_query", AmbiguousQueryError("ambiguous")),
    ("data_unavailable_remap", "upstream_unavailable", DataUnavailableError("index not built")),
    ("rate_limited", "rate_limited", RateLimitError("slow down")),
    ("upstream_unavailable", "upstream_unavailable", ServiceUnavailableError("upstream down")),
    ("internal", "internal", RuntimeError("boom")),
]


@pytest.mark.parametrize(
    "expected_code,exc", [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES]
)
async def test_every_error_code_populates_next_commands(expected_code: str, exc: Exception) -> None:
    """Each closed-enum error code returns a non-empty _meta.next_commands rail."""

    async def call() -> dict[str, object]:
        raise exc

    result = await run_mcp_tool(
        "resolve_term",
        call,
        context=McpErrorContext("resolve_term", arguments={"query": "kidney cyst"}),
    )
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    env = result.structured_content
    assert isinstance(env, dict)
    assert env["success"] is False
    assert env["error_code"] == expected_code
    steps = env["_meta"]["next_commands"]
    assert steps, f"{expected_code} produced no next_commands"
    assert all("tool" in s for s in steps), f"{expected_code} step missing a tool"


async def test_success_path_has_next_commands() -> None:
    """The success path also carries a next_commands rail at compact (default)."""

    async def call() -> dict[str, object]:
        return {"hpo_id": "HP:0000118", "_meta": {"next_commands": [{"tool": "get_term"}]}}

    result = await run_mcp_tool("resolve_term", call, context=McpErrorContext("resolve_term"))
    assert result["success"] is True
    assert result["_meta"]["next_commands"]
