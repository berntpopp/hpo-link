"""Locks the ratified GeneFoundry Response-Envelope Standard v1 contract at
hpo-link's MCP wrapper boundary (``hpo_link.mcp.envelope.run_mcp_tool``).

Adapted from clingen-link (fleet exemplar, PR #20:
https://github.com/berntpopp/clingen-link/pull/20) for this repo's actual
``mcp/envelope.py`` shape. hpo-link has no separate ``mcp/errors.py`` and no
``build_meta`` function: ``run_mcp_tool`` and the flat error-envelope builder
(``_error_envelope``) both live in ``envelope.py``. The success ``_meta`` is
assembled *inline* inside ``run_mcp_tool`` (banner injection, then tiered by
``response_mode`` via ``_shape_meta``) rather than through a standalone
``build_meta(...)`` helper.

The ratified v1 contract is the *flat banner* already shipped by this and the
other already-conformant ``-link`` backends (see
``docs/RESPONSE-ENVELOPE-STANDARD-v1.md`` in the router repo -- its header
note states the strict nested ``error:{}``/``isError`` body is a non-normative
"v2 future", and the current router-compatible contract is the flat shape
below):

  - SUCCESS: ``{"success": True, <payload: "results":[...] or "result":{...}>,
    "_meta": {..., "unsafe_for_clinical_use": True}}``.
  - FAILURE: a FLAT in-band envelope ``{"success": False, "error_code",
    "message", "retryable", "recovery_action", "_meta": {"tool": ...,
    "unsafe_for_clinical_use": True}}`` -- never a bare exception, never a
    nested ``error: {}`` object. ``isError: true`` is an explicit v2/future
    concern and is intentionally NOT asserted here.

FLEET DISCLAIMER STANDARDIZATION (2026-07-03, verified by reading
``hpo_link/mcp/envelope.py``): hpo-link's per-call ``_meta`` now carries
``unsafe_for_clinical_use: True`` on BOTH the success and the error path, at
every ``response_mode`` including ``minimal`` -- the key is a universal
invariant with no opt-out (see ``_shape_meta`` in ``envelope.py``). This is
purely additive to the response envelope described above; the research-use
notice/citation/HPO-release provenance triad remains declared once in the
``get_server_capabilities`` discovery payload
(``hpo_link/mcp/capabilities.py``) and is not duplicated per-call.
"""

from __future__ import annotations

from fastmcp.tools.tool import ToolResult

from hpo_link.exceptions import NotFoundError
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool


async def test_success_envelope_matches_response_envelope_standard_v1() -> None:
    """A dict-returning tool body is banner-wrapped: success + payload + _meta.

    Uses the fleet-canon ``results`` payload key (array of records); the
    wrapper is payload-shape-agnostic, and the single-item ``result`` (object)
    variant is covered separately below.
    """

    async def call() -> dict[str, object]:
        return {"results": [{"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}]}

    result = await run_mcp_tool("search_terms", call)

    assert result["success"] is True
    assert result["results"] == [{"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}]
    assert result["_meta"]["tool"] == "search_terms"
    assert isinstance(result["_meta"]["request_id"], str) and result["_meta"]["request_id"]
    # Fleet disclaimer standardization (2026-07-03): every success _meta carries
    # unsafe_for_clinical_use, regardless of response_mode.
    assert result["_meta"]["unsafe_for_clinical_use"] is True


async def test_single_item_result_key_is_preserved() -> None:
    """The single-item ``result`` (object) payload variant passes through unchanged."""

    async def call() -> dict[str, object]:
        return {"result": {"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}}

    result = await run_mcp_tool("get_term", call)

    assert result["success"] is True
    assert result["result"] == {"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}
    assert result["_meta"]["tool"] == "get_term"
    assert result["_meta"]["unsafe_for_clinical_use"] is True


async def test_error_envelope_is_flat_and_carries_iserror() -> None:
    """An exception raised through the wrapper becomes a ToolResult(is_error=True).

    The FLAT envelope (top-level ``error_code``/``retryable``/``recovery_action``, no
    nested ``error: {}`` object) is preserved as ``structured_content``, AND the MCP
    protocol ``isError`` flag is set (issue #28 D3): the two used to disagree — the
    envelope said ``success: false`` while the wire said the call succeeded. The failure
    is now a ``ToolResult``, never a bare dict (a dict cannot set ``isError``).
    """

    async def call() -> dict[str, object]:
        raise NotFoundError("HP:9999999 not found in the local HPO index")

    result = await run_mcp_tool(
        "get_term",
        call,
        context=McpErrorContext(tool_name="get_term", arguments={"term": "HP:9999999"}),
    )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    env = result.structured_content
    assert isinstance(env, dict)
    assert env["success"] is False
    assert isinstance(env["error_code"], str) and env["error_code"]
    assert isinstance(env["message"], str) and env["message"]
    assert isinstance(env["retryable"], bool)
    assert isinstance(env["recovery_action"], str) and env["recovery_action"]
    # Flat, not nested: no strict-Rules "error" object anywhere in the envelope.
    assert "error" not in env
    assert env["_meta"]["tool"] == "get_term"
    # Fleet disclaimer standardization (2026-07-03): every error _meta carries
    # unsafe_for_clinical_use too, not just the success path.
    assert env["_meta"]["unsafe_for_clinical_use"] is True


async def test_minimal_response_mode_still_carries_unsafe_for_clinical_use() -> None:
    """``response_mode="minimal"`` strips ``next_commands``/``capabilities_version``/
    ``elapsed_ms``, but ``unsafe_for_clinical_use`` is a universal invariant with no
    opt-out -- it must survive on both the success and the error path.
    """

    async def ok_call() -> dict[str, object]:
        return {"result": {"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}}

    ok_result = await run_mcp_tool(
        "get_term",
        ok_call,
        context=McpErrorContext(tool_name="get_term", response_mode="minimal"),
    )
    assert ok_result["_meta"]["unsafe_for_clinical_use"] is True
    assert "next_commands" not in ok_result["_meta"]

    async def err_call() -> dict[str, object]:
        raise NotFoundError("HP:9999999 not found in the local HPO index")

    err_result = await run_mcp_tool(
        "get_term",
        err_call,
        context=McpErrorContext(
            tool_name="get_term", arguments={"term": "HP:9999999"}, response_mode="minimal"
        ),
    )
    assert isinstance(err_result, ToolResult)
    assert err_result.is_error is True
    err_env = err_result.structured_content
    assert isinstance(err_env, dict)
    assert err_env["_meta"]["unsafe_for_clinical_use"] is True
    assert "next_commands" not in err_env["_meta"]
