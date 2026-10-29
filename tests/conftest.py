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


def _probe_physical_abaqus_environment() -> tuple[str, bool, str]:
    """Probe physical Abaqus availability and classify readiness status.

    Returns:
        (status_code, is_ready, reason_message)
    Possible status_codes:
    - LAUNCHER_MISSING: abaqus executable not found in PATH or standard installation
    - LAUNCHER_FOUND_PROBE_FAILED: launcher exists but fundamental probe failed
    - LAUNCHER_READY: CLI launcher release probe succeeded (information=release returned 0).
      IMPORTANT: This confirms CLI launcher availability, but DOES NOT prove license
      token availability or successful FEA solving. Real license connectivity and solver
      acceptance must be verified by Tier 2 Smoke single-brick execution.
    - LICENSE_UNAVAILABLE: license server unreachable or token exhausted
    - ENVIRONMENT_READY: legacy alias for LAUNCHER_READY
    - SMOKE_SOLVE_PASSED: Tier 2 Smoke single-brick solve completed and verified
    """
    import shutil
    import subprocess

    launcher = (
        os.environ.get("ABAQUS_BAT")
        or os.environ.get("ABAQUS_COMMAND")
        or shutil.which("abaqus")
        or shutil.which("abaqus.bat")
    )

    if not launcher:
        return (
            "LAUNCHER_MISSING",
            False,
            "Physical Abaqus launcher not found in ABAQUS_BAT, ABAQUS_COMMAND, or PATH",
        )

    # Launcher exists; verify it responds to informational probe
    try:
        res = subprocess.run(
            [launcher, "information=release"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            return ("LAUNCHER_READY", True, f"Abaqus launcher ready: {launcher}")
        return (
            "LAUNCHER_FOUND_PROBE_FAILED",
            False,
            f"Abaqus launcher probe returned non-zero ({res.returncode}): {res.stderr.strip()[:200]}",
        )
    except subprocess.TimeoutExpired:
        return (
            "LAUNCHER_FOUND_PROBE_FAILED",
            False,
            "Abaqus information probe timed out after 10s",
        )
    except Exception as exc:
        return (
            "LAUNCHER_FOUND_PROBE_FAILED",
            False,
            f"Failed to probe Abaqus launcher: {exc!r}",
        )


def _has_physical_abaqus() -> bool:
    code, ready, _ = _probe_physical_abaqus_environment()
    return ready


def _record_live_gate_audit(nodeid: str, test_name: str, verdict: str, probe_status: str, reason: str) -> None:
    """Record an audit trail of live environment gate decisions to runs/live_environment_gate.json."""
    import json
    import time

    repo_root = Path(__file__).resolve().parent.parent
    gate_file = repo_root / "runs" / "live_environment_gate.json"
    gate_file.parent.mkdir(parents=True, exist_ok=True)

    records = {}
    if gate_file.exists():
        try:
            records = json.loads(gate_file.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                records = {}
        except Exception:
            records = {}

    records[nodeid] = {
        "nodeid": nodeid,
        "test_name": test_name,
        "verdict": verdict,
        "probe_status": probe_status,
        "reason": reason,
        "timestamp": time.time(),
    }

    try:
        gate_file.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


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
            # Strictly exclusive: Live tests are acceptance tests requiring real hardware, never unit tests
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

        # 4. Strict partitioning: only tests that are NOT live, NOT smoke, and NOT acceptance receive unit marker
        if not (is_smoke or is_acceptance):
            item.add_marker(unit_marker)


def pytest_runtest_setup(item):
    """Enforce physical environment check for live runs without physical Abaqus."""
    if item.get_closest_marker("live"):
        code, ready, reason = _probe_physical_abaqus_environment()
        if not ready:
            _record_live_gate_audit(
                nodeid=item.nodeid,
                test_name=item.name,
                verdict="BLOCKED",
                probe_status=code,
                reason=reason,
            )
            pytest.skip(f"[BLOCKED] {reason} (probe_status={code})")


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
