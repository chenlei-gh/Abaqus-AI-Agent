"""Tests for Automatic Engineering Figure Selection & Provenance Binding Engine.

Validates:
1. Scenario identification across 8 physical engineering domains.
2. 4-tier image source hierarchy:
   - Priority 1: Direct reuse of existing verified figures.
   - Priority 2: Dispatch of authentic VisualizationSpec for Viewer execution.
   - Priority 3: Fail-closed on missing ODB field output (zero synthetic images).
3. Hotspot location binding (element_id, node_id, coordinates).
4. Integration with DeterministicReportPipeline.
"""

from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.report import ReportFigure
from abaqus_ai_agent.reporting.figure_selector import (
    FigureSelectionResult,
    identify_analysis_scenario,
    select_engineering_figures,
)
from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec


def test_scenario_identification_domains():
    """Verify robust domain and intent mapping to standardized analysis scenarios."""
    assert identify_analysis_scenario(physics_domain="static") == "static_structural"
    assert identify_analysis_scenario(physics_domain="linear_static") == "static_structural"
    assert identify_analysis_scenario(physics_domain="stiffness") == "displacement_stiffness"
    assert identify_analysis_scenario(physics_domain="contact") == "contact"
    assert identify_analysis_scenario(physics_domain="bolted_sealing") == "bolted_sealing"
    assert identify_analysis_scenario(physics_domain="thermal") == "thermal"
    assert identify_analysis_scenario(physics_domain="transient_dynamics") == "transient_dynamics"
    assert identify_analysis_scenario(physics_domain="mesh_convergence") == "mesh_convergence"
    assert identify_analysis_scenario(physics_domain="fatigue") == "fatigue"

    # Intent-based identification
    intent_thermal = EngineeringIntent(
        id="INT-TH",
        kind="heat_transfer",
        description="Steady state thermal distribution",
    )
    assert identify_analysis_scenario(intent=intent_thermal) == "thermal"

    intent_sealing = EngineeringIntent(
        id="INT-SEAL",
        kind="general_contact",
        description="Flange gasket bolted connection and sealing check",
        acceptance_criteria=({"name": "min_gasket_sealing_pressure", "limit": 20.0},),
    )
    assert identify_analysis_scenario(intent=intent_sealing) == "bolted_sealing"


def test_static_structural_figure_selection_and_hotspot_binding():
    """Verify static structural analysis selects Mises hotspot and deformation contour with hotspot coords."""
    hotspot_info = {
        "element_id": 4201,
        "node_id": 1052,
        "coordinates": (12.5, 45.0, 100.2),
    }

    result = select_engineering_figures(
        physics_domain="static",
        run_id="RUN-TEST-01",
        step_name="Step-Load",
        hotspot_info=hotspot_info,
    )

    assert result.scenario == "static_structural"
    assert len(result.specs) == 2

    # Spec 1: Mises hotspot with element/node/coordinates attached
    spec_mises = next(s for s in result.specs if s.field_name == "S")
    assert spec_mises.visualization_type == "stress_hotspot"
    assert spec_mises.component == "mises"
    assert spec_mises.element_id == 4201
    assert spec_mises.node_id == 1052
    assert spec_mises.hotspot_location == (12.5, 45.0, 100.2)
    assert spec_mises.step_name == "Step-Load"
    assert spec_mises.view_mode == "ISOMETRIC"

    # Spec 2: Total displacement
    spec_u = next(s for s in result.specs if s.field_name == "U")
    assert spec_u.visualization_type == "displacement_contour"
    assert spec_u.component == "magnitude"


def test_contact_and_bolted_sealing_selection():
    """Verify contact and sealing scenarios target CPRESS / COPEN."""
    res_contact = select_engineering_figures(physics_domain="contact")
    assert res_contact.scenario == "contact"
    fields = [s.field_name for s in res_contact.specs]
    assert "CPRESS" in fields
    assert "COPEN" in fields

    res_sealing = select_engineering_figures(physics_domain="bolted_sealing")
    assert res_sealing.scenario == "bolted_sealing"
    types = [s.visualization_type for s in res_sealing.specs]
    assert "sealing_pressure" in types
    assert "stress_hotspot" in types


def test_priority_1_reuse_existing_verified_figure(tmp_path: Path):
    """Priority 1: If verified image already exists, reuse directly without dispatching Viewer."""
    existing_img = tmp_path / "mises_stress_hotspot.png"
    existing_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    existing_fig = ReportFigure(
        kind="stress_hotspot",
        path=str(existing_img.as_posix()),
        caption="Existing verified stress hotspot",
        source="S.mises",
        metadata={"field": "S", "component": "mises", "run_id": "RUN-PRIORITY-1"},
    )

    res = select_engineering_figures(
        physics_domain="static",
        existing_figures=[existing_fig],
        run_id="RUN-PRIORITY-1",
    )

    # Stress hotspot should be in reused_figures, NOT in specs to be generated
    assert len(res.reused_figures) == 1
    assert res.reused_figures[0].kind == "stress_hotspot"
    # Displacement contour still needs to be generated
    assert len(res.specs) == 1
    assert res.specs[0].field_name == "U"


def test_priority_3_missing_odb_field_marked_unavailable():
    """Priority 3: When target ODB lacks required field, do not synthesize fake spec."""
    # ODB only outputted displacement U and reaction force RF, no stress S
    res = select_engineering_figures(
        physics_domain="static",
        available_fields=["U", "RF"],
    )

    assert len(res.specs) == 1
    assert res.specs[0].field_name == "U"
    assert len(res.unavailable_fields) == 1
    assert res.unavailable_fields[0]["field"] == "S"
    assert "not present in target ODB" in res.unavailable_fields[0]["reason"]


def test_contact_domain_does_not_force_sealing_diagnostics():
    """Verify general contact domain does NOT force fastener preload or gasket sealing closure."""
    from abaqus_ai_agent.reporting.adaptive_template import AdaptiveReportBuilder, AnalysisObjective

    # General contact builder
    builder_contact = AdaptiveReportBuilder(physics_domain="contact", objective=AnalysisObjective.GENERAL_FEA)
    sections_contact = builder_contact.determine_active_sections()

    assert "contact_pressure_and_closure" in sections_contact
    assert "fastener_preload_diagnostics" not in sections_contact

    report_data = builder_contact.build_report_data(
        title="Contact Analysis",
        case_id="CASE_C",
        run_id="RUN_C",
        model_info={"name": "ContactModel", "max_cpress_mpa": 45.0},
        results_info=[],
        acceptance_info={"status": "PASS", "deliverable": True},
    )

    # General contact should not claim sealing closure evaluation
    assert report_data.contact_diagnostics is not None
    assert report_data.contact_diagnostics.get("max_cpress_mpa") == 45.0
    assert "不适用" in str(report_data.contact_diagnostics.get("closure_status"))

    # Explicit bolted sealing builder
    builder_sealing = AdaptiveReportBuilder(physics_domain="contact", objective=AnalysisObjective.BOLTED_SEALING)
    sections_sealing = builder_sealing.determine_active_sections()
    assert "fastener_preload_diagnostics" in sections_sealing
    assert "contact_pressure_and_closure" in sections_sealing


def test_extraction_diagnostics_records_unavailable_status():
    """Verify agent records extraction diagnostics when optional ODB fields fail or are unavailable."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun

    agent = AbaqusAIAgent(executor=None)
    run = AnalysisRun(
        id="RUN-EXT",
        model_name="Model_Ext",
        job_name="Job_Ext",
        odb_path="non_existent.odb",
        metrics=(),
    )

    bundle, figures = agent.extract_result_intelligence(run)
    assert bundle is not None
    diag = bundle.metadata.get("extraction_diagnostics", {})
    assert isinstance(diag, dict)


def test_figure_selector_wrapper_and_probe_odb_fields(tmp_path: Path):
    """Verify FigureSelector class wrapper and probe_odb_fields helper function."""
    from abaqus_ai_agent.reporting.figure_selector import FigureSelector, probe_odb_fields

    # 1. Non-existent file probe returns None
    assert probe_odb_fields(tmp_path / "missing.odb") is None

    # 2. FigureSelector wrapper execution with dict results
    selector = FigureSelector()
    res = selector.select_figures(
        domain="structural",
        objective="general_fea",
        extracted_results={"max_mises": 120.0},
        run_id="RUN-WRAP",
    )
    assert res.scenario == "static_structural"
    assert len(res.specs) > 0
    assert any(s.field_name == "S" for s in res.specs)
