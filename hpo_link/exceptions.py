"""Custom exceptions for hpo-link.

These errors flow into the MCP envelope from the local SQLite repository /
services (``NotFoundError``, ``WithdrawnEntryError``, ``AmbiguousQueryError``,
``DataUnavailableError``). hpo-link has no live API: the local HPO index is
the only source.

``run_mcp_tool`` classifies each into a stable ``error_code`` (see
``hpo_link.mcp.envelope``).
"""

from __future__ import annotations

from typing import Any


class HpoLinkError(Exception):
    """Base exception for all hpo-link data/client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Store a human-readable message and optional HTTP status code."""
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        """Return the message (with status code when present)."""
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class InvalidInputError(HpoLinkError):
    """A tool/service argument failed validation before any lookup ran."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        *,
        allowed: list[str] | None = None,
        hint: str | None = None,
    ) -> None:
        """Initialise with the offending field and optional recovery data.

        ``allowed`` and ``hint`` are surfaced as structured top-level keys on the
        error envelope (``allowed_values``/``hint``) so a consumer never has to
        parse them out of a (length-capped) message.
        """
        super().__init__(message)
        self.field = field
        self.allowed = allowed
        self.hint = hint


class NotFoundError(HpoLinkError):
    """A lookup returned no rows for an otherwise valid identifier.

    For a free-text label miss the service may attach ``suggestions`` (the closest
    search hits) so the envelope can chain straight to the answer (``get_disease``
    on the top hit) instead of merely routing the client back to the search tool.
    """

    def __init__(
        self,
        message: str = "No matching HPO term found.",
        *,
        suggestions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialise with a 404 status code and optional close-match suggestions."""
        super().__init__(message, status_code=404)
        self.suggestions = suggestions or []


class WithdrawnEntryError(NotFoundError):
    """The term exists in HPO but is obsolete (deprecated / merged).

    Subclasses :class:`NotFoundError` so it classifies as ``not_found`` in the
    error envelope, but carries the withdrawn term, the withdrawal status, and
    any replacement records so the envelope can flag ``obsolete: true`` and chain
    to the successor(s).
    """

    def __init__(
        self,
        withdrawn: str,
        *,
        status: str,
        replaced_by: list[dict[str, str]] | None = None,
        message: str | None = None,
    ) -> None:
        """Store the withdrawn term/ID, its status, and replacement record(s)."""
        self.withdrawn = withdrawn
        self.withdrawn_status = status
        self.replaced_by = replaced_by or []
        if message is None:
            if self.replaced_by:
                targets = ", ".join(
                    f"{r.get('name', '?')} ({r.get('hpo_id', '?')})" for r in self.replaced_by
                )
                message = f"{withdrawn} is obsolete in HPO ({status}). See: {targets}."
            else:
                message = f"{withdrawn} is obsolete in HPO ({status}) and has no replacement."
        super().__init__(message)


class AmbiguousQueryError(HpoLinkError):
    """A query matched several records and cannot be resolved unambiguously."""

    def __init__(self, message: str, *, candidates: list[dict[str, str]] | None = None) -> None:
        """Store the ambiguous candidates so the envelope can surface them."""
        super().__init__(message)
        self.candidates = candidates or []


class DataUnavailableError(HpoLinkError):
    """The local HPO SQLite index is missing, unbuilt, or unreadable."""

    def __init__(self, message: str = "The local HPO database is not available.") -> None:
        """Initialise with a 503 status code."""
        super().__init__(message, status_code=503)


class RateLimitError(HpoLinkError):
    """An upstream endpoint signalled rate limiting (HTTP 429)."""

    def __init__(self, message: str = "Upstream rate limit hit.") -> None:
        """Initialise with a 429 status code."""
        super().__init__(message, status_code=429)


class ServiceUnavailableError(HpoLinkError):
    """An upstream endpoint is temporarily unavailable (5xx / network error)."""

    def __init__(self, message: str = "Upstream service is temporarily unavailable.") -> None:
        """Initialise with a 503 status code."""
        super().__init__(message, status_code=503)


class DownloadError(HpoLinkError):
    """A bulk-download attempt failed (network/HTTP error)."""
