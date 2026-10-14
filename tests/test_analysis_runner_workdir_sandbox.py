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
    from abaqus_ai_agent.paths import resolve_runs_root

    assigned_dir = resolve_runs_root() / run_id
    # 2. Verify workdir was created outside the repository.
    assert assigned_dir.exists()
    assert not assigned_dir.resolve().is_relative_to(repo_root.resolve())

    # 3. Verify project root has zero temporary job artifacts
    root_artifacts = list(repo_root.glob("Job_AutoSandboxTest.*"))
    assert len(root_artifacts) == 0

    # Cleanup the created run directory
    if assigned_dir.exists():
        shutil.rmtree(assigned_dir)


def test_inp_contract_diagnostics_attached_to_run(tmp_path):
    """MS13L lesson: model-contract smells (C3D4-only bending, elastic-only deck
    claiming plasticity) must surface in run.diagnostics, not only in the CLI."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState

    inp = (
        "*Node\n1, 0., 0., 0.\n"
        "*Element, type=C3D4\n1, 1,1,1,1\n"
        "*Material, name=PCABS\n*Elastic\n1900., 0.38\n"
        "*Step\n*Static\n*Cload\n_G2, 1, 100.\n*End Step\n"
    )
    (tmp_path / "Job_X.inp").write_text(inp, encoding="utf-8")

    runner = AnalysisRunner(DummyMockExecutor())
    run = AnalysisRun(id="r1", model_name="M", job_name="Job_X",
                      state=AnalysisRunState.ODB_VALIDATED)
    out = runner._attach_inp_contract_diagnostics(run, str(tmp_path), "Job_X")
    kinds = {d.get("diagnosis_id") for d in out.diagnostics if isinstance(d, dict)}
    assert "STATIC_BENDING_TET4_ONLY" in kinds
    assert all(d.get("severity") == "WARNING" for d in out.diagnostics)


def test_inp_contract_diagnostics_silent_when_no_inp(tmp_path):
    """Missing inp must never raise nor block: run returned unchanged."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
    runner = AnalysisRunner(DummyMockExecutor())
    run = AnalysisRun(id="r2", model_name="M", job_name="Job_None",
                      state=AnalysisRunState.ODB_VALIDATED)
    out = runner._attach_inp_contract_diagnostics(run, str(tmp_path), "Job_None")
    assert out.diagnostics == ()


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
