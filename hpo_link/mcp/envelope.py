"""MCP envelope boundary: success/_meta injection and structured errors.

Tools return a plain dict; :func:`run_mcp_tool` injects ``success`` and ``_meta``
on success, and converts any exception into a structured error dict (returned,
never raised) so the LLM sees a typed failure rather than an opaque masked
message.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

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
from hpo_link.mcp.untrusted_content import UntrustedTextLimitError, sanitize_message
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


#: Fixed, server-authored public messages keyed by error_code. A classified exception
#: whose own message is built from the caller's query/identifier or an upstream/DB value
#: (``NotFoundError``, ``AmbiguousQueryError``, ``DataUnavailableError``) is SEVERED to
#: one of these: code-point stripping alone would leave injection prose — and, for the
#: local SQLite path, deployment-layout detail — intact. The raw detail survives only in
#: the chained exception cause (logged by type, never surfaced to the caller).
_PUBLIC_ERROR_MESSAGE: dict[str, str] = {
    "invalid_input": "The request contained an invalid argument; see field.",
    "not_found": "No matching HPO term was found.",
    "ambiguous_query": "The query matched multiple HPO terms; see candidates.",
    "data_unavailable": "The local HPO database is unavailable.",
    "rate_limited": "Upstream rate limit hit. Retry shortly.",
    "upstream_unavailable": "The upstream is temporarily unavailable.",
    "obsolete_term": "The requested HPO term is obsolete; see replaced_by.",
    "internal_error": "An internal error occurred. The request was not completed.",
}

#: A code-point-clean identifier/argument-name token (no whitespace or punctuation that
#: could carry prose). Anything else is redacted rather than echoed.
_SAFE_FIELD_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
_REDACTED_FIELD = "argument"


def _safe_message(exc: BaseException) -> str:
    """Code-point-strip + cap a SERVER-AUTHORED exception message.

    Only for messages whose prose is server-authored (the fixed ``InvalidInputError``
    guidance strings, the ``UntrustedTextLimitError`` ceiling text, an ``McpToolError``
    message). Exceptions whose message interpolates caller/upstream text are severed to a
    fixed ``_PUBLIC_ERROR_MESSAGE`` in :func:`_classify` — sanitize does not remove prose.
    """
    return sanitize_message(str(exc) or exc.__class__.__name__)


def safe_field_name(loc: str, known: frozenset[str] | set[str] | tuple[str, ...] = ()) -> str:
    """Return a code-point-clean, non-prose field label for an error envelope.

    The failing-argument name can be entirely caller-controlled (an unknown keyword
    argument), so it may carry injection prose or forbidden code points. Strip the code
    points; then, when a set of ``known`` parameter names is supplied, echo the name only
    if its (dotted) root is a real parameter, else redact it. With no ``known`` set (a
    tool-body pydantic field name), echo only a plain identifier, else redact.
    """
    clean = sanitize_message(loc)
    root = clean.split(".", 1)[0]
    if known:
        return clean if root in known else _REDACTED_FIELD
    return clean if _SAFE_FIELD_RE.match(clean) else _REDACTED_FIELD


def _scrub(value: Any) -> Any:
    """Recursively strip forbidden code points from every string leaf of an envelope.

    The last-line code-point backstop over the WHOLE error frame — ``message``,
    ``field``, ``allowed_values``, ``hint``, ``candidates``, ``replaced_by``, and
    ``_meta.next_commands`` arguments — layered ON TOP of the fixed-message severing
    above (which removes prose). Guarantees no control/zero-width/bidi/NUL code point
    survives anywhere in the caller-visible error envelope.
    """
    if isinstance(value, str):
        return sanitize_message(value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _scrub_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Apply the recursive code-point backstop to a fully built envelope dict."""
    return cast("dict[str, Any]", _scrub(envelope))


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, client_safe_message)`` for an exception.

    Caller/upstream-derived messages are severed to a fixed public string; only
    server-authored prose (fixed guidance, server-int ceilings) is passed through the
    code-point backstop.
    """
    if isinstance(exc, McpToolError):
        return exc.error_code, _safe_message(exc)
    if isinstance(exc, WithdrawnEntryError):  # subclasses NotFoundError — check first
        return "not_found", _PUBLIC_ERROR_MESSAGE["obsolete_term"]
    if isinstance(exc, NotFoundError):
        return "not_found", _PUBLIC_ERROR_MESSAGE["not_found"]
    if isinstance(exc, AmbiguousQueryError):
        return "ambiguous_query", _PUBLIC_ERROR_MESSAGE["ambiguous_query"]
    if isinstance(exc, InvalidInputError):
        # SEVER: some validators interpolate the rejected identifier (e.g.
        # ``disease_id {value!r} is not a valid CURIE``), so the message can carry caller
        # prose. Return a FIXED public message; the offending argument is named by the
        # server-authored structured ``field`` (and ``allowed_values``/``hint``) instead.
        return "invalid_input", _PUBLIC_ERROR_MESSAGE["invalid_input"]
    if isinstance(exc, DataUnavailableError):
        # SEVER: the message can embed the local SQLite path + a raw sqlite str(exc).
        return "data_unavailable", _PUBLIC_ERROR_MESSAGE["data_unavailable"]
    if isinstance(exc, RateLimitError):
        return "rate_limited", _PUBLIC_ERROR_MESSAGE["rate_limited"]
    if isinstance(exc, ServiceUnavailableError | DownloadError):
        return "upstream_unavailable", _PUBLIC_ERROR_MESSAGE["upstream_unavailable"]
    if isinstance(exc, UntrustedTextLimitError):
        # A v1.1 untrusted-text ceiling was exceeded — a typed limit error whose message
        # carries only server-authored ints (never a generic internal_error).
        return "limit_exceeded", _safe_message(exc)
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "input"
        # Map to a fixed reason keyed on the pydantic error TYPE (a bounded vocabulary,
        # never caller input) and a redacted/sanitized field name; drop the pydantic
        # ``msg`` (it can echo the rejected input value).
        return "invalid_input", f"Invalid input for `{safe_field_name(loc)}`."
    return "internal_error", _PUBLIC_ERROR_MESSAGE["internal_error"]


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
    """Build the flat error envelope, then apply the recursive code-point backstop."""
    return _scrub_envelope(_build_error_envelope(exc, context))


def _build_error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
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

    The offending argument NAME (``loc``) can be entirely caller-controlled (an unknown
    keyword argument), so it is never echoed verbatim: a known parameter name is echoed
    code-point-clean, an unknown one is redacted and ``field`` is omitted. The whole
    envelope passes the recursive code-point backstop before return.
    """
    known = set(valid_params)
    safe_loc = safe_field_name(loc, known)
    loc_known = safe_loc != _REDACTED_FIELD
    safe_suggestion = sanitize_message(suggestion) if suggestion else None
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
        # constraints are only computed for a KNOWN argument (see middleware), so echoing
        # the sanitized name is safe; ``human`` is server-authored from the field schema.
        allowed, human = constraints
        message = f"Invalid value for argument `{safe_loc}` of {tool_name}: {human}."
        return _scrub_envelope(
            {
                "success": False,
                "error_code": "invalid_input",
                "message": message[:280],
                "retryable": False,
                "recovery_action": "reformulate_input",
                "field": safe_loc,
                "allowed_values": allowed,
                "hint": signature,
                "_meta": shaped_meta,
            }
        )
    if error_type in ("missing", "missing_argument"):
        head = (
            f"Missing required argument `{safe_loc}` for {tool_name}."
            if loc_known
            else f"A required argument for {tool_name} is missing."
        )
    elif error_type == "unexpected_keyword_argument":
        # Never echo an unknown, caller-controlled argument name.
        head = f"Unrecognized argument for {tool_name}."
    else:
        head = (
            f"Invalid value for argument `{safe_loc}` of {tool_name}."
            if loc_known
            else f"Invalid argument value for {tool_name}."
        )
    dym = f" Did you mean `{safe_suggestion}`?" if safe_suggestion else ""
    message = f"{head}{dym} Valid argument names are listed in allowed_values."
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": "invalid_input",
        "message": message[:280],
        "retryable": False,
        "recovery_action": "reformulate_input",
        "allowed_values": valid_params,
        "hint": signature,
        "_meta": shaped_meta,
    }
    if loc_known:
        envelope["field"] = safe_loc
    return _scrub_envelope(envelope)


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
