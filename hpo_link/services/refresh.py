"""Startup data bootstrap and the optional in-process refresh scheduler.

Cron is the recommended refresh mechanism (see docs/deployment.md), so the
in-process scheduler is OFF by default. ``bootstrap_data`` builds the index on
first start if absent — non-fatal: the server still starts and tools report
``data_unavailable`` until the build lands.

The frozen ingest builder (``ensure_database`` / ``rebuild``) is imported lazily
inside function bodies so this module stays importable (and the app boots) even
if the ingest plane is mid-build. The builder reads ``config.data.*``, so the
``HPODataConfig`` handed to us by the server entry points is wrapped back into
a full :class:`ServerSettings` before the build runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hpo_link.config import HPODataConfig, ServerSettings


def _as_settings(config: HPODataConfig) -> ServerSettings:
    """Wrap a :class:`HPODataConfig` into the ``ServerSettings`` the builder reads.

    The server entry points hand us ``settings.data``; the frozen builder reads
    ``config.data.*``. Reuse the live ``settings`` when it already carries this
    exact data config (the common case), otherwise build a thin one around it.
    """
    from hpo_link.config import ServerSettings, settings

    if settings.data is config:
        return settings
    return ServerSettings(data=config)


async def bootstrap_data(config: HPODataConfig, logger: Any) -> None:
    """Ensure the index exists, building it in a worker thread. Non-fatal."""
    from hpo_link.ingest.builder import ensure_database
    from hpo_link.mcp.service_adapters import reset_services

    try:
        path = await asyncio.to_thread(ensure_database, _as_settings(config))
        reset_services()
        # Log the basename only — never the full path (deployment-layout disclosure).
        logger.info("hpo_data_ready", db=path.name)
    except Exception as exc:
        # Broad + non-fatal: any failure (BadGzipFile, UnicodeDecodeError, OSError, ...)
        # leaves the server up with tools reporting data_unavailable. Log only the
        # exception CLASS — str(exc) can carry a path / decoded upstream bytes.
        logger.warning("hpo_data_bootstrap_failed", error_type=type(exc).__name__)


async def _refresh_loop(config: HPODataConfig, logger: Any) -> None:
    """Conditionally rebuild the index on an interval; reset the service on change."""
    from hpo_link.ingest.builder import rebuild
    from hpo_link.mcp.service_adapters import reset_services

    settings = _as_settings(config)
    interval = config.refresh_interval_hours * 3600
    while True:
        jitter = random.uniform(0, config.refresh_jitter_seconds)  # noqa: S311 - jitter only
        await asyncio.sleep(interval + jitter)
        try:
            result = await asyncio.to_thread(rebuild, settings, force=False)
            if result.changed:
                reset_services()
                version = result.meta.hpo_version if result.meta else None
                logger.info("hpo_data_refreshed", hpo_version=version)
            else:
                logger.debug("hpo_data_unchanged")
        except Exception as exc:
            # Broad + non-fatal (see bootstrap_data); log only the exception CLASS.
            logger.warning("hpo_data_refresh_failed", error_type=type(exc).__name__)


def start_refresh_scheduler(config: HPODataConfig, logger: Any) -> asyncio.Task[None] | None:
    """Start the optional refresh loop; returns the task, or ``None`` if disabled."""
    if not config.refresh_enabled:
        return None
    logger.info("hpo_refresh_scheduler_enabled", interval_hours=config.refresh_interval_hours)
    return asyncio.create_task(_refresh_loop(config, logger))


async def stop_refresh_scheduler(task: asyncio.Task[None] | None) -> None:
    """Cancel the refresh loop task if running."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
