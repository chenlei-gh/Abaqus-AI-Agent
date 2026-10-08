import os
import shutil
from pathlib import Path
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner, AnalysisRunState
from abaqus_ai_agent.execution.batch import BatchExecutor


class DummyMockExecutor:
    """Mock executor recording chdir and execution without touching root."""
    def __init__(self):
        self.workdir = None
        self.commands = []

    def snapshot(self):
        return None

    def execute(self, code, timeout=120):
        self.commands.append(code)
        if "os.path.exists" in code:
            return ""
        return ""


def test_analysis_runner_auto_sandbox_isolation(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    mock_exec = DummyMockExecutor()
    runner = AnalysisRunner(mock_exec)

    # Execute run without providing workdir
    run_res = runner.run(
        model_name="Model-AutoSandbox",
        job_name="Job_AutoSandboxTest",
        result_values={"max_stress": 120.0},
    )

    # 1. Verification of execution and command history
    assert run_res is not None
    chdir_cmds = [cmd for cmd in mock_exec.commands if "os.chdir" in cmd]
    assert len(chdir_cmds) >= 1
    # Check that os.chdir pointed to runs/<run_id>
    assert "runs" in chdir_cmds[0]

    run_id = run_res.id
    assigned_dir = repo_root / "runs" / run_id
    # 2. Verify workdir was created under runs/<run_id>
    assert assigned_dir.exists()

    # 3. Verify project root has zero temporary job artifacts
    root_artifacts = list(repo_root.glob("Job_AutoSandboxTest.*"))
    assert len(root_artifacts) == 0

    # Cleanup the created run directory
    if assigned_dir.exists():
        shutil.rmtree(assigned_dir)


def test_batch_executor_auto_sandbox_isolation():
    batch = BatchExecutor(launcher="echo")
    assert batch.workdir is None

    # Simulate run
    res = batch._run(["echo", "hello"])
    assert res.succeeded
    assert batch.workdir is not None

    assigned_dir = Path(batch.workdir)
    assert assigned_dir.exists()
    assert "runs" in assigned_dir.parts

    # Cleanup
    if assigned_dir.exists():
        shutil.rmtree(assigned_dir)


def test_batch_executor_redirects_explicit_repo_root_workdir():
    repo_root = Path(__file__).resolve().parent.parent
    # User passes repo root as workdir
    batch = BatchExecutor(launcher="echo", workdir=str(repo_root))
    res = batch._run(["echo", "hello"])
    assert res.succeeded
    assigned_dir = Path(batch.workdir)
    assert assigned_dir.exists()
    assert assigned_dir != repo_root
    assert "runs" in assigned_dir.parts

    # Cleanup
    if assigned_dir.exists():
        shutil.rmtree(assigned_dir)


def test_batch_executor_preserves_custom_isolated_workdir(tmp_path):
    # Isolated user scratch dir
    custom_dir = tmp_path / "custom_scratch"
    custom_dir.mkdir()
    batch = BatchExecutor(launcher="echo", workdir=str(custom_dir))
    res = batch._run(["echo", "hello"])
    assert res.succeeded
    assert Path(batch.workdir) == custom_dir
