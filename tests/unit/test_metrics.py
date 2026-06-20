"""Tests for hpo_link.mcp.metrics — WS-A (TDD, written before implementation)."""

from __future__ import annotations

from hpo_link.mcp.metrics import _ERROR_RATE_MIN_SAMPLE, _Metrics

# ---------------------------------------------------------------------------
# T0.3 — error_rate_withheld_below
# ---------------------------------------------------------------------------


def test_snapshot_withholds_error_rate_below_threshold() -> None:
    """When requests < _ERROR_RATE_MIN_SAMPLE, error_rate must be None."""
    m = _Metrics()
    # Record one request fewer than the minimum sample
    for _ in range(_ERROR_RATE_MIN_SAMPLE - 1):
        m.record("some_tool", 5, ok=True)
    snap = m.snapshot()
    assert snap["error_rate"] is None


def test_snapshot_includes_withheld_explanation_below_threshold() -> None:
    """When error_rate is withheld, snapshot must include error_rate_withheld_below = threshold."""
    m = _Metrics()
    # Record fewer than the minimum sample
    for _ in range(_ERROR_RATE_MIN_SAMPLE - 1):
        m.record("some_tool", 5, ok=True)
    snap = m.snapshot()
    assert "error_rate_withheld_below" in snap, (
        "error_rate_withheld_below should be present when error_rate is None"
    )
    assert snap["error_rate_withheld_below"] == _ERROR_RATE_MIN_SAMPLE


def test_snapshot_omits_withheld_key_when_error_rate_reported() -> None:
    """When requests >= _ERROR_RATE_MIN_SAMPLE, error_rate_withheld_below must NOT appear."""
    m = _Metrics()
    for _ in range(_ERROR_RATE_MIN_SAMPLE):
        m.record("some_tool", 5, ok=True)
    snap = m.snapshot()
    assert snap["error_rate"] is not None
    assert "error_rate_withheld_below" not in snap, (
        "error_rate_withheld_below must not appear when error_rate is reported"
    )


def test_snapshot_reports_error_rate_as_float_above_threshold() -> None:
    """When requests >= threshold, error_rate is a float (rounded)."""
    m = _Metrics()
    # Record _ERROR_RATE_MIN_SAMPLE requests, half of which are errors
    half = _ERROR_RATE_MIN_SAMPLE // 2
    for _ in range(half):
        m.record("some_tool", 5, ok=True)
    for _ in range(_ERROR_RATE_MIN_SAMPLE - half):
        m.record("some_tool", 5, ok=False)
    snap = m.snapshot()
    assert isinstance(snap["error_rate"], float)
    assert 0.0 <= snap["error_rate"] <= 1.0


def test_snapshot_zero_requests_withholds_error_rate() -> None:
    """With zero requests, error_rate must be None and withheld key present."""
    m = _Metrics()
    snap = m.snapshot()
    assert snap["error_rate"] is None
    assert "error_rate_withheld_below" in snap
    assert snap["error_rate_withheld_below"] == _ERROR_RATE_MIN_SAMPLE


def test_snapshot_tracks_errors_by_code() -> None:
    """snapshot() reports a per-error-code breakdown of failures."""
    from hpo_link.mcp import metrics

    metrics.reset()
    metrics.record("get_term", 1, ok=True)
    metrics.record("get_term", 1, ok=False, error_code="not_found")
    metrics.record("resolve_term", 1, ok=False, error_code="invalid_input")
    metrics.record("resolve_term", 1, ok=False, error_code="not_found")
    snap = metrics.snapshot()
    assert snap["errors_by_code"] == {"invalid_input": 1, "not_found": 2}
    metrics.reset()


def test_record_failure_without_code_is_internal_error() -> None:
    """A failure recorded without an explicit code is bucketed as internal_error."""
    from hpo_link.mcp import metrics

    metrics.reset()
    metrics.record("x", 1, ok=False)
    assert metrics.snapshot()["errors_by_code"] == {"internal_error": 1}
    metrics.reset()


def test_snapshot_errors_by_code_empty_when_no_failures() -> None:
    """No failures -> empty errors_by_code map (still present)."""
    from hpo_link.mcp import metrics

    metrics.reset()
    metrics.record("x", 1, ok=True)
    assert metrics.snapshot()["errors_by_code"] == {}
    metrics.reset()
