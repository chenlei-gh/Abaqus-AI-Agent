"""Tests for canonical workspace paths resolution contracts."""

import os
from pathlib import Path
import pytest

from abaqus_ai_agent.paths import (
    ENV_RUNS_DIR,
    ENV_DELIVERABLES_DIR,
    ENV_VALIDATION_ASSETS_DIR,
    get_repo_root,
    resolve_runs_root,
    resolve_deliverables_root,
    resolve_validation_assets_root,
    create_run_workdir,
    ExternalProjectContext,
    create_external_project_context,
    resolve_project_root,
    assert_path_outside_repo,
    ENV_PROJECT_ROOT,
)


def test_get_repo_root_detects_project():
    root = get_repo_root()
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "abaqus_ai_agent").is_dir()


def test_resolve_runs_root_default(monkeypatch):
    monkeypatch.delenv(ENV_RUNS_DIR, raising=False)
    root = get_repo_root()
    runs_dir = resolve_runs_root()
    assert runs_dir == (root / "runs").resolve()


def test_resolve_runs_root_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(custom))
    assert resolve_runs_root() == custom.resolve()


def test_resolve_runs_root_explicit_param(monkeypatch, tmp_path):
    env_dir = tmp_path / "env_runs"
    explicit_dir = tmp_path / "explicit_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(env_dir))
    assert resolve_runs_root(override=explicit_dir) == explicit_dir.resolve()


def test_resolve_deliverables_root_default(monkeypatch):
    monkeypatch.delenv(ENV_DELIVERABLES_DIR, raising=False)
    root = get_repo_root()
    deliv_dir = resolve_deliverables_root()
    assert deliv_dir == (root / "deliverables").resolve()


def test_resolve_deliverables_root_override(monkeypatch, tmp_path):
    target = tmp_path / "official_deliverables"
    monkeypatch.setenv(ENV_DELIVERABLES_DIR, str(target))
    assert resolve_deliverables_root() == target.resolve()
    explicit = tmp_path / "another_target"
    assert resolve_deliverables_root(override=explicit) == explicit.resolve()


def test_resolve_validation_assets_root_fallback(monkeypatch):
    monkeypatch.delenv(ENV_VALIDATION_ASSETS_DIR, raising=False)
    val_dir = resolve_validation_assets_root()
    assert val_dir.is_dir()
    # Should resolve to either validation_assets or fallback to machine_validation
    assert val_dir.name in ("validation_assets", "machine_validation")


def test_resolve_validation_assets_root_override(monkeypatch, tmp_path):
    custom_val = tmp_path / "custom_val"
    monkeypatch.setenv(ENV_VALIDATION_ASSETS_DIR, str(custom_val))
    assert resolve_validation_assets_root() == custom_val.resolve()


def test_create_run_workdir(tmp_path):
    run_id = "test-run-12345"
    workdir = create_run_workdir(run_id, runs_root=tmp_path)
    assert workdir.is_dir()
    assert workdir == (tmp_path / run_id).resolve()


def test_analysis_runner_respects_external_runs_dir(monkeypatch, tmp_path):
    external_runs = tmp_path / "ext_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(external_runs))

    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class DummyExecutor:
        workdir = None

    executor = DummyExecutor()
    runner = AnalysisRunner(executor)
    run = runner.run(model_name="TestModel", job_name="Job-Test")
    # Verify that the run directory was created inside external_runs
    created_run_dir = external_runs / run.id
    assert created_run_dir.is_dir()


def test_telemetry_tracker_respects_external_runs_dir(monkeypatch, tmp_path):
    external_runs = tmp_path / "ext_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(external_runs))

    from abaqus_ai_agent.telemetry.tracker import ContextTelemetryTracker

    tracker = ContextTelemetryTracker(case_id="case_01", run_id="run_999")
    assert tracker.output_dir.resolve().is_relative_to(external_runs.resolve())
    assert tracker.calls_dir.is_dir()


def test_create_external_project_context_structure(tmp_path):
    proj_root = tmp_path / "engineering_projects" / "turbine_blade_01"
    ctx = create_external_project_context(
        project_root=proj_root,
        project_name="turbine_blade_01",
        enforce_outside_repo=False,
    )
    assert ctx.project_root == proj_root.resolve()
    assert ctx.project_name == "turbine_blade_01"
    assert ctx.input_dir == (proj_root / "input").resolve()
    assert ctx.working_dir == (proj_root / "working").resolve()
    assert ctx.solver_dir == (proj_root / "solver").resolve()
    assert ctx.evidence_dir == (proj_root / "evidence").resolve()
    assert ctx.delivery_dir == (proj_root / "delivery").resolve()

    for d in (ctx.input_dir, ctx.working_dir, ctx.solver_dir, ctx.evidence_dir, ctx.delivery_dir):
        assert d.is_dir()


def test_external_project_context_run_isolation(tmp_path):
    proj_root = tmp_path / "proj_gearbox"
    ctx = create_external_project_context(proj_root, enforce_outside_repo=False)

    run_solver = ctx.create_run_solver_dir("run_abc_123")
    assert run_solver == (proj_root / "solver" / "run_abc_123").resolve()
    assert run_solver.is_dir()

    run_evidence = ctx.create_run_evidence_dir("run_abc_123")
    assert run_evidence == (proj_root / "evidence" / "run_abc_123").resolve()
    assert run_evidence.is_dir()


def test_external_project_context_working_copy_isolation(tmp_path):
    proj_root = tmp_path / "proj_piping"
    ctx = create_external_project_context(proj_root, enforce_outside_repo=False)

    # Place an original model in input/
    orig_inp = ctx.input_dir / "flange.inp"
    orig_inp.write_text("*HEADING\nOriginal Flange Model\n", encoding="utf-8")

    working_inp = ctx.prepare_working_copy("flange.inp")
    assert working_inp == (ctx.working_dir / "flange.inp").resolve()
    assert working_inp.is_file()

    # Mutate working copy and ensure input/ is unchanged
    working_inp.write_text("*HEADING\nMutated Working Model\n", encoding="utf-8")
    assert "Original Flange Model" in orig_inp.read_text(encoding="utf-8")
    assert "Mutated Working Model" in working_inp.read_text(encoding="utf-8")


def test_external_project_context_path_traversal_prevention(tmp_path):
    proj_root = tmp_path / "proj_traversal"
    ctx = create_external_project_context(proj_root, enforce_outside_repo=False)

    with pytest.raises(PermissionError, match="Path traversal security violation"):
        ctx.assert_within_project(proj_root.parent / "escape.txt")


def test_assert_path_outside_repo_rejects_repo_subdirectories():
    repo_root = get_repo_root()
    inside_candidate = repo_root / "runs" / "illegal_user_project"
    with pytest.raises(PermissionError, match="cannot reside inside the core Abaqus-AI-Agent repository"):
        assert_path_outside_repo(inside_candidate)


def test_resolve_project_root_priority_and_fail_closed(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_PROJECT_ROOT, raising=False)
    # Default without fail_closed returns None
    assert resolve_project_root() is None

    # Default with fail_closed raises ValueError
    with pytest.raises(ValueError, match="No external engineering project root configured"):
        resolve_project_root(fail_closed=True)

    # Env override
    env_proj = tmp_path / "env_proj"
    monkeypatch.setenv(ENV_PROJECT_ROOT, str(env_proj))
    assert resolve_project_root() == env_proj.resolve()

    # Explicit override takes highest precedence
    explicit_proj = tmp_path / "explicit_proj"
    assert resolve_project_root(override=explicit_proj) == explicit_proj.resolve()


def test_analysis_runner_integrates_with_external_project_context(tmp_path):
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    proj_root = tmp_path / "external_client_case"
    ctx = create_external_project_context(proj_root, enforce_outside_repo=False)

    class DummyExecutor:
        workdir = None

    runner = AnalysisRunner(DummyExecutor())
    run = runner.run(
        model_name="CasingModel",
        job_name="Job-Casing",
        project_context=ctx,
    )

    # Verify run workdir was created in ctx.solver_dir/<run_id>
    assert Path(run.work_dir).resolve().is_relative_to(ctx.solver_dir.resolve())
    assert Path(run.work_dir).is_dir()
    assert run.provenance.environment.get("project_root") == str(ctx.project_root)
    assert run.provenance.environment.get("project_name") == str(ctx.project_name)


def test_agent_solve_requirement_with_external_project_context(tmp_path, monkeypatch):
    """REQ-ISO-003 & REQ-ISO-005: End-to-end verification that external project context
    directs execution and reporting to external project directories without polluting the repository.
    """
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline

    class DummyExecutor(AbaqusExecutor):
        def execute(self, code, timeout=120):
            return {"status": "completed"}
        def inspect_odb(self, path):
            return {"status": "available", "steps": ["Step-1"]}

    ext_root = tmp_path / "ExternalCustomerProject"
    ctx = create_external_project_context(ext_root, project_name="CustomerProjectBeta")

    executor = DummyExecutor()
    agent = AbaqusAIAgent(executor=executor)

    mock_run = AnalysisRun(
        id="RUN-EXT-001",
        model_name="Model_Beta",
        job_name="Job_Beta",
        state=AnalysisRunState.ACCEPTED,
        engineering_status="RESULT_VALID",
        acceptance_passed=True,
        acceptance={"status": "PASS", "deliverable": False, "passed": True},
        metrics=(),
    )
    monkeypatch.setattr(agent, "analysis_run", lambda *args, **kwargs: mock_run)

    intent = EngineeringIntent(
        id="INT-EXT",
        kind="linear_static",
        analysis_type="linear_static",
        description="External project test",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "youngs_modulus": 210000.0, "poisson_ratio": 0.3},
        metadata={"geometry": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0},),
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
    )

    # 1. solve_requirement with project_context
    res = agent.solve_requirement(
        intent,
        project_context=ctx,
        require_production=False,
    )

    # In non-production/diagnostic mode, result report is returned
    assert res.report_markdown is not None
    assert "DIAGNOSTIC" in res.report_markdown or "External project test" in res.report_markdown

    # 2. Pipeline render explicitly into ctx.delivery_dir
    pipeline = DeterministicReportPipeline()
    _, _, report_data = pipeline.build_and_render(
        output_dir=ctx.delivery_dir,
        title="Official External Project Engineering Report",
        case_id="Case_External_01",
        run_id="RUN-EXT-001",
        model_info={"name": "Model_Beta", "material": "Steel"},
        results_info=[{"metric": "max_mises", "value": 150.0}],
        acceptance_info={"status": "PASS", "deliverable": False},
        require_deliverable=False,  # Diagnostic render into external delivery dir
    )

    report_file = ctx.delivery_dir / "report.html"
    assert report_file.is_file(), "Report HTML must be placed in external delivery_dir"
    ctx.assert_within_project(report_file)


def test_workdir_cannot_bypass_project_context_solver_dir(tmp_path):
    """P0-1 Contract: When project_context is passed, an explicit workdir MUST be
    strictly validated to reside inside project_context.solver_dir.
    Any attempt to route workdir to repo runs/, other project subdirs, or external locations MUST fail.
    """
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class DummyExecutor(AbaqusExecutor):
        def execute(self, code, timeout=120):
            return {}

    ext_root = tmp_path / "ProjectAlpha"
    ctx = create_external_project_context(ext_root)
    runner = AnalysisRunner(DummyExecutor())

    # 1. Attempt to pass workdir escaping into project delivery_dir
    illegal_workdir_delivery = ctx.delivery_dir / "escaped_run"
    with pytest.raises(PermissionError) as exc_info:
        runner.run(
            model_name="M",
            job_name="J",
            workdir=str(illegal_workdir_delivery),
            project_context=ctx,
            require_production=False,
        )
    assert "Subdirectory boundary violation" in str(exc_info.value)

    # 2. Attempt to pass workdir escaping completely outside the project
    illegal_workdir_outside = tmp_path / "arbitrary_dir"
    with pytest.raises(PermissionError) as exc_info2:
        runner.run(
            model_name="M",
            job_name="J",
            workdir=str(illegal_workdir_outside),
            project_context=ctx,
            require_production=False,
        )
    assert "Subdirectory boundary violation" in str(exc_info2.value)

    # 3. Legitimate workdir inside solver_dir succeeds
    legal_workdir = ctx.solver_dir / "custom_run_01"
    run = runner.run(
        model_name="M",
        job_name="J",
        workdir=str(legal_workdir),
        project_context=ctx,
        require_production=False,
    )
    assert Path(run.work_dir).resolve() == legal_workdir.resolve()
    assert Path(run.work_dir).is_dir()
    # Evidence dir is also populated in provenance environment
    assert run.provenance.environment.get("evidence_dir") is not None
    assert Path(run.provenance.environment["evidence_dir"]).resolve().is_relative_to(ctx.evidence_dir.resolve())


def test_subdirectory_containment_and_run_id_validation(tmp_path):
    """P0-2 Contract: run_id and subdirectories enforce strict boundary checks."""
    ext_root = tmp_path / "ProjectSubdirTest"
    ctx = create_external_project_context(ext_root)

    # 1. Malicious run_id with path traversal
    for bad_id in ("../escaped", "run/nested", "..\\win_escaped", "run\\slash", "run*bad", " "):
        with pytest.raises(ValueError) as exc:
            ctx.create_run_solver_dir(bad_id)
        assert "Path traversal" in str(exc.value) or "invalid characters" in str(exc.value)

        with pytest.raises(ValueError) as exc2:
            ctx.create_run_evidence_dir(bad_id)
        assert "Path traversal" in str(exc2.value) or "invalid characters" in str(exc2.value)

    # 2. Legitimate run_id creates valid isolated subdirs
    s_dir = ctx.create_run_solver_dir("run-001_A.b")
    assert s_dir.is_relative_to(ctx.solver_dir)
    e_dir = ctx.create_run_evidence_dir("run-001_A.b")
    assert e_dir.is_relative_to(ctx.evidence_dir)


def test_validate_identifier_cross_platform_posix_altsep_none(monkeypatch, tmp_path):
    """P0-2 Cross-platform Contract: In pure POSIX environments where os.sep is '/' and os.altsep is None,
    _validate_identifier must NOT treat empty string as separator, and must allow valid identifiers.
    """
    import os
    monkeypatch.setattr(os, "sep", "/")
    monkeypatch.setattr(os, "altsep", None)
    ext_root = tmp_path / "ProjectPosixTest"
    ctx = create_external_project_context(ext_root)

    # Legitimate identifiers must succeed without false positives
    ctx._validate_identifier("run_abc_123", "run_id")
    ctx._validate_identifier("flange.inp", "source_filename")
    ctx._validate_identifier("assembly.cae", "target_filename")
    ctx._validate_identifier("123e4567-e89b-12d3-a456-426614174000", "run_id")

    # Path traversal with / or \ must still be rejected
    for bad in ("run/abc", "run\\abc", "../escape", "..\\escape"):
        with pytest.raises(ValueError):
            ctx._validate_identifier(bad, "run_id")


def test_prepare_working_copy_overwrite_protection_and_containment(tmp_path):
    """P0-2 Contract: prepare_working_copy strictly protects input/ and working/ boundaries
    and forbids accidental overwrite of existing working copies without overwrite=True.
    """
    ext_root = tmp_path / "ProjectCopyTest"
    ctx = create_external_project_context(ext_root)

    # Create original input file
    input_file = ctx.input_dir / "assembly.cae"
    input_file.write_bytes(b"ORIGINAL_INPUT_BYTES_001")

    # 1. Attempt path traversal in source_filename
    with pytest.raises(ValueError):
        ctx.prepare_working_copy("../escape.cae")

    with pytest.raises(ValueError):
        ctx.prepare_working_copy("assembly.cae", target_filename="../escape.cae")

    # 2. Normal copy succeeds
    dest = ctx.prepare_working_copy("assembly.cae", "assembly_working.cae")
    assert dest == ctx.working_dir / "assembly_working.cae"
    assert dest.read_bytes() == b"ORIGINAL_INPUT_BYTES_001"
    # Original remains untouched
    assert input_file.read_bytes() == b"ORIGINAL_INPUT_BYTES_001"

    # 3. Duplicate attempt without overwrite=True MUST raise FileExistsError
    with pytest.raises(FileExistsError) as fe_info:
        ctx.prepare_working_copy("assembly.cae", "assembly_working.cae", overwrite=False)
    assert "already exists" in str(fe_info.value)

    # 4. Explicit overwrite=True succeeds
    input_file.write_bytes(b"UPDATED_INPUT_BYTES_002")
    dest_overwritten = ctx.prepare_working_copy("assembly.cae", "assembly_working.cae", overwrite=True)
    assert dest_overwritten.read_bytes() == b"UPDATED_INPUT_BYTES_002"


def test_analysis_runner_production_mode_strict_guards(tmp_path):
    """P1.4 Task 35.2 Contract: Production mode (require_production=True) enforces strict validation:
    1. project_context is None -> RuntimeError
    2. project_context inside repo -> PermissionError (assert_path_outside_repo)
    3. Invalid mock object lacking required project structure -> TypeError
    """
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class DummyExecutor(AbaqusExecutor):
        def execute(self, code, timeout=120):
            return {}

    runner = AnalysisRunner(DummyExecutor())

    # 1. Missing project_context in production mode
    with pytest.raises(RuntimeError) as exc_none:
        runner.run(
            model_name="M",
            job_name="J",
            project_context=None,
            require_production=True,
        )
    assert "[Production Guard]" in str(exc_none.value)

    # 2. Fake project context lacking required attributes
    class FakeContext:
        pass

    with pytest.raises(TypeError) as exc_type:
        runner.run(
            model_name="M",
            job_name="J",
            project_context=FakeContext(),
            require_production=True,
        )
    assert "must be a valid ExternalProjectContext" in str(exc_type.value)

    # 3. Project context pointing inside repository root
    repo_root = get_repo_root()
    repo_internal_project = repo_root / "tests" / "dummy_internal_project"
    try:
        repo_internal_project.mkdir(parents=True, exist_ok=True)
        # Manually assemble a context-like object inside repo
        class RepoInternalContext:
            project_root = repo_internal_project
            solver_dir = repo_internal_project / "solver"
            def create_run_solver_dir(self, run_id):
                return self.solver_dir / run_id
            def create_run_evidence_dir(self, run_id):
                return repo_internal_project / "evidence" / run_id

        with pytest.raises(PermissionError) as exc_perm:
            runner.run(
                model_name="M",
                job_name="J",
                project_context=RepoInternalContext(),
                require_production=True,
            )
        assert "Security violation (REQ-ISO-003)" in str(exc_perm.value)
    finally:
        if repo_internal_project.exists():
            import shutil
            shutil.rmtree(repo_internal_project, ignore_errors=True)

    # 4. Context where a subdirectory escapes outside project_root
    ext_root = tmp_path / "LegitExtProject"
    ext_root.mkdir()
    outside_dir = tmp_path / "EscapedSubdir"
    outside_dir.mkdir()
    class EscapedSubdirContext:
        project_root = ext_root
        input_dir = ext_root / "input"
        working_dir = ext_root / "working"
        solver_dir = outside_dir  # Escapes project_root!
        evidence_dir = ext_root / "evidence"
        delivery_dir = ext_root / "delivery"

    with pytest.raises(PermissionError) as exc_sub_esc:
        runner.run(
            model_name="M",
            job_name="J",
            project_context=EscapedSubdirContext(),
            require_production=True,
        )
    assert "Subdirectory boundary escape" in str(exc_sub_esc.value)


def test_agent_production_mode_blocks_execution_in_repo_runs(tmp_path):
    """P0-3 Contract: When executing with a non-test-double executor in production mode,
    falling back to internal repository runs/ or executing in the repo is strictly blocked.
    """
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.paths import get_repo_root

    class RealSimulatedClient(AbaqusExecutor):
        """Simulates a real production client without test double naming markers."""
        def execute(self, code, timeout=120):
            return {}

    real_client = RealSimulatedClient()
    agent = AbaqusAIAgent(executor=real_client, mode="production")

    intent = EngineeringIntent(
        id="INT-PROD-BLOCK",
        kind="linear_static",
        analysis_type="linear_static",
        description="Production mode block test",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "youngs_modulus": 210000.0, "poisson_ratio": 0.3},
        metadata={"geometry": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0},),
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
    )

    # 1. No project_context and no workdir -> would fallback to repo runs/ -> must fail
    with pytest.raises((RuntimeError, PermissionError)) as exc_info:
        agent.solve_requirement(
            intent,
            require_production=True,
        )
    assert "Production execution blocked" in str(exc_info.value) or "Production Guard" in str(exc_info.value)

    # 2. workdir explicitly passed pointing inside the repo -> must fail
    repo_workdir = get_repo_root() / "runs" / "illegal_run"
    with pytest.raises(PermissionError) as exc_info2:
        agent.solve_requirement(
            intent,
            workdir=str(repo_workdir),
            require_production=True,
        )
    assert "Production execution blocked" in str(exc_info2.value)


def test_production_guard_analysis_runner_requires_external_project_context():
    """Task 35.2 Contract: AnalysisRunner.run in production mode (require_production=True)
    strictly requires a valid ExternalProjectContext. Silent fallback to internal runs/
    is strictly forbidden and must raise RuntimeError with '[Production Guard]'.
    """
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class RealExecutor(AbaqusExecutor):
        def execute(self, code, timeout=120):
            return {}

    runner = AnalysisRunner(RealExecutor())
    with pytest.raises(RuntimeError) as exc_info:
        runner.run(
            model_name="Model_Prod",
            job_name="Job_Prod",
            require_production=True,
            project_context=None,
        )
    assert "[Production Guard]" in str(exc_info.value)
    assert "requires a valid ExternalProjectContext" in str(exc_info.value)
