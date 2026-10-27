import json
import re
from pathlib import Path

from abaqus_ai_agent.execution.batch import BatchResult
from tools import b28_smoke, runtime_smoke


def _markers_with_run_id(script_path):
    """Emit the passing marker stream bound to the run_id embedded in the
    generated smoke script -- the same binding the real CAE-side script uses."""
    script = Path(script_path).read_text(encoding="utf-8")
    run_id = re.search(r"RUN_ID = '([0-9a-f]+)'", script).group(1)
    stages = [
        {"marker": "model_created"},
        {"marker": "input_written"},
        {"marker": "job_submitted"},
        {"marker": "job_completed", "status": "COMPLETED"},
        {"marker": "odb_exists"},
        {"marker": "odb_opened"},
        {"marker": "required_outputs_present"},
        {"marker": "script_completed", "passed": True},
    ]
    return "".join(
        "AIA_SMOKE_MARKER " + json.dumps(dict(m, run_id=run_id), sort_keys=True) + "\n"
        for m in stages
    )


class _FakeExecutor:
    def __init__(self, launcher, workdir, timeout):
        self.launcher = launcher
        self.workdir = workdir
        self.timeout = timeout

    def run_nogui(self, script_path, timeout=None):
        return BatchResult(
            command=("abaqus", "cae", "noGUI=" + script_path),
            return_code=0,
            stdout=_markers_with_run_id(script_path),
            stderr="",
            workdir=self.workdir,
        )


def test_runtime_smoke_tool_writes_machine_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_smoke, "BatchExecutor", _FakeExecutor)
    output = tmp_path / "evidence.json"
    rc = runtime_smoke.main([
        "--workdir", str(tmp_path),
        "--job-name", "SmokeTool",
        "--timeout", "77",
        "--output", str(output),
    ])

    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["status"] == "pass"
    assert data["process_succeeded"] is True
    assert data["run_id"]
    assert data["harness"]["required_outputs_present"] is True


def test_b28_smoke_wrapper_forwards_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_smoke, "BatchExecutor", _FakeExecutor)
    output = tmp_path / "legacy_evidence.json"
    rc = b28_smoke.main([
        "--workdir", str(tmp_path),
        "--job-name", "SmokeToolLegacy",
        "--timeout", "77",
        "--output", str(output),
    ])

    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["status"] == "pass"
    assert data["process_succeeded"] is True
    assert data["harness"]["required_outputs_present"] is True


def test_stall_exception_still_writes_classified_evidence(tmp_path, monkeypatch):
    """P0-1: a watchdog stall must not skip the JSON evidence write."""
    from abaqus_ai_agent.execution.watchdog import SolverProcessStalledError

    class StallingExecutor(_FakeExecutor):
        def run_nogui(self, script_path, timeout=None):
            raise SolverProcessStalledError("stalled", cmd=("abaqus",), workdir=str(tmp_path))

    monkeypatch.setattr(runtime_smoke, "BatchExecutor", StallingExecutor)
    output = tmp_path / "stalled.json"
    rc = runtime_smoke.main([
        "--workdir", str(tmp_path),
        "--job-name", "SmokeTool",
        "--output", str(output),
    ])

    assert rc == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["status"] == "fail"
    assert data["error_class"] == "SolverProcessStalledError"
    assert data["run_id"]


def test_unexpected_exception_still_writes_evidence(tmp_path, monkeypatch):
    class BrokenExecutor(_FakeExecutor):
        def run_nogui(self, script_path, timeout=None):
            raise ValueError("unexpected defect")

    monkeypatch.setattr(runtime_smoke, "BatchExecutor", BrokenExecutor)
    output = tmp_path / "broken.json"
    rc = runtime_smoke.main([
        "--workdir", str(tmp_path), "--job-name", "SmokeTool", "--output", str(output),
    ])
    assert rc == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["error_class"] == "ValueError"


def test_stale_rpy_from_earlier_run_cannot_pass_current_run(tmp_path, monkeypatch):
    """P0-3: an old abaqus.rpy without this run_id must not rescue a pass."""

    class SilentExecutor(_FakeExecutor):
        def run_nogui(self, script_path, timeout=None):
            # CAE captured stdout: no markers on the stream at all.
            return BatchResult(
                command=("abaqus", "cae", "noGUI=" + script_path),
                return_code=0, stdout="", stderr="", workdir=self.workdir,
            )

    # A previous run left a fully-passing rpy behind (legacy markers, no run_id).
    stale = "\n".join(
        "AIA_SMOKE_MARKER " + json.dumps(m)
        for m in (
            {"marker": "model_created"},
            {"marker": "input_written"},
            {"marker": "job_submitted"},
            {"marker": "job_completed", "status": "COMPLETED"},
            {"marker": "odb_exists"},
            {"marker": "odb_opened"},
            {"marker": "required_outputs_present"},
            {"marker": "script_completed", "passed": True},
        )
    )
    (tmp_path / "abaqus.rpy.1").write_text(stale, encoding="utf-8")

    monkeypatch.setattr(runtime_smoke, "BatchExecutor", SilentExecutor)
    output = tmp_path / "evidence.json"
    rc = runtime_smoke.main([
        "--workdir", str(tmp_path), "--job-name", "SmokeTool", "--output", str(output),
    ])

    assert rc == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["status"] == "fail"
    assert data["rpy_fallback"], "the rpy fallback must record its diagnostics"
    assert not any(entry.get("passed") for entry in data["rpy_fallback"])


def test_unsettled_artifacts_block_pass(tmp_path, monkeypatch):
    """P1-4: launcher rc=0 with still-changing artifacts is not a pass."""

    class EarlyExitExecutor(_FakeExecutor):
        def run_nogui(self, script_path, timeout=None):
            return BatchResult(
                command=("abaqus", "cae", "noGUI=" + script_path),
                return_code=0,
                stdout=_markers_with_run_id(script_path),
                stderr="",
                workdir=self.workdir,
                settled=False,
                settle_note="workdir still changing after launcher exit",
            )

    monkeypatch.setattr(runtime_smoke, "BatchExecutor", EarlyExitExecutor)
    output = tmp_path / "evidence.json"
    rc = runtime_smoke.main([
        "--workdir", str(tmp_path), "--job-name", "SmokeTool", "--output", str(output),
    ])

    assert rc == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["process_succeeded"] is True
    assert data["artifacts_settled"] is False
    assert data["status"] == "fail"
