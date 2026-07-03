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

GROUND-TRUTH DRIFT (verified by reading ``hpo_link/mcp/envelope.py``, not
assumed): hpo-link's per-call ``_meta`` never carries
``unsafe_for_clinical_use``, on either the success or the error path. The
module's own top-of-file comment states the design intent explicitly: "Per-
call _meta is kept lean: static provenance (research-use restriction,
citation, HPO release) lives ONLY in get_server_capabilities." The research-
use disclaimer is only present as ``research_use_only: True`` in the
``get_server_capabilities`` discovery payload
(``hpo_link/mcp/capabilities.py``), never echoed per-call. The tests below
assert that REAL behavior (the key's absence) instead of fabricating
conformance that is not there; the drift is reported alongside this test in
the PR description as a follow-up candidate.
"""

from __future__ import annotations

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
    # GROUND TRUTH (drift vs. the ratified contract -- see module docstring):
    # the per-call success _meta does NOT carry unsafe_for_clinical_use here.
    assert "unsafe_for_clinical_use" not in result["_meta"]


async def test_single_item_result_key_is_preserved() -> None:
    """The single-item ``result`` (object) payload variant passes through unchanged."""

    async def call() -> dict[str, object]:
        return {"result": {"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}}

    result = await run_mcp_tool("get_term", call)

    assert result["success"] is True
    assert result["result"] == {"hpo_id": "HP:0000118", "name": "Phenotypic abnormality"}
    assert result["_meta"]["tool"] == "get_term"
    assert "unsafe_for_clinical_use" not in result["_meta"]


async def test_error_envelope_is_flat_not_a_bare_exception() -> None:
    """An exception raised through the wrapper becomes a flat in-band envelope.

    Never a bare exception, and never a nested ``error: {code, message, ...}``
    object -- the ratified v1 contract is the flat banner: top-level
    ``error_code``/``retryable``/``recovery_action``, with no ``isError``
    (that is an explicit v2/future concern, out of scope here).
    """

    async def call() -> dict[str, object]:
        raise NotFoundError("HP:9999999 not found in the local HPO index")

    result = await run_mcp_tool(
        "get_term",
        call,
        context=McpErrorContext(tool_name="get_term", arguments={"term": "HP:9999999"}),
    )

    assert result["success"] is False
    assert isinstance(result["error_code"], str) and result["error_code"]
    assert isinstance(result["message"], str) and result["message"]
    assert isinstance(result["retryable"], bool)
    assert isinstance(result["recovery_action"], str) and result["recovery_action"]
    # Flat, not nested: no strict-Rules "error" object anywhere in the payload.
    assert "error" not in result
    assert "isError" not in result
    assert result["_meta"]["tool"] == "get_term"
    # GROUND TRUTH (drift vs. the ratified contract -- see module docstring):
    # the error-path _meta does NOT carry unsafe_for_clinical_use here either.
    assert "unsafe_for_clinical_use" not in result["_meta"]
