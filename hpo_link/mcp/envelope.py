"""MCP envelope boundary: success/_meta injection and structured errors.

Tools return a plain dict; :func:`run_mcp_tool` injects ``success`` and ``_meta``
on success, and converts any exception into a structured error dict (returned,
never raised) so the LLM sees a typed failure rather than an opaque masked
message.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
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
#: The CLOSED error_code enum (Response-Envelope Standard v1, "harmonized with codes
#: already used in the fleet"). Nothing outside this set may reach the wire — a
#: ``McpToolError`` carrying an off-contract code is severed to ``internal`` at
#: classification, because a type annotation is not enforced by the interpreter.
ErrorCode = Literal[
    "invalid_input",
    "not_found",
    "ambiguous_query",
    "upstream_unavailable",
    "rate_limited",
    "internal",
]
_ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "upstream_unavailable",
        "rate_limited",
        "internal",
    }
)
_RETRYABLE = {"rate_limited", "upstream_unavailable"}

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

    def __init__(self, *, error_code: ErrorCode, message: str) -> None:
        """Store an error code (closed enum) and client-safe message."""
        super().__init__(message)
        self.error_code: str = error_code
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
    "rate_limited": "Upstream rate limit hit. Retry shortly.",
    "upstream_unavailable": "The upstream is temporarily unavailable.",
    "internal": "An internal error occurred. The request was not completed.",
}

#: Classified messages reused across the closed enum (not error_code keys). The local
#: SQLite index being unavailable maps to ``upstream_unavailable`` (the closed-enum home
#: for a temporarily-unreachable data source); the obsolete-term message maps to
#: ``not_found`` (an obsolete id resolves to no live term).
_DB_UNAVAILABLE_MESSAGE = "The local HPO database is unavailable."
_OBSOLETE_MESSAGE = "The requested HPO term is obsolete; see replaced_by."

#: A code-point-clean identifier/argument-name token (no whitespace or punctuation that
#: could carry prose). Anything else is redacted rather than echoed.
_SAFE_FIELD_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
_REDACTED_FIELD = "argument"

#: Canonical HP id grammar — the only shape allowed into a caller-visible error field.
_HP_ID_RE = re.compile(r"^HP:\d{7}$")


def _valid_hp_ids(items: Any) -> list[dict[str, str]]:
    """Reduce candidate / suggestion / replacement rows to grammar-validated HP-id identity.

    Structured fields built ONLY from a validated identifier (e.g. the ``next_commands``
    recovery steps): each row is rebuilt as ``{"hpo_id": ...}`` keeping only a canonical
    ``HP:\\d{7}`` id, and any row whose id is free-text or non-conforming is DROPPED.
    """
    out: list[dict[str, str]] = []
    for item in items or []:
        if isinstance(item, dict):
            hid = item.get("hpo_id")
            if isinstance(hid, str) and _HP_ID_RE.match(hid):
                out.append({"hpo_id": hid})
    return out


def _valid_candidates(items: Any) -> list[dict[str, str]]:
    """Rebuild candidate/suggestion rows as grammar-validated ``{hpo_id, name}``.

    Unlike :func:`_valid_hp_ids`, this CARRIES the term ``name``: a candidate label is a
    TRUSTED provenance string from the local HPO index (the same curated source every
    other tool surfaces ``name`` from — search hits, get_term, parents/children), not
    caller- or upstream-derived free text. The audit (issue #28 D2) flagged that dropping
    it forced an agent into N extra ``get_term`` round trips just to read the labels the
    server already holds. The id is still grammar-gated (a non-conforming row is dropped),
    and the ``name`` is code-point-scrubbed via :func:`sanitize_message` here AND again by
    the whole-envelope backstop, so no forbidden code point can ride in on the label.
    """
    out: list[dict[str, str]] = []
    for item in items or []:
        if isinstance(item, dict):
            hid = item.get("hpo_id")
            if isinstance(hid, str) and _HP_ID_RE.match(hid):
                row: dict[str, str] = {"hpo_id": hid}
                name = item.get("name")
                if isinstance(name, str) and name:
                    row["name"] = sanitize_message(name)
                out.append(row)
    return out


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
        # error_code is set inside a tool body; re-check it at RUNTIME and sever anything
        # outside the closed enum to ``internal`` — the ``ErrorCode`` annotation is not
        # enforced by the interpreter, and this is the one branch that echoes its code.
        code = exc.error_code if exc.error_code in _ERROR_CODES else "internal"
        return code, _safe_message(exc)
    if isinstance(exc, WithdrawnEntryError):  # subclasses NotFoundError — check first
        return "not_found", _OBSOLETE_MESSAGE
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
        # SEVER: the message can embed the local SQLite path + a raw sqlite str(exc). The
        # local index being unavailable is a temporarily-unreachable data source →
        # ``upstream_unavailable`` (the closed-enum home; ``data_unavailable`` is not in it).
        return "upstream_unavailable", _DB_UNAVAILABLE_MESSAGE
    if isinstance(exc, RateLimitError):
        return "rate_limited", _PUBLIC_ERROR_MESSAGE["rate_limited"]
    if isinstance(exc, ServiceUnavailableError | DownloadError):
        return "upstream_unavailable", _PUBLIC_ERROR_MESSAGE["upstream_unavailable"]
    if isinstance(exc, UntrustedTextLimitError):
        # A v1.1 untrusted-text ceiling was exceeded — a server-side response-size limit
        # whose message carries only server-authored ints. The closed error_code enum has
        # no bespoke limit code, so it maps to ``internal`` (still an explicit typed error,
        # never silent omission).
        return "internal", _safe_message(exc)
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "input"
        # Map to a fixed reason keyed on the pydantic error TYPE (a bounded vocabulary,
        # never caller input) and a redacted/sanitized field name; drop the pydantic
        # ``msg`` (it can echo the rejected input value).
        return "invalid_input", f"Invalid input for `{safe_field_name(loc)}`."
    return "internal", _PUBLIC_ERROR_MESSAGE["internal"]


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
    if error_code in {"invalid_input", "not_found", "ambiguous_query"}:
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
        # ``field`` is a server-authored parameter name; code-point-strip + identifier-gate
        # it. ``allowed``/``hint`` are server-authored guidance (scrubbed by the backstop).
        if exc.field is not None:
            envelope["field"] = safe_field_name(exc.field)
        if exc.allowed is not None:
            envelope["allowed_values"] = exc.allowed
        if exc.hint is not None:
            envelope["hint"] = exc.hint
    # candidates/suggestions/replaced_by are rebuilt from grammar-validated HP ids AND
    # carry the term ``name`` — a TRUSTED, DB-sourced label (see _valid_candidates), so the
    # agent can disambiguate in one call instead of N extra get_term round trips (issue #28
    # D2). next_commands still chain only to the validated id.
    if isinstance(exc, AmbiguousQueryError) and exc.candidates:
        candidates = _valid_candidates(exc.candidates)
        if candidates:
            envelope["candidates"] = candidates
        envelope["_meta"]["next_commands"] = [
            cmd("get_term", term=c["hpo_id"]) for c in candidates[:3]
        ] or [cmd("get_server_capabilities")]
        return envelope
    if isinstance(exc, WithdrawnEntryError):
        envelope["obsolete"] = True
        replaced_by = _valid_candidates(exc.replaced_by)
        if replaced_by:
            envelope["replaced_by"] = replaced_by
        envelope["_meta"]["next_commands"] = withdrawn_recovery(replaced_by)
        return envelope
    if isinstance(exc, NotFoundError) and exc.suggestions:
        candidates = _valid_candidates(exc.suggestions)
        if candidates:
            envelope["candidates"] = candidates
        steps = [cmd("get_term", term=c["hpo_id"]) for c in candidates[:3]]
        # NOTE: the caller's free-text query is deliberately NOT reflected into a recovery
        # step here (error path) — only validated candidate ids and fixed fallbacks.
        envelope["_meta"]["next_commands"] = steps or [cmd("get_server_capabilities")]
        return envelope
    if context.fallback is not None:
        envelope["_meta"]["next_commands"] = [context.fallback]
    else:
        envelope["_meta"]["next_commands"] = default_error_next_commands(
            context.tool_name, error_code, context.arguments
        )
    return envelope


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


def error_result(envelope: dict[str, Any]) -> ToolResult:
    """Wrap an error envelope so it carries BOTH the structure and MCP's ``isError``.

    Response-Envelope Standard v1: *"isError: true is REQUIRED so clients surface the
    error to the model for self-correction."* A tool that RETURNS a dict can never set it
    (fastmcp builds the ToolResult with ``is_error`` defaulted false), so every error
    envelope this server returned was delivered as a SUCCESSFUL call carrying
    ``success: false`` — a client branching on ``isError``, as the protocol tells it to,
    saw nothing wrong (issue #28 D3, the fleet's most widespread protocol violation).

    Raising instead is NOT the fix: FastMCP's raise path sets ``isError`` but discards
    ``structuredContent``, throwing away the machine-readable envelope (error_code, field,
    allowed_values, candidates, next_commands) the model needs to self-correct. Returning a
    ``ToolResult`` is the only shape that gives us both. The TextContent mirror is kept in
    step with ``structured_content`` so neither caller-visible surface disagrees.
    """
    return ToolResult(
        structured_content=envelope,
        content=[TextContent(type="text", text=json.dumps(envelope))],
        is_error=True,
    )


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
) -> dict[str, Any] | ToolResult:
    """Execute a tool body.

    Returns the result dict on success, or — on failure — a ``ToolResult`` carrying the
    structured error envelope AND ``isError: true`` (never a bare dict, which cannot set
    the protocol flag; never a raise, which would discard the envelope).
    """
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
        # Return a ToolResult (never a bare dict) so the error envelope carries isError:true.
        return error_result(_scrub_envelope(envelope))
