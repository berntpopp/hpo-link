"""In-process runtime metrics for the MCP tool surface (observability).

``run_mcp_tool`` records each call's latency and outcome here; ``get_diagnostics``
surfaces a compact snapshot (request/error counts + latency percentiles) alongside
the build/data provenance. The latency window is bounded so memory stays constant,
and the collector is process-local (reset on restart, and in tests).
"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any

#: Rolling latency window. Percentiles are computed over the most recent calls;
#: counters (requests/errors) are cumulative for the process lifetime.
_MAX_SAMPLES = 1024

#: Minimum request count before ``error_rate`` is reported. Below this the ratio is
#: withheld (``None``): an error or two over a handful of calls reads as alarming
#: noise rather than signal. Raw ``requests``/``errors`` counts are always reported.
_ERROR_RATE_MIN_SAMPLE = 20


def _percentile(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile of a pre-sorted list (0 for an empty window)."""
    if not sorted_vals:
        return 0
    rank = max(0, math.ceil(q / 100 * len(sorted_vals)) - 1)
    return sorted_vals[min(rank, len(sorted_vals) - 1)]


class _Metrics:
    """Thread-safe counters + a bounded latency window."""

    def __init__(self) -> None:
        """Initialise empty counters, latency window, and per-tool tallies."""
        self._lock = threading.Lock()
        self._latencies: deque[int] = deque(maxlen=_MAX_SAMPLES)
        self._requests = 0
        self._errors = 0
        self._per_tool: dict[str, dict[str, int]] = {}

    def record(self, tool: str, elapsed_ms: int, *, ok: bool) -> None:
        """Record one tool call's latency and success/failure outcome."""
        with self._lock:
            self._requests += 1
            self._latencies.append(max(0, int(elapsed_ms)))
            tally = self._per_tool.setdefault(tool, {"requests": 0, "errors": 0})
            tally["requests"] += 1
            if not ok:
                self._errors += 1
                tally["errors"] += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a compact, JSON-safe view of current runtime behaviour."""
        with self._lock:
            requests = self._requests
            errors = self._errors
            samples = sorted(self._latencies)
            per_tool = {k: dict(v) for k, v in sorted(self._per_tool.items())}
        report_rate = requests >= _ERROR_RATE_MIN_SAMPLE
        snap: dict[str, Any] = {
            "requests": requests,
            "errors": errors,
            "error_rate": round(errors / requests, 4) if report_rate else None,
        }
        if not report_rate:
            snap["error_rate_withheld_below"] = _ERROR_RATE_MIN_SAMPLE
        snap["latency_ms"] = {
            "p50": _percentile(samples, 50),
            "p95": _percentile(samples, 95),
            "p99": _percentile(samples, 99),
            "max": samples[-1] if samples else 0,
            "sampled": len(samples),
        }
        snap["per_tool"] = per_tool
        return snap

    def reset(self) -> None:
        """Clear all counters and the latency window (test/process boundary)."""
        with self._lock:
            self._latencies.clear()
            self._requests = 0
            self._errors = 0
            self._per_tool.clear()


_METRICS = _Metrics()


def record(tool: str, elapsed_ms: int, *, ok: bool) -> None:
    """Record one tool call into the process-wide collector."""
    _METRICS.record(tool, elapsed_ms, ok=ok)


def snapshot() -> dict[str, Any]:
    """Return the process-wide runtime snapshot."""
    return _METRICS.snapshot()


def reset() -> None:
    """Reset the process-wide collector."""
    _METRICS.reset()
