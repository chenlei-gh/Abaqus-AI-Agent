"""Global pytest session lifecycle and workspace hygiene."""

import shutil
from pathlib import Path
import pytest


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
