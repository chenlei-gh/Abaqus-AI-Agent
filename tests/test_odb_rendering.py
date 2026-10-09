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
