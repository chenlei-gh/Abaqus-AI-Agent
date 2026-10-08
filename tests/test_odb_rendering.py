"""Unit tests for Headless Abaqus Viewer ODB Visualization and Contour Rendering Engine."""

import os
from pathlib import Path
import pytest

from abaqus_ai_agent.execution.odb_rendering import (
    ContourPlotRequest,
    generate_headless_viewer_script,
    render_odb_contours_headless,
)
from abaqus_ai_agent.execution.case_03_contours import (
    generate_case_03_all_contour_pngs,
    render_mises_stress_contour,
    render_displacement_contour,
    render_temperature_contour,
    render_contact_pressure_contour,
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


def test_generate_case_03_all_contour_pngs(tmp_path):
    """Verify production of all 4 authentic engineering contour PNG files."""
    images = generate_case_03_all_contour_pngs(tmp_path)
    assert len(images) == 4

    expected_names = [
        "case_03_manifold_mises_stress.png",
        "case_03_manifold_displacement.png",
        "case_03_manifold_temperature.png",
        "case_03_manifold_contact_pressure.png",
    ]

    for img_path in images:
        assert img_path.is_file()
        assert img_path.name in expected_names
        # Check valid PNG binary header
        raw = img_path.read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n"), f"File {img_path.name} is not a valid PNG!"
        # Check non-trivial size (> 15 KB)
        assert len(raw) > 15000


def test_individual_contour_renderers(tmp_path):
    """Test each individual contour renderer function directly."""
    f_stress = tmp_path / "stress.png"
    f_disp = tmp_path / "disp.png"
    f_temp = tmp_path / "temp.png"
    f_cpress = tmp_path / "cpress.png"

    render_mises_stress_contour(f_stress)
    assert f_stress.is_file() and f_stress.stat().st_size > 10000

    render_displacement_contour(f_disp)
    assert f_disp.is_file() and f_disp.stat().st_size > 10000

    render_temperature_contour(f_temp)
    assert f_temp.is_file() and f_temp.stat().st_size > 10000

    render_contact_pressure_contour(f_cpress)
    assert f_cpress.is_file() and f_cpress.stat().st_size > 10000
