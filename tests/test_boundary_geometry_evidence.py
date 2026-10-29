"""Boundary-geometry evidence: loads/BCs must carry where they act and which way
they point, so the report figures can show it on the real model view."""

from types import SimpleNamespace

import pytest

from abaqus_ai_agent.agent import _boundary_evidence_for_figures
from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
from abaqus_ai_agent.execution.odb_rendering import (
    ContourPlotRequest,
    generate_headless_viewer_script,
)
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.planning.compiler import (
    IntentBoundarySpec,
    IntentGeometrySpec,
    IntentLoadSpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_intent_to_actions,
)
from abaqus_ai_agent.reporting.figure_selector import select_engineering_figures


def _steel():
    return MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )


def _compile(loads, bcs, grounded_regions=None):
    return compile_intent_to_actions(
        model_name="EvidenceModel",
        part_name="BeamPart",
        job_name="EvidenceJob",
        geometry=IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0),
        material=_steel(),
        step=IntentStepSpec(name="Step-1", step_type="static_general"),
        bcs=bcs,
        loads=loads,
        mesh=IntentMeshSpec(element_type="C3D8R", global_size=3.0, primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED'),
        grounded_regions=grounded_regions,
    )


def test_grounded_load_carries_point_direction_and_area():
    gr = GroundedRegion(
        target_semantic="TIP_FACE",
        entity_type="Face",
        entity_ids=("F_7",),
        anchor_point=(120.0, 4.0, 6.0),
    )
    loads = [IntentLoadSpec(
        name="TipForce", load_type="concentrated_force", region="TipFace",
        magnitude=-500.0, direction="CF2",
    )]
    plan = _compile(loads, [], grounded_regions={"TipFace": gr})

    evidence = plan.intent_summary["boundary_geometry"]["loads"]
    assert len(evidence) == 1
    item = evidence[0]
    assert item["point"] == (120.0, 4.0, 6.0)
    assert item["direction_vector"] == (0.0, 1.0, 0.0)
    assert item["entity_ids"] == ("F_7",)
    # cantilever_box face: width * height = 12 * 8 = 96 mm^2
    assert item["area"] == pytest.approx(96.0)


def test_fallback_points_match_the_compiled_findat_coordinates():
    loads = [
        IntentLoadSpec(name="TipForce", load_type="concentrated_force", region="TipPoint",
                       magnitude=-500.0, direction="CF2"),
        IntentLoadSpec(name="TopPressure", load_type="pressure", region="TopSurface",
                       magnitude=2.0),
    ]
    bcs = [IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace")]
    plan = _compile(loads, bcs)

    evidence = plan.intent_summary["boundary_geometry"]
    tip = next(i for i in evidence["loads"] if i["name"] == "TipForce")
    assert tip["point"] == (12.0, 8.0, 120.0)  # fallback tip vertex
    pressure = next(i for i in evidence["loads"] if i["name"] == "TopPressure")
    assert pressure["point"] == (6.0, 4.0, 120.0)  # TOP -> z = length
    assert "direction_vector" not in pressure  # pressure follows the surface normal
    fixed = evidence["bcs"][0]
    assert fixed["point"] == (6.0, 4.0, 0.0)  # encastre root face center


def test_gravity_load_has_no_invented_point():
    loads = [IntentLoadSpec(name="SelfWeight", load_type="gravity", region="WholeModel",
                            magnitude=9.806e3, direction="CF3")]
    plan = _compile(loads, [])
    item = plan.intent_summary["boundary_geometry"]["loads"][0]
    assert "point" not in item


def test_boundary_evidence_merges_compile_geometry_into_report_rows():
    intent = SimpleNamespace(loads=(
        IntentLoadSpec(name="TipForce", load_type="concentrated_force", region="TipFace",
                       magnitude=-500.0, direction="CF2"),
    ))
    plan = SimpleNamespace(intent_summary={
        "geometry": {},
        "boundary_geometry": {
            "loads": ({
                "name": "TipForce", "region": "TipFace",
                "point": (120.0, 4.0, 6.0), "direction_vector": (0.0, 1.0, 0.0),
                "area": 96.0,
            },),
            "bcs": (),
        },
    })
    boundary = _boundary_evidence_for_figures(plan, intent)
    row = boundary["loads"][0]
    assert row["point"] == (120.0, 4.0, 6.0)
    assert row["direction_vector"] == (0.0, 1.0, 0.0)
    assert row["area"] == 96.0


def test_pressure_marker_is_point_only_and_label_carries_units_and_area():
    result = select_engineering_figures(
        physics_domain="static",
        run_id="RUN-PRESSURE",
        boundary_evidence={
            "loads": [{
                "name": "TopPressure", "load_type": "pressure", "region": "TopSurface",
                "magnitude": 2.0, "direction": "CF2",  # CF token must be ignored for pressure
                "point": (6.0, 4.0, 120.0),
            }],
        },
    )
    spec = next(s for s in result.specs if s.visualization_type == "load_application")
    assert len(spec.boundary_markers) == 1
    marker = spec.boundary_markers[0]
    assert marker["point"] == [6.0, 4.0, 120.0]
    assert marker["vector"] is None
    assert "2.0 MPa" in marker["label"]
    assert "normal to surface" in marker["label"]


def test_force_marker_label_carries_newtons_direction_and_area():
    result = select_engineering_figures(
        physics_domain="static",
        run_id="RUN-FORCE",
        boundary_evidence={
            "loads": [{
                "name": "TipForce", "load_type": "concentrated_force", "region": "TipFace",
                "magnitude": -500.0, "direction": "CF2",
                "direction_vector": (0.0, 1.0, 0.0),
                "point": (120.0, 4.0, 6.0), "area": 96.0,
            }],
        },
    )
    spec = next(s for s in result.specs if s.visualization_type == "load_application")
    marker = spec.boundary_markers[0]
    assert marker["vector"] == [0.0, 1.0, 0.0]
    assert "-500.0 N" in marker["label"]
    assert "CF2" in marker["label"]
    assert "area=96 mm^2" in marker["label"]


def test_headless_script_labels_markers_and_never_fakes_an_arrow_direction():
    req = ContourPlotRequest(
        output_filename="load_application.png",
        variable_label="U",
        plot_symbols="loads",
        boundary_markers=(
            {"kind": "load", "name": "TipForce", "point": (120.0, 4.0, 6.0),
             "vector": (0.0, 1.0, 0.0), "label": "TipForce -500.0 N CF2 area=96 mm^2"},
            {"kind": "load", "name": "TopPressure", "point": (6.0, 4.0, 120.0),
             "vector": None, "label": "TopPressure 2.0 MPa (normal to surface)"},
        ),
    )
    script = generate_headless_viewer_script("dummy.odb", [req], output_dir="dummy_out")
    compile(script, "<headless-viewer>", "exec")
    assert "userData.Text is unavailable" in script
    assert "_text_api(name=_name + '_Label'" in script
    assert "_label_anchor = _tip" in script
    assert "_label_anchor = _origin" in script
    # The old behaviour invented a +Z arrow for point-only markers; that lie is gone.
    assert "_marker.get('vector') or (0.0, 0.0, 1.0)" not in script
    assert "TipForce -500.0 N CF2 area=96 mm^2" in script
