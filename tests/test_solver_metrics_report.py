from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.metrics import EngineeringMetric, metric_from_extraction
from abaqus_ai_agent.contracts.results import ResultRequirement, ResultExtraction
from abaqus_ai_agent.contracts.solver_selection import select_solver
from abaqus_ai_agent.contracts.report import EngineeringReportData, ReportFigure
from abaqus_ai_agent.contracts.postprocess import profile_for_solver_selection
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown
from abaqus_ai_agent.planning.output import plan_outputs

def test_static_selects_standard():
    result = select_solver(EngineeringIntent("s", "structural", "static bracket", analysis_type="static"))
    assert result.solver == "STANDARD" and result.strategy == "STATIC_GENERAL"
    assert not result.requires_user_confirmation

def test_impact_selects_explicit_and_requires_confirmation():
    result = select_solver(EngineeringIntent("d", "structural", "short-duration impact with complex contact", analysis_type="dynamic", metadata={"impact": True, "complex_contact": True}))
    assert result.solver == "EXPLICIT" and result.strategy == "DYNAMIC_EXPLICIT"
    assert result.requires_user_confirmation

def test_quasi_static_explicit_warns_about_energy():
    result = select_solver(EngineeringIntent("q", "forming", "quasi-static forming with large deformation", analysis_type="static", metadata={"quasi_static": True, "large_deformation": True}))
    assert result.solver == "EXPLICIT"
    assert any("kinetic/internal energy" in x for x in result.warnings)

def test_frequency_is_standard():
    result = select_solver(EngineeringIntent("m", "modal", "natural frequencies", analysis_type="frequency"))
    assert result.solver == "STANDARD" and result.strategy == "FREQUENCY"

def test_metric_preserves_odb_locator():
    req = ResultRequirement(name="Maximum Mises Stress", value_key="max_mises", field="S", invariant="MISES", step="Step-1", unit="MPa", quantity="stress")
    metric = metric_from_extraction(ResultExtraction(req, 238.4, {"step": "Step-1", "frame": -1, "element_label": 17}))
    assert metric.value == 238.4 and metric.unit == "MPa"
    assert metric.location["element_label"] == 17

def test_postprocess_profile_links_explicit_to_energy_checks():
    selection = select_solver(EngineeringIntent("q", "forming", "quasi-static forming", analysis_type="static", metadata={"quasi_static": True}))
    profile = profile_for_solver_selection(selection)
    assert "ALLKE" in profile.history_variables
    assert "energy_ratio" in profile.checks


def test_report_is_source_first():
    report = EngineeringReportData(title="Bracket Analysis", objective="Static strength check", results=(EngineeringMetric("Maximum Mises Stress", 238.4, "MPa"),), figures=(ReportFigure("contour", "stress.png", "Stress contour", "viewport"),))
    assert "238.4" in render_markdown(report) and "238.4" in render_html(report)
    assert "AI" not in render_markdown(report)
    assert "stress.png" in render_markdown(report)


def test_postprocess_profile_drives_output_plan():
    selection = select_solver(EngineeringIntent("s", "structural", "static bracket", analysis_type="static"))
    profile = profile_for_solver_selection(selection)
    plan = plan_outputs((), postprocess_profile=profile)
    assert "S" in plan.field_variables
    assert "U" in plan.field_variables
    assert "RF" in plan.field_variables
    assert "RF" in plan.history_variables
