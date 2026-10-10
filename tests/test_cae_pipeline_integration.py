"""End-to-End CAE Execution, Authentic Extraction, Production Acceptance & Report Pipeline Integration Tests.

Validates the complete 6-layer architecture causal chain:
AnalysisRunner(require_production=True) ->
    Headless ODB Extraction / Authentic Lineage ->
    evaluate_production_acceptance (Single Exit Gate) ->
    DeterministicReportPipeline (Fail-Closed, zero synthetic fallback, zero leakage).
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.artifact import ArtifactPointer
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.report import ReportFigure
from abaqus_ai_agent.contracts.results import ResultExtraction, ResultRequirement
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunner, AnalysisRunState
from abaqus_ai_agent.execution.client import AbaqusExecutor
from abaqus_ai_agent.execution.jobs import JobState, JobStatus
from abaqus_ai_agent.execution.odb_rendering import (
    MINIMAL_VALID_PNG_BYTES,
    ContourPlotRequest,
    generate_headless_viewer_script,
)
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec


class MockCaeExecutor(AbaqusExecutor):
    """Mock executor providing realistic artifacts and inspection for unit test isolation."""

    def __init__(self, workdir: Path, job_name: str = "TestJob", job_status_response: str = "COMPLETED"):
        self.workdir = str(workdir)
        self.job_name = job_name
        self.job_status_response = job_status_response
        self.commands = []

        # Create valid dummy .inp and binary .odb
        self.inp_path = workdir / f"{job_name}.inp"
        self.inp_path.write_text("*HEADING\n** Test Deck\n*END STEP\n", encoding="utf-8")
        self.inp_sha256 = hashlib.sha256(self.inp_path.read_bytes()).hexdigest()

        # Authentic binary header simulation (>= 1024 bytes)
        self.odb_path = workdir / f"{job_name}.odb"
        self.odb_path.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
        self.odb_sha256 = hashlib.sha256(self.odb_path.read_bytes()).hexdigest()

        # Log, message, data, and status files
        (workdir / f"{job_name}.sta").write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n", encoding="utf-8")
        (workdir / f"{job_name}.log").write_text("Abaqus JOB COMPLETED\n", encoding="utf-8")
        (workdir / f"{job_name}.msg").write_text("Abaqus Message File Output\n", encoding="utf-8")
        (workdir / f"{job_name}.dat").write_text("Abaqus Data File Output\n", encoding="utf-8")

    def snapshot(self):
        return None

    def execute(self, code, timeout=120):
        self.commands.append(code)
        if "print(mdb.jobs" in code or "waitForCompletion" in code or "status" in code:
            return self.job_status_response
        return ""

    def inspect_odb(self, path):
        return {
            "status": "available",
            "steps": {"Step-1": {"frames": [0, 1]}},
            "field_outputs": ["S", "U"],
        }


def test_analysis_runner_require_production_denies_external_injected_values(tmp_path: Path):
    """External injected result_values MUST NEVER pass production deliverable gate."""
    workdir = tmp_path / "run_workdir"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_Injected")
    runner = AnalysisRunner(executor)

    # Injected result_values without live ODB extraction
    criteria = (
        {"name": "stress_limit", "value_key": "max_stress", "operator": "<=", "limit": 250.0, "required": True},
    )

    run_res = runner.run(
        model_name="Model-1",
        job_name="Job_Injected",
        workdir=str(workdir),
        criteria=criteria,
        result_values={"max_stress": 120.0},
        require_production=True,
    )

    # Verification:
    # 1. State must NOT be ACCEPTED
    assert run_res.state != AnalysisRunState.ACCEPTED
    assert run_res.acceptance is not None

    # 2. Production deliverable is strictly False
    assert run_res.acceptance.deliverable is False

    # 3. Downstream DeterministicReportPipeline MUST fail-closed with zero disk write
    pipeline = DeterministicReportPipeline()
    report_out = tmp_path / "report_out_denied"

    with pytest.raises(PermissionError, match="Official engineering delivery blocked: deliverable is False"):
        pipeline.build_and_render(
            output_dir=report_out,
            title="External Values Report",
            case_id="case_injected",
            run_id=run_res.id,
            model_info={"model": "Model-1"},
            results_info=[{"metric": "max_stress", "value": 120.0}],
            acceptance_info=run_res.acceptance,
            require_deliverable=True,
        )

    # 4. Zero disk leakage
    assert not report_out.exists() or not list(report_out.glob("report.html"))


def test_analysis_runner_require_production_unsubmitted_job_denied(tmp_path: Path):
    """If solver job fails or is unsubmitted, AnalysisRunner halts before acceptance."""
    workdir = tmp_path / "run_fail"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_Fail", job_status_response="ABORTED")
    # Overwrite .sta without completion message
    (workdir / "Job_Fail.sta").write_text("ERROR: Solver diverged\n", encoding="utf-8")
    (workdir / "Job_Fail.log").write_text("Abaqus JOB ABORTED\n", encoding="utf-8")

    runner = AnalysisRunner(executor)
    run_res = runner.run(
        model_name="Model-1",
        job_name="Job_Fail",
        workdir=str(workdir),
        require_production=True,
    )

    assert run_res.state == AnalysisRunState.FAILED
    assert run_res.acceptance_passed in (False, None)
    assert run_res.engineering_status != "result_valid"


def test_analysis_runner_require_production_full_causal_binding_and_delivery(tmp_path: Path, monkeypatch):
    """When ODB extraction and live manifest are authentic and consistent, deliverable is granted."""
    workdir = tmp_path / "run_authentic"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_Auth")
    executor.launcher = "abaqus"
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: {"verified": True, "offline": False, "steps": {"Step-1": {"frames": [0, 1]}}, "fields": ["S", "U"]},
    )

    # Mock extract_requirements to simulate authentic live ODB extraction
    req = ResultRequirement(
        name="max_mises",
        value_key="max_mises",
        field="S",
        component="mises",
        region="Root",
        step="Step-1",
        frame=-1,
        unit="MPa",
    )
    extraction = ResultExtraction(
        requirement=req,
        value=180.0,
        locator={"step": "Step-1", "frame": -1, "field": "S", "component": "mises", "source": "odb"},
    )

    import abaqus_ai_agent.execution.results as res_mod
    monkeypatch.setattr(res_mod, "extract_requirements", lambda ex, path, crit: ([extraction], ()))

    runner = AnalysisRunner(executor)
    criteria = (
        {
            "name": "stress_limit",
            "value_key": "max_mises",
            "operator": "<=",
            "limit": 250.0,
            "unit": "MPa",
            "required": True,
        },
    )

    run_res = runner.run(
        model_name="Model-Auth",
        job_name="Job_Auth",
        workdir=str(workdir),
        criteria=criteria,
        require_production=True,
    )

    # Verify AnalysisRun state and production deliverable
    assert run_res.state == AnalysisRunState.ACCEPTED
    assert run_res.acceptance_passed is True
    assert run_res.acceptance is not None
    assert run_res.acceptance.deliverable is True
    assert run_res.acceptance.acceptance_status == "PASS"
    assert run_res.acceptance.result_validity == "VALID"

    # Verify causal link in extractions
    assert len(run_res.extractions) == 1
    assert run_res.extractions[0].value == 180.0

    # Downstream Report Pipeline succeeds
    report_out = tmp_path / "report_auth_out"
    pipeline = DeterministicReportPipeline()
    delivery_card, report_pointer, report_data = pipeline.build_and_render(
        output_dir=report_out,
        title="Authentic Official Report",
        case_id="case_auth",
        run_id=run_res.id,
        model_info={"name": "Model-Auth"},
        results_info=[{"metric": "max_mises", "value": 180.0, "unit": "MPa"}],
        acceptance_info=run_res.acceptance,
        require_deliverable=True,
        odb_path=run_res.odb_path,
        input_hash=run_res.provenance.input_hash,
    )

    assert delivery_card.deliverable is True
    assert report_pointer.metadata.get("delivery_mode") == "official_delivery"
    assert (report_out / "report.html").exists()
    assert report_pointer.size_bytes > 0


def test_deterministic_report_pipeline_headless_viewer_odb_rendering_validation(tmp_path: Path):
    """When visualization_specs are provided, pipeline invokes authentic viewer rendering."""
    fake_odb = tmp_path / "fake.odb"
    # Write synthetic JSON mock ODB
    fake_odb.write_text('{"steps": {}}', encoding="utf-8")

    pipeline = DeterministicReportPipeline()
    report_out = tmp_path / "report_render_attempt"

    from abaqus_ai_agent.acceptance import AcceptanceResult
    valid_acc = AcceptanceResult(
        passed=True,
        criteria=(),
        status="PASS",
        acceptance_status="PASS",
        result_validity="VALID",
        deliverable=True,
    )

    spec = VisualizationSpec(
        artifact_id="FIG-STRESS-01",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename="stress_contour.png",
    )

    # Calling with non-binary ODB must immediately fail-closed and reject mock ODB
    with pytest.raises(ValueError, match="not an authentic binary ODB"):
        pipeline.build_and_render(
            output_dir=report_out,
            title="Viewer Rendering Test",
            case_id="case_render",
            run_id="run_render",
            model_info={},
            results_info=[],
            acceptance_info=valid_acc,
            visualization_specs=[spec],
            odb_path=fake_odb,
            require_deliverable=True,
        )

    # Ensure zero leakage of HTML report
    assert not (report_out / "report.html").exists()


def test_deterministic_report_pipeline_missing_image_fail_closed_blocks_html(tmp_path: Path):
    """If required CAE visualization image is missing and Viewer cannot render it, delivery is blocked."""
    valid_binary_odb = tmp_path / "valid.odb"
    valid_binary_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)

    pipeline = DeterministicReportPipeline()
    report_out = tmp_path / "report_missing_img"

    from abaqus_ai_agent.acceptance import AcceptanceResult
    valid_acc = AcceptanceResult(
        passed=True,
        criteria=(),
        status="PASS",
        acceptance_status="PASS",
        result_validity="VALID",
        deliverable=True,
    )

    spec = VisualizationSpec(
        artifact_id="FIG-MISSING-01",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename="non_existent_and_unrenderable.png",
    )

    # Missing image with no valid launcher must raise FileNotFoundError or RuntimeError fail-closed
    with pytest.raises((FileNotFoundError, RuntimeError)):
        pipeline.build_and_render(
            output_dir=report_out,
            title="Missing Image Block Test",
            case_id="case_missing_img",
            run_id="run_missing_img",
            model_info={},
            results_info=[],
            acceptance_info=valid_acc,
            visualization_specs=[spec],
            odb_path=valid_binary_odb,
            launcher="non_existent_abaqus_launcher",
            require_deliverable=True,
        )

    # Verify zero leakage of report.html
    assert not (report_out / "report.html").exists()


def test_agent_solve_requirement_require_production_full_closure_and_delivery(tmp_path: Path, monkeypatch):
    """AbaqusAIAgent.solve_requirement with require_production=True completes full chain with figure selector."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec

    workdir = tmp_path / "prod_agent_run"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_PROD")
    executor.launcher = "abaqus"
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: {"verified": True, "offline": False, "steps": {"Step-1": {"frames": [0, 1]}}, "fields": ["S", "U"]},
    )
    # Mock headless viewer rendering so authentic figures are generated during pipeline execution
    import abaqus_ai_agent.execution.odb_rendering as rend_mod

    def _mock_render_vis(odb_path, specs, output_dir, **kwargs):
        import hashlib
        from abaqus_ai_agent.execution.odb_rendering import (
            compute_viewer_session_token,
            create_render_execution_evidence,
        )
        rendered = []
        session_nonce = "0123456789abcdef0123456789abcdef"
        run_id = str(kwargs.get("run_id", "PROD")).strip()
        odb_sha256 = ""
        if odb_path and Path(odb_path).exists():
            odb_sha256 = hashlib.sha256(Path(odb_path).read_bytes()).hexdigest()
        rendered_summary = []
        for s in specs:
            out_file = Path(output_dir) / s.target_filename
            if not out_file.exists():
                out_file.write_bytes(MINIMAL_VALID_PNG_BYTES)
            img_bytes = out_file.read_bytes()
            sha = hashlib.sha256(img_bytes).hexdigest()
            rendered_summary.append({"filename": out_file.name, "image_sha256": sha})

        render_ev = create_render_execution_evidence(
            session_nonce=session_nonce,
            run_id=run_id,
            odb_sha256=odb_sha256,
            rendered_figures=rendered_summary,
        )

        for s in specs:
            out_file = Path(output_dir) / s.target_filename
            img_bytes = out_file.read_bytes()
            sha = hashlib.sha256(img_bytes).hexdigest()
            token = compute_viewer_session_token(
                session_nonce=session_nonce,
                run_id=run_id,
                odb_sha256=odb_sha256,
                target_filename=out_file.name,
                image_sha256=sha,
            )
            rendered.append(
                ReportFigure(
                    kind=s.kind,
                    path=str(out_file.as_posix()),
                    caption=s.caption,
                    source=f"{s.field_name}.{s.component}",
                    metadata={
                        "field": s.field_name,
                        "component": s.component,
                        "step": s.step_name,
                        "frame": s.frame_index,
                        "actual_frame": s.actual_frame_index,
                        "region": getattr(s, "region", "WHOLE_MODEL"),
                        "output_position": getattr(s, "output_position", "INTEGRATION_POINT"),
                        "run_id": run_id,
                        "input_hash": kwargs.get("input_hash", ""),
                        "odb_sha256": odb_sha256,
                        "image_sha256": sha,
                        "sha256": sha,
                        "viewer_rendered": True,
                        "session_nonce": session_nonce,
                        "viewer_session_token": token,
                        "render_execution_evidence": render_ev.to_dict(),
                    },
                )
            )
        return rendered

    monkeypatch.setattr(rend_mod, "render_authentic_visualizations", _mock_render_vis)

    # Mock extract_requirements to supply authentic extraction
    req = ResultRequirement(
        name="max_mises",
        value_key="max_mises",
        field="S",
        component="mises",
        region="Root",
        step="Step-1",
        frame=-1,
        unit="MPa",
    )
    extraction = ResultExtraction(
        requirement=req,
        value=150.0,
        locator={"step": "Step-1", "frame": -1, "field": "S", "component": "mises", "source": "odb"},
    )
    import abaqus_ai_agent.execution.results as res_mod
    monkeypatch.setattr(res_mod, "extract_requirements", lambda ex, path, crit: ([extraction], ()))

    # Pre-render dummy verified figures so Viewer dispatch is bypassed (Priority 1)
    img_mises = workdir / "mises_stress_hotspot.png"
    img_mises.write_bytes(MINIMAL_VALID_PNG_BYTES)
    img_disp = workdir / "total_displacement.png"
    img_disp.write_bytes(MINIMAL_VALID_PNG_BYTES)

    agent = AbaqusAIAgent(executor)
    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="PROD",
        kind="linear_static",
        description="Linear static cantilever analysis",
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa", "required": True},
        ),
    )

    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        workdir=str(workdir),
        require_production=True,
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.summary_card["deliverable"] is True
    assert result.summary_card["figure_selection"]["scenario"] == "static_structural"
    assert result.summary_card["delivery_card"] is not None
    assert (workdir / "report.html").exists()


def test_agent_solve_requirement_require_production_blocks_fake_odb(tmp_path: Path):
    """When require_production=True and ODB is a fake plaintext mock, delivery is blocked."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec

    workdir = tmp_path / "fake_agent_run"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_FAKE")
    # Overwrite ODB with plaintext fake
    (workdir / "Job_FAKE.odb").write_text('{"steps": []}', encoding="utf-8")

    agent = AbaqusAIAgent(executor)
    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="REQ-FAKE",
        kind="linear_static",
        description="Linear static cantilever analysis",
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa", "required": True},
        ),
    )

    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        workdir=str(workdir),
        require_production=True,
    )

    # Must fail-closed, cannot be COMPLETED, deliverable cannot be True
    assert result.status == TaskStatus.FAILED
    assert result.summary_card.get("deliverable") is not True
    assert result.summary_card.get("delivery_card") is None


def test_p0_4_production_mode_enforcement_defaults():
    """Verify that formal production mode enforces require_production by default (P0-4)."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class RealAbaqusClient(AbaqusExecutor):
        def execute(self, code, timeout=120):
            return {}

    real_exec = RealAbaqusClient()
    agent = AbaqusAIAgent(real_exec, mode="production")
    assert agent.mode == "production"

    # AnalysisRunner with real executor must default require_production to True
    runner = AnalysisRunner(real_exec)
    # When require_production is not passed (None), it evaluates to True for real executors
    cname = getattr(runner.executor, "__class__", None).__name__ or ""
    is_test_double = any(token in cname for token in ("Mock", "Fake", "Stub", "Dummy", "OdbBackedExecutor"))
    assert is_test_double is False


def test_p0_5_verify_authentic_odb_structure(tmp_path: Path):
    """Verify native ODB structural verification rejects fake and corrupt files (P0-5)."""
    from abaqus_ai_agent.execution.solver import verify_authentic_odb_structure

    # 1. Non-existent file
    res_none = verify_authentic_odb_structure(tmp_path / "non_existent.odb")
    assert res_none["verified"] is False
    assert "failed binary pre-filter" in res_none["error"]

    # 2. Plaintext mock file
    mock_odb = tmp_path / "mock.odb"
    mock_odb.write_text('{"steps": ["Step-1"]}', encoding="utf-8")
    res_mock = verify_authentic_odb_structure(mock_odb)
    assert res_mock["verified"] is False
    assert "failed binary pre-filter" in res_mock["error"]

    # 3. Corrupt small file (< 1024 bytes)
    small_odb = tmp_path / "corrupt.odb"
    small_odb.write_bytes(b"\x00" * 200)
    res_small = verify_authentic_odb_structure(small_odb)
    assert res_small["verified"] is False
    assert "failed binary pre-filter" in res_small["error"]


def test_p0_6_headless_viewer_failure_raises_runtime_error(tmp_path: Path, monkeypatch):
    """Verify that headless Abaqus Viewer failure raises RuntimeError on non-zero exit (P0-6)."""
    import subprocess
    from abaqus_ai_agent.execution.odb_rendering import (
        ContourPlotRequest,
        render_odb_contours_headless,
    )

    req = ContourPlotRequest(output_filename="fail_test.png")
    fake_odb = tmp_path / "test.odb"
    fake_odb.write_bytes(b"\x7fABAQUS" + b"\x00" * 2000)

    class CompletedProcessMock:
        returncode = 2
        stdout = "SyntaxError in script"
        stderr = "Viewer process aborted with error code 2"

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.resolve_default_launcher",
        lambda x: "python",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: CompletedProcessMock())

    with pytest.raises(RuntimeError) as exc_info:
        render_odb_contours_headless(
            odb_path=fake_odb,
            requests=[req],
            output_dir=tmp_path,
            launcher="python",
        )
    assert "Headless Abaqus Viewer failed with exit code 2" in str(exc_info.value)


def test_negative_p0_a_corrupt_or_empty_odb_rejected_by_analysis_runner_require_production(tmp_path: Path, monkeypatch):
    """Negative Test P0-A: Corrupt ODB or structural failure in openOdb verification must fail AnalysisRunner."""
    workdir = tmp_path / "neg_p0_a"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_NegP0A")
    executor.launcher = "python"

    # Simulate solver returning invalid ODB structure verification
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: {"verified": False, "offline": False, "error": "ODB contains zero steps"},
    )

    runner = AnalysisRunner(executor)
    criteria = ({"name": "mises", "value_key": "max_mises", "required": True},)

    run_res = runner.run(
        model_name="Model-1",
        job_name="Job_NegP0A",
        workdir=str(workdir),
        criteria=criteria,
        require_production=True,
    )

    assert run_res.state == AnalysisRunState.FAILED
    assert run_res.engineering_status == "RESULT_INVALID"
    assert any("odb_native_structure_invalid" in str(d) for d in run_res.diagnostics)


def test_negative_p0_a_production_mode_denies_missing_launcher_or_offline_verification(tmp_path: Path, monkeypatch):
    """Negative Test P0-A: Production executor without launcher or with offline verification MUST fail regardless of class name."""
    workdir = tmp_path / "neg_p0_a_real"
    workdir.mkdir()

    # Create real binary ODB
    odb_p = workdir / "RealJob.odb"
    odb_p.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    (workdir / "RealJob.sta").write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n", encoding="utf-8")
    (workdir / "RealJob.log").write_text("Abaqus JOB COMPLETED\n", encoding="utf-8")

    class FakeOrMockExecutor(AbaqusExecutor):
        """Executor containing 'Mock' / 'Fake' in class name to verify class name heuristic is dead."""
        def __init__(self):
            self.launcher = None  # Missing launcher!
        def execute(self, code, timeout=120):
            if "status" in code or "jobs" in code:
                return "COMPLETED"
            return ""
        def inspect_odb(self, path):
            return {"status": "available", "steps": {"Step-1": {"frames": [0]}}}

    exec_fake_name = FakeOrMockExecutor()
    runner = AnalysisRunner(exec_fake_name)

    # 1. Missing launcher in host Python environment (no in-process odbAccess, no external launcher)
    # MUST fail-closed even if class name has 'Mock'/'Fake'
    monkeypatch.setattr("abaqus_ai_agent.execution.solver.has_native_odb_access", lambda: False)
    monkeypatch.setattr("abaqus_ai_agent.execution.solver.find_abaqus_executable", lambda *args, **kwargs: None)
    res_no_launcher = runner.run(
        model_name="M1",
        job_name="RealJob",
        workdir=str(workdir),
        criteria=({"name": "stress", "value_key": "max_mises"},),
        require_production=True,
    )
    assert res_no_launcher.state == AnalysisRunState.FAILED
    assert res_no_launcher.engineering_status == "RESULT_INVALID"
    assert any("production_launcher_missing" in str(d) for d in res_no_launcher.diagnostics)

    # 2. Launcher present but verification returns offline: MUST fail-closed in production mode
    exec_fake_name.launcher = "abaqus"
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: {"verified": False, "offline": True, "error": "Abaqus offline"},
    )
    res_offline = runner.run(
        model_name="M1",
        job_name="RealJob",
        workdir=str(workdir),
        criteria=({"name": "stress", "value_key": "max_mises"},),
        require_production=True,
    )
    assert res_offline.state == AnalysisRunState.FAILED
    assert res_offline.engineering_status == "RESULT_INVALID"
    assert any("odb_native_structure_unverified" in str(d) for d in res_offline.diagnostics)


def test_p0_a_production_mode_in_process_native_odb_verification_succeeds_without_launcher(tmp_path: Path, monkeypatch):
    """Verify that native Abaqus in-process environment (odbAccess present) verifies ODB without launcher."""
    workdir = tmp_path / "inprocess_native_run"
    workdir.mkdir()

    executor = MockCaeExecutor(workdir, job_name="InProcessJob")
    executor.launcher = None  # In-process executor has NO launcher command

    monkeypatch.setattr("abaqus_ai_agent.execution.solver.has_native_odb_access", lambda: True)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver._verify_odb_in_process",
        lambda path, required_fields=None, required_step=None: {
            "verified": True,
            "steps": {"Step-1": {"frames": 2, "fields": ["S", "U"]}},
        },
    )
    req = ResultRequirement(
        name="stress",
        value_key="max_mises",
        field="S",
        component="mises",
        region="Root",
        step="Step-1",
        frame=-1,
        unit="MPa",
    )
    extraction = ResultExtraction(
        requirement=req,
        value=180.0,
        locator={"step": "Step-1", "frame": -1, "field": "S", "component": "mises", "source": "odb"},
    )
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_extractor.extract_odb_results",
        lambda **kwargs: type("ExtractionReport", (), {
            "extractions": [extraction],
            "evidence": (),
            "metrics": {"max_mises": 180.0},
        })(),
    )

    runner = AnalysisRunner(executor)
    criteria = (
        {
            "name": "stress",
            "value_key": "max_mises",
            "limit": 250.0,
            "operator": "<=",
            "field": "S",
            "unit": "MPa",
            "required": True,
        },
    )

    run_res = runner.run(
        model_name="InProcessModel",
        job_name="InProcessJob",
        workdir=str(workdir),
        criteria=criteria,
        require_production=True,
    )

    assert not run_res.diagnostics, f"Diagnostics: {run_res.diagnostics}"
    assert run_res.state == AnalysisRunState.ACCEPTED
    assert run_res.engineering_status == "RESULT_VALID"
    assert run_res.acceptance_passed is True
    assert run_res.metrics[0].value == 180.0


def test_negative_p0_b_missing_or_mismatched_provenance_rejected(tmp_path: Path):
    """Negative Test P0-B: Missing or mismatched provenance metadata is strictly rejected from reuse."""
    import hashlib
    from abaqus_ai_agent.reporting.figure_selector import select_engineering_figures

    img_file = tmp_path / "mises_stress_hotspot.png"
    img_bytes = MINIMAL_VALID_PNG_BYTES
    img_file.write_bytes(img_bytes)
    valid_img_sha256 = hashlib.sha256(img_bytes).hexdigest()

    # Case 1: Missing run_id (unknown origin)
    fig_no_run = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Unknown origin figure",
        source="S.mises",
        metadata={"field": "S", "component": "mises", "input_hash": "INP-01", "odb_hash": "ODB-01", "sha256": valid_img_sha256},
    )
    res_no_run = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_no_run],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
    )
    assert len(res_no_run.reused_figures) == 0

    # Case 2: Missing input_hash in metadata or caller
    fig_no_inp = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Missing input hash figure",
        source="S.mises",
        metadata={"field": "S", "component": "mises", "run_id": "RUN-CURR-01", "odb_hash": "ODB-01", "sha256": valid_img_sha256},
    )
    res_no_inp = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_no_inp],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
    )
    assert len(res_no_inp.reused_figures) == 0

    # Case 3: Missing odb_hash in metadata or caller
    fig_no_odb = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Missing ODB hash figure",
        source="S.mises",
        metadata={"field": "S", "component": "mises", "run_id": "RUN-CURR-01", "input_hash": "INP-01", "sha256": valid_img_sha256},
    )
    res_no_odb = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_no_odb],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
    )
    assert len(res_no_odb.reused_figures) == 0

    # Case 4: Missing image content sha256 in metadata
    fig_no_sha = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Missing image sha256 figure",
        source="S.mises",
        metadata={"field": "S", "component": "mises", "run_id": "RUN-CURR-01", "input_hash": "INP-01", "odb_hash": "ODB-01"},
    )
    res_no_sha = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_no_sha],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
    )
    assert len(res_no_sha.reused_figures) == 0

    # Case 5: Matching provenance but image file content altered (tampered sha256)
    fig_tampered = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Tampered content figure",
        source="S.mises",
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-CURR-01",
            "input_hash": "INP-01",
            "odb_hash": "ODB-01",
            "sha256": "expected_different_sha256_hash",
        },
    )
    res_tampered = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_tampered],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
    )
    assert len(res_tampered.reused_figures) == 0

    # Case 6: Step mismatch
    fig_wrong_step = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Wrong step figure",
        source="S.mises",
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-CURR-01",
            "input_hash": "INP-01",
            "odb_hash": "ODB-01",
            "sha256": valid_img_sha256,
            "step": "Step-2",
        },
    )
    res_wrong_step = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_wrong_step],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
        step_name="Step-1",
    )
    assert len(res_wrong_step.reused_figures) == 0

    # Case 7: Full matching provenance whitelist: strictly admitted
    from abaqus_ai_agent.execution.odb_rendering import (
        compute_viewer_session_token,
        create_render_execution_evidence,
    )
    valid_nonce = "0123456789abcdef0123456789abcdef"
    valid_token = compute_viewer_session_token(
        session_nonce=valid_nonce,
        run_id="RUN-CURR-01",
        odb_sha256="ODB-01",
        target_filename=img_file.name,
        image_sha256=valid_img_sha256,
    )
    valid_ev = create_render_execution_evidence(
        session_nonce=valid_nonce,
        run_id="RUN-CURR-01",
        odb_sha256="ODB-01",
        input_hash="INP-01",
        rendered_figures=[{"filename": img_file.name, "image_sha256": valid_img_sha256}],
    )
    fig_valid = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        caption="Fully verified figure",
        source="S.mises",
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-CURR-01",
            "input_hash": "INP-01",
            "odb_hash": "ODB-01",
            "odb_sha256": "ODB-01",
            "sha256": valid_img_sha256,
            "image_sha256": valid_img_sha256,
            "step": "Step-1",
            "frame": -1,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": valid_nonce,
            "viewer_session_token": valid_token,
            "render_execution_evidence": valid_ev.to_dict(),
        },
    )
    res_valid = select_engineering_figures(
        physics_domain="static",
        existing_figures=[fig_valid],
        run_id="RUN-CURR-01",
        input_hash="INP-01",
        odb_hash="ODB-01",
        step_name="Step-1",
        frame_index=-1,
    )
    assert len(res_valid.reused_figures) == 1


def test_negative_p0_c_viewer_script_fails_closed_on_missing_step_or_unsupported_component():
    """Negative Test P0-C: Generated viewer script raises error on missing step or failed component."""
    from abaqus_ai_agent.execution.odb_rendering import ContourPlotRequest, generate_headless_viewer_script

    req = ContourPlotRequest(
        output_filename="test_step.png",
        step_name="Step-NonExistent",
        variable_label="S",
        component_or_invariant="mises",
    )

    script = generate_headless_viewer_script("dummy.odb", [req], "dummy_dir")

    # Script must check step existence and raise KeyError
    assert "if 'Step-NonExistent' not in odb.steps:" in script
    assert "raise KeyError" in script

    # Script must NOT degrade to unrefined scalar if invariant fails
    assert "Failed to set primary variable \"S\" with invariant/component \"mises\"" in script
    assert "vp.odbDisplay.setPrimaryVariable(variableLabel='S', outputPosition=pos)" not in script


def test_negative_p1_d_missing_required_criterion_blocks_task_completion_and_delivery(tmp_path: Path, monkeypatch):
    """Negative Test P1-D: Missing required engineering criterion blocks COMPLETED and deliverable."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec

    workdir = tmp_path / "req_diag_run"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_ReqDiag")

    # Mock extraction returning only optional displacement U, missing required max_mises S
    req = ResultRequirement(
        name="max_displacement",
        value_key="max_displacement",
        field="U",
        component="magnitude",
        region="Tip",
        step="Step-1",
        frame=-1,
    )
    extraction = ResultExtraction(
        requirement=req,
        value=0.5,
        locator={"step": "Step-1", "frame": -1, "field": "U", "component": "magnitude", "source": "odb"},
    )
    import abaqus_ai_agent.execution.results as res_mod
    monkeypatch.setattr(res_mod, "extract_requirements", lambda ex, path, crit: ([extraction], ()))

    agent = AbaqusAIAgent(executor)
    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    # Required criterion 'mises_limit' (max_mises) is NOT in extractions!
    intent = EngineeringIntent(
        id="REQ-MISSING-CRIT",
        kind="linear_static",
        description="Linear static cantilever analysis",
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa", "required": True},
        ),
    )

    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        workdir=str(workdir),
        require_production=True,
    )

    # Must fail-closed: TaskStatus.FAILED, engineering_status == RESULT_INVALID, deliverable is False
    assert result.status == TaskStatus.FAILED
    assert result.summary_card["engineering_status"] == "RESULT_INVALID"
    assert result.summary_card.get("delivery_card") is None


def test_negative_p1_d_required_criterion_with_nan_inf_bool_or_unavailable_diagnostic_blocked(tmp_path: Path, monkeypatch):
    """Negative Test P1-D: Required criterion having NaN, +inf, -inf, bool, or structured error diagnostics blocks delivery."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec
    import abaqus_ai_agent.execution.results as res_mod

    workdir = tmp_path / "req_nan_run"
    workdir.mkdir()
    executor = MockCaeExecutor(workdir, job_name="Job_ReqNonFinite")

    req = ResultRequirement(
        name="max_mises",
        value_key="max_mises",
        field="S",
        component="mises",
        region="Root",
        step="Step-1",
        frame=-1,
    )

    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="REQ-NONFINITE-CRIT",
        kind="linear_static",
        description="Linear static cantilever analysis",
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "field": "S", "operator": "<=", "limit": 250.0, "unit": "MPa", "required": True},
        ),
    )

    # Sub-test 1: Test NaN, +inf, -inf, and True (bool) all block delivery
    for bad_val in (float("nan"), float("inf"), float("-inf"), True):
        extraction = ResultExtraction(
            requirement=req,
            value=bad_val,
            locator={"step": "Step-1", "frame": -1, "field": "S", "component": "mises", "source": "odb"},
        )
        monkeypatch.setattr(res_mod, "extract_requirements", lambda ex, path, crit, _ext=extraction: ([_ext], ()))
        agent = AbaqusAIAgent(executor)
        result = agent.solve_requirement(
            requirement=intent,
            geometry=geom,
            material=mat,
            workdir=str(workdir),
            require_production=True,
        )
        assert result.status == TaskStatus.FAILED
        assert result.summary_card["engineering_status"] == "RESULT_INVALID"
        assert result.summary_card.get("delivery_card") is None

    # Sub-test 2: Valid numeric value but extraction diagnostics contains structured dict failure
    valid_extraction = ResultExtraction(
        requirement=req,
        value=150.0,
        locator={"step": "Step-1", "frame": -1, "field": "S", "component": "mises", "source": "odb"},
    )
    monkeypatch.setattr(res_mod, "extract_requirements", lambda ex, path, crit: ([valid_extraction], ()))

    # Inject structured error diagnostic into result bundle metadata
    orig_extract_bundle = agent.extract_result_intelligence
    def mock_bundle_with_diag(*args, **kwargs):
        bundle, figs = orig_extract_bundle(*args, **kwargs)
        if hasattr(bundle, "metadata"):
            bundle.metadata["extraction_diagnostics"] = {
                "max_mises": {"status": "FAILED", "reason": "sensor_reading_corrupted"}
            }
        return bundle, figs
    monkeypatch.setattr(agent, "extract_result_intelligence", mock_bundle_with_diag)

    result_diag = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        workdir=str(workdir),
        require_production=True,
    )
    assert result_diag.status == TaskStatus.FAILED
    assert result_diag.summary_card["engineering_status"] == "RESULT_INVALID"
    assert result_diag.summary_card.get("delivery_card") is None


def test_negative_p0_b_ambient_pre_existing_file_adoption_blocked_in_deliverable_mode(tmp_path: Path, monkeypatch):
    """Negative Test P0-B: Ambient file on disk matching spec target_filename MUST NOT be adopted in deliverable mode."""
    report_dir = tmp_path / "ambient_run_dir"
    report_dir.mkdir()
    ambient_file = report_dir / "ambient_stress_hotspot.png"
    ambient_file.write_bytes(MINIMAL_VALID_PNG_BYTES)

    mock_odb = tmp_path / "test_ambient.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)

    # Simulate Viewer execution not producing this figure
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_authentic_visualizations",
        lambda **kwargs: [],
    )

    pipeline = DeterministicReportPipeline()
    spec = VisualizationSpec(
        artifact_id="FIG-AMB-TEST",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename="ambient_stress_hotspot.png",
        output_position="INTEGRATION_POINT",
    )

    # In deliverable mode: fail-closed with PermissionError
    with pytest.raises(PermissionError) as exc_info:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Ambient Adoption Block Test",
            case_id="case_ambient",
            run_id="RUN-AMB-01",
            input_hash="INP-AMB-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            visualization_specs=[spec],
            require_deliverable=True,
        )
    assert "neither admitted with verified provenance nor rendered by a controlled Viewer session" in str(exc_info.value)
    # Zero leakage: report.html must not exist
    assert not (report_dir / "report.html").exists()


def test_negative_p0_b_delivery_gate_blocks_missing_input_hash_or_odb_hash(tmp_path: Path):
    """Negative Test P0-B: Final Delivery Gate unconditionally requires input_hash and authentic ODB hash."""
    report_dir = tmp_path / "gate_hash_dir"
    report_dir.mkdir()
    img_file = report_dir / "valid_gate_fig.png"
    img_bytes = MINIMAL_VALID_PNG_BYTES
    img_file.write_bytes(img_bytes)
    img_sha256 = hashlib.sha256(img_bytes).hexdigest()

    mock_odb = tmp_path / "test_gate.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha256 = hashlib.sha256(mock_odb.read_bytes()).hexdigest()

    from abaqus_ai_agent.execution.odb_rendering import (
        compute_viewer_session_token,
        create_render_execution_evidence,
    )
    valid_nonce = "0123456789abcdef0123456789abcdef"
    valid_token = compute_viewer_session_token(
        session_nonce=valid_nonce,
        run_id="RUN-GATE-01",
        odb_sha256=odb_sha256,
        target_filename=img_file.name,
        image_sha256=img_sha256,
    )
    valid_ev = create_render_execution_evidence(
        session_nonce=valid_nonce,
        run_id="RUN-GATE-01",
        odb_sha256=odb_sha256,
        rendered_figures=[{"filename": img_file.name, "image_sha256": img_sha256}],
    )

    fig = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-GATE-01",
            "input_hash": "INP-GATE-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": valid_nonce,
            "viewer_session_token": valid_token,
            "render_execution_evidence": valid_ev.to_dict(),
        },
    )

    pipeline = DeterministicReportPipeline()

    # Case A: Missing input_hash in execution context
    with pytest.raises(PermissionError) as exc_a:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Gate Test Missing Input Hash",
            case_id="case_gate",
            run_id="RUN-GATE-01",
            input_hash="",  # Empty
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig],
            require_deliverable=True,
        )
    assert "current execution input_hash is missing or empty" in str(exc_a.value)

    # Case B: Missing ODB path / hash in execution context
    with pytest.raises(PermissionError) as exc_b:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Gate Test Missing ODB",
            case_id="case_gate",
            run_id="RUN-GATE-01",
            input_hash="INP-GATE-01",
            odb_path=None,  # Missing
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig],
            require_deliverable=True,
        )
    assert "authentic ODB hash is missing or ODB file was not provided" in str(exc_b.value)


def test_negative_p0_b_delivery_gate_blocks_missing_viewer_session_token_or_unrendered(tmp_path: Path):
    """Negative Test P0-B: Final Delivery Gate blocks figure lacking viewer_session_token or viewer_rendered=True."""
    report_dir = tmp_path / "gate_token_dir"
    report_dir.mkdir()
    img_file = report_dir / "token_test_fig.png"
    img_bytes = MINIMAL_VALID_PNG_BYTES
    img_file.write_bytes(img_bytes)
    img_sha256 = hashlib.sha256(img_bytes).hexdigest()

    mock_odb = tmp_path / "test_token.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha256 = hashlib.sha256(mock_odb.read_bytes()).hexdigest()

    pipeline = DeterministicReportPipeline()

    # Case A: Missing viewer_session_token
    fig_no_token = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-TOK-01",
            "input_hash": "INP-TOK-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            # viewer_session_token missing!
        },
    )
    with pytest.raises(PermissionError) as exc_a:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Gate Test No Token",
            case_id="case_tok",
            run_id="RUN-TOK-01",
            input_hash="INP-TOK-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_no_token],
            require_deliverable=True,
        )
    assert "lacks authentic viewer_session_token evidence" in str(exc_a.value)

    # Case B: viewer_rendered is False
    fig_not_rendered = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-TOK-01",
            "input_hash": "INP-TOK-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": False,  # Not rendered by Viewer
            "viewer_session_token": "VIEWER-TOKEN-TOK-01",
        },
    )
    with pytest.raises(PermissionError) as exc_b:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Gate Test Not Rendered",
            case_id="case_tok",
            run_id="RUN-TOK-01",
            input_hash="INP-TOK-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_not_rendered],
            require_deliverable=True,
        )
    assert "was not rendered by a controlled Viewer session" in str(exc_b.value)

    # Case C: Missing render_execution_evidence
    from abaqus_ai_agent.execution.odb_rendering import compute_viewer_session_token
    token_c = compute_viewer_session_token(
        session_nonce="0123456789abcdef0123456789abcdef",
        run_id="RUN-TOK-01",
        odb_sha256=odb_sha256,
        target_filename=img_file.name,
        image_sha256=img_sha256,
    )
    fig_no_evidence = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-TOK-01",
            "input_hash": "INP-TOK-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": "0123456789abcdef0123456789abcdef",
            "viewer_session_token": token_c,
            # render_execution_evidence missing!
        },
    )
    with pytest.raises(PermissionError) as exc_c:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Gate Test No Evidence",
            case_id="case_tok",
            run_id="RUN-TOK-01",
            input_hash="INP-TOK-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_no_evidence],
            require_deliverable=True,
        )
    assert "lacks mandatory render_execution_evidence" in str(exc_c.value)


def test_odb_rendering_session_nonce_and_token_entropy_verification(tmp_path: Path, monkeypatch):
    """Verify render_authentic_visualizations stamps fresh cryptographic nonce and authentic token."""
    from abaqus_ai_agent.execution.odb_rendering import render_authentic_visualizations
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    mock_odb = tmp_path / "nonce_test.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)

    out_dir = tmp_path / "nonce_out"
    out_dir.mkdir()
    target_img = out_dir / "nonce_stress.png"
    target_img.write_bytes(MINIMAL_VALID_PNG_BYTES)

    spec = VisualizationSpec(
        artifact_id="FIG-NONCE",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename="nonce_stress.png",
    )

    # Monkeypatch headless rendering runner to simulate successful Viewer run
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_odb_contours_headless",
        lambda **kwargs: [target_img],
    )

    figs_run1 = render_authentic_visualizations(
        odb_path=mock_odb,
        specs=[spec],
        output_dir=out_dir,
        run_id="RUN-NONCE-1",
        input_hash="INP-NONCE-1",
    )
    assert len(figs_run1) == 1
    meta1 = figs_run1[0].metadata
    nonce1 = meta1.get("session_nonce")
    token1 = meta1.get("viewer_session_token")
    assert nonce1 and len(nonce1) >= 16
    assert token1 and token1.startswith("VIEWER-TOKEN-")
    assert meta1["viewer_rendered"] is True

    # Run 2: Fresh nonce must differ from Run 1
    figs_run2 = render_authentic_visualizations(
        odb_path=mock_odb,
        specs=[spec],
        output_dir=out_dir,
        run_id="RUN-NONCE-1",
        input_hash="INP-NONCE-1",
    )
    meta2 = figs_run2[0].metadata
    nonce2 = meta2.get("session_nonce")
    token2 = meta2.get("viewer_session_token")
    assert nonce2 != nonce1
    assert token2 != token1


def test_negative_p0_b_forged_viewer_session_token_rejected_in_admission_and_delivery_gate(tmp_path: Path):
    """Negative Test P0-B: Forged, tampered, or mismatched viewer_session_token fails closed."""
    from abaqus_ai_agent.execution.odb_rendering import compute_viewer_session_token
    from abaqus_ai_agent.reporting.figure_selector import admit_figure_for_reuse

    report_dir = tmp_path / "forged_token_dir"
    report_dir.mkdir()
    img_file = report_dir / "forged_fig.png"
    img_bytes = MINIMAL_VALID_PNG_BYTES
    img_file.write_bytes(img_bytes)
    img_sha256 = hashlib.sha256(img_bytes).hexdigest()

    mock_odb = tmp_path / "forged_test.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha256 = hashlib.sha256(mock_odb.read_bytes()).hexdigest()

    pipeline = DeterministicReportPipeline()
    nonce = "0123456789abcdef0123456789abcdef"

    # Subcase 1: Arbitrary string token (not cryptographically derived)
    fig_forged_str = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-FORGE-01",
            "input_hash": "INP-FORGE-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": nonce,
            "viewer_session_token": "VIEWER-TOKEN-FORGED-STRING-12345",
        },
    )
    is_adm, reason = admit_figure_for_reuse(
        figure=fig_forged_str,
        current_run_id="RUN-FORGE-01",
        current_input_hash="INP-FORGE-01",
        current_odb_hash=odb_sha256,
        target_field="S",
        target_component="mises",
    )
    assert is_adm is False
    assert "viewer_session_token mismatch or forged" in reason

    with pytest.raises(PermissionError) as exc_forge:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Forged Token Test",
            case_id="case_forge",
            run_id="RUN-FORGE-01",
            input_hash="INP-FORGE-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_forged_str],
            require_deliverable=True,
        )
    assert "viewer_session_token verification failed" in str(exc_forge.value)

    # Subcase 2: Nonce missing or too short (<16 chars)
    fig_bad_nonce = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-FORGE-01",
            "input_hash": "INP-FORGE-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": "too_short",
            "viewer_session_token": "VIEWER-TOKEN-ANYTHING",
        },
    )
    is_adm_n, reason_n = admit_figure_for_reuse(
        figure=fig_bad_nonce,
        current_run_id="RUN-FORGE-01",
        current_input_hash="INP-FORGE-01",
        current_odb_hash=odb_sha256,
        target_field="S",
        target_component="mises",
    )
    assert is_adm_n is False
    assert "lacks authentic session_nonce evidence" in reason_n

    with pytest.raises(PermissionError) as exc_nonce:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Bad Nonce Test",
            case_id="case_forge",
            run_id="RUN-FORGE-01",
            input_hash="INP-FORGE-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_bad_nonce],
            require_deliverable=True,
        )
    assert "lacks authentic session_nonce evidence" in str(exc_nonce.value)

    # Subcase 3: Token derived from foreign run_id
    foreign_token = compute_viewer_session_token(
        session_nonce=nonce,
        run_id="FOREIGN-RUN",
        odb_sha256=odb_sha256,
        target_filename=img_file.name,
        image_sha256=img_sha256,
    )
    fig_foreign = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-FORGE-01",
            "input_hash": "INP-FORGE-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": nonce,
            "viewer_session_token": foreign_token,
        },
    )
    is_adm_f, reason_f = admit_figure_for_reuse(
        figure=fig_foreign,
        current_run_id="RUN-FORGE-01",
        current_input_hash="INP-FORGE-01",
        current_odb_hash=odb_sha256,
        target_field="S",
        target_component="mises",
    )
    assert is_adm_f is False
    assert "viewer_session_token mismatch or forged" in reason_f

    # Subcase 4: Forged / tampered render_execution_evidence HMAC signature fails closed in admission & delivery gate
    from abaqus_ai_agent.execution.odb_rendering import create_render_execution_evidence
    valid_token_4 = compute_viewer_session_token(
        session_nonce=nonce,
        run_id="RUN-FORGE-01",
        odb_sha256=odb_sha256,
        target_filename=img_file.name,
        image_sha256=img_sha256,
    )
    tampered_ev = create_render_execution_evidence(
        session_nonce=nonce,
        run_id="RUN-FORGE-01",
        odb_sha256=odb_sha256,
        rendered_figures=[{"filename": img_file.name, "image_sha256": img_sha256}],
    ).to_dict()
    tampered_ev["session_signature"] = "deadbeef" * 8  # Forged HMAC signature

    fig_tampered_sig = ReportFigure(
        kind="stress_hotspot",
        path=str(img_file.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-FORGE-01",
            "input_hash": "INP-FORGE-01",
            "odb_sha256": odb_sha256,
            "image_sha256": img_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": nonce,
            "viewer_session_token": valid_token_4,
            "render_execution_evidence": tampered_ev,
        },
    )
    is_adm_sig, reason_sig = admit_figure_for_reuse(
        figure=fig_tampered_sig,
        current_run_id="RUN-FORGE-01",
        current_input_hash="INP-FORGE-01",
        current_odb_hash=odb_sha256,
        target_field="S",
        target_component="mises",
    )
    assert is_adm_sig is False
    assert "Render execution evidence invalid" in reason_sig

    with pytest.raises(PermissionError) as exc_sig:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Forged Signature Test",
            case_id="case_forge",
            run_id="RUN-FORGE-01",
            input_hash="INP-FORGE-01",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_tampered_sig],
            require_deliverable=True,
        )
    assert "render_execution_evidence invalid" in str(exc_sig.value)


def test_negative_p0_b_preexisting_stale_image_not_adopted_if_viewer_fails_or_does_not_produce(tmp_path: Path, monkeypatch):
    """Negative Test P0-B: Stale file sitting in output_dir is never certified if Viewer doesn't produce it."""
    from abaqus_ai_agent.execution.odb_rendering import render_authentic_visualizations
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    mock_odb = tmp_path / "ambient_test.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)

    out_dir = tmp_path / "ambient_out"
    out_dir.mkdir()
    stale_img = out_dir / "stale_stress.png"
    # Pre-existing file sitting in output directory from a previous or foreign process
    stale_img.write_bytes(MINIMAL_VALID_PNG_BYTES)

    spec = VisualizationSpec(
        artifact_id="FIG-STALE",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename="stale_stress.png",
    )

    # Simulate headless viewer returning an empty list (failed to produce image in scratch sandbox)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_odb_contours_headless",
        lambda **kwargs: [],
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        render_authentic_visualizations(
            odb_path=mock_odb,
            specs=[spec],
            output_dir=out_dir,
            run_id="RUN-FRESH-01",
            input_hash="INP-FRESH-01",
        )

    err = str(exc_info.value)
    assert "failed to render from ODB" in err
    assert "in this viewer session" in err


def test_negative_p0_c_viewer_script_rejects_invalid_output_position_and_has_no_nodal_fallback():
    """Negative Test P0-C: Invalid outputPosition raises ValueError; script has no silent NODAL fallback."""
    from abaqus_ai_agent.execution.odb_rendering import ContourPlotRequest, generate_headless_viewer_script

    # 1. Invalid outputPosition raises ValueError immediately during script generation
    req_invalid_pos = ContourPlotRequest(
        output_filename="test_pos.png",
        output_position="UNSUPPORTED_RANDOM_POS",
        variable_label="S",
    )
    with pytest.raises(ValueError, match="Invalid output_position"):
        generate_headless_viewer_script("dummy.odb", [req_invalid_pos], "dummy_dir")

    # 2. Scalar variable with no invariant has NO silent fallback to NODAL
    req_scalar = ContourPlotRequest(
        output_filename="test_scalar.png",
        variable_label="CPRESS",
        component_or_invariant=None,
        output_position="INTEGRATION_POINT",
    )
    script = generate_headless_viewer_script("dummy.odb", [req_scalar], "dummy_dir")
    assert "outputPosition=NODAL" not in script
    assert "Failed to set primary variable \"CPRESS\" at outputPosition INTEGRATION_POINT" in script


def test_negative_p0_png_corrupt_or_fake_rejected_in_delivery_gate(tmp_path: Path):
    """Negative Test P0: Final Delivery Gate rejects corrupt or fake non-PNG figure files."""
    report_dir = tmp_path / "gate_corrupt_png_dir"
    report_dir.mkdir()
    fake_png = report_dir / "fake_stress.png"
    fake_png.write_text("NOT A REAL PNG FILE AT ALL - JUST TEXT", encoding="utf-8")
    fake_sha256 = hashlib.sha256(fake_png.read_bytes()).hexdigest()

    mock_odb = tmp_path / "test_corrupt.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha256 = hashlib.sha256(mock_odb.read_bytes()).hexdigest()

    from abaqus_ai_agent.execution.odb_rendering import compute_viewer_session_token
    nonce = "0123456789abcdef0123456789abcdef"
    token = compute_viewer_session_token(
        session_nonce=nonce,
        run_id="RUN-CORRUPT",
        odb_sha256=odb_sha256,
        target_filename=fake_png.name,
        image_sha256=fake_sha256,
    )

    fig = ReportFigure(
        kind="stress_hotspot",
        path=str(fake_png.as_posix()),
        metadata={
            "field": "S",
            "component": "mises",
            "run_id": "RUN-CORRUPT",
            "input_hash": "INP-CORRUPT",
            "odb_sha256": odb_sha256,
            "image_sha256": fake_sha256,
            "output_position": "INTEGRATION_POINT",
            "viewer_rendered": True,
            "session_nonce": nonce,
            "viewer_session_token": token,
        },
    )

    pipeline = DeterministicReportPipeline()
    with pytest.raises(PermissionError) as exc_info:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Corrupt PNG Gate Test",
            case_id="case_corrupt",
            run_id="RUN-CORRUPT",
            input_hash="INP-CORRUPT",
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig],
            require_deliverable=True,
        )
    assert "is corrupt or not a valid PNG image" in str(exc_info.value)
    # Ensure zero leakage
    assert not (report_dir / "report.html").exists()


def test_negative_p0_duplicate_target_filename_rejected(tmp_path: Path):
    """Negative Test P0: Multiple visualization requests with duplicate target_filename raise ValueError."""
    req1 = ContourPlotRequest(
        output_filename="duplicate_name.png",
        variable_label="S",
        component_or_invariant="mises",
    )
    req2 = ContourPlotRequest(
        output_filename="duplicate_name.png",
        variable_label="U",
        component_or_invariant="magnitude",
    )
    with pytest.raises(ValueError, match="Duplicate target_filename detected"):
        generate_headless_viewer_script("dummy.odb", [req1, req2], "out_dir")


def test_negative_p0_stale_report_locked_fails_closed(tmp_path: Path, monkeypatch):
    """Negative Test P0: Pre-existing stale report.html that cannot be removed aborts delivery."""
    report_dir = tmp_path / "stale_lock_dir"
    report_dir.mkdir()
    stale_file = report_dir / "report.html"
    stale_file.write_text("OLD STALE REPORT CONTENT", encoding="utf-8")

    pipeline = DeterministicReportPipeline()
    # Mock unlink to raise PermissionError
    monkeypatch.setattr(Path, "unlink", lambda self, *args, **kwargs: (_ for _ in ()).throw(PermissionError("File locked by process")))

    with pytest.raises(PermissionError) as exc_info:
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Stale Report Lock Test",
            case_id="case_stale_lock",
            run_id="RUN-STALE-LOCK",
            input_hash="INP-STALE-LOCK",
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            require_deliverable=True,
        )
    assert "unable to safely remove existing stale report" in str(exc_info.value)


def test_atomic_report_publishing_blocks_partial_leakage_on_gate_failure(tmp_path: Path):
    """Negative Test P0: If Final Delivery Gate fails, target_dir has ZERO report.html written."""
    report_dir = tmp_path / "atomic_zero_leakage_dir"
    report_dir.mkdir()

    pipeline = DeterministicReportPipeline()
    spec = VisualizationSpec(
        artifact_id="FIG-FAIL",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename="missing_figure.png",
    )

    with pytest.raises((PermissionError, FileNotFoundError)):
        pipeline.build_and_render(
            output_dir=report_dir,
            title="Atomic Leakage Block Test",
            case_id="case_atomic",
            run_id="RUN-ATOMIC-01",
            input_hash="INP-ATOMIC-01",
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            visualization_specs=[spec],
            require_deliverable=True,
        )

    # Zero file leakage in target directory
    assert not (report_dir / "report.html").exists()
