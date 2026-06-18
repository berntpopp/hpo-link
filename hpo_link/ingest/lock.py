"""Cross-process advisory lock that serializes database builds.

The entrypoint build, the optional in-process refresh, and any external cron all
funnel through ``hpo-link-data``/``rebuild``. This lock ensures only one of them
downloads + rebuilds at a time, so they never clobber each other's temp file.

Uses POSIX ``fcntl.flock`` on a lock file in the data directory. On platforms
without ``fcntl`` (e.g. Windows) it degrades to a no-op, which is acceptable
because the primary deployment target is Linux containers and the builder's
final ``os.replace`` is itself atomic.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from hpo_link.exceptions import DataUnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterator

try:  # POSIX only
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-POSIX fallback
    _HAVE_FCNTL = False

LOCK_FILENAME = ".build.lock"


@contextmanager
def build_lock(data_dir: Path, *, timeout: int = 600, poll_interval: float = 0.5) -> Iterator[bool]:
    """Acquire the build lock for ``data_dir``, blocking up to ``timeout`` seconds.

    Yields ``True`` once the lock is held (always ``True`` on the no-fcntl
    fallback). Raises :class:`DataUnavailableError` if the lock cannot be acquired
    within ``timeout``.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    if not _HAVE_FCNTL:  # pragma: no cover - non-POSIX fallback
        yield True
        return

    lock_path = data_dir / LOCK_FILENAME
    fd = open(lock_path, "w")  # noqa: SIM115 - released in finally
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise DataUnavailableError(
                        f"Timed out after {timeout}s waiting for the Mondo build lock; "
                        "another build is in progress."
                    ) from exc
                time.sleep(poll_interval)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()
