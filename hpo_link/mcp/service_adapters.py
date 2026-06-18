"""Lazily-constructed singleton services for MCP tools.

The repository is opened against the already-built SQLite index. If the index
is not present yet, services are built without a repository — tools then return
``data_unavailable``. hpo-link has no live API, so there is no fallback client.
"""

from __future__ import annotations

import logging

from hpo_link.config import settings
from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import DataUnavailableError
from hpo_link.services.annotation_service import AnnotationService
from hpo_link.services.hpo_service import HpoService

logger = logging.getLogger(__name__)

_hpo_service: HpoService | None = None
_annotation_service: AnnotationService | None = None


def _build_services() -> tuple[HpoService, AnnotationService]:
    repo: HpoRepository | None = None
    db_path = settings.data.db_path
    if db_path.exists():
        try:
            repo = HpoRepository(db_path)
        except DataUnavailableError as exc:  # pragma: no cover - corrupt db
            logger.warning("hpo_repo_open_failed path=%s err=%s", db_path, exc)
    return HpoService(repo), AnnotationService(repo)


def get_hpo_service() -> HpoService:
    """Return a process-wide :class:`HpoService` (built on first use)."""
    global _hpo_service, _annotation_service
    if _hpo_service is None:
        _hpo_service, _annotation_service = _build_services()
    return _hpo_service


def get_annotation_service() -> AnnotationService:
    """Return a process-wide :class:`AnnotationService` (built on first use)."""
    global _hpo_service, _annotation_service
    if _annotation_service is None:
        _hpo_service, _annotation_service = _build_services()
    return _annotation_service


def reset_services() -> None:
    """Drop the cached services so the next call re-opens the repository."""
    global _hpo_service, _annotation_service
    _hpo_service = None
    _annotation_service = None
    # Clear the capabilities version cache so it is recomputed after reset.
    try:
        from hpo_link.mcp.capabilities import _VERSION_CACHE

        _VERSION_CACHE.clear()
    except Exception:  # pragma: no cover - startup ordering guard
        logger.debug("capabilities version cache clear skipped (not yet imported)")


def set_hpo_service(service: HpoService | None) -> None:
    """Override the HpoService singleton (used by tests)."""
    global _hpo_service
    _hpo_service = service


def set_annotation_service(service: AnnotationService | None) -> None:
    """Override the AnnotationService singleton (used by tests)."""
    global _annotation_service
    _annotation_service = service
