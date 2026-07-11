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


class ExternalErrorDetailFilter(logging.Filter):
    """Drop caller-derived detail from FastMCP/MCP framework error log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Clear ``args``/``exc_info``/``exc_text`` on framework WARNING+ records."""
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
