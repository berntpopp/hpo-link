"""FastMCP middleware that wraps argument-binding failures in the error envelope.

FastMCP validates call arguments with pydantic inside ``FunctionTool.run()`` --
before the registered tool body executes -- so a wrong argument *name*/*type* or a
*missing required* argument raises a ``pydantic.ValidationError`` that never reaches
``run_mcp_tool``'s error boundary. This middleware catches it at ``on_call_tool``
and returns the standard ``invalid_input`` envelope (valid names + a did-you-mean).
It also normalizes curated argument aliases (e.g. ``term`` -> ``query``) before
dispatch and discloses any rewrite under ``_meta.argument_aliases_applied``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    GetPromptRequest,
    ReadResourceRequest,
    ReadResourceRequestParams,
    ServerResult,
    TextContent,
)
from pydantic import ValidationError as PydanticValidationError

from hpo_link.mcp.arg_help import (
    describe_constraints,
    describe_type_expectation,
    did_you_mean,
    normalize_alias_args,
    tool_signature,
)
from hpo_link.mcp.envelope import (
    build_arg_error_envelope,
    build_fixed_error_envelope,
    safe_field_name,
)

#: Fixed, name-free frames for reflection surfaces that bypass the tool error envelope.
_UNKNOWN_TOOL_MESSAGE = "The requested tool is not available. Call get_server_capabilities."
_UNKNOWN_RESOURCE_MESSAGE = "The requested resource is not available."
_UNKNOWN_PROMPT_MESSAGE = "The requested prompt is not available."

logger = logging.getLogger(__name__)


class ArgValidationMiddleware(Middleware):
    """Reshape argument-binding errors into the envelope and apply argument aliases."""

    def __init__(self) -> None:
        """Initialise the per-tool parameter-schema cache."""
        self._schema_cache: dict[str, dict[str, Any]] = {}

    async def _schema(self, context: MiddlewareContext[Any], name: str) -> dict[str, Any]:
        if name not in self._schema_cache:
            fctx = context.fastmcp_context
            if fctx is None:
                raise RuntimeError("no fastmcp context")
            tool = await fctx.fastmcp.get_tool(name)
            self._schema_cache[name] = dict(getattr(tool, "parameters", None) or {})
        return self._schema_cache[name]

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Normalize aliases, then convert binding errors into the envelope."""
        name = context.message.name
        fctx = context.fastmcp_context
        if fctx is not None:
            # Preflight the registry: get_tool returns None for an unknown tool, and the
            # core would then raise "Unknown tool: '<name>'" (echoing the caller-supplied
            # name, bypassing mask_error_details). Return a FIXED, name-free frame instead.
            try:
                tool_obj = await fctx.fastmcp.get_tool(name)
            except Exception:
                tool_obj = None
            if tool_obj is None:
                logger.warning("mcp_unknown_tool")
                return self._fixed_tool_result(_UNKNOWN_TOOL_MESSAGE)
            schema = dict(getattr(tool_obj, "parameters", None) or {})
        else:
            try:
                schema = await self._schema(context, name)
            except Exception:  # no context and no schema: let core handle the call
                return await call_next(context)

        valid = list(schema.get("properties", {}).keys())
        new_args, applied = normalize_alias_args(valid, context.message.arguments or {})
        context.message.arguments = new_args
        start = time.perf_counter()

        try:
            result = await call_next(context)
        except FastMCPValidationError as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            response_mode = str(new_args.get("response_mode", "compact"))
            validation_error = exc.__cause__
            if isinstance(validation_error, PydanticValidationError):
                return self._error_result(
                    name, valid, schema, validation_error, response_mode, elapsed
                )
            # FastMCP's OWN ValidationError without a pydantic cause: still never surface
            # str(exc) — emit a fixed generic invalid_input frame.
            return self._generic_error_result(name, valid, schema, response_mode, elapsed)

        if (
            applied
            and isinstance(result, ToolResult)
            and isinstance(result.structured_content, dict)
        ):
            meta = result.structured_content.setdefault("_meta", {})
            meta["argument_aliases_applied"] = [list(pair) for pair in applied]
        return result

    def _error_result(
        self,
        name: str,
        valid: list[str],
        schema: dict[str, Any],
        exc: PydanticValidationError,
        response_mode: str,
        elapsed_ms: int,
    ) -> ToolResult:
        first = exc.errors(include_url=False)[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "input"
        error_type = str(first.get("type", "value_error"))
        # A real param with a bad *value* -> surface the constraint (enum/range)
        # or, failing that, the expected type + an example -- never the list of
        # argument names (which is reserved for genuinely unknown arguments).
        constraints = None
        if loc in valid and error_type not in ("missing", "missing_argument"):
            field_schema = schema.get("properties", {}).get(loc, {})
            constraints = describe_constraints(field_schema) or describe_type_expectation(
                field_schema
            )
        suggestion = did_you_mean(loc, valid) if loc not in valid else None
        envelope = build_arg_error_envelope(
            tool_name=name,
            loc=loc,
            error_type=error_type,
            valid_params=valid,
            signature=tool_signature(name, schema),
            suggestion=suggestion,
            constraints=constraints,
            response_mode=response_mode,
            elapsed_ms=elapsed_ms,
        )
        # Log a redacted field name only — the raw ``loc`` is caller-controlled and can
        # carry prose / forbidden code points (path-disclosure & log-hygiene invariant).
        logger.warning(
            "mcp_arg_error tool=%s field=%s type=%s",
            name,
            safe_field_name(loc, set(valid)),
            error_type,
        )
        return ToolResult(
            structured_content=envelope,
            content=[TextContent(type="text", text=json.dumps(envelope))],
        )

    def _generic_error_result(
        self,
        name: str,
        valid: list[str],
        schema: dict[str, Any],
        response_mode: str,
        elapsed_ms: int,
    ) -> ToolResult:
        """Fixed invalid_input frame for a validation error with no pydantic detail."""
        envelope = build_arg_error_envelope(
            tool_name=name,
            loc="",
            error_type="invalid_arguments",
            valid_params=valid,
            signature=tool_signature(name, schema),
            suggestion=None,
            response_mode=response_mode,
            elapsed_ms=elapsed_ms,
        )
        logger.warning("mcp_arg_error tool=%s type=invalid_arguments", name)
        return ToolResult(
            structured_content=envelope,
            content=[TextContent(type="text", text=json.dumps(envelope))],
        )

    @staticmethod
    def _fixed_tool_result(message: str) -> ToolResult:
        """A ToolResult carrying a FIXED, caller-echo-free error envelope."""
        envelope = build_fixed_error_envelope(
            error_code="invalid_input", message=message, recovery_action="switch_tool"
        )
        return ToolResult(
            structured_content=envelope,
            content=[TextContent(type="text", text=json.dumps(envelope))],
        )

    async def on_read_resource(
        self,
        context: MiddlewareContext[ReadResourceRequestParams],
        call_next: CallNext[ReadResourceRequestParams, Any],
    ) -> Any:
        """Never echo a caller-supplied resource URI on a failed/unknown read.

        FastMCP's default resource-not-found error embeds the requested URI (which is
        caller-controlled and can carry prose / forbidden code points). Replace any read
        failure with a FIXED, URI-free ``ResourceError``.
        """
        try:
            return await call_next(context)
        except Exception:
            logger.warning("mcp_unknown_resource")
            raise ResourceError(_UNKNOWN_RESOURCE_MESSAGE) from None


# ---------------------------------------------------------------------------
# Layer 3 -- protocol-handler backstop (clinvar pattern)
# ---------------------------------------------------------------------------
# FastMCP's CORE dispatch reflects the caller-controlled component name/URI
# verbatim when it is unknown -- notably ``Unknown prompt: '<name>'`` (raised by
# the low-level prompts/get handler, which mcp turns into ``ErrorData(code=0,
# message=str(exc))``, echoing the name to the caller BEFORE any FastMCP
# middleware can intervene). This wraps the raw ``_mcp_server.request_handlers``
# for CallTool / ReadResource / GetPrompt as the OUTERMOST layer so no requested
# name/URI (nor its code points) can reach the JSON-RPC error frame. All messages
# are fixed server-authored constants.


class _ProtocolError(Exception):
    """A dispatch-level failure re-raised with a FIXED, input-free message."""


def _is_structured_envelope(result: CallToolResult) -> bool:
    """True if an isError CallToolResult carries one of OUR JSON envelopes.

    Distinguishes a structured hpo-link error (already name-free, e.g. the Layer-1
    unknown-tool frame) from a RAW FastMCP dispatch error whose plain text echoes
    the caller-supplied tool name.
    """
    if not result.content:
        return False
    text = getattr(result.content[0], "text", None)
    if not isinstance(text, str):
        return False
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return False
    return isinstance(obj, dict) and "error_code" in obj


def _fixed_tool_not_found_result() -> ServerResult:
    """A fixed, name-free CallToolResult for an unknown/failed tool dispatch."""
    envelope = build_fixed_error_envelope(
        error_code="invalid_input",
        message=_UNKNOWN_TOOL_MESSAGE,
        recovery_action="switch_tool",
    )
    return ServerResult(
        CallToolResult(
            content=[TextContent(type="text", text=json.dumps(envelope))],
            structuredContent=envelope,
            isError=True,
        )
    )


def install_protocol_error_handler(mcp: FastMCP) -> None:
    """Wrap the raw tool/resource/prompt request handlers so a FastMCP-core
    not-found (or read) error can never reflect the caller-supplied name/URI.

    Install AFTER all tools/resources are registered (so the handlers exist) and
    as the OUTERMOST wrapper on ``CallToolRequest``.
    """
    handlers = mcp._mcp_server.request_handlers

    call_tool = handlers.get(CallToolRequest)
    if call_tool is not None:

        async def wrapped_call_tool(
            request: CallToolRequest,
            *,
            _orig: Any = call_tool,
        ) -> ServerResult:
            try:
                result = cast(ServerResult, await _orig(request))
            except Exception:
                # A registered tool never raises here (run_mcp_tool returns an
                # envelope); any exception is a dispatch-level failure whose
                # message would echo the caller name -- mask it.
                logger.warning("mcp_protocol_error kind=tool")
                return _fixed_tool_not_found_result()
            root = getattr(result, "root", None)
            if (
                isinstance(root, CallToolResult)
                and root.isError
                and not _is_structured_envelope(root)
            ):
                # FastMCP RETURNS an isError result echoing "Unknown tool: '<name>'"
                # for the return-path; replace any non-structured isError frame.
                logger.warning("mcp_protocol_error kind=tool")
                return _fixed_tool_not_found_result()
            return result

        handlers[CallToolRequest] = wrapped_call_tool

    for request_type, message, kind in (
        (ReadResourceRequest, _UNKNOWN_RESOURCE_MESSAGE, "resource"),
        (GetPromptRequest, _UNKNOWN_PROMPT_MESSAGE, "prompt"),
    ):
        orig = handlers.get(request_type)
        if orig is None:
            continue

        async def wrapped(
            request: Any,
            *,
            _orig: Any = orig,
            _message: str = message,
            _kind: str = kind,
        ) -> Any:
            try:
                return await _orig(request)
            except Exception as exc:
                # Re-raise with a FIXED, input-free message so no requested
                # name/URI (or its code points) reaches the JSON-RPC error frame.
                # Log the exception CLASS only (never the caller-controlled value).
                logger.warning("mcp_protocol_error kind=%s type=%s", _kind, type(exc).__name__)
                raise _ProtocolError(_message) from None

        handlers[request_type] = wrapped
