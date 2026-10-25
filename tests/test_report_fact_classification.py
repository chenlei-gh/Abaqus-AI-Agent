"""T-P5 report fact classification contract.

RESULT facts are measured values, LIMITATION facts constrain validity, and
DEV_PROCESS facts describe solver/self-healing process. LIMITATION facts are
mandatory-retention and must survive rendering in both formats.
"""
from __future__ import annotations

from abaqus_ai_agent.contracts.diagnostics import HealingAttempt, SelfHealingResult
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.report import (
    EngineeringReportData,
    ReportFact,
    ReportFactClass,
    classify_report_facts,
)
from abaqus_ai_agent.reporting import AdaptiveReportBuilder, AnalysisObjective, InterpretationCard
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown


VALIDITY_LIMITATION = "分析在 16.43 ms 终止，未达到 30 ms 目标时间。"
MATERIAL_LIMITATION = "材料塑性参数仅基于有限试验点，未覆盖全部应变率。"
RESULT_STATEMENT = "Max Mises Stress: 314.92 MPa"


def _builder():
    return AdaptiveReportBuilder(
        physics_domain="structural",
        objective=AnalysisObjective.STATIC_STRENGTH,
    )


def _self_healing():
    return SelfHealingResult(
        healed=True,
        total_attempts=1,
        initial_status="SOLVER_FAILED",
        final_status="COMPLETED",
        attempts=(
            HealingAttempt(
                attempt_number=1,
                trigger_issues=("too many attempts made for this increment",),
                actions_applied=(),
                pre_run_id="run-1",
                post_run_id="run-2",
                outcome="ACCEPTED",
            ),
        ),
    )


def _report():
    return _builder().build_report_data(
        title="Fact Classification Report",
        case_id="case-tp5",
        run_id="run-tp5",
        model_info={"name": "Cantilever"},
        results_info=(EngineeringMetric("Max Mises Stress", 314.92, "MPa"),),
        acceptance_info={"status": "PASS"},
        interpretation_card=InterpretationCard(
            risk_notes=(VALIDITY_LIMITATION, MATERIAL_LIMITATION)
        ),
        self_healing=_self_healing(),
        language="en",
    )


def test_classifier_separates_results_limitations_and_dev_process():
    report = _report()
    categories = [fact.category for fact in report.classified_facts]
    assert ReportFactClass.RESULT in categories
    assert ReportFactClass.LIMITATION in categories
    assert ReportFactClass.DEV_PROCESS in categories

    results = [f for f in report.classified_facts if f.category == ReportFactClass.RESULT]
    limitations = [f for f in report.classified_facts if f.category == ReportFactClass.LIMITATION]
    dev = [f for f in report.classified_facts if f.category == ReportFactClass.DEV_PROCESS]
    assert results[0].statement == RESULT_STATEMENT
    assert results[0].source == "odb"
    assert [f.statement for f in limitations] == [VALIDITY_LIMITATION, MATERIAL_LIMITATION]
    assert all(f.mandatory_retention for f in limitations)
    assert all(f.source == "interpretation_card.risk_notes" for f in limitations)
    assert any("Self-healing cycle" in f.statement for f in dev)
    assert any("Healing attempt 1" in f.statement for f in dev)


def test_limitations_are_not_removed_from_markdown_or_html():
    report = _report()
    markdown = render_markdown(report, language="en")
    html = render_html(report, language="en")
    for output in (markdown, html):
        assert "16b. Classified Engineering Facts" in output
        assert "Measured Results (RESULT)" in output
        assert "Scope / Limitations (LIMITATION)" in output
        assert "Development Process (DEV_PROCESS)" in output
        assert VALIDITY_LIMITATION in output
        assert MATERIAL_LIMITATION in output
        assert RESULT_STATEMENT in output
    assert markdown.count(VALIDITY_LIMITATION) >= 2
    assert html.count(VALIDITY_LIMITATION) >= 2


def test_manually_constructed_validity_limitation_is_rendered():
    report = EngineeringReportData(
        title="Manual Report",
        classified_facts=(
            ReportFact(ReportFactClass.LIMITATION, VALIDITY_LIMITATION, "solver.sta"),
            ReportFact(ReportFactClass.RESULT, RESULT_STATEMENT, "odb"),
        ),
    )
    markdown = render_markdown(report, language="en")
    html = render_html(report, language="en")
    assert VALIDITY_LIMITATION in markdown
    assert VALIDITY_LIMITATION in html
    assert "mandatory-retention" in markdown
    assert "mandatory-retention" in html


def test_legacy_report_without_classified_facts_remains_compatible():
    report = EngineeringReportData(title="Legacy Report")
    assert report.classified_facts == ()
    markdown = render_markdown(report, language="en")
    html = render_html(report, language="en")
    assert "16b. Classified Engineering Facts" not in markdown
    assert "16b. Classified Engineering Facts" not in html


def test_classify_report_facts_accepts_dict_metrics_and_keeps_duplicate_limits():
    facts = classify_report_facts(
        results=({"name": "Max Mises Stress", "value": 314.92, "unit": "MPa"},),
        limitations=(VALIDITY_LIMITATION, VALIDITY_LIMITATION),
    )
    classified_limitations = [f for f in facts if f.category == ReportFactClass.LIMITATION]
    assert len(classified_limitations) == 2
    assert facts[0].statement == RESULT_STATEMENT
