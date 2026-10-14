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


def test_render_signing_key_lifecycle_and_cross_process_contract(monkeypatch):
    """Verify in-process ephemeral vs cross-process persistent key lifecycle contract."""
    from abaqus_ai_agent.execution.odb_rendering import (
        create_render_execution_evidence,
        get_render_signing_key,
        verify_render_execution_evidence,
    )

    # 1. Ephemeral in-process default
    monkeypatch.delenv("ABAQUS_RENDER_SIGNING_SECRET", raising=False)
    k1 = get_render_signing_key(require_persistent=False)
    assert len(k1) == 32

    # 2. require_persistent fails closed when environment secret is missing
    with pytest.raises(RuntimeError, match="Persistent evidence verification requires"):
        get_render_signing_key(require_persistent=True)

    # 3. Explicit signing_key override takes absolute priority
    explicit_key = b"explicit_secret_key_32bytes_pad"
    k_exp = get_render_signing_key(signing_key=explicit_key, require_persistent=True)
    assert k_exp == explicit_key

    # 4. Environment-controlled secret key enables cross-process audit verification
    shared_secret = "ci_audit_production_signing_secret_999"
    monkeypatch.setenv("ABAQUS_RENDER_SIGNING_SECRET", shared_secret)
    k_env = get_render_signing_key(require_persistent=True)
    import hashlib
    assert k_env == hashlib.sha256(shared_secret.encode("utf-8")).digest()

    ev_persistent = create_render_execution_evidence(
        session_nonce="nonce_persistent_0123456789abcdef",
        run_id="RUN-PERSISTENT-01",
        odb_sha256="ODB-PERSISTENT-SHA",
        input_hash="INP-PERSISTENT-HASH",
        rendered_figures=[{"filename": "contour.png", "image_sha256": "sha_contour"}],
        require_persistent_key=True,
    )

    # Verify successfully in simulated cross-process with same secret
    ok, msg = verify_render_execution_evidence(
        evidence=ev_persistent,
        expected_run_id="RUN-PERSISTENT-01",
        expected_odb_sha256="ODB-PERSISTENT-SHA",
        expected_input_hash="INP-PERSISTENT-HASH",
        require_persistent_key=True,
    )
    assert ok, f"Expected valid persistent verification, got: {msg}"

    # Verify fails closed if cross-process verifier uses wrong secret
    monkeypatch.setenv("ABAQUS_RENDER_SIGNING_SECRET", "wrong_cross_process_secret")
    ok_bad, msg_bad = verify_render_execution_evidence(
        evidence=ev_persistent,
        expected_run_id="RUN-PERSISTENT-01",
        expected_odb_sha256="ODB-PERSISTENT-SHA",
        expected_input_hash="INP-PERSISTENT-HASH",
        require_persistent_key=True,
    )
    assert not ok_bad
    assert "session_signature mismatch or forged" in msg_bad


def test_render_evidence_actual_cross_process_subprocess_audit(tmp_path):
    """Launch real independent Python subprocesses to verify cross-process audit contract."""
    import hashlib
    import json
    import os
    import subprocess
    import sys
    from abaqus_ai_agent.execution.odb_rendering import (
        create_render_execution_evidence,
    )

    shared_secret = "ci_audit_production_signing_secret_999"
    ev = create_render_execution_evidence(
        session_nonce="nonce_subprocess_audit_0123456789",
        run_id="RUN-SUBPROCESS-01",
        odb_sha256="ODB-SUBPROCESS-SHA",
        input_hash="INP-SUBPROCESS-HASH",
        rendered_figures=[{"filename": "contour.png", "image_sha256": "sha_contour"}],
        require_persistent_key=True,
        signing_key=hashlib.sha256(shared_secret.encode("utf-8")).digest(),
    )

    evidence_json_path = tmp_path / "evidence.json"
    evidence_json_path.write_text(json.dumps(ev.to_dict()), encoding="utf-8")

    probe_script = tmp_path / "probe.py"
    probe_script.write_text(
        "import json, sys\n"
        "from abaqus_ai_agent.execution.odb_rendering import verify_render_execution_evidence\n"
        "with open(sys.argv[1], 'r', encoding='utf-8') as f:\n"
        "    ev_data = json.load(f)\n"
        "ok, msg = verify_render_execution_evidence(\n"
        "    evidence=ev_data,\n"
        "    expected_run_id='RUN-SUBPROCESS-01',\n"
        "    expected_odb_sha256='ODB-SUBPROCESS-SHA',\n"
        "    expected_input_hash='INP-SUBPROCESS-HASH',\n"
        "    require_persistent_key=True,\n"
        ")\n"
        "if not ok:\n"
        "    sys.exit(2)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    # 1. Subprocess with matching secret -> Must return 0
    env_good = dict(os.environ, ABAQUS_RENDER_SIGNING_SECRET=shared_secret)
    p_good = subprocess.run([sys.executable, str(probe_script), str(evidence_json_path)], env=env_good, capture_output=True, text=True)
    assert p_good.returncode == 0

    # 2. Subprocess with mismatch secret -> Must return 2
    env_bad = dict(os.environ, ABAQUS_RENDER_SIGNING_SECRET="mismatch_secret_xyz")
    p_bad = subprocess.run([sys.executable, str(probe_script), str(evidence_json_path)], env=env_bad, capture_output=True, text=True)
    assert p_bad.returncode == 2

    # 3. Subprocess with missing secret -> Must fail closed (return 2)
    env_none = dict(os.environ)
    env_none.pop("ABAQUS_RENDER_SIGNING_SECRET", None)
    p_none = subprocess.run([sys.executable, str(probe_script), str(evidence_json_path)], env=env_none, capture_output=True, text=True)
    assert p_none.returncode == 2


def test_generate_headless_viewer_script_animation_options():
    """Verify headless viewer script generation handles animation parameters and sampling."""
    req_anim = ContourPlotRequest(
        output_filename="motion.gif",
        variable_label="U",
        component_or_invariant="Magnitude",
        is_animation=True,
        animation_frames=30,
        animation_duration_ms=80,
        is_ping_pong=False,
    )

    script = generate_headless_viewer_script(
        odb_path="dummy.odb",
        requests=[req_anim],
        output_dir="dummy_out",
    )

    assert "target_samples = 30" in script
    assert "_anim_frames_0" in script
    assert "session.printToFile(fileName=frame_target, format=PNG, canvasObjects=(vp,))" in script
    assert "target_step.frames" in script


def test_render_odb_animation_headless_missing_odb(tmp_path):
    """Verify render_odb_animation_headless fails closed when ODB does not exist."""
    from abaqus_ai_agent.execution.odb_rendering import render_odb_animation_headless

    non_existent = tmp_path / "does_not_exist.odb"
    out_gif = tmp_path / "anim.gif"
    with pytest.raises(FileNotFoundError, match="Target ODB file does not exist"):
        render_odb_animation_headless(
            odb_path=non_existent,
            output_path=out_gif,
        )


def test_contour_plot_request_safe_margin_and_motion_detection_defaults():
    """Verify default and custom parameters for viewport zoom and active motion detection."""
    req_default = ContourPlotRequest(output_filename="mises.png")
    assert req_default.viewport_zoom_factor is None
    assert req_default.active_motion_only is True
    assert req_default.motion_threshold == 0.005

    req_custom = ContourPlotRequest(
        output_filename="anim.gif",
        viewport_zoom_factor=0.75,
        active_motion_only=False,
        motion_threshold=0.01,
    )
    assert req_custom.viewport_zoom_factor == 0.75
    assert req_custom.active_motion_only is False
    assert req_custom.motion_threshold == 0.01


def test_generate_headless_viewer_script_safe_margin_zoom():
    """Verify contour plots zoom out and pan left so the right-side legend does not cover the model."""
    req_static = ContourPlotRequest(
        output_filename="stress.png",
        variable_label="S",
        view_orientation="Iso",
    )
    req_anim = ContourPlotRequest(
        output_filename="deform.gif",
        variable_label="U",
        is_animation=True,
    )
    req_explicit_zoom = ContourPlotRequest(
        output_filename="zoomed.png",
        variable_label="S",
        viewport_zoom_factor=0.78,
    )
    req_mesh = ContourPlotRequest(
        output_filename="mesh.png",
        variable_label="MESH",
        plot_state="UNDEFORMED",
    )

    script = generate_headless_viewer_script(
        odb_path="dummy.odb",
        requests=[req_static, req_anim, req_explicit_zoom, req_mesh],
        output_dir="dummy_out",
    )

    assert "vp.view.fitView()" in script
    # Contour legend occupies the right of the viewport; default zoom must leave clearance.
    assert "vp.view.zoom(factor=0.75)" in script
    assert "vp.view.zoom(factor=0.85)" not in script
    # Animation keeps extra margin for deformed envelopes.
    assert "vp.view.zoom(factor=0.72)" in script
    # Explicit override is respected, and still pans away from the legend.
    assert "vp.view.zoom(factor=0.78)" in script
    assert script.count("vp.view.pan(xFraction=-0.12, yFraction=0.0)") == 3
    # Mesh plots have no legend and must stay centered.
    assert "vp.view.zoom(factor=0.9)" in script
    assert "vp.view.pan(xFraction=0.0, yFraction=0.0)" in script
    assert "Viewport pan adjustment bypassed" in script


def test_prune_static_animation_frames_and_difference():
    """Verify static tail pruning removes dead stationary frames while keeping minimum valid sequence."""
    from PIL import Image
    from abaqus_ai_agent.execution.odb_rendering import (
        calculate_frame_difference,
        prune_static_animation_frames,
    )

    # Create synthetic frames: 3 moving frames + 5 completely static tail frames
    f1 = Image.new("RGB", (64, 64), color=(255, 0, 0))
    f2 = Image.new("RGB", (64, 64), color=(0, 255, 0))
    f3 = Image.new("RGB", (64, 64), color=(0, 0, 255))
    # Static tail: 5 identical white frames
    f_tail = [Image.new("RGB", (64, 64), color=(255, 255, 255)) for _ in range(5)]

    all_frames = [f1, f2, f3] + f_tail

    # Check differences
    diff_dyn = calculate_frame_difference(f1, f2)
    assert diff_dyn > 0.05

    diff_stat = calculate_frame_difference(f_tail[0], f_tail[1])
    assert diff_stat < 0.001

    # Pruning: with max_static_tail=1, 3 redundant tail frames should be pruned (keeping 1 tail transition)
    pruned_1 = prune_static_animation_frames(all_frames, motion_threshold=0.005, max_static_tail=1)
    # Result should be: f1, f2, f3, f_tail[0], f_tail[1] -> 5 frames
    assert len(pruned_1) == 5
    assert pruned_1[-1] is f_tail[1]

    # Pruning: with max_static_tail=0, all 4 redundant tail frames are pruned
    pruned_0 = prune_static_animation_frames(all_frames, motion_threshold=0.005, max_static_tail=0)
    # Result should be: f1, f2, f3, f_tail[0] -> 4 frames
    assert len(pruned_0) == 4
    assert pruned_0[-1] is f_tail[0]

    # Minimal frame guarantee: 2 static frames should not be pruned to 0 or 1
    two_static = [Image.new("RGB", (64, 64), color=(100, 100, 100)) for _ in range(2)]
    pruned_min = prune_static_animation_frames(two_static, motion_threshold=0.005, max_static_tail=0)
    assert len(pruned_min) == 2


def test_render_odb_animation_headless_and_agent_integration(tmp_path, monkeypatch):
    """Verify end-to-end headless animation generation and AbaqusAIAgent helper integration."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.odb_rendering import (
        MINIMAL_VALID_GIF_BYTES,
        render_odb_animation_headless,
        verify_gif_image_integrity,
    )

    valid_odb = tmp_path / "authentic.odb"
    valid_odb.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 4096)

    out_gif = tmp_path / "test_motion.gif"

    def mock_headless_render(odb_path, requests, output_dir, **kwargs):
        out_gif.write_bytes(MINIMAL_VALID_GIF_BYTES)
        return [out_gif]

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_odb_contours_headless",
        mock_headless_render,
    )

    result_path = render_odb_animation_headless(
        odb_path=valid_odb,
        output_path=out_gif,
        variable_label="U",
        component_or_invariant="Magnitude",
        frames=20,
        duration_ms=90,
    )

    assert result_path == out_gif
    assert result_path.is_file()
    w, h = verify_gif_image_integrity(result_path)
    assert w > 0 and h > 0

    # Also verify AbaqusAIAgent.export_odb_animation wrapper
    agent = AbaqusAIAgent(executor=None)
    out_agent_gif = tmp_path / "agent_motion.gif"

    def mock_agent_headless_render(odb_path, requests, output_dir, **kwargs):
        out_agent_gif.write_bytes(MINIMAL_VALID_GIF_BYTES)
        return [out_agent_gif]

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.odb_rendering.render_odb_contours_headless",
        mock_agent_headless_render,
    )

    agent_result = agent.export_odb_animation(
        odb_path=valid_odb,
        output_path=out_agent_gif,
        field_name="S",
        component="Mises",
        frames=15,
    )
    assert agent_result == out_agent_gif
    assert agent_result.is_file()


def test_generate_headless_viewer_script_animation_last_frame_guaranteed():
    """Verify script generation guarantees the authentic final frame is strictly sampled."""
    from abaqus_ai_agent.execution.odb_rendering import (
        ContourPlotRequest,
        generate_headless_viewer_script,
    )

    req = ContourPlotRequest(
        output_filename="deform.gif",
        variable_label="U",
        is_animation=True,
        animation_frames=10,
        animation_mode="full_timeline",
    )
    script = generate_headless_viewer_script(
        odb_path="dummy.odb",
        requests=[req],
        output_dir="dummy_out",
    )
    assert "target_samples = 10" in script
    assert "step_factor = (len(chosen_indices) - 1.0) / float(target_samples - 1)" in script
    assert "chosen_indices[-1] = n_total_frames - 1" in script
    assert "for f_seq, f_idx in enumerate(chosen_indices):" in script


def test_animation_mode_dual_modal_full_timeline_and_presentation():
    """Verify animation_mode contracts: full_timeline preserves history while active_presentation prunes."""
    from PIL import Image
    from abaqus_ai_agent.execution.odb_rendering import (
        ContourPlotRequest,
        prune_static_animation_frames,
    )

    # 1. Default request uses full_timeline mode
    req_default = ContourPlotRequest(output_filename="test.gif", is_animation=True)
    assert req_default.animation_mode == "full_timeline"

    # 2. Synthetic frames: 2 dynamic frames + 4 static tail frames
    f1 = Image.new("RGB", (32, 32), color=(255, 0, 0))
    f2 = Image.new("RGB", (32, 32), color=(0, 255, 0))
    f_tail = [Image.new("RGB", (32, 32), color=(255, 255, 255)) for _ in range(4)]
    all_frames = [f1, f2] + f_tail

    # In active_presentation mode, static frames are pruned
    pruned = prune_static_animation_frames(all_frames, motion_threshold=0.005, max_static_tail=1)
    assert len(pruned) == 4  # f1, f2, f_tail[0], f_tail[1]

    # In full_timeline mode, original sequence is kept intact (all 6 frames)
    req_full = ContourPlotRequest(
        output_filename="full.gif",
        is_animation=True,
        animation_mode="full_timeline",
    )
    assert req_full.animation_mode == "full_timeline"
