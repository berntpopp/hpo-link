"""FastAPI host for hpo-link (thin: health + service info)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hpo_link import __version__
from hpo_link.buildinfo import build_info
from hpo_link.config import settings
from hpo_link.logging_config import configure_logging

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Log application lifetime; immutable data is prepared by the init sidecar."""
    logger = configure_logging()
    logger.info("hpo-link starting", host=settings.host, port=settings.port)
    try:
        yield
    finally:
        logger.info("hpo-link shutting down")


def _validate_cors(*, allow_credentials: bool, origins: list[str]) -> None:
    """Fail closed on the credentials-plus-wildcard CORS footgun.

    hpo-link is unauthenticated and holds no cookies or session, so combining
    ``allow_credentials=True`` with a ``"*"`` origin is both meaningless and
    unsafe (browsers reject it, and it signals a misconfiguration). Refuse to
    start rather than serve it.
    """
    if allow_credentials and "*" in origins:
        msg = (
            "Refusing to start: CORS allow_credentials=True is incompatible with a "
            "wildcard '*' origin. hpo-link is unauthenticated and holds no cookies; "
            "keep allow_credentials off."
        )
        raise RuntimeError(msg)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="hpo-link",
        description="MCP/API server grounding phenotype work in the Human Phenotype Ontology (HPO).",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Credentials off: the backend holds no cookies/session, so CORS credentials
    # are meaningless and a footgun if origins ever widen to "*" (see D4).
    allow_credentials = False
    _validate_cors(allow_credentials=allow_credentials, origins=settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe (reports build provenance for deploy checks)."""
        return {
            "status": "ok",
            "service": "hpo-link",
            "transport": "streamable-http-stateless",
            **build_info(),
        }

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Service information."""
        return {
            "name": "hpo-link",
            "version": __version__,
            "data_source": "Human Phenotype Ontology (HPO) OBO + HPOA annotations -> local SQLite index",
            "mcp_endpoint": settings.mcp_path,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
