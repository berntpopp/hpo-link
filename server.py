#!/usr/bin/env python3
"""Unified entry point for hpo-link.

python server.py --transport unified  # FastAPI + MCP at /mcp (default)
python server.py --transport http     # FastAPI only
python server.py --transport stdio    # FastMCP stdio (for Claude Desktop)
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from typing import TYPE_CHECKING

from hpo_link.config import settings
from hpo_link.logging_config import configure_logging
from hpo_link.server_manager import UnifiedServerManager

if TYPE_CHECKING:
    from types import FrameType


async def _run() -> None:
    parser = argparse.ArgumentParser(description="hpo-link server")
    parser.add_argument(
        "--transport",
        choices=["unified", "http", "stdio"],
        default=settings.transport,
        help="Server transport mode",
    )
    parser.add_argument("--host", default=settings.host, help="Server host")
    parser.add_argument("--port", type=int, default=settings.port, help="Server port")
    parser.add_argument("--log-level", default=settings.log_level, help="Logging level")
    args = parser.parse_args()

    settings.transport = args.transport
    settings.host = args.host
    settings.port = args.port
    settings.log_level = args.log_level

    logger = configure_logging()
    manager = UnifiedServerManager(logger=logger)

    shutdown_task: asyncio.Task[None] | None = None

    def _signal(signum: int, _frame: FrameType | None) -> None:
        nonlocal shutdown_task
        logger.info("Received shutdown signal", signal=signum)
        if shutdown_task is None or shutdown_task.done():
            shutdown_task = asyncio.create_task(manager.shutdown())

    signal.signal(signal.SIGINT, _signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal)

    try:
        if args.transport == "unified":
            await manager.start_unified_server(host=args.host, port=args.port)
        elif args.transport == "http":
            await manager.start_http_only_server(host=args.host, port=args.port)
        elif args.transport == "stdio":
            await manager.start_stdio_server()
        else:
            logger.error("Invalid transport", transport=args.transport)
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as exc:
        logger.error("Server error", error=str(exc))
        sys.exit(1)
    finally:
        await manager.shutdown()


def main() -> None:
    """Run the unified hpo-link entry point."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
