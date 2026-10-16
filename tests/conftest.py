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
_test_runs_base = Path(tempfile.gettempdir()) / "abaqus_agent_pytest_runs"
_test_runs_base.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ABAQUS_AGENT_RUNS_DIR", str(_test_runs_base))


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


def pytest_sessionfinish(session, exitstatus):
    """Fail the session if a test rewrote tracked evidence despite the read-only guard."""
    from abaqus_ai_agent.evidence_guard import (
        EvidenceRewriteError,
        tracked_evidence_dirty,
    )

    try:
        dirty = tracked_evidence_dirty()
    except EvidenceRewriteError:
        return
    if dirty:
        session.exitstatus = 1
        reporter = session.config.pluginmanager.getplugin("terminalreporter")
        message = "Tracked evidence was rewritten during tests:\n" + "\n".join(dirty)
        if reporter is not None:
            reporter.write_line(message, red=True)
        else:
            print(message)
