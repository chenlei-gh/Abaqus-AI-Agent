"""Unit tests for Headless Abaqus Viewer ODB Visualization and Contour Rendering Engine."""

import os
from pathlib import Path
import pytest

from abaqus_ai_agent.execution.odb_rendering import (
    ContourPlotRequest,
    generate_headless_viewer_script,
    render_odb_contours_headless,
)


def test_contour_plot_request_defaults():
    """Verify default values and data structure of ContourPlotRequest."""
    req = ContourPlotRequest(output_filename="stress.png")
    assert req.output_filename == "stress.png"
    assert req.variable_label == "S"
    assert req.component_or_invariant == "Mises"
    assert req.output_position == "INTEGRATION_POINT"
    assert req.step_name is None
    assert req.frame_index == -1
    assert req.plot_state == "CONTOURS_ON_DEF"
    assert req.view_orientation == "Iso"
    assert req.deformation_scale_factor is None
    assert req.caption == ""
    assert req.description == ""


def test_contour_plot_request_custom():
    """Verify custom attributes assignment in ContourPlotRequest."""
    req = ContourPlotRequest(
        output_filename="disp_5x.png",
        variable_label="U",
        component_or_invariant="Magnitude",
        output_position="NODAL",
        step_name="Step-2",
        frame_index=10,
        plot_state="CONTOURS_ON_DEF",
        view_orientation="Top",
        deformation_scale_factor=5.0,
        caption="Displacement Contour",
        description="5x magnified displacement field",
    )
    assert req.output_filename == "disp_5x.png"
    assert req.variable_label == "U"
    assert req.component_or_invariant == "Magnitude"
    assert req.output_position == "NODAL"
    assert req.step_name == "Step-2"
    assert req.frame_index == 10
    assert req.view_orientation == "Top"
    assert req.deformation_scale_factor == 5.0
    assert req.caption == "Displacement Contour"


def test_generate_headless_viewer_script_syntax_and_api():
    """Verify generated Python script conforms to Abaqus Viewer headless API standards."""
    requests = [
        ContourPlotRequest(
            output_filename="case_03_manifold_mises_stress.png",
            variable_label="S",
            component_or_invariant="Mises",
            step_name="Hot_Coupled_Operation",
            plot_state="CONTOURS_ON_DEF",
            view_orientation="Iso",
        ),
        ContourPlotRequest(
            output_filename="case_03_manifold_displacement.png",
            variable_label="U",
            component_or_invariant="Magnitude",
            output_position="NODAL",
            step_name="Hot_Coupled_Operation",
            plot_state="CONTOURS_ON_DEF",
            view_orientation="Iso",
            deformation_scale_factor=5.0,
        ),
        ContourPlotRequest(
            output_filename="case_03_manifold_temperature.png",
            variable_label="NT",
            component_or_invariant="NT11",
            output_position="NODAL",
            step_name="Steady_Heat_Transfer",
        ),
        ContourPlotRequest(
            output_filename="case_03_manifold_contact_pressure.png",
            variable_label="CPRESS",
            component_or_invariant=None,
            view_orientation="Top",
        ),
    ]

    script = generate_headless_viewer_script(
        odb_path="D:/Vault/Abaqus/runs/job.odb",
        requests=requests,
        output_dir="D:/Vault/Abaqus/output",
    )

    # 1. Essential Abaqus module imports
    assert "from abaqus import *" in script
    assert "from abaqusConstants import *" in script
    assert "import visualization" in script

    # 2. ODB opening and viewport binding
    assert "visualization.openOdb(path=odb_path, readOnly=True)" in script
    assert "vp.setValues(displayedObject=odb)" in script

    # 3. Clean publication-grade viewport presentation
    assert "session.printOptions.setValues(vpBackground=OFF)" in script
    assert "renderStyle=SHADED" in script

    # 4. Request 1: S (Mises)
    assert "case_03_manifold_mises_stress.png" in script
    assert "variableLabel='S'" in script
    assert "refinement=(INVARIANT, 'MISES')" in script
    assert "plotState=(CONTOURS_ON_DEF,)" in script

    # 5. Request 2: U (Magnitude) with 5.0x deformation scale
    assert "case_03_manifold_displacement.png" in script
    assert "variableLabel='U'" in script
    assert "uniformScaleFactor=5.0" in script
    assert "outputPosition=NODAL" in script

    # 6. Request 3: NT11 temperature field
    assert "case_03_manifold_temperature.png" in script
    assert "variableLabel='NT'" in script

    # 7. Request 4: CPRESS scalar and Top camera view
    assert "case_03_manifold_contact_pressure.png" in script
    assert "variableLabel='CPRESS'" in script
    assert "session.views['Top']" in script

    # 8. Printing and cleanup
    assert "session.printToFile(fileName=out_img, format=PNG, canvasObjects=(vp,))" in script
    assert "odb.close()" in script


def test_render_odb_contours_headless_missing_launcher(tmp_path):
    """Verify runtime error when specified Abaqus launcher does not exist."""
    req = ContourPlotRequest(output_filename="test.png")
    with pytest.raises(RuntimeError, match="Abaqus launcher not found"):
        render_odb_contours_headless(
            odb_path="dummy.odb",
            requests=[req],
            output_dir=tmp_path,
            launcher="non_existent_abaqus_launcher_999",
        )


def test_render_authentic_visualizations_fails_closed_on_fake_odb(tmp_path):
    from abaqus_ai_agent.execution.odb_rendering import render_authentic_visualizations
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    fake_odb = tmp_path / "fake.odb"
    fake_odb.write_text('{"fake": "odb"}', encoding="utf-8")
    spec = VisualizationSpec(
        artifact_id="fig_1",
        visualization_type="stress_contour",
        field_name="S",
        component="Mises",
        target_filename="stress.png",
    )

    with pytest.raises(ValueError, match="not an authentic binary ODB"):
        render_authentic_visualizations(
            odb_path=fake_odb,
            specs=[spec],
            output_dir=tmp_path,
        )


def test_render_authentic_visualizations_fails_closed_when_image_missing(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution.odb_rendering import render_authentic_visualizations
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    # Create dummy binary ODB
    valid_odb = tmp_path / "valid.odb"
    valid_odb.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 4096)

    # Monkeypatch render_odb_contours_headless to simulate a failure where no PNG is produced
    def mock_headless_render(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_odb_contours_headless",
        mock_headless_render,
    )

    spec = VisualizationSpec(
        artifact_id="fig_fail",
        visualization_type="stress_contour",
        field_name="S",
        component="Mises",
        target_filename="stress_missing.png",
    )

    with pytest.raises(FileNotFoundError, match="Fail-Closed: Authentic CAE visualization"):
        render_authentic_visualizations(
            odb_path=valid_odb,
            specs=[spec],
            output_dir=tmp_path,
            run_id="run_test",
            input_hash="hash_test",
        )


def test_render_authentic_visualizations_success_and_lineage_binding(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution.odb_rendering import render_authentic_visualizations
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    valid_odb = tmp_path / "valid.odb"
    valid_odb.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 4096)

    target_png = tmp_path / "stress_success.png"

    # Monkeypatch render_odb_contours_headless to simulate successful PNG rendering
    def mock_headless_render(odb_path, requests, output_dir, **kwargs):
        from abaqus_ai_agent.execution.odb_rendering import MINIMAL_VALID_PNG_BYTES
        target_png.write_bytes(MINIMAL_VALID_PNG_BYTES)
        return [target_png]

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_odb_contours_headless",
        mock_headless_render,
    )

    spec = VisualizationSpec(
        artifact_id="fig_success",
        visualization_type="stress_contour",
        field_name="S",
        component="Mises",
        target_filename="stress_success.png",
        caption_zh="Mises 应力云图",
        caption_en="Mises Stress Contour",
    )

    figures = render_authentic_visualizations(
        odb_path=valid_odb,
        specs=[spec],
        output_dir=tmp_path,
        run_id="run_golden_render",
        input_hash="hash_golden_render",
    )

    assert len(figures) == 1
    fig = figures[0]
    assert fig.kind == "stress_contour"
    assert fig.metadata["run_id"] == "run_golden_render"
    assert fig.metadata["input_hash"] == "hash_golden_render"
    assert fig.metadata["odb_path"] == str(valid_odb.resolve())
    assert len(fig.metadata["odb_sha256"]) == 64
    assert len(fig.metadata["image_sha256"]) == 64


def test_verify_render_execution_evidence_input_hash_strictness():
    """Verify input_hash strict fail-closed enforcement in verify_render_execution_evidence."""
    from abaqus_ai_agent.execution.odb_rendering import (
        create_render_execution_evidence,
        verify_render_execution_evidence,
    )

    ev_no_hash = create_render_execution_evidence(
        session_nonce="nonce123456789012345678901234567",
        run_id="RUN-STRICT-01",
        odb_sha256="ODB-SHA-1",
        input_hash="",
        rendered_figures=[{"filename": "a.png", "image_sha256": "sha_a"}],
    )
    ok, reason = verify_render_execution_evidence(
        evidence=ev_no_hash,
        expected_run_id="RUN-STRICT-01",
        expected_odb_sha256="ODB-SHA-1",
        expected_input_hash="INPUT-REQUIRED-01",
    )
    assert not ok
    assert "Evidence lacks required input_hash" in reason

    ev_mismatch = create_render_execution_evidence(
        session_nonce="nonce123456789012345678901234567",
        run_id="RUN-STRICT-01",
        odb_sha256="ODB-SHA-1",
        input_hash="INPUT-A",
        rendered_figures=[{"filename": "a.png", "image_sha256": "sha_a"}],
    )
    ok_m, reason_m = verify_render_execution_evidence(
        evidence=ev_mismatch,
        expected_run_id="RUN-STRICT-01",
        expected_odb_sha256="ODB-SHA-1",
        expected_input_hash="INPUT-B",
    )
    assert not ok_m
    assert "Evidence input_hash mismatch" in reason_m


def test_verify_render_execution_evidence_duplicate_filenames_rejected():
    """Verify duplicate filenames in rendered_figures are rejected."""
    from abaqus_ai_agent.execution.odb_rendering import (
        create_render_execution_evidence,
        verify_render_execution_evidence,
    )

    ev_dup = create_render_execution_evidence(
        session_nonce="nonce123456789012345678901234567",
        run_id="RUN-DUP-01",
        odb_sha256="ODB-SHA-1",
        input_hash="INP-1",
        rendered_figures=[
            {"filename": "dup.png", "image_sha256": "sha_1"},
            {"filename": "dup.png", "image_sha256": "sha_2"},
        ],
    )
    ok, reason = verify_render_execution_evidence(
        evidence=ev_dup,
        expected_run_id="RUN-DUP-01",
        expected_odb_sha256="ODB-SHA-1",
        expected_input_hash="INP-1",
    )
    assert not ok
    assert "duplicate filenames" in reason


def test_admit_figure_and_pipeline_delivery_fails_closed_on_unregistered_or_duplicate_figure(tmp_path):
    """Verify admit_figure_for_reuse and DeterministicReportPipeline reject unregistered or duplicate figures."""
    import hashlib
    from abaqus_ai_agent.contracts.report import ReportFigure
    from abaqus_ai_agent.execution.odb_rendering import (
        MINIMAL_VALID_PNG_BYTES,
        compute_viewer_session_token,
        create_render_execution_evidence,
    )
    from abaqus_ai_agent.reporting import AdaptiveReportBuilder, AnalysisObjective
    from abaqus_ai_agent.reporting.figure_selector import admit_figure_for_reuse
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    nonce = "0123456789abcdef0123456789abcdef"
    run_id = "RUN-FAIL-CLOSED-01"
    inp_hash = "INP-FC-1"

    mock_odb = tmp_path / "mock.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha = hashlib.sha256(mock_odb.read_bytes()).hexdigest()

    img_path = tmp_path / "test_fig.png"
    img_path.write_bytes(MINIMAL_VALID_PNG_BYTES)
    img_sha = hashlib.sha256(MINIMAL_VALID_PNG_BYTES).hexdigest()

    token = compute_viewer_session_token(
        session_nonce=nonce,
        run_id=run_id,
        odb_sha256=odb_sha,
        target_filename=img_path.name,
        image_sha256=img_sha,
    )

    # 1. Unregistered figure in manifest
    ev_unregistered = create_render_execution_evidence(
        session_nonce=nonce,
        run_id=run_id,
        odb_sha256=odb_sha,
        input_hash=inp_hash,
        rendered_figures=[{"filename": "other_file.png", "image_sha256": "other_sha"}],
    )
    fig_unreg = ReportFigure(
        kind="stress_hotspot",
        path=str(img_path.as_posix()),
        caption="Unregistered figure",
        source="S.mises",
        metadata={
            "field": "S",
            "component": "mises",
            "step": "Step-1",
            "frame": -1,
            "region": "WHOLE_MODEL",
            "output_position": "INTEGRATION_POINT",
            "run_id": run_id,
            "input_hash": inp_hash,
            "odb_hash": odb_sha,
            "odb_sha256": odb_sha,
            "sha256": img_sha,
            "image_sha256": img_sha,
            "viewer_rendered": True,
            "session_nonce": nonce,
            "viewer_session_token": token,
            "render_execution_evidence": ev_unregistered.to_dict(),
        },
    )

    ok, reason = admit_figure_for_reuse(
        figure=fig_unreg,
        current_run_id=run_id,
        current_input_hash=inp_hash,
        current_odb_hash=odb_sha,
        target_field="S",
        target_component="mises",
    )
    assert not ok
    assert "is not registered in signed RenderExecutionEvidence manifest" in reason

    # Pipeline delivery check
    pipeline = DeterministicReportPipeline(
        builder=AdaptiveReportBuilder(
            physics_domain="structural",
            objective=AnalysisObjective.STATIC_STRENGTH,
        )
    )
    spec = VisualizationSpec(
        artifact_id="FIG-S-01",
        visualization_type="stress_hotspot",
        field_name="S",
        component="mises",
        target_filename=img_path.name,
    )

    with pytest.raises(PermissionError, match="is not registered in signed RenderExecutionEvidence"):
        pipeline.build_and_render(
            output_dir=tmp_path / "out_unreg",
            title="Unregistered Test",
            case_id="case_unreg",
            run_id=run_id,
            input_hash=inp_hash,
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_unreg],
        )

    # 2. Duplicate figure entries in manifest
    ev_duplicate_manifest = {
        "session_nonce": nonce,
        "run_id": run_id,
        "odb_sha256": odb_sha,
        "timestamp_utc": "2026-10-10T12:00:00Z",
        "rendered_figures": [
            {"filename": img_path.name, "image_sha256": img_sha},
            {"filename": img_path.name, "image_sha256": img_sha},
        ],
        "exit_code": 0,
        "viewer_duration_sec": 0.5,
        "input_hash": inp_hash,
        "viewer_script_sha256": "",
        "session_signature": "mock_sig",
    }
    # Direct check against figure_selector and pipeline with duplicate entries in dict
    fig_dup = ReportFigure(
        kind="stress_hotspot",
        path=str(img_path.as_posix()),
        caption="Duplicate entry figure",
        source="S.mises",
        metadata={
            "field": "S",
            "component": "mises",
            "step": "Step-1",
            "frame": -1,
            "region": "WHOLE_MODEL",
            "output_position": "INTEGRATION_POINT",
            "run_id": run_id,
            "input_hash": inp_hash,
            "odb_hash": odb_sha,
            "odb_sha256": odb_sha,
            "sha256": img_sha,
            "image_sha256": img_sha,
            "viewer_rendered": True,
            "session_nonce": nonce,
            "viewer_session_token": token,
            "render_execution_evidence": ev_duplicate_manifest,
        },
    )

    with pytest.raises(
        PermissionError,
        match=r"(Evidence rendered_figures contains duplicate filenames|has duplicate entries in signed RenderExecutionEvidence)",
    ):
        pipeline.build_and_render(
            output_dir=tmp_path / "out_dup",
            title="Duplicate Test",
            case_id="case_dup",
            run_id=run_id,
            input_hash=inp_hash,
            odb_path=mock_odb,
            model_info={},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            figures=[fig_dup],
        )
