"""T-P6 structured conclusion binding contract."""

from abaqus_ai_agent.acceptance import AcceptanceResult, CriterionResult, evaluate_result_acceptance
from abaqus_ai_agent.contracts.mesh_quality import MeshQualityResult
from abaqus_ai_agent.contracts.conclusions import (
    ReportConclusionLayer,
    ReportConclusionStatus,
    build_report_conclusions,
)
from abaqus_ai_agent.contracts.report import EngineeringReportData
from abaqus_ai_agent.reporting import AdaptiveReportBuilder, AnalysisObjective
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown

PULLOUT_OBJECTIVE = "Assess pull-out capability at 180 N."


def _by_layer(conclusions, layer):
    return next(item for item in conclusions if item.layer == layer)


def _passing_acceptance():
    return AcceptanceResult(
        passed=True,
        criteria=(
            CriterionResult(
                name="convergence_at_180N",
                passed=True,
                actual=180.0,
                operator=">=",
                limit=180.0,
                unit="N",
            ),
        ),
        status="PASS",
        result_validity="VALID",
        deliverable=True,
    )


def _pullout_report():
    acceptance = _passing_acceptance()
    return AdaptiveReportBuilder(
        physics_domain="structural",
        objective=AnalysisObjective.STATIC_STRENGTH,
    ).build_report_data(
        title="180 N Pull-Out Conclusion Report",
        case_id="case-180n",
        run_id="RUN-180N",
        model_info={"name": "PulloutSpecimen"},
        results_info=acceptance.criteria,
        acceptance_info=acceptance,
        objective_context=PULLOUT_OBJECTIVE,
        language="en",
    )


def test_acceptance_pass_does_not_prove_pullout_objective():
    report = _pullout_report()
    acceptance_c = _by_layer(report.conclusions, ReportConclusionLayer.ACCEPTANCE)
    objective_c = _by_layer(report.conclusions, ReportConclusionLayer.ENGINEERING_OBJECTIVE)
    criterion_c = _by_layer(report.conclusions, ReportConclusionLayer.CRITERION)

    assert acceptance_c.status == ReportConclusionStatus.PASS
    assert objective_c.status == ReportConclusionStatus.NOT_PROVEN
    assert "no matching acceptance criterion" in objective_c.statement
    assert criterion_c.status == ReportConclusionStatus.PASS
    assert "criterion:convergence_at_180N" in criterion_c.evidence
    assert objective_c.scope != ""


def test_missing_required_metric_is_not_proven():
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(),
        blocked=("missing_required_metric:max_mises",),
        missing_required_metrics=("max_mises",),
        status="BLOCKED",
        result_validity="RESULT_INVALID",
    )
    conclusion = build_report_conclusions(acceptance)[0]
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN
    assert any("missing_metric:max_mises" in item for item in conclusion.evidence)


def test_explicit_gate_violations_are_rejected():
    cases = (
        AcceptanceResult(
            passed=False,
            criteria=(),
            failures=("evidence_tampered:sha256_mismatch",),
            blocked=("evidence_tampered:sha256_mismatch",),
            status="BLOCKED",
            result_validity="EVIDENCE_TAMPERED",
        ),
        AcceptanceResult(
            passed=False,
            criteria=(),
            failures=("material_mapping:incomplete_assignment_to_critical_regions",),
            blocked=("material_mapping:incomplete_assignment_to_critical_regions",),
            status="BLOCKED",
            result_validity="RESULT_INVALID",
        ),
        AcceptanceResult(
            passed=False,
            criteria=(),
            failures=("elastic_range_exceeded:stress_above_yield",),
            blocked=(),
            status="BLOCKED",
            result_validity="RESULT_INVALID",
        ),
    )
    for acceptance in cases:
        assert build_report_conclusions(acceptance)[0].status == ReportConclusionStatus.REJECTED


def test_failed_criterion_is_fail_not_rejected():
    criterion = CriterionResult(
        name="max_mises", passed=False, actual=400.0, operator="<=", limit=355.0, unit="MPa"
    )
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(criterion,),
        failures=("max_mises_exceeded",),
        status="FAIL",
        result_validity="VALID",
    )
    conclusion = build_report_conclusions(acceptance)[0]
    assert conclusion.status == ReportConclusionStatus.FAIL


def test_every_criterion_generates_a_subconclusion():
    criteria = (
        CriterionResult(name="max_mises", passed=True, actual=300.0, operator="<=", limit=355.0, unit="MPa"),
        {"name": "pullout_capacity", "actual": 180.0, "target": ">= 200 N"},
    )
    conclusions = build_report_conclusions(
        AcceptanceResult(
            passed=False,
            criteria=criteria,
            missing_required_fields=("pullout_capacity.passed",),
            status="BLOCKED",
            result_validity="VALID",
        )
    )
    subconclusions = [item for item in conclusions if item.layer == ReportConclusionLayer.CRITERION]
    assert len(subconclusions) == 2
    assert subconclusions[0].status == ReportConclusionStatus.PASS
    assert subconclusions[1].status == ReportConclusionStatus.NOT_PROVEN
    assert "actual/limit unavailable" not in subconclusions[1].statement


def test_matching_pullout_criterion_can_support_objective_pass():
    criterion = CriterionResult(
        name="pullout_capacity_180N",
        passed=True,
        actual=220.0,
        operator=">=",
        limit=180.0,
        unit="N",
    )
    acceptance = AcceptanceResult(
        passed=True,
        criteria=(criterion,),
        status="PASS",
        result_validity="VALID",
        deliverable=True,
    )
    conclusions = build_report_conclusions(
        acceptance,
        objective_context=PULLOUT_OBJECTIVE,
        run_id="RUN-180N",
        model_name="PulloutSpecimen",
        physics_domain="structural",
    )
    objective_c = _by_layer(conclusions, ReportConclusionLayer.ENGINEERING_OBJECTIVE)
    assert objective_c.status == ReportConclusionStatus.PASS
    assert "criterion:pullout_capacity_180N" in objective_c.evidence


def test_renderers_share_conclusion_binding_and_retain_scope():
    report = _pullout_report()
    markdown = render_markdown(report, language="en")
    html = render_html(report, language="en")
    for output in (markdown, html):
        assert "19b. Conclusions" in output or "19b. Conclusions &amp; Evidence Binding" in output
        assert "NOT_PROVEN" in output
        assert "does not upgrade" in output
    for conclusion in report.conclusions:
        assert conclusion.conclusion_id in markdown
        assert conclusion.conclusion_id in html
        assert conclusion.scope in markdown
        assert conclusion.scope in html
        assert conclusion.status.value in markdown
        assert conclusion.status.value in html


def test_legacy_report_without_conclusions_has_no_19b():
    report = EngineeringReportData(title="Legacy Report")
    assert report.conclusions == ()
    for output in (render_markdown(report, language="en"), render_html(report, language="en")):
        assert "19b. Conclusions" not in output


def test_missing_acceptance_is_not_proven():
    conclusion = build_report_conclusions(None)[0]
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN
    assert any("acceptance:missing" in item for item in conclusion.evidence)


def test_legacy_boolean_acceptance_is_labeled_coarse():
    conclusion = build_report_conclusions(True)[0]
    assert conclusion.status == ReportConclusionStatus.PASS
    assert "coarse acceptance status PASS" in conclusion.statement
    assert any("acceptance:boolean" in item for item in conclusion.evidence)

def test_contact_diagnostics_insufficient_evidence_is_not_proven():
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(),
        failures=("contact_diagnostics_insufficient_evidence",),
        blocked=("contact_diagnostics_insufficient_evidence",),
        status="BLOCKED",
        result_validity="RESULT_INVALID",
    )
    conclusion = build_report_conclusions(acceptance)[0]
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN


def test_criteria_evaluation_error_is_not_proven():
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(),
        failures=("criteria_evaluation_error:bad operand type",),
        blocked=("criteria_evaluation_error:bad operand type",),
        status="BLOCKED",
        result_validity="RESULT_INVALID",
    )
    conclusion = build_report_conclusions(acceptance)[0]
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN

def test_legacy_blocked_dict_without_details_is_not_proven():
    conclusion = build_report_conclusions({"status": "BLOCKED"})[0]
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN


def test_legacy_result_invalid_dict_without_details_is_rejected():
    conclusion = build_report_conclusions({"status": "RESULT_INVALID"})[0]
    assert conclusion.status == ReportConclusionStatus.REJECTED


def _mesh_conclusion(mesh_quality):
    acceptance = evaluate_result_acceptance(
        result_status="completed",
        mesh_quality=mesh_quality,
        required_gates=("mesh_quality",),
        values={},
        criteria=(),
    )
    return build_report_conclusions(acceptance)[0]


def test_mesh_quality_not_run_is_not_proven():
    conclusion = _mesh_conclusion(MeshQualityResult(status="not_run"))
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN
    assert any("mesh_quality_not_run" in item for item in conclusion.evidence)


def test_mesh_quality_unsupported_is_not_proven():
    conclusion = _mesh_conclusion(
        MeshQualityResult(status="unsupported", unsupported_checks=("aspect_ratio",))
    )
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN
    assert any("mesh_quality_unsupported:aspect_ratio" in item for item in conclusion.evidence)


def test_mesh_quality_no_shape_criterion_is_not_proven():
    conclusion = _mesh_conclusion(MeshQualityResult(status="warning", severity="advisory"))
    assert conclusion.status == ReportConclusionStatus.NOT_PROVEN
    assert any("mesh_quality_no_shape_criterion" in item for item in conclusion.evidence)


def test_mesh_quality_expired_remains_rejected():
    conclusion = _mesh_conclusion(MeshQualityResult(status="expired"))
    assert conclusion.status == ReportConclusionStatus.REJECTED


def test_mesh_quality_blocking_warning_remains_rejected():
    conclusion = _mesh_conclusion(MeshQualityResult(status="warning", severity="blocking"))
    assert conclusion.status == ReportConclusionStatus.REJECTED


def test_mesh_quality_fail_is_fail():
    conclusion = _mesh_conclusion(MeshQualityResult(status="fail"))
    assert conclusion.status == ReportConclusionStatus.FAIL


def test_unknown_blocker_remains_rejected():
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(),
        blocked=("new_unknown_gate:xyz",),
        status="BLOCKED",
        result_validity="VALID",
    )
    assert build_report_conclusions(acceptance)[0].status == ReportConclusionStatus.REJECTED

def test_mesh_quality_prefix_near_miss_remains_rejected():
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(),
        blocked=("mesh_quality_not_run_unexpected",),
        status="BLOCKED",
        result_validity="VALID",
    )
    assert build_report_conclusions(acceptance)[0].status == ReportConclusionStatus.REJECTED


def _kpi_html(report):
    html = render_html(report, language="en")
    start = html.find('<div class="kpi-grid">')
    end = html.find('<h2 class="section-heading">', start)
    assert start >= 0 and end > start
    return html[start:end]


def _passing_pullout_report():
    criterion = CriterionResult(
        name="pullout_capacity_180N",
        passed=True,
        actual=220.0,
        operator=">=",
        limit=180.0,
        unit="N",
    )
    acceptance = AcceptanceResult(
        passed=True,
        criteria=(criterion,),
        status="PASS",
        result_validity="VALID",
        deliverable=True,
    )
    return AdaptiveReportBuilder(
        physics_domain="structural",
        objective=AnalysisObjective.STATIC_STRENGTH,
    ).build_report_data(
        title="180 N Pull-Out Conclusion Report",
        case_id="case-180n",
        run_id="RUN-180N",
        model_info={"name": "PulloutSpecimen"},
        results_info=acceptance.criteria,
        acceptance_info=acceptance,
        objective_context=PULLOUT_OBJECTIVE,
        language="en",
    )


def _failing_pullout_report():
    criterion = CriterionResult(
        name="pullout_capacity_180N",
        passed=False,
        actual=150.0,
        operator=">=",
        limit=180.0,
        unit="N",
    )
    acceptance = AcceptanceResult(
        passed=False,
        criteria=(criterion,),
        status="FAIL",
        result_validity="VALID",
        deliverable=False,
    )
    return AdaptiveReportBuilder(
        physics_domain="structural",
        objective=AnalysisObjective.STATIC_STRENGTH,
    ).build_report_data(
        title="180 N Pull-Out Conclusion Report",
        case_id="case-180n",
        run_id="RUN-180N",
        model_info={"name": "PulloutSpecimen"},
        results_info=acceptance.criteria,
        acceptance_info=acceptance,
        objective_context=PULLOUT_OBJECTIVE,
        language="en",
    )


def test_html_kpi_scopes_acceptance_and_surfaces_not_proven_objective():
    kpi = _kpi_html(_pullout_report())
    assert "Acceptance Criteria (listed)" in kpi
    assert "Listed criteria and gates only" in kpi
    assert "Engineering Objective" in kpi
    assert "NOT_PROVEN" in kpi
    assert "Overall Acceptance" not in kpi


def test_html_kpi_omits_objective_card_when_objective_passes():
    kpi = _kpi_html(_passing_pullout_report())
    assert "Acceptance Criteria (listed)" in kpi
    assert "Engineering Objective" not in kpi


def test_legacy_report_without_conclusions_keeps_overall_acceptance_kpi():
    report = EngineeringReportData(title="Legacy Report", acceptance=True)
    kpi = _kpi_html(report)
    assert "Overall Acceptance" in kpi
    assert "Acceptance Criteria (listed)" not in kpi


def test_markdown_section_19_scopes_acceptance_when_objective_not_proven():
    markdown = render_markdown(_pullout_report(), language="en")
    start = markdown.find("## 19. Conclusion")
    end = markdown.find("## 19b.", start)
    assert start >= 0 and end > start
    section = markdown[start:end]
    assert "Acceptance criteria passed" in section
    assert "stated engineering objective is NOT_PROVEN" in section


def test_html_section_19_scopes_acceptance_when_objective_not_proven():
    html = render_html(_pullout_report(), language="en")
    start = html.find('<h2 class="section-heading">19. Conclusion</h2>')
    end = html.find('<h2 class="section-heading">19b.', start)
    assert start >= 0 and end > start
    section = html[start:end]
    assert "Acceptance criteria passed" in section
    assert "stated engineering objective is NOT_PROVEN" in section


def test_html_kpi_reports_actual_failing_objective_status():
    kpi = _kpi_html(_failing_pullout_report())
    assert "Engineering Objective" in kpi
    assert "contradicted by the listed evidence" in kpi


def test_section_19_reports_actual_failing_objective_status():
    report = _failing_pullout_report()
    markdown = render_markdown(report, language="en")
    start = markdown.find("## 19. Conclusion")
    end = markdown.find("## 19b.", start)
    assert start >= 0 and end > start
    markdown_section = markdown[start:end]
    assert "stated engineering objective is FAIL" in markdown_section
    assert "NOT_PROVEN" not in markdown_section

    html = render_html(report, language="en")
    start = html.find('<h2 class="section-heading">19. Conclusion</h2>')
    end = html.find('<h2 class="section-heading">19b.', start)
    assert start >= 0 and end > start
    html_section = html[start:end]
    assert "stated engineering objective is FAIL" in html_section
    assert "NOT_PROVEN" not in html_section


def test_legacy_positional_construction_preserves_field_order():
    evidence = ("legacy-evidence",)
    provenance = {"source": "legacy"}
    intelligence = {"summary": "legacy"}
    healing = {"attempted": False}
    metadata = {"run_id": "legacy"}
    report = EngineeringReportData(
        "Legacy", "", {}, {}, (), (), (), {}, (), (), (), None, None, None, None, None, None, (), (), (), evidence,
        provenance, intelligence, healing, metadata,
    )
    assert report.evidence == evidence
    assert report.provenance == provenance
    assert report.result_intelligence == intelligence
    assert report.self_healing == healing
    assert report.metadata == metadata
    assert report.conclusions == ()
