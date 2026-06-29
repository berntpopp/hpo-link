"""Unified server manager for HTTP, stdio, and unified (HTTP+MCP) transports."""

from __future__ import annotations

import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

import uvicorn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from structlog.typing import FilteringBoundLogger


class UnifiedServerManager:
    """Orchestrate startup of hpo-link in any transport mode."""

    def __init__(self, logger: FilteringBoundLogger | None = None) -> None:
        """Build a manager with an optional structlog logger."""
        self.logger = logger
        self._uvicorn_server: uvicorn.Server | None = None

    async def start_unified_server(self, host: str, port: int) -> None:
        """Start FastAPI + MCP (streamable-http) on the same port."""
        if self.logger:
            self.logger.info("Starting unified server", host=host, port=port, mcp_path="/mcp")

        from hpo_link.app import app as fastapi_app
        from hpo_link.config import settings
        from hpo_link.mcp.facade import create_hpo_mcp

        mcp = create_hpo_mcp()
        mcp_asgi = mcp.http_app(path=settings.mcp_path, stateless_http=True, json_response=True)

        original_lifespan = fastapi_app.router.lifespan_context

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(original_lifespan(app))
                await stack.enter_async_context(mcp_asgi.router.lifespan_context(app))
                yield

        fastapi_app.router.lifespan_context = combined_lifespan
        fastapi_app.mount("/", mcp_asgi)

        config = uvicorn.Config(
            app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def start_http_only_server(self, host: str, port: int) -> None:
        """Start FastAPI only (no MCP)."""
        if self.logger:
            self.logger.info("Starting HTTP-only server", host=host, port=port)
        from hpo_link.app import app as fastapi_app

        config = uvicorn.Config(
            app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def start_stdio_server(self) -> None:
        """Start the FastMCP stdio transport (for Claude Desktop)."""
        self._configure_stdio_environment()
        if self.logger:
            self.logger.info("Starting stdio MCP server")
        from hpo_link.config import settings
        from hpo_link.logging_config import configure_logging
        from hpo_link.mcp.facade import create_hpo_mcp
        from hpo_link.services.refresh import bootstrap_data

        # Bootstrap the index before serving (stdio has no FastAPI lifespan).
        await bootstrap_data(settings.data, self.logger or configure_logging())
        mcp = create_hpo_mcp()
        # show_banner=False is critical: stray stdout bytes corrupt JSON-RPC framing.
        await mcp.run_async(transport="stdio", show_banner=False)

    async def shutdown(self) -> None:
        """Gracefully stop any running server."""
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self.logger:
            self.logger.info("Shutdown complete")

    @staticmethod
    def _configure_stdio_environment() -> None:
        """Suppress non-JSON output that would corrupt stdio MCP framing."""
        env_defaults: dict[str, Any] = {
            "PYTHONUNBUFFERED": "1",
            "HPO_LINK_TRANSPORT": "stdio",
            "FASTMCP_DISABLE_BANNER": "1",
            "FASTMCP_QUIET": "1",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "TERM": "dumb",
            "PYTHONWARNINGS": "ignore",
        }
        for key, value in env_defaults.items():
            os.environ.setdefault(key, value)
