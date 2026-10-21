"""Global pytest session lifecycle and workspace hygiene."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

# Explicit Test Mode Marker (Contract: Never rely on Mock/Dummy class names in production)
os.environ.setdefault("ABAQUS_AGENT_TEST_MODE", "1")
# Tests may read committed evidence. They must not rewrite it.
os.environ.setdefault("ABAQUS_AGENT_EVIDENCE_READONLY", "1")
# Isolated ephemeral runs directory for test sessions to avoid sandbox AppData conflicts
_test_runs_base = Path(tempfile.gettempdir()) / "abaqus_agent_pytest" / "runs"
_test_runs_base.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ABAQUS_AGENT_RUNS_DIR", str(_test_runs_base))
# Extraction result cache is machine-local derived state. Tests must not read or
# write the cache a real user run would use, otherwise a leftover entry from a
# previous session silently satisfies a later extraction.
_result_cache_base = Path(tempfile.gettempdir()) / "abaqus_agent_pytest" / "result_cache"
_owns_result_cache_env = "ABAQUS_AGENT_RESULT_CACHE_DIR" not in os.environ
if _owns_result_cache_env:
    os.environ["ABAQUS_AGENT_RESULT_CACHE_DIR"] = str(_result_cache_base)


@pytest.fixture(scope="session", autouse=True)
def isolated_result_cache():
    """Start every test session with an empty extraction cache."""
    if _owns_result_cache_env:
        shutil.rmtree(_result_cache_base, ignore_errors=True)
    _result_cache_base.mkdir(parents=True, exist_ok=True)
    yield _result_cache_base


@pytest.fixture(scope="session", autouse=True)
def clean_ephemeral_test_runs():
    """Ensure test runs leave no orphan empty directories or replay files."""
    yield
    repo_root = Path(__file__).resolve().parent.parent
    runs_dir = repo_root / "runs"
    if runs_dir.exists():
        for d in sorted(runs_dir.glob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass
    # Clean any accidental root abaqus.rpy or mock dirs
    for rpy in repo_root.glob("abaqus.rpy*"):
        try:
            rpy.unlink()
        except OSError:
            pass
    mock_dir = repo_root / "MagicMock"
    if mock_dir.exists():
        shutil.rmtree(mock_dir, ignore_errors=True)


def _evidence_snapshot() -> tuple[str, ...] | None:
    """Capture tracked evidence state relative to HEAD.

    The comparison in ``pytest_sessionfinish`` is between session start and end, not
    against a clean HEAD: a developer may legitimately start a run with intentional
    evidence edits, and those must not be reported as test-time rewrites.
    """
    from abaqus_ai_agent.evidence_guard import EvidenceRewriteError, tracked_evidence_dirty

    try:
        return tuple(sorted(tracked_evidence_dirty()))
    except EvidenceRewriteError:
        return None


@pytest.fixture(scope="session", autouse=True)
def evidence_baseline_snapshot():
    """Record the pre-existing evidence state before any test runs."""
    pytest._evidence_baseline = _evidence_snapshot()
    yield


def _has_physical_abaqus() -> bool:
    import shutil
    return bool(
        shutil.which("abaqus")
        or shutil.which("abaqus.bat")
        or Path(r"C:\SIMULIA\Commands\abaqus.bat").exists()
    )


def pytest_collection_modifyitems(config, items):
    unit_marker = pytest.mark.unit
    smoke_marker = pytest.mark.smoke
    acceptance_marker = pytest.mark.acceptance
    live_marker = pytest.mark.live

    for item in items:
        existing = {m.name for m in item.iter_markers()}

        # 1. Live tests (requires physical Abaqus launcher execution)
        is_evidence_audit = any(k in item.name.lower() for k in ("manifest", "integrity", "audit", "envelope", "json"))
        is_live = (
            (
                "live" in existing
                or "live_abaqus" in item.name.lower()
                or item.name.endswith("_real_machine")
                or "h6_image_intent_grounding_e2e" in item.nodeid
            )
            and not is_evidence_audit
        )
        if is_live:
            item.add_marker(live_marker)
            item.add_marker(acceptance_marker)
            continue

        # 2. Smoke tests
        is_smoke = "smoke" in existing or "smoke" in item.name.lower() or "smoke" in str(item.fspath).lower()
        if is_smoke:
            item.add_marker(smoke_marker)

        # 3. Acceptance / benchmark / golden / qualification / e2e
        is_acceptance = (
            "acceptance" in existing
            or "acceptance" in str(item.fspath).lower()
            or "golden" in str(item.fspath).lower()
            or "benchmark" in str(item.fspath).lower()
            or "qualification" in str(item.fspath).lower()
            or "e2e" in str(item.fspath).lower()
        )
        if is_acceptance:
            item.add_marker(acceptance_marker)

        # 4. All offline tests receive the unit marker so `pytest -m unit` runs full offline suite
        item.add_marker(unit_marker)


def pytest_runtest_setup(item):
    """Enforce physical environment check for live runs without physical Abaqus."""
    if item.get_closest_marker("live"):
        if not _has_physical_abaqus():
            pytest.skip("[BLOCKED] Physical Abaqus environment not detected")


def pytest_sessionfinish(session, exitstatus):
    """Fail the session if a test rewrote tracked evidence despite the read-only guard."""
    baseline = getattr(pytest, "_evidence_baseline", None)
    after = _evidence_snapshot()
    if baseline is None or after is None:
        return

    newly_dirty = tuple(sorted(set(after) - set(baseline)))
    if not newly_dirty:
        return

    session.exitstatus = 1
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    message = "Tracked evidence was rewritten during tests:\n" + "\n".join(newly_dirty)
    if reporter is not None:
        reporter.write_line(message, red=True)
    else:
        print(message)
