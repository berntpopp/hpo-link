"""Logging filter that keeps external-framework error detail out of the log sink.

FastMCP logs the full pydantic ``ValidationError`` — which echoes caller-supplied
argument values (``loc``/``input``) and can carry forbidden code points — around
argument binding, *before* the router's :class:`ArgValidationMiddleware` reshapes the
caller-facing frame (see ``fastmcp.server.server``:
``logger.warning("Invalid arguments for tool %r: %s", name, e.errors())``).

``mask_error_details=True`` masks the tool *response*, not this *log* record. This
filter strips the caller-derived detail (``args`` / ``exc_info`` / ``exc_text``) from
FastMCP/MCP framework records at WARNING and above, keeping only the stable
server-authored message template, so raw caller input never lands in a log sink
(the fleet PII / log-hygiene invariant).
"""

from __future__ import annotations

import logging

#: Framework logger-name prefixes whose error records may echo caller input.
_SCRUBBED_LOGGERS = ("fastmcp", "mcp")

#: ``mcp.shared.session`` logs request/notification VALIDATION failures via the ROOT
#: logger (bare ``logging.warning``/``logging.debug``, no module logger) with the
#: offending, caller-controlled URI/params ALREADY f-string-interpolated into the
#: message itself (not in ``args``) — so clearing ``args`` is insufficient and the
#: whole message must be replaced. A malformed / forbidden-code-point resource URI
#: (which pydantic ``AnyUrl`` rejects during request deserialization, BEFORE any
#: request handler runs) reflects here; the caller-visible JSON-RPC frame is already
#: fixed ("Invalid request parameters") but this log record is not.
_SESSION_VALIDATION_PREFIXES = (
    "Failed to validate request",
    "Failed to validate notification",
    "Message that failed validation",
)
_SESSION_VALIDATION_REPLACEMENT = "mcp request/notification failed validation (details omitted)"


class ExternalErrorDetailFilter(logging.Filter):
    """Drop caller-derived detail from FastMCP/MCP framework error log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Scrub caller input from framework/session error records (in place)."""
        msg = record.msg if isinstance(record.msg, str) else ""
        # mcp.shared.session records bake the caller URI/params into the message via
        # an f-string, so replace the whole message (any logger, any level).
        if msg.startswith(_SESSION_VALIDATION_PREFIXES):
            record.msg = _SESSION_VALIDATION_REPLACEMENT
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            return True
        if record.levelno < logging.WARNING:
            return True
        if not record.name.startswith(_SCRUBBED_LOGGERS):
            return True
        # The %-template is server-authored and safe; the interpolated args (pydantic
        # error list with caller loc/input) and any traceback are not — drop them.
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


#: One shared filter instance so idempotent installs don't stack duplicates.
_SHARED_FILTER = ExternalErrorDetailFilter()


def _has_filter(target: logging.Logger | logging.Handler) -> bool:
    return any(isinstance(existing, ExternalErrorDetailFilter) for existing in target.filters)


def install_external_error_filter() -> None:
    """Attach the scrub filter to the framework loggers' OWN (non-propagating) handlers.

    FastMCP configures the ``fastmcp`` logger with its own ``RichHandler``s and
    ``propagate=False``, so its validation/exception records never reach the root
    handler's filter. Attach the filter directly to those handlers (idempotently) — and
    to the loggers themselves as a fallback for records emitted directly on them. Call
    after the FastMCP facade is built, so the framework handlers already exist.

    Also attach the filter to the ROOT logger: ``mcp.shared.session`` emits its
    request/notification-validation-failure records with a bare ``logging.warning``
    (root logger, record name ``"root"``), which the framework-name prefix match
    would otherwise miss.
    """
    root = logging.getLogger()
    if not _has_filter(root):
        root.addFilter(_SHARED_FILTER)
    for name in _SCRUBBED_LOGGERS:
        logger = logging.getLogger(name)
        if not _has_filter(logger):
            logger.addFilter(_SHARED_FILTER)
        for handler in logger.handlers:
            if not _has_filter(handler):
                handler.addFilter(_SHARED_FILTER)
