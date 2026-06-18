#!/usr/bin/env python3
"""Stdio MCP entry point for Claude Desktop and similar clients.

For HTTP transport use `server.py --transport unified` (or `--transport http`).
"""

from __future__ import annotations

import asyncio
import os
import sys


def main() -> None:
    """Run the hpo-link MCP server on the stdio transport."""
    # Configure environment BEFORE importing anything that may print to stdout.
    os.environ.setdefault("MONDO_LINK_TRANSPORT", "stdio")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ.setdefault("FASTMCP_DISABLE_BANNER", "1")
    os.environ.setdefault("FASTMCP_QUIET", "1")
    os.environ.setdefault("NO_COLOR", "1")

    try:
        from hpo_link.logging_config import configure_logging
        from hpo_link.server_manager import UnifiedServerManager
    except Exception as exc:
        print(f"ERROR: hpo_link import failed: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = configure_logging()
    manager = UnifiedServerManager(logger=logger)
    try:
        asyncio.run(manager.start_stdio_server())
    except KeyboardInterrupt:
        logger.info("MCP stdio server shutdown requested")
    except Exception as exc:
        logger.error("MCP stdio server error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
