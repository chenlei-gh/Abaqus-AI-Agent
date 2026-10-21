"""Timing-plumbing contract tests (task graph A1 / A3).

Layer of evidence: **unit only**. These prove the fields are populated from real
measurements and default to "not measured" rather than zero. They do not measure
a real Abaqus solve or a real license server.

Deliberately NOT asserted here:
  - any absolute duration for a real solve or license queue;
  - that ``AnalysisRunner`` emits these values (it is not wired, by decision);
  - behaviour of a real FlexNet/DSLS server under contention.
"""

from __future__ import annotations

import time

import pytest

from abaqus_ai_agent.execution.batch import BatchResult
from abaqus_ai_agent.execution.license import (
    LicenseProvider,
    LicenseHandle,
    MockLicenseProvider,
)
from abaqus_ai_agent.execution.queue import (
    AnalysisRunQueue,
    QueueItemState,
    RunResourceSpec,
)


# ---------------------------------------------------------------------------
# A1: BatchResult carries the watchdog's own measurement
# ---------------------------------------------------------------------------

def test_batch_result_duration_defaults_to_not_measured():
    """Hand-built results must not claim "took zero seconds"."""
    result = BatchResult(command=("abaqus", "job=x"), return_code=0)
    assert result.duration is None
    assert result.get("duration") is None


def test_batch_result_duration_is_preserved_verbatim():
    result = BatchResult(
        command=("abaqus", "job=x"), return_code=0, duration=12.5
    )
    assert result.duration == pytest.approx(12.5)


def test_batch_result_keeps_its_mapping_compatibility():
    """Existing dict-style consumers must keep working unchanged."""
    result = BatchResult(
        command=("abaqus", "job=x"), return_code=0, stdout="out",
        stderr="err", workdir="C:/tmp", duration=3.0,
    )
    assert result["returncode"] == 0
    assert result["return_code"] == 0
    assert result["stdout"] == "out"
    assert result["duration"] == pytest.approx(3.0)
    assert result.get("missing", "fallback") == "fallback"
    assert result.succeeded


def test_zero_duration_is_distinct_from_none():
    """A genuine instant result is 0.0 (measured); absence is None."""
    instant = BatchResult(command=("x",), return_code=0, duration=0.0)
    absent = BatchResult(command=("x",), return_code=0)
    assert instant.duration == 0.0
    assert absent.duration is None


# ---------------------------------------------------------------------------
# A3: license queue time is reported, not inferred
# ---------------------------------------------------------------------------

class _SlowProvider(LicenseProvider):
    """Provider that takes a known amount of time to grant a token."""

    def __init__(self, delay: float = 0.05, grant: bool = True):
        self.delay = delay
        self.grant = grant

    def available_tokens(self, feature="standard"):
        return 1 if self.grant else 0

    def reserve(self, feature="standard", tokens=1, timeout=0.0):
        time.sleep(self.delay)
        if not self.grant:
            return None
        return LicenseHandle(
            handle_id="h1", feature=feature, tokens=tokens,
            provider_name="SlowProvider",
        )

    def release(self, handle):
        return True

    def health(self):
        from abaqus_ai_agent.execution.license import LicenseHealthStatus
        return LicenseHealthStatus(
            healthy=True, server="test", available_tokens=1, total_tokens=1
        )


def test_license_context_reports_wait_time():
    provider = _SlowProvider(delay=0.05)
    ctx = provider.acquire(timeout=5.0)
    with ctx:
        pass
    assert ctx.wait_seconds is not None
    assert ctx.wait_seconds >= 0.04


def test_license_context_wait_is_none_when_acquisition_fails():
    """A failed acquisition has no queue time worth claiming."""
    provider = _SlowProvider(delay=0.01, grant=False)
    ctx = provider.acquire(timeout=0.1)
    with pytest.raises(TimeoutError):
        with ctx:
            pass
    assert ctx.wait_seconds is None


def test_unlimited_local_provider_still_records_a_wait():
    """Local provider grants immediately; the wait is a real, tiny measurement."""
    provider = MockLicenseProvider()
    ctx = provider.acquire(timeout=1.0)
    with ctx:
        pass
    assert ctx.wait_seconds is not None
    assert ctx.wait_seconds >= 0.0


def test_queue_item_records_license_wait_from_enqueue():
    """T3 in the queue path: measured from enqueue, including backoff paid."""
    queue = AnalysisRunQueue(max_concurrency=2, license_provider=MockLicenseProvider())
    item = queue.enqueue(
        payload={"k": "v"},
        resources=RunResourceSpec(feature="standard", tokens=1),
    )
    assert item.license_wait_seconds is None

    dispatched = queue.process_next(current_time=item.enqueued_at + 3.0)
    assert dispatched is not None
    assert dispatched.state is QueueItemState.RUNNING
    assert dispatched.license_wait_seconds == pytest.approx(3.0)
    assert dispatched.to_dict()["license_wait_seconds"] == pytest.approx(3.0)


def test_queue_item_wait_starts_as_not_measured():
    """Pending items must not report a fabricated zero."""
    queue = AnalysisRunQueue(max_concurrency=2)
    assert queue.process_next() is None
    for it in queue.list_items():
        assert it.license_wait_seconds is None
