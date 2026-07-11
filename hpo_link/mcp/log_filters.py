"""Logging filter that keeps external-framework caller input out of the log sink.

FastMCP core and the MCP SDK log the caller's OWN requested tool name / resource URI
/ prompt name (with any control/zero-width/bidi/NUL code points it carries) on their
OWN loggers, BEFORE the router's :class:`ArgValidationMiddleware` / the Layer-3
protocol backstop reshape the caller-facing frame. These records reflect caller input
into a log/telemetry sink independent of who the caller is. Examples (all real, this
FastMCP/mcp version):

* ``fastmcp.server.server``   — ``Invalid arguments for tool %r: %s`` (arg values)
* ``fastmcp.server.mixins.mcp_operations`` — ``[<srv>] Handler called: call_tool %s
  with %s`` / ``... get_prompt %s ...`` / ``... read_resource %s`` (name/URI in args)
* ``mcp.server.lowlevel.server`` — ``Tool cache miss for %s, refreshing cache``
* ROOT (``mcp.shared.session`` bare ``logging.warning``) — ``Failed to validate
  request: <pydantic error with the raw URI>`` / ``Message that failed validation: …``

``mask_error_details=True`` masks the tool *response*, not these *log* records. This
filter neutralizes them at the SOURCE logger (a logging filter only runs for records
emitted on the logger it is attached to — ancestor filters are skipped during
propagation), replacing the whole message and clearing ``args``/``exc_info`` so raw
caller input never lands in a log sink at ANY level (the fleet PII / log-hygiene
invariant), then a WARNING+ prefix fallback catches any other framework record whose
interpolated args carry caller-derived detail.
"""

from __future__ import annotations

import logging

#: Framework logger-name prefixes for the WARNING+ args-clearing fallback.
_SCRUBBED_LOGGERS = ("fastmcp", "mcp")

#: Substrings that appear in ``record.msg`` (the f-string prefix or %-template) of a
#: FastMCP-core / MCP-SDK record that reflects the caller-supplied name/URI (carried
#: in ``args`` or, for the session records, interpolated into the message). Matching on
#: ``msg`` covers both forms because the scrub replaces the message AND clears args.
_REFLECTION_MARKERS = (
    "Handler called: call_tool",
    "Handler called: read_resource",
    "Handler called: get_prompt",
    "Tool cache miss for",
    "Invalid arguments for tool",
    "Error calling tool",
    "Error reading resource",
    "Failed to validate request",
    "Failed to validate notification",
    "Message that failed validation",
)
_SCRUBBED_MESSAGE = "MCP request detail omitted (caller input redacted)."

#: The SOURCE loggers on which those records are CREATED. Attach the filter directly to
#: each (root covers ``mcp.shared.session``'s bare ``logging.warning``); ``fastmcp`` /
#: ``mcp`` are kept for the WARNING+ fallback and their non-propagating Rich handlers.
_SOURCE_LOGGERS = (
    "",  # root — mcp.shared.session request-validation failures
    "fastmcp",
    "fastmcp.server.server",
    "fastmcp.server.mixins.mcp_operations",
    "mcp",
    "mcp.server.lowlevel.server",
)


class ExternalErrorDetailFilter(logging.Filter):
    """Scrub caller-supplied name/URI from FastMCP/MCP framework log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Neutralize reflecting records in place; always emit the scrubbed record."""
        msg = record.msg if isinstance(record.msg, str) else ""
        # Records that reflect the caller-supplied name/URI (any logger, any level):
        # replace the whole message and clear the interpolated args/traceback.
        if any(marker in msg for marker in _REFLECTION_MARKERS):
            record.msg = _SCRUBBED_MESSAGE
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            return True
        # Fallback: other FastMCP/MCP framework WARNING+ records may carry
        # caller-derived detail in their interpolated args — drop it.
        if record.levelno < logging.WARNING:
            return True
        if not record.name.startswith(_SCRUBBED_LOGGERS):
            return True
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


#: One shared filter instance so idempotent installs don't stack duplicates.
_SHARED_FILTER = ExternalErrorDetailFilter()


def _has_filter(target: logging.Logger | logging.Handler) -> bool:
    return any(isinstance(existing, ExternalErrorDetailFilter) for existing in target.filters)


def install_external_error_filter() -> None:
    """Attach the scrub filter to every SOURCE logger (and its handlers), idempotently.

    A logging filter runs only for records emitted on the logger it is attached to
    (ancestor filters are skipped during propagation), so the filter is attached
    directly to each originating logger — including the ROOT logger, where
    ``mcp.shared.session`` emits its request-validation failures via a bare
    ``logging.warning``, and FastMCP's own ``fastmcp`` logger, whose non-propagating
    ``RichHandler``s would otherwise bypass a root-only filter. Also attach to each
    logger's existing handlers as belt-and-braces. Call after the FastMCP facade is
    built, so the framework handlers already exist.
    """
    for name in _SOURCE_LOGGERS:
        logger = logging.getLogger(name)
        if not _has_filter(logger):
            logger.addFilter(_SHARED_FILTER)
        for handler in logger.handlers:
            if not _has_filter(handler):
                handler.addFilter(_SHARED_FILTER)
