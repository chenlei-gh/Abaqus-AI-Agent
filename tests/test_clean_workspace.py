"""Unit tests verifying the fail-closed security guarantees of clean_workspace.py."""

import json
import subprocess
from pathlib import Path
import pytest

from scripts.clean_workspace import (
    collect_candidates,
    get_tracked_paths,
    Candidate,
    compute_sha256,
)


def test_get_tracked_paths_fail_closed(tmp_path):
    """When Git execution fails or is not a git repo, fail-closed RuntimeError MUST be raised."""
    non_repo = tmp_path / "not_a_git_repo"
    non_repo.mkdir()
    with pytest.raises(RuntimeError) as exc_info:
        get_tracked_paths(non_repo)
    assert "Fail-closed safety trigger" in str(exc_info.value)


def test_runs_dir_strict_protection(tmp_path):
    """Untracked .py, .json, .html, and images in runs/ MUST be protected."""
    root = tmp_path / "repo"
    root.mkdir()
    runs_dir = root / "runs" / "test_run_1"
    runs_dir.mkdir(parents=True)

    # Protected assets in runs/
    script_file = runs_dir / "reproduce_case.py"
    script_file.write_text("print('critical script')", encoding="utf-8")

    evidence_file = runs_dir / "run_evidence.json"
    evidence_file.write_text("{}", encoding="utf-8")

    report_file = runs_dir / "report.html"
    report_file.write_text("<html></html>", encoding="utf-8")

    image_file = runs_dir / "contour.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    unknown_file = runs_dir / "custom.unknown_ext"
    unknown_file.write_text("unknown data", encoding="utf-8")

    # Cleanable ephemeral solver artifacts in runs/
    odb_file = runs_dir / "Job-1.odb"
    odb_file.write_bytes(b"dummy odb")

    log_file = runs_dir / "Job-1.log"
    log_file.write_text("solver log", encoding="utf-8")

    sta_file = runs_dir / "Job-1.sta"
    sta_file.write_text("status file", encoding="utf-8")

    tracked: set[str] = set()  # nothing is tracked

    candidates, cache_dirs, _ = collect_candidates(root, tracked)
    candidate_names = {c.path.name for c in candidates}

    # Protected files MUST NOT be candidates
    assert "reproduce_case.py" not in candidate_names
    assert "run_evidence.json" not in candidate_names
    assert "report.html" not in candidate_names
    assert "contour.png" not in candidate_names
    assert "custom.unknown_ext" not in candidate_names

    # Solver artifacts MUST be candidates
    assert "Job-1.odb" in candidate_names
    assert "Job-1.log" in candidate_names
    assert "Job-1.sta" in candidate_names


def test_candidate_sha256_and_manifest_structure(tmp_path):
    """Candidates must record SHA-256 and support structured manifest serialization."""
    root = tmp_path / "repo"
    root.mkdir()
    runs_dir = root / "runs" / "run_2"
    runs_dir.mkdir(parents=True)

    test_content = b"sample transient solver log data"
    test_artifact = runs_dir / "job.log"
    test_artifact.write_bytes(test_content)

    expected_sha = compute_sha256(test_artifact)
    assert len(expected_sha) == 64

    candidates, _, _ = collect_candidates(root, set())
    assert len(candidates) == 1
    c = candidates[0]
    assert c.path.name == "job.log"
    assert c.sha256 == expected_sha
    assert c.size == len(test_content)
    assert c.scope == "runs"
    assert c.risk_level == "SAFE_PURGE_IF_AUTHORIZED"


def test_clean_workspace_cli_dry_run_and_manifest_export(tmp_path):
    """Running main() with --export-manifest must export valid JSON without deleting files."""
    root = tmp_path / "repo"
    root.mkdir()
    runs_dir = root / "runs" / "run_3"
    runs_dir.mkdir(parents=True)

    log_file = runs_dir / "analysis.log"
    log_file.write_text("sim log", encoding="utf-8")

    manifest_out = tmp_path / "audit_manifest.json"

    # We mock get_tracked_paths by monkeypatching or testing via subprocess if git initialized
    # Let's initialize a minimal git repo so real git commands succeed
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "clean_workspace.py"
    res = subprocess.run(
        [
            "python",
            str(script_path),
            "--root",
            str(root),
            "--export-manifest",
            str(manifest_out),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "[DRY-RUN]" in res.stdout
    assert log_file.is_file()  # file not deleted

    assert manifest_out.is_file()
    with open(manifest_out, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["candidate_count"] == 1
    assert data["candidates"][0]["relative_path"] == "runs/run_3/analysis.log"
    assert len(data["candidates"][0]["sha256"]) == 64
