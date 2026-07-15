"""Argument-binding error envelopes (used by ArgValidationMiddleware).

Split out of ``envelope.py`` to keep that module within the per-file line budget. These
build the flat ``invalid_input`` envelope for a failure that never reaches a tool body —
a wrong/missing/extra argument caught by FastMCP's pydantic binding, or an unknown tool
name — where the offending token can be caller-controlled and so must never be echoed
verbatim. They reuse the same meta-shaping, code-point backstop, and field-name gating as
the tool error boundary in ``envelope.py``.
"""

from __future__ import annotations

from typing import Any

from hpo_link.mcp.envelope import (
    _REDACTED_FIELD,
    _RETRYABLE,
    UNSAFE_FOR_CLINICAL_USE,
    _request_id,
    _scrub_envelope,
    _shape_meta,
    _stamp_capabilities_version,
    safe_field_name,
)
from hpo_link.mcp.next_commands import cmd
from hpo_link.mcp.untrusted_content import sanitize_message
from hpo_link.services.shaping import DEFAULT_RESPONSE_MODE


def build_fixed_error_envelope(
    *,
    error_code: str,
    message: str,
    recovery_action: str,
    tool: str = "unknown",
    response_mode: str = DEFAULT_RESPONSE_MODE,
) -> dict[str, Any]:
    """A flat error envelope with a FIXED server-authored message and no caller echo.

    Used for failures that never bind to a tool body (an unknown tool name, an unknown
    resource URI) so the caller-supplied name/URI is never reflected. ``tool`` is a fixed
    label, never the caller-supplied value.
    """
    meta: dict[str, Any] = {
        "tool": tool,
        "request_id": _request_id(),
        "unsafe_for_clinical_use": UNSAFE_FOR_CLINICAL_USE,
        "next_commands": [cmd("get_server_capabilities")],
    }
    _stamp_capabilities_version(meta)
    return _scrub_envelope(
        {
            "success": False,
            "error_code": error_code,
            "message": sanitize_message(message),
            "retryable": error_code in _RETRYABLE,
            "recovery_action": recovery_action,
            "_meta": _shape_meta(meta, response_mode),
        }
    )


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
