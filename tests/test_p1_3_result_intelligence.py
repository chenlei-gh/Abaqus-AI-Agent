"""Tests for P1.3 Result Intelligence & Engineering Deliverable Delivery (R1~R6).

Validates:
1. XYPoint & XYCurveData parametric history contracts.
2. SpatialHotspot continuum extraction and serialization contracts.
3. Derived metrics: static equilibrium balance, energy stability, factor of safety.
4. Pure Python vector SVG visualization engine (curves & hotspots).
5. Report generation & HTML/Markdown rendering with Result Intelligence.
6. solve_requirement() end-to-end integration and asset packaging.
"""

import os
import tempfile
import pytest

from abaqus_ai_agent.contracts.report import EngineeringReportData, ReportFigure
from abaqus_ai_agent.contracts.result_intelligence import (
    DerivedEngineeringMetrics,
    EnergyStability,
    FactorOfSafetyMetric,
    ReactionForceBalance,
    ResultIntelligenceBundle,
    SpatialHotspot,
    XYCurveData,
    XYPoint,
)
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown
from abaqus_ai_agent.results.derived_metrics import (
    calculate_derived_metrics,
    calculate_energy_stability,
    calculate_factor_of_safety,
    calculate_reaction_force_balance,
)
from abaqus_ai_agent.results.history_extraction import (
    _parse_payload,
    generate_history_curve_script,
)
from abaqus_ai_agent.results.spatial_hotspots import (
    _parse_hotspots_payload,
    generate_spatial_hotspots_script,
)
from abaqus_ai_agent.visualization.engine import (
    render_hotspots_svg,
    render_xy_curve_svg,
    save_chart_figure,
)


def test_xy_curve_data_properties_and_serialization():
    pts = (
        XYPoint(x=0.0, y=0.0),
        XYPoint(x=0.5, y=120.5),
        XYPoint(x=1.0, y=-45.2),
    )
    curve = XYCurveData(
        curve_name="StrainEnergy",
        x_label="Time",
        y_label="ALLSE",
        x_unit="s",
        y_unit="mJ",
        points=pts,
    )
    assert curve.point_count == 3
    assert curve.min_y == -45.2
    assert curve.max_y == 120.5
    assert curve.peak_abs_y == 120.5

    d = curve.to_dict()
    assert d["curve_name"] == "StrainEnergy"
    assert len(d["points"]) == 3
    assert d["points"][1] == (0.5, 120.5)


def test_spatial_hotspot_contract():
    hotspot = SpatialHotspot(
        rank=1,
        value=215.8,
        field_name="S",
        component="Mises",
        unit="MPa",
        coordinates=(10.0, 20.0, 50.0),
        instance="BRACKET-1",
        element_label=402,
        node_label=1520,
    )
    assert hotspot.rank == 1
    assert hotspot.value == 215.8
    d = hotspot.to_dict()
    assert d["coordinates"] == [10.0, 20.0, 50.0]
    assert d["element_label"] == 402


def test_reaction_force_balance_calculation():
    # 1. Exact balance
    bal1 = calculate_reaction_force_balance(
        applied_load=[0.0, -1000.0, 0.0],
        reaction_load=[0.0, 1000.0, 0.0],
    )
    assert bal1.is_balanced is True
    assert bal1.balance_error_percent == 0.0

    # 2. Within tolerance (0.05% difference)
    bal2 = calculate_reaction_force_balance(
        applied_load=1000.0,
        reaction_load=1000.5,
        tolerance_ratio=0.01,
    )
    assert bal2.is_balanced is True
    assert bal2.balance_error_percent < 0.1

    # 3. Severe equilibrium violation (20% drift)
    bal3 = calculate_reaction_force_balance(
        applied_load=1000.0,
        reaction_load=800.0,
        tolerance_ratio=0.01,
    )
    assert bal3.is_balanced is False
    assert bal3.balance_error_percent == 20.0


def test_energy_stability_calculation():
    # 1. Perfectly constant total energy
    etotal = [10.0, 10.0, 10.0, 10.0]
    allie = [0.0, 5.0, 8.0, 10.0]
    allke = [10.0, 5.0, 2.0, 0.0]
    es1 = calculate_energy_stability(etotal, allke, allie)
    assert es1.is_stable is True
    assert es1.total_energy_drift_ratio == 0.0

    # 2. Large numerical energy explosion (100% drift)
    etotal_bad = [10.0, 25.0, 50.0]
    es2 = calculate_energy_stability(etotal_bad, None, allie, max_drift_tolerance=0.05)
    assert es2.is_stable is False
    assert es2.total_energy_drift_ratio > 0.05

    # 3. Fallback when no energy data provided
    es3 = calculate_energy_stability(None, None, None)
    assert es3.is_stable is True


def test_factor_of_safety_calculation():
    # Nominal yield strength 235 MPa, stress 150 MPa
    sf = calculate_factor_of_safety(
        max_stress=150.0,
        yield_strength=235.0,
        material_name="Q235",
    )
    assert pytest.approx(sf.factor_of_safety, 0.01) == 1.566
    assert pytest.approx(sf.margin_of_safety, 0.01) == 0.566

    # Stress exceeding yield (nominal FoS < 1.0)
    sf_high = calculate_factor_of_safety(
        max_stress=250.0,
        yield_strength=235.0,
        material_name="Q235",
    )
    assert sf_high.factor_of_safety < 1.0
    assert sf_high.margin_of_safety < 0.0


def test_calculate_derived_metrics_aggregation():
    dm = calculate_derived_metrics(
        applied_load=500.0,
        reaction_load=500.0,
        max_stress=120.0,
        yield_strength=235.0,
    )
    assert dm.force_balance is not None
    assert dm.force_balance.is_balanced is True
    assert dm.safety_factor is not None
    assert dm.safety_factor.factor_of_safety > 1.0


def test_visualization_svg_rendering():
    pts = (
        XYPoint(0.0, 0.0),
        XYPoint(0.5, 50.0),
        XYPoint(1.0, 120.0),
    )
    curve = XYCurveData("Test_ALLSE", points=pts, y_unit="mJ")
    svg_curve = render_xy_curve_svg(curve)
    assert "<svg" in svg_curve
    assert "</svg>" in svg_curve
    assert "Test_ALLSE" in svg_curve
    assert "Peak: 120" in svg_curve

    # Empty curve handling
    empty_svg = render_xy_curve_svg(XYCurveData("Empty"))
    assert "No curve data available" in empty_svg

    # Hotspots SVG
    hotspots = [
        SpatialHotspot(1, 230.5, coordinates=(0.0, 10.0, 20.0), element_label=10),
        SpatialHotspot(2, 180.2, coordinates=(5.0, 10.0, 20.0), element_label=15),
    ]
    svg_hotspots = render_hotspots_svg(hotspots)
    assert "Top-2 Localized Stress" in svg_hotspots
    assert "#1" in svg_hotspots
    assert "230.5" in svg_hotspots


def test_visualization_save_chart_figure():
    with tempfile.TemporaryDirectory() as tmpdir:
        svg_content = "<svg><circle cx='10' cy='10' r='5'/></svg>"
        fig_path = os.path.join(tmpdir, "chart.svg")
        fig = save_chart_figure(
            svg_content=svg_content,
            output_path=fig_path,
            caption="Test Chart",
            kind="xy_curve",
        )
        assert os.path.exists(fig_path)
        assert fig.kind == "xy_curve"
        assert "sha256" in fig.metadata
        assert len(fig.metadata["sha256"]) == 64


def test_history_curve_and_hotspot_payload_parsing():
    # 1. Test history parsing
    out_text = 'Abaqus output\n{"points": [[0.0, 0.0], [1.0, 100.0]], "step": "Step-1"}\n'
    parsed = _parse_payload(out_text)
    assert len(parsed["points"]) == 2

    # 2. Test script generator
    script = generate_history_curve_script("test.odb", variable_name="ALLSE")
    assert "ALLSE" in script
    assert "odbAccess" in script

    # 3. Test hotspots script & parsing
    h_script = generate_spatial_hotspots_script("test.odb", top_k=5)
    assert "top_k_limit = 5" in h_script

    h_text = 'Processing...\n{"hotspots": [{"rank": 1, "value": 200.0, "coordinates": [1,2,3]}]}'
    h_parsed = _parse_hotspots_payload(h_text)
    assert len(h_parsed["hotspots"]) == 1


def test_report_renderer_with_result_intelligence():
    hotspots = (
        SpatialHotspot(1, 210.0, coordinates=(1.0, 2.0, 3.0), element_label=101, node_label=202),
        SpatialHotspot(2, 175.0, coordinates=(4.0, 5.0, 6.0), element_label=102, node_label=203),
    )
    curves = (
        XYCurveData("Energy_History", points=(XYPoint(0.0, 0.0), XYPoint(1.0, 50.0)), y_unit="mJ"),
    )
    derived = calculate_derived_metrics(
        applied_load=1000.0,
        reaction_load=1000.0,
        max_stress=210.0,
        yield_strength=235.0,
    )
    bundle = ResultIntelligenceBundle(
        primary_metrics={"max_mises": 210.0, "max_u": 1.25},
        hotspots=hotspots,
        curves=curves,
        derived_metrics=derived,
    )

    fig = ReportFigure(kind="xy_curve", path="curve.svg", caption="Energy History")
    report = EngineeringReportData(
        title="P1.3 Comprehensive Deliverable Test",
        objective="Verify report rendering with Result Intelligence",
        figures=(fig,),
        result_intelligence=bundle,
    )

    md = render_markdown(report)
    html_out = render_html(report)

    # Verify Markdown sections
    assert "## 8b. Result Intelligence & Derived Metrics" in md
    assert "### Localized Spatial Field Hotspots (Top-K)" in md
    assert "### Global Static Equilibrium & Reaction Force Balance" in md
    assert "### Structural Factor of Safety" in md
    assert "### Parametric & Time-History Response Curves" in md
    assert "210" in md
    assert "Energy_History" in md

    # Verify HTML output
    assert "<!doctype html>" in html_out
    assert "P1.3 Comprehensive Deliverable Test" in html_out
    assert "curve.svg" in html_out


def test_solve_requirement_delivers_result_intelligence():
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec

    class MockOdbExecutor(AbaqusExecutor):
        def execute(self, code, timeout=120):
            if "rootAssembly" in code:
                return {"steps": ["Step-1"], "instances": ["Part-1-1"], "step_frames": {"Step-1": 1}}
            if "fo=" in code:
                return {"values": [{"value": 120.0}]}
            return {"status": "COMPLETED", "output": "COMPLETED"}

        def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
            return {"status": "COMPLETED", "output": "COMPLETED"}

        def snapshot(self):
            return None

    agent = AbaqusAIAgent(MockOdbExecutor())
    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="REQ-P1-3-E2E",
        kind="linear_static",
        description="Cantilever beam under vertical 1kN tip load",
        material={"name": "Steel_Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "unit": "MPa"},
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=({"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )

    result = agent.solve_requirement(requirement=intent, geometry=geom, material=mat)

    assert result.status == TaskStatus.COMPLETED
    assert result.result_intelligence is not None
    assert result.report_markdown is not None
    assert result.report_html is not None
    assert "<!doctype html>" in result.report_html
    assert "result_intelligence" in result.summary_card
    assert result.summary_card["result_intelligence"]["derived_metrics"] is not None

    # Check derived metrics: nominal FoS calculated from 120 MPa stress and Q235
    dm = result.result_intelligence.derived_metrics
    assert dm.safety_factor is not None
    assert dm.safety_factor.yield_strength == 235.0
    assert pytest.approx(dm.safety_factor.factor_of_safety, 0.01) == 235.0 / 120.0
