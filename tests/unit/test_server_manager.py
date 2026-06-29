"""Unit tests for the UnifiedServerManager transport orchestrator.

The real ``serve()`` / ``run_async()`` calls block forever, so uvicorn and the
FastMCP facade are stubbed: these tests assert the *wiring* each transport mode
performs (mounting, lifespan combination, stdio env hardening, bootstrap, and
graceful shutdown) rather than starting a live socket.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from hpo_link.server_manager import UnifiedServerManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest

_STDIO_ENV_KEYS = (
    "PYTHONUNBUFFERED",
    "HPO_LINK_TRANSPORT",
    "FASTMCP_DISABLE_BANNER",
    "FASTMCP_QUIET",
    "NO_COLOR",
    "FORCE_COLOR",
    "TERM",
    "PYTHONWARNINGS",
)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_init_defaults() -> None:
    """A bare manager has no logger and no live server."""
    mgr = UnifiedServerManager()
    assert mgr.logger is None
    assert mgr._uvicorn_server is None


def test_init_accepts_logger() -> None:
    """The supplied logger is stored verbatim."""
    logger = MagicMock()
    assert UnifiedServerManager(logger=logger).logger is logger


# ---------------------------------------------------------------------------
# start_unified_server
# ---------------------------------------------------------------------------


async def test_start_unified_server_wires_mcp_and_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unified mode mounts the MCP ASGI app on FastAPI and runs uvicorn."""
    from hpo_link.config import settings

    entered: list[str] = []

    @asynccontextmanager
    async def original_lifespan(_app: object) -> AsyncIterator[None]:
        entered.append("fastapi")
        yield

    @asynccontextmanager
    async def mcp_lifespan(_app: object) -> AsyncIterator[None]:
        entered.append("mcp")
        yield

    fake_app = MagicMock()
    fake_app.router.lifespan_context = original_lifespan
    fake_asgi = MagicMock()
    fake_asgi.router.lifespan_context = mcp_lifespan
    fake_mcp = MagicMock()
    fake_mcp.http_app.return_value = fake_asgi
    fake_server = MagicMock()
    fake_server.serve = AsyncMock()
    config_factory = MagicMock(return_value="config-sentinel")
    server_factory = MagicMock(return_value=fake_server)

    monkeypatch.setattr("hpo_link.app.app", fake_app)
    monkeypatch.setattr("hpo_link.mcp.facade.create_hpo_mcp", lambda: fake_mcp)
    monkeypatch.setattr("hpo_link.server_manager.uvicorn.Config", config_factory)
    monkeypatch.setattr("hpo_link.server_manager.uvicorn.Server", server_factory)

    logger = MagicMock()
    mgr = UnifiedServerManager(logger=logger)
    await mgr.start_unified_server("127.0.0.1", 9123)

    fake_mcp.http_app.assert_called_once_with(path=settings.mcp_path)
    fake_app.mount.assert_called_once_with("/", fake_asgi)
    # The FastAPI lifespan was replaced by a composed one that enters BOTH the
    # original FastAPI lifespan and the mounted MCP app's lifespan, in order.
    combined = fake_app.router.lifespan_context
    assert combined is not original_lifespan
    async with combined(fake_app):
        pass
    assert entered == ["fastapi", "mcp"]
    config_factory.assert_called_once()
    assert config_factory.call_args.kwargs["app"] is fake_app
    assert config_factory.call_args.kwargs["port"] == 9123
    server_factory.assert_called_once_with("config-sentinel")
    fake_server.serve.assert_awaited_once()
    assert mgr._uvicorn_server is fake_server
    logger.info.assert_called_once()


# ---------------------------------------------------------------------------
# start_http_only_server
# ---------------------------------------------------------------------------


async def test_start_http_only_server_serves_without_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP-only mode runs uvicorn over the FastAPI app and never mounts MCP."""
    fake_app = MagicMock()
    fake_server = MagicMock()
    fake_server.serve = AsyncMock()
    config_factory = MagicMock(return_value="config-sentinel")
    server_factory = MagicMock(return_value=fake_server)

    monkeypatch.setattr("hpo_link.app.app", fake_app)
    monkeypatch.setattr("hpo_link.server_manager.uvicorn.Config", config_factory)
    monkeypatch.setattr("hpo_link.server_manager.uvicorn.Server", server_factory)

    mgr = UnifiedServerManager(logger=MagicMock())
    await mgr.start_http_only_server("127.0.0.1", 9124)

    fake_app.mount.assert_not_called()
    assert config_factory.call_args.kwargs["host"] == "127.0.0.1"
    assert config_factory.call_args.kwargs["port"] == 9124
    fake_server.serve.assert_awaited_once()
    assert mgr._uvicorn_server is fake_server


# ---------------------------------------------------------------------------
# start_stdio_server
# ---------------------------------------------------------------------------


async def test_start_stdio_server_bootstraps_then_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdio mode hardens the env, bootstraps data, then runs banner-free stdio."""
    from hpo_link.config import settings

    fake_mcp = MagicMock()
    fake_mcp.run_async = AsyncMock()
    boot_mock = AsyncMock()
    monkeypatch.setattr("hpo_link.mcp.facade.create_hpo_mcp", lambda: fake_mcp)
    monkeypatch.setattr("hpo_link.services.refresh.bootstrap_data", boot_mock)

    logger = MagicMock()
    mgr = UnifiedServerManager(logger=logger)
    await mgr.start_stdio_server()

    boot_mock.assert_awaited_once_with(settings.data, logger)
    fake_mcp.run_async.assert_awaited_once_with(transport="stdio", show_banner=False)
    # Env hardening must have run.
    assert os.environ["HPO_LINK_TRANSPORT"] == "stdio"
    assert os.environ["FASTMCP_DISABLE_BANNER"] == "1"


async def test_start_stdio_server_uses_configured_logger_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no injected logger, bootstrap uses a freshly configured logger."""
    from hpo_link.config import settings

    fake_mcp = MagicMock()
    fake_mcp.run_async = AsyncMock()
    boot_mock = AsyncMock()
    fallback_logger = MagicMock(name="configured")
    monkeypatch.setattr("hpo_link.mcp.facade.create_hpo_mcp", lambda: fake_mcp)
    monkeypatch.setattr("hpo_link.services.refresh.bootstrap_data", boot_mock)
    monkeypatch.setattr("hpo_link.logging_config.configure_logging", lambda: fallback_logger)

    mgr = UnifiedServerManager()  # logger is None
    await mgr.start_stdio_server()

    boot_mock.assert_awaited_once_with(settings.data, fallback_logger)
    fake_mcp.run_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# _configure_stdio_environment
# ---------------------------------------------------------------------------


def test_configure_stdio_environment_sets_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All stdio-hardening vars are set when previously absent."""
    for key in _STDIO_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    UnifiedServerManager._configure_stdio_environment()

    assert os.environ["HPO_LINK_TRANSPORT"] == "stdio"
    assert os.environ["PYTHONUNBUFFERED"] == "1"
    assert os.environ["NO_COLOR"] == "1"
    assert os.environ["TERM"] == "dumb"


def test_configure_stdio_environment_preserves_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """setdefault semantics: an operator-provided value is left untouched."""
    monkeypatch.setenv("HPO_LINK_TRANSPORT", "operator-choice")

    UnifiedServerManager._configure_stdio_environment()

    assert os.environ["HPO_LINK_TRANSPORT"] == "operator-choice"


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


async def test_shutdown_signals_running_server() -> None:
    """Shutdown flips should_exit on the live uvicorn server and logs."""
    logger = MagicMock()
    mgr = UnifiedServerManager(logger=logger)
    fake_server = MagicMock()
    fake_server.should_exit = False
    mgr._uvicorn_server = fake_server

    await mgr.shutdown()

    assert fake_server.should_exit is True
    logger.info.assert_called_once_with("Shutdown complete")


async def test_shutdown_without_server_is_noop() -> None:
    """Shutdown with no server and no logger must not raise."""
    mgr = UnifiedServerManager()
    await mgr.shutdown()
    assert mgr._uvicorn_server is None
