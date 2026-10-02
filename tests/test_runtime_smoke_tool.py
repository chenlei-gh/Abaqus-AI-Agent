import json

from abaqus_ai_agent.execution.batch import BatchResult
from tools import b28_smoke, runtime_smoke


def test_runtime_smoke_tool_writes_machine_evidence(tmp_path, monkeypatch):
    class FakeExecutor:
        def __init__(self, launcher, workdir, timeout):
            self.launcher = launcher
            self.workdir = workdir
            self.timeout = timeout

        def run_nogui(self, script_path, timeout=None):
            assert script_path.endswith("SmokeTool_script.py")
            assert timeout == 77
            return BatchResult(
                command=("abaqus", "cae", "noGUI=" + script_path),
                return_code=0,
                stdout='AIA_SMOKE_MARKER {"marker":"model_created"}\n'
                        'AIA_SMOKE_MARKER {"marker":"input_written"}\n'
                        'AIA_SMOKE_MARKER {"marker":"job_submitted"}\n'
                        'AIA_SMOKE_MARKER {"marker":"job_completed","status":"COMPLETED"}\n'
                        'AIA_SMOKE_MARKER {"marker":"odb_exists"}\n'
                        'AIA_SMOKE_MARKER {"marker":"odb_opened"}\n'
                        'AIA_SMOKE_MARKER {"marker":"required_outputs_present"}\n'
                        'AIA_SMOKE_MARKER {"marker":"script_completed","passed":true}\n',
                stderr="",
                workdir=self.workdir,
            )

    monkeypatch.setattr(runtime_smoke, "BatchExecutor", FakeExecutor)
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
    assert data["harness"]["required_outputs_present"] is True


def test_b28_smoke_wrapper_forwards_cleanly(tmp_path, monkeypatch):
    class FakeExecutor:
        def __init__(self, launcher, workdir, timeout):
            self.launcher = launcher
            self.workdir = workdir
            self.timeout = timeout

        def run_nogui(self, script_path, timeout=None):
            return BatchResult(
                command=("abaqus", "cae", "noGUI=" + script_path),
                return_code=0,
                stdout='AIA_B28_MARKER {"marker":"model_created"}\n'
                        'AIA_B28_MARKER {"marker":"input_written"}\n'
                        'AIA_B28_MARKER {"marker":"job_submitted"}\n'
                        'AIA_B28_MARKER {"marker":"job_completed","status":"COMPLETED"}\n'
                        'AIA_B28_MARKER {"marker":"odb_exists"}\n'
                        'AIA_B28_MARKER {"marker":"odb_opened"}\n'
                        'AIA_B28_MARKER {"marker":"required_outputs_present"}\n'
                        'AIA_B28_MARKER {"marker":"script_completed","passed":true}\n',
                stderr="",
                workdir=self.workdir,
            )

    monkeypatch.setattr(runtime_smoke, "BatchExecutor", FakeExecutor)
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
