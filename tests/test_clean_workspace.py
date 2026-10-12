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
    assert c.protection_decision == "UNPROTECTED_EPHEMERAL_CANDIDATE"


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
    assert data["candidates"][0]["protection_decision"] == "UNPROTECTED_EPHEMERAL_CANDIDATE"
    assert len(data["candidates"][0]["sha256"]) == 64


def test_clean_aborts_on_content_tampering_with_same_size(tmp_path, monkeypatch):
    """When a candidate's content is tampered with exact same byte size, SHA-256 check must abort deletion."""
    root = tmp_path / "repo"
    root.mkdir()
    runs_dir = root / "runs" / "run_tamper"
    runs_dir.mkdir(parents=True)

    log_file = runs_dir / "Job-tamper.log"
    initial_bytes = b"ORIGINAL_SOLVER_LOG_BYTES_0001"
    log_file.write_bytes(initial_bytes)

    # Initialize a git repo so git ls-files succeeds
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    # Collect candidates
    candidates, _, _ = collect_candidates(root, set())
    assert len(candidates) == 1
    c = candidates[0]
    assert c.size == len(initial_bytes)
    assert c.sha256 == compute_sha256(log_file)

    # Tamper file with EXACT same byte size but different content
    tampered_bytes = b"TAMPERED_OUTPUT_LOG_BYTES_0001"
    assert len(tampered_bytes) == len(initial_bytes)
    log_file.write_bytes(tampered_bytes)
    assert log_file.stat().st_size == len(initial_bytes)
    assert compute_sha256(log_file) != c.sha256

    # Mock collect_candidates to return the candidate captured prior to tampering
    from scripts.clean_workspace import main
    monkeypatch.setattr(
        "scripts.clean_workspace.collect_candidates",
        lambda r, t: ([c], [], 0),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["clean_workspace.py", "--root", str(root), "--clean"],
    )
    rc = main()
    # Must fail/return 1 due to safety abort
    assert rc == 1
    # File must NOT be deleted
    assert log_file.is_file()
    assert log_file.read_bytes() == tampered_bytes


def test_clean_aborts_on_path_outside_root(tmp_path, monkeypatch):
    """Candidate located outside the repository root must trigger path boundary abort."""
    root = tmp_path / "repo"
    root.mkdir()
    outside_file = tmp_path / "outside.log"
    outside_file.write_bytes(b"outside")

    c = Candidate(
        path=outside_file,
        scope="external",
        size=len(b"outside"),
        sha256=compute_sha256(outside_file),
        reason="test outside",
    )

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    from scripts.clean_workspace import main
    monkeypatch.setattr("scripts.clean_workspace.collect_candidates", lambda r, t: ([c], [], 0))
    monkeypatch.setattr("sys.argv", ["clean_workspace.py", "--root", str(root), "--clean"])

    rc = main()
    assert rc == 1
    assert outside_file.is_file()


def test_clean_aborts_on_empty_or_failed_hash(tmp_path, monkeypatch):
    """C6 contract: when candidate hash is empty or recomputation returns empty, clean must abort."""
    root = tmp_path / "repo"
    root.mkdir()
    runs_dir = root / "runs" / "run_empty_hash"
    runs_dir.mkdir(parents=True)
    log_file = runs_dir / "Job.log"
    log_file.write_bytes(b"some solver output")

    # Case 1: Candidate with empty sha256
    c_empty = Candidate(
        path=log_file,
        scope="runs",
        size=len(b"some solver output"),
        sha256="",
        reason="empty hash test",
    )

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    from scripts.clean_workspace import main
    monkeypatch.setattr("scripts.clean_workspace.collect_candidates", lambda r, t: ([c_empty], [], 0))
    monkeypatch.setattr("sys.argv", ["clean_workspace.py", "--root", str(root), "--clean"])

    rc = main()
    assert rc == 1
    assert log_file.is_file(), "File must not be deleted if candidate hash is empty"

    # Case 2: Recomputation fails (returns empty string)
    c_valid = Candidate(
        path=log_file,
        scope="runs",
        size=len(b"some solver output"),
        sha256=compute_sha256(log_file),
        reason="recomputation failure test",
    )
    monkeypatch.setattr("scripts.clean_workspace.collect_candidates", lambda r, t: ([c_valid], [], 0))
    # Mock compute_sha256 during deletion to return empty string (simulating read failure)
    monkeypatch.setattr("scripts.clean_workspace.compute_sha256", lambda p: "")

    rc = main()
    assert rc == 1
    assert log_file.is_file(), "File must not be deleted if sha256 recomputation fails"


def test_clean_aborts_when_root_is_not_git_toplevel(tmp_path):
    """C2 contract: execution must abort fail-closed if --root is not the Git repository toplevel."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)

    sub_dir = repo_root / "subdir"
    sub_dir.mkdir()

    with pytest.raises(RuntimeError) as exc_info:
        get_tracked_paths(sub_dir)
    assert "Fail-closed safety trigger" in str(exc_info.value)
    assert "is not the Git repository toplevel root" in str(exc_info.value)


def test_clean_skips_symlinks(tmp_path, monkeypatch):
    """C3 contract: candidate paths that are symlinks must be rejected/skipped and abort deletion."""
    root = tmp_path / "repo"
    root.mkdir()
    runs_dir = root / "runs" / "run_symlink"
    runs_dir.mkdir(parents=True)
    log_file = runs_dir / "Job.log"
    log_file.write_bytes(b"ephemeral log")

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    # 1. In collect_candidates, a symlink must be ignored
    orig_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: True if self.name == "Job.log" else orig_is_symlink(self))
    candidates, _, _ = collect_candidates(root, set())
    assert not any(c.path.name == "Job.log" for c in candidates), "Symlinks must be skipped in collect_candidates"

    # 2. In execution phase, if candidate is detected as symlink, deletion must abort with failure
    c = Candidate(
        path=log_file,
        scope="runs",
        size=len(b"ephemeral log"),
        sha256=compute_sha256(log_file),
        reason="symlink test",
    )
    from scripts.clean_workspace import main
    monkeypatch.setattr("scripts.clean_workspace.collect_candidates", lambda r, t: ([c], [], 0))
    monkeypatch.setattr("sys.argv", ["clean_workspace.py", "--root", str(root), "--clean"])

    rc = main()
    assert rc == 1, "Exit code must be 1 on symlink abort"
    assert log_file.is_file(), "Symlink target must not be deleted"


def test_clean_preserves_cache_dir_with_protected_file(tmp_path):
    """C7 contract: cache directories containing protected files (.py, .json, etc.) must NEVER be collected or deleted."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    cache_dir = root / "__pycache__"
    cache_dir.mkdir()
    bytecode = cache_dir / "module.cpython-312.pyc"
    bytecode.write_bytes(b"dummy bytecode")

    # Inject a protected script into __pycache__
    protected_script = cache_dir / "critical_tool.py"
    protected_script.write_text("print('critical')", encoding="utf-8")

    candidates, cache_dirs, _ = collect_candidates(root, set())
    assert cache_dir not in cache_dirs, "Cache dir with protected files must NOT be in cache_dirs"
    assert not any(c.path == protected_script for c in candidates), "Protected file must NOT be a candidate"

    # Also test .pytest_cache with protected markdown / json
    pytest_cache = root / ".pytest_cache"
    pytest_cache.mkdir()
    protected_notes = pytest_cache / "notes.md"
    protected_notes.write_text("# Important notes", encoding="utf-8")

    _, cache_dirs2, _ = collect_candidates(root, set())
    assert pytest_cache not in cache_dirs2, ".pytest_cache with protected file must NOT be in cache_dirs"


def test_clean_returns_error_on_dir_deletion_failure(tmp_path, monkeypatch):
    """C9 contract: directory deletion failures must be counted and return non-zero exit code."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    cache_dir = root / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "test.pyc").write_bytes(b"bytecode")

    from scripts.clean_workspace import main
    monkeypatch.setattr("scripts.clean_workspace.collect_candidates", lambda r, t: ([], [cache_dir], 0))
    monkeypatch.setattr("sys.argv", ["clean_workspace.py", "--root", str(root), "--clean"])

    def mock_rmtree(d):
        raise OSError("Simulated permission denied deleting directory")

    monkeypatch.setattr("shutil.rmtree", mock_rmtree)

    rc = main()
    assert rc == 1, "Exit code must be 1 when directory deletion fails"


def test_clean_returns_error_on_manifest_export_failure(tmp_path, monkeypatch):
    """C8 contract: manifest export failure must abort with non-zero exit code."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    from scripts.clean_workspace import main
    monkeypatch.setattr("sys.argv", ["clean_workspace.py", "--root", str(root), "--export-manifest", "invalid/path/manifest.json"])

    def mock_open(*args, **kwargs):
        raise OSError("Disk full / permission denied")

    monkeypatch.setattr("builtins.open", mock_open)

    rc = main()
    assert rc == 1, "Exit code must be 1 when manifest export fails"


def test_clean_preserves_machine_validation_ephemeral_assets(tmp_path, monkeypatch):
    """C4 contract: machine_validation/ must be completely protected from candidate scanning and deletion,
    even if it contains untracked solver ephemeral artifacts (.odb, .log, .sta, .dat, .msg, .env)."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    mv_dir = root / "machine_validation" / "historical_workdir"
    mv_dir.mkdir(parents=True)

    odb_file = mv_dir / "Job-benchmark.odb"
    odb_file.write_bytes(b"critical benchmark odb data")

    log_file = mv_dir / "Job-benchmark.log"
    log_file.write_text("critical solver log", encoding="utf-8")

    sta_file = mv_dir / "Job-benchmark.sta"
    sta_file.write_text("critical status file", encoding="utf-8")

    dat_file = mv_dir / "Job-benchmark.dat"
    dat_file.write_text("critical dat file", encoding="utf-8")

    msg_file = mv_dir / "Job-benchmark.msg"
    msg_file.write_text("critical diagnostic msg", encoding="utf-8")

    # 1. Verification in collect_candidates: untracked artifacts in machine_validation must NOT be candidates
    candidates, cache_dirs, _ = collect_candidates(root, set())
    assert len(candidates) == 0, f"Expected 0 candidates from machine_validation, got {len(candidates)}"
    assert len(cache_dirs) == 0, f"Expected 0 cache_dirs from machine_validation, got {len(cache_dirs)}"

    # 2. Execution phase with --clean: files must remain completely untouched
    from scripts.clean_workspace import main
    monkeypatch.setattr("sys.argv", ["clean_workspace.py", "--root", str(root), "--clean"])

    rc = main()
    assert rc == 0
    assert odb_file.is_file(), "Untracked ODB in machine_validation must NOT be deleted"
    assert odb_file.read_bytes() == b"critical benchmark odb data"
    assert log_file.is_file(), "Untracked LOG in machine_validation must NOT be deleted"
    assert sta_file.is_file(), "Untracked STA in machine_validation must NOT be deleted"
    assert dat_file.is_file(), "Untracked DAT in machine_validation must NOT be deleted"
    assert msg_file.is_file(), "Untracked MSG in machine_validation must NOT be deleted"
