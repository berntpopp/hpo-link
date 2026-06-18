"""Lazily-constructed singleton HpoService for MCP tools.

The repository is opened against the already-built SQLite index (the server
lifespan bootstraps it; see ``hpo_link.app``). If the index is not present yet,
the service is built without a repository — tools then return ``data_unavailable``.
hpo-link has no live API, so there is no fallback client.
"""

from __future__ import annotations

import logging

from hpo_link.config import settings
from hpo_link.data.repository import MondoRepository
from hpo_link.exceptions import DataUnavailableError
from hpo_link.services.hpo_service import HpoService

logger = logging.getLogger(__name__)

_service: HpoService | None = None


def _build_service() -> HpoService:
    repo: MondoRepository | None = None
    db_path = settings.data.db_path
    if db_path.exists():
        try:
            repo = MondoRepository(db_path)
        except DataUnavailableError as exc:  # pragma: no cover - corrupt db
            logger.warning("mondo_repo_open_failed path=%s err=%s", db_path, exc)
    return HpoService(repo)


def get_hpo_service() -> HpoService:
    """Return a process-wide :class:`HpoService` (built on first use)."""
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def reset_hpo_service() -> None:
    """Drop the cached service so the next call re-opens the repository."""
    global _service
    _service = None


def set_hpo_service(service: HpoService | None) -> None:
    """Override the singleton (used by tests)."""
    global _service
    _service = service
