"""Validated redirect and bounded atomic download primitives for HPO ingest."""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from hpo_link.exceptions import DownloadError

_CHUNK_SIZE = 1 << 16
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SAFE_REDIRECT_HEADERS = frozenset({"accept", "user-agent", "if-none-match", "if-modified-since"})


@dataclass(frozen=True)
class DownloadPolicy:
    """Exact network and resource limits for one download flow."""

    allowed_hosts: frozenset[str]
    max_redirects: int = 5
    max_bytes: int = 128 * 1024 * 1024
    max_seconds: float | None = None


def validate_https_url(url: httpx.URL, policy: DownloadPolicy) -> None:
    """Reject unsafe schemes, authorities, ports, and non-allowlisted hosts."""
    host = (url.host or "").lower()
    if url.scheme != "https":
        raise DownloadError(f"download URL must use HTTPS: {url}")
    if url.userinfo:
        raise DownloadError("download URL must not contain user information")
    if url.port not in (None, 443):
        raise DownloadError(f"download URL port {url.port} is not allowed")
    if host not in policy.allowed_hosts:
        raise DownloadError(f"download host {host} is not allowed")


@contextmanager
def open_validated_stream(
    client: httpx.Client,
    url: str,
    *,
    headers: Mapping[str, str],
    policy: DownloadPolicy,
) -> Iterator[httpx.Response]:
    """Open a stream after validating the initial URL and every redirect hop."""
    current = httpx.URL(url)
    safe_headers = {
        name: value for name, value in headers.items() if name.lower() in _SAFE_REDIRECT_HEADERS
    }
    for hop in range(policy.max_redirects + 1):
        validate_https_url(current, policy)
        request = client.build_request("GET", current, headers=safe_headers)
        response = client.send(request, stream=True, follow_redirects=False)
        if response.status_code not in _REDIRECT_STATUSES:
            try:
                yield response
            finally:
                response.close()
            return
        location = response.headers.get("Location")
        response.close()
        if location is None:
            raise DownloadError("redirect response is missing Location")
        if hop == policy.max_redirects:
            raise DownloadError(f"download exceeded {policy.max_redirects} redirects")
        current = current.join(location)
    raise AssertionError("redirect loop exhausted unexpectedly")


def _content_length(response: httpx.Response) -> int | None:
    raw = response.headers.get("Content-Length")
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def read_bounded(response: httpx.Response, *, max_bytes: int) -> bytes:
    """Read a small metadata response while enforcing header and streamed limits."""
    length = _content_length(response)
    if length is not None and length > max_bytes:
        raise DownloadError(f"download Content-Length {length} exceeds {max_bytes} bytes")
    chunks: list[bytes] = []
    written = 0
    for chunk in response.iter_bytes(_CHUNK_SIZE):
        written += len(chunk)
        if written > max_bytes:
            raise DownloadError(f"download exceeded {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def stream_atomic(
    response: httpx.Response,
    destination: Path,
    *,
    max_bytes: int,
    expected_size: int | None = None,
    hasher: Any | None = None,
    max_seconds: float | None = None,
) -> int:
    """Count and validate a response before atomically replacing its destination."""
    length = _content_length(response)
    if length is not None and length > max_bytes:
        raise DownloadError(f"download Content-Length {length} exceeds {max_bytes} bytes")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=destination.parent, suffix=".download.tmp")
    tmp_path = Path(tmp_name)
    started = time.monotonic()
    written = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            for chunk in response.iter_bytes(_CHUNK_SIZE):
                written += len(chunk)
                if written > max_bytes:
                    raise DownloadError(f"download exceeded {max_bytes} bytes")
                if max_seconds is not None and time.monotonic() - started > max_seconds:
                    raise DownloadError(f"download exceeded {max_seconds:g} seconds")
                handle.write(chunk)
                if hasher is not None:
                    hasher.update(chunk)
        if expected_size is not None and written != expected_size:
            raise DownloadError(
                f"download size mismatch: expected {expected_size}, received {written}"
            )
        os.replace(tmp_path, destination)
        return written
    finally:
        tmp_path.unlink(missing_ok=True)


def copy_bounded(source: BinaryIO, destination: BinaryIO, *, max_bytes: int) -> int:
    """Copy decompressed output without ever writing beyond the configured cap."""
    written = 0
    while chunk := source.read(min(_CHUNK_SIZE, max_bytes - written + 1)):
        written += len(chunk)
        if written > max_bytes:
            raise DownloadError(f"expanded artifact exceeded {max_bytes} bytes")
        destination.write(chunk)
    return written
