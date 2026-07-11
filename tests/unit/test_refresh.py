"""Unit tests for the startup bootstrap and refresh scheduler in services/refresh.

These exercise real control flow with the heavy ingest builder (``ensure_database``
/ ``rebuild``) and the service-singleton reset stubbed out, so the branching logic
(success/failure, changed/unchanged, enabled/disabled) is covered without touching
the network or rebuilding a SQLite index.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from hpo_link.exceptions import DownloadError
from hpo_link.services.refresh import (
    _as_settings,
    bootstrap_data,
    start_refresh_scheduler,
    stop_refresh_scheduler,
)

if TYPE_CHECKING:
    import pytest as _pytest


# ---------------------------------------------------------------------------
# _as_settings
# ---------------------------------------------------------------------------


def test_as_settings_reuses_live_settings() -> None:
    """When given the live ``settings.data``, return the live ``settings`` object."""
    from hpo_link.config import settings

    assert _as_settings(settings.data) is settings


def test_as_settings_wraps_foreign_config(tmp_path: Path) -> None:
    """A foreign data config is wrapped into a fresh ServerSettings carrying it."""
    from hpo_link.config import HPODataConfig, ServerSettings, settings

    cfg = HPODataConfig(data_dir=tmp_path / "foreign")
    result = _as_settings(cfg)

    assert isinstance(result, ServerSettings)
    assert result.data is cfg
    assert result is not settings


# ---------------------------------------------------------------------------
# bootstrap_data
# ---------------------------------------------------------------------------


async def test_bootstrap_data_success(monkeypatch: _pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Successful build resets services and logs hpo_data_ready with the db basename only.

    Guard (PII/path hygiene): the event must carry the file basename, never the
    full filesystem path (deployment-layout disclosure).
    """
    from hpo_link.config import settings

    built_path = tmp_path / "hpo.sqlite"
    ensure_mock = MagicMock(return_value=built_path)
    reset_mock = MagicMock()
    monkeypatch.setattr("hpo_link.ingest.builder.ensure_database", ensure_mock)
    monkeypatch.setattr("hpo_link.mcp.service_adapters.reset_services", reset_mock)
    logger = MagicMock()

    await bootstrap_data(settings.data, logger)

    ensure_mock.assert_called_once()
    reset_mock.assert_called_once()
    logger.info.assert_called_once_with("hpo_data_ready", db="hpo.sqlite")
    # The full path (tmp_path) must not leak into any log field.
    assert str(tmp_path) not in str(logger.info.call_args)
    logger.warning.assert_not_called()


async def test_bootstrap_data_failure_is_non_fatal(monkeypatch: _pytest.MonkeyPatch) -> None:
    """A build error is swallowed: services are NOT reset and a warning is logged."""
    from hpo_link.config import settings

    ensure_mock = MagicMock(side_effect=DownloadError("offline"))
    reset_mock = MagicMock()
    monkeypatch.setattr("hpo_link.ingest.builder.ensure_database", ensure_mock)
    monkeypatch.setattr("hpo_link.mcp.service_adapters.reset_services", reset_mock)
    logger = MagicMock()

    await bootstrap_data(settings.data, logger)

    reset_mock.assert_not_called()
    logger.info.assert_not_called()
    assert logger.warning.call_args.args[0] == "hpo_data_bootstrap_failed"


async def test_bootstrap_data_decode_error_is_non_fatal_and_logs_class_only(
    monkeypatch: _pytest.MonkeyPatch,
) -> None:
    """A UnicodeDecodeError (previously uncaught) is swallowed; str(exc) is NOT logged."""
    from hpo_link.config import settings

    decode_error = UnicodeDecodeError("utf-8", b"\xff\x00", 0, 1, "invalid start byte")
    ensure_mock = MagicMock(side_effect=decode_error)
    monkeypatch.setattr("hpo_link.ingest.builder.ensure_database", ensure_mock)
    monkeypatch.setattr("hpo_link.mcp.service_adapters.reset_services", MagicMock())
    logger = MagicMock()

    await bootstrap_data(settings.data, logger)  # must NOT raise

    call = logger.warning.call_args
    assert call.args[0] == "hpo_data_bootstrap_failed"
    assert call.kwargs == {"error_type": "UnicodeDecodeError"}
    # the raw decode message (str(exc)) must not appear anywhere in the log call
    assert "invalid start byte" not in str(call)
    assert "codec can't decode" not in str(call)


# ---------------------------------------------------------------------------
# start_refresh_scheduler / stop_refresh_scheduler
# ---------------------------------------------------------------------------


def test_start_refresh_scheduler_disabled_returns_none() -> None:
    """Scheduler is OFF by default: returns None and logs nothing."""
    from hpo_link.config import HPODataConfig

    cfg = HPODataConfig(refresh_enabled=False)
    logger = MagicMock()

    assert start_refresh_scheduler(cfg, logger) is None
    logger.info.assert_not_called()


async def test_start_refresh_scheduler_enabled_returns_task() -> None:
    """When enabled, a running asyncio Task is returned and the start is logged."""
    from hpo_link.config import HPODataConfig

    # Large interval so the loop parks on its first sleep instead of rebuilding.
    cfg = HPODataConfig(refresh_enabled=True, refresh_interval_hours=720.0)
    logger = MagicMock()

    task = start_refresh_scheduler(cfg, logger)

    assert isinstance(task, asyncio.Task)
    assert not task.done()
    logger.info.assert_called_once_with("hpo_refresh_scheduler_enabled", interval_hours=720.0)

    await stop_refresh_scheduler(task)
    assert task.cancelled()


async def test_stop_refresh_scheduler_none_is_noop() -> None:
    """Stopping a None task is a no-op and must not raise."""
    await stop_refresh_scheduler(None)


async def test_stop_refresh_scheduler_cancels_running_task() -> None:
    """A live task is cancelled and awaited to completion."""

    async def _sleep_forever() -> None:
        await asyncio.sleep(3600)

    task: asyncio.Task[None] = asyncio.create_task(_sleep_forever())
    await asyncio.sleep(0)  # let the task start

    await stop_refresh_scheduler(task)

    assert task.cancelled()


# ---------------------------------------------------------------------------
# _refresh_loop — drive changed / unchanged / error iterations then break
# ---------------------------------------------------------------------------


async def test_refresh_loop_handles_all_branches(monkeypatch: _pytest.MonkeyPatch) -> None:
    """One pass each through changed, unchanged, and error branches of the loop."""
    from hpo_link.config import HPODataConfig
    from hpo_link.services.refresh import _refresh_loop

    cfg = HPODataConfig(refresh_interval_hours=1.0, refresh_jitter_seconds=0)
    logger = MagicMock()
    reset_mock = MagicMock()

    changed = SimpleNamespace(changed=True, meta=SimpleNamespace(hpo_version="v2025-06-01"))
    unchanged = SimpleNamespace(changed=False, meta=None)
    rebuild_mock = MagicMock(side_effect=[changed, unchanged, OSError("disk full")])

    sleep_count = {"n": 0}

    async def fake_sleep(_delay: float) -> None:
        sleep_count["n"] += 1
        # Break out after the three rebuild iterations have run.
        if sleep_count["n"] >= 4:
            raise asyncio.CancelledError

    async def fake_to_thread(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    monkeypatch.setattr("hpo_link.ingest.builder.rebuild", rebuild_mock)
    monkeypatch.setattr("hpo_link.mcp.service_adapters.reset_services", reset_mock)
    monkeypatch.setattr("hpo_link.services.refresh.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("hpo_link.services.refresh.asyncio.to_thread", fake_to_thread)

    with pytest.raises(asyncio.CancelledError):
        await _refresh_loop(cfg, logger)

    assert rebuild_mock.call_count == 3
    # reset_services only fires on the "changed" iteration.
    reset_mock.assert_called_once()
    logger.info.assert_called_once_with("hpo_data_refreshed", hpo_version="v2025-06-01")
    logger.debug.assert_called_once_with("hpo_data_unchanged")
    assert logger.warning.call_args.args[0] == "hpo_data_refresh_failed"
