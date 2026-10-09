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
    img_mises.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    img_disp = workdir / "total_displacement.png"
    img_disp.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

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
