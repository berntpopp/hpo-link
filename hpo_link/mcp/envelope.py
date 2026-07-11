"""MCP envelope boundary: success/_meta injection and structured errors.

Tools return a plain dict; :func:`run_mcp_tool` injects ``success`` and ``_meta``
on success, and converts any exception into a structured error dict (returned,
never raised) so the LLM sees a typed failure rather than an opaque masked
message.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from hpo_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    WithdrawnEntryError,
)
from hpo_link.mcp import metrics
from hpo_link.mcp.next_commands import cmd, default_error_next_commands, withdrawn_recovery
from hpo_link.mcp.untrusted_content import UntrustedTextLimitError
from hpo_link.services.shaping import DEFAULT_RESPONSE_MODE

logger = logging.getLogger(__name__)

# Per-call _meta carries: tool, request_id, unsafe_for_clinical_use (always present,
# every response_mode, success and error alike -- see the fleet-wide Response-Envelope
# Standard v1 disclaimer decision), plus [next_commands, capabilities_version,
# elapsed_ms] -- those three are tiered by response_mode (see _shape_meta). Static
# provenance (research-use restriction, citation, HPO release) otherwise lives ONLY
# in get_server_capabilities.
_RETRYABLE = {"rate_limited", "upstream_unavailable", "data_unavailable"}

#: Emitted on every ``_meta`` block (success and error, all response_modes) per the
#: fleet-wide Response-Envelope Standard v1 disclaimer decision (2026-07-03).
UNSAFE_FOR_CLINICAL_USE = True


@dataclass
class McpErrorContext:
    """Per-call context so envelopes can name the failing tool and recovery."""

    tool_name: str
    fallback: dict[str, Any] | None = field(default=None)
    arguments: dict[str, Any] = field(default_factory=dict)
    #: The caller's verbosity, used to tier _meta (see :func:`_shape_meta`).
    response_mode: str = DEFAULT_RESPONSE_MODE


class McpToolError(Exception):
    """Raised inside a tool body to emit a specific error code/message."""

    def __init__(self, *, error_code: str, message: str) -> None:
        """Store an error code and client-safe message."""
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _request_id() -> str:
    return uuid.uuid4().hex[:12]


def _capabilities_version() -> str | None:
    """Cached discovery-contract hash for the ``_meta`` echo (never raises)."""
    try:
        from hpo_link.mcp.capabilities import capabilities_version

        return capabilities_version()
    except Exception:  # pragma: no cover - the _meta echo must never break a tool
        return None


def _safe_message(exc: BaseException) -> str:
    return (str(exc) or exc.__class__.__name__)[:280]


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, client_safe_message)`` for an exception."""
    if isinstance(exc, McpToolError):
        return exc.error_code, exc.message
    if isinstance(exc, NotFoundError):  # WithdrawnEntryError subclasses this
        return "not_found", _safe_message(exc)
    if isinstance(exc, AmbiguousQueryError):
        return "ambiguous_query", _safe_message(exc)
    if isinstance(exc, InvalidInputError):
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, DataUnavailableError):
        return "data_unavailable", _safe_message(exc)
    if isinstance(exc, RateLimitError):
        return "rate_limited", "Upstream rate limit hit. Retry shortly."
    if isinstance(exc, ServiceUnavailableError | DownloadError):
        return "upstream_unavailable", "The upstream is temporarily unavailable."
    if isinstance(exc, UntrustedTextLimitError):
        # A v1.1 untrusted-text ceiling was exceeded — an explicit typed limit error,
        # never a generic internal_error (the standard forbids silent omission).
        return "limit_exceeded", _safe_message(exc)
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "input"
        return "invalid_input", f"Invalid input -- `{loc}`: {first['msg']}"
    return "internal_error", "An internal error occurred. The request was not completed."


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Public per-item classifier: ``(error_code, client-safe message)``.

    Batch tools catch typed exceptions per item and need the same taxonomy the
    error envelope applies, without building a whole envelope. Delegates to the
    shared classifier so single-item and batch error shaping never diverge.
    """
    return _classify(exc)


def _recovery_action(error_code: str) -> str:
    if error_code in _RETRYABLE:
        return "retry_backoff"
    if error_code in {"invalid_input", "not_found", "ambiguous_query", "limit_exceeded"}:
        return "reformulate_input"
    return "switch_tool"


def _error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
    error_code, message = _classify(exc)
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "retryable": error_code in _RETRYABLE,
        "recovery_action": _recovery_action(error_code),
        "_meta": {
            "tool": context.tool_name,
            "request_id": _request_id(),
            "unsafe_for_clinical_use": UNSAFE_FOR_CLINICAL_USE,
        },
    }
    if isinstance(exc, InvalidInputError):
        if exc.field is not None:
            envelope["field"] = exc.field
        if exc.allowed is not None:
            envelope["allowed_values"] = exc.allowed
        if exc.hint is not None:
            envelope["hint"] = exc.hint
    if isinstance(exc, AmbiguousQueryError) and exc.candidates:
        envelope["candidates"] = exc.candidates
        envelope["_meta"]["next_commands"] = [
            cmd("get_term", term=c["hpo_id"]) for c in exc.candidates[:3] if c.get("hpo_id")
        ] or [cmd("get_server_capabilities")]
        return envelope
    if isinstance(exc, WithdrawnEntryError):
        envelope["obsolete"] = True
        envelope["withdrawn_status"] = exc.withdrawn_status
        envelope["replaced_by"] = exc.replaced_by
        envelope["_meta"]["next_commands"] = withdrawn_recovery(exc.replaced_by)
        return envelope
    if isinstance(exc, NotFoundError) and exc.suggestions:
        envelope["candidates"] = exc.suggestions
        steps = [cmd("get_term", term=s["hpo_id"]) for s in exc.suggestions[:3] if s.get("hpo_id")]
        query = str(context.arguments.get("term", "") or context.arguments.get("query", ""))
        if query:
            steps.append(cmd("search_terms", query=query))
        envelope["_meta"]["next_commands"] = steps or [cmd("get_server_capabilities")]
        return envelope
    if context.fallback is not None:
        envelope["_meta"]["next_commands"] = [context.fallback]
    else:
        envelope["_meta"]["next_commands"] = default_error_next_commands(
            context.tool_name, error_code, context.arguments
        )
    return envelope


def build_arg_error_envelope(
    *,
    tool_name: str,
    loc: str,
    error_type: str,
    valid_params: list[str],
    signature: str,
    suggestion: str | None,
    constraints: tuple[list[str], str] | None = None,
    response_mode: str = DEFAULT_RESPONSE_MODE,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """Standard invalid-input envelope for an argument-binding failure.

    When ``constraints`` is supplied the failure is an invalid *value* on a known
    argument, so ``allowed_values`` carries the valid range/enum (not the list of
    argument *names*) and the message states the constraint.
    """
    meta: dict[str, Any] = {
        "tool": tool_name,
        "request_id": _request_id(),
        "unsafe_for_clinical_use": UNSAFE_FOR_CLINICAL_USE,
        "next_commands": [cmd("get_server_capabilities")],
        "elapsed_ms": elapsed_ms,
    }
    _stamp_capabilities_version(meta)
    shaped_meta = _shape_meta(meta, response_mode)
    if constraints is not None:
        allowed, human = constraints
        message = f"Invalid value for argument `{loc}` of {tool_name}: {human}."
        return {
            "success": False,
            "error_code": "invalid_input",
            "message": message[:280],
            "retryable": False,
            "recovery_action": "reformulate_input",
            "field": loc,
            "allowed_values": allowed,
            "hint": signature,
            "_meta": shaped_meta,
        }
    if error_type == "missing_argument":
        head = f"Missing required argument `{loc}` for {tool_name}."
    elif error_type == "unexpected_keyword_argument":
        head = f"Unknown argument `{loc}` for {tool_name}."
    else:
        head = f"Invalid value for argument `{loc}` of {tool_name}."
    dym = f" Did you mean `{suggestion}`?" if suggestion else ""
    message = f"{head}{dym} Valid argument names are listed in allowed_values."
    return {
        "success": False,
        "error_code": "invalid_input",
        "message": message[:280],
        "retryable": False,
        "recovery_action": "reformulate_input",
        "field": loc,
        "allowed_values": valid_params,
        "hint": signature,
        "_meta": shaped_meta,
    }


def _stamp_capabilities_version(meta: dict[str, Any]) -> None:
    """Add the cached capabilities_version to a ``_meta`` block when available."""
    version = _capabilities_version()
    if version:
        meta["capabilities_version"] = version


def _shape_meta(meta: dict[str, Any], response_mode: str) -> dict[str, Any]:
    """Tier ``_meta`` verbosity by ``response_mode`` to control the per-call token tax.

    - ``minimal``: the trace essentials only -- ``{tool, request_id,
      unsafe_for_clinical_use}``. The caller explicitly opted out of guidance, so
      ``next_commands`` / ``capabilities_version`` / ``elapsed_ms`` are dropped, but
      the clinical-use disclaimer is never dropped at any response_mode.
    - ``compact`` (default): keep ``next_commands`` (workflow guidance) and
      ``capabilities_version`` (the warm-client cache key the discovery contract leans
      on), but drop the ``elapsed_ms`` observability echo from the hot path -- it is
      still recorded server-side and surfaced by ``get_diagnostics``.
    - ``standard`` / ``full``: the complete ``_meta``, including ``elapsed_ms``.

    The universal ``next_commands`` invariant therefore holds for ``compact`` and
    richer (every default response still chains); ``minimal`` is the documented opt-out.
    ``unsafe_for_clinical_use`` is a universal invariant with no opt-out: it is
    attached uniformly regardless of response_mode (Response-Envelope Standard v1).
    """
    if response_mode == "minimal":
        return {
            "tool": meta["tool"],
            "request_id": meta["request_id"],
            "unsafe_for_clinical_use": meta["unsafe_for_clinical_use"],
        }
    if response_mode in ("standard", "full"):
        return meta
    return {k: v for k, v in meta.items() if k != "elapsed_ms"}


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
) -> dict[str, Any]:
    """Execute a tool body, returning the result dict or a structured error dict."""
    ctx = context or McpErrorContext(tool_name=tool_name)
    start = time.perf_counter()
    try:
        result = await call()
        elapsed = int((time.perf_counter() - start) * 1000)
        if isinstance(result, dict):
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            success = bool(result.setdefault("success", True))
            meta = {
                **existing_meta,
                "tool": tool_name,
                "request_id": _request_id(),
                "unsafe_for_clinical_use": UNSAFE_FOR_CLINICAL_USE,
                "elapsed_ms": elapsed,
            }
            _stamp_capabilities_version(meta)
            result["_meta"] = _shape_meta(meta, ctx.response_mode)
            metrics.record(tool_name, elapsed, ok=success)
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        elapsed = int((time.perf_counter() - start) * 1000)
        envelope = _error_envelope(exc, ctx)
        envelope["_meta"]["elapsed_ms"] = elapsed
        _stamp_capabilities_version(envelope["_meta"])
        envelope["_meta"] = _shape_meta(envelope["_meta"], ctx.response_mode)
        metrics.record(tool_name, elapsed, ok=False, error_code=envelope["error_code"])
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name,
            envelope["error_code"],
            exc.__class__.__name__,
        )
        return envelope
