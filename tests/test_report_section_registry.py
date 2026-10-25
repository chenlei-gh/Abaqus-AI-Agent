"""T-P8 stable report section registry contract."""

import html as html_lib
import re

from abaqus_ai_agent.contracts.conclusions import (
    ReportConclusion,
    ReportConclusionLayer,
    ReportConclusionStatus,
)
from abaqus_ai_agent.contracts.report import (
    EngineeringReportData,
    ReportFact,
    ReportFactClass,
    ReportFigure,
)
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown
from abaqus_ai_agent.reporting.sections import (
    REPORT_SECTION_BY_KEY,
    REPORT_SECTIONS,
    section_title,
)


EXPECTED_NUMBERS = (
    "1", "2", "3", "4", "5", "6", "7", "8", "8b", "9", "10", "11",
    "12", "12b", "13", "13b", "14", "14b", "15", "16", "16b", "17",
    "18", "19", "19b",
)


def _md_headings(markdown_text):
    return [line[3:].strip() for line in markdown_text.splitlines() if line.startswith("## ")]


def _html_headings(html_text):
    matches = re.findall(r'<h2 class="section-heading">(.*?)</h2>', html_text)
    return [html_lib.unescape(re.sub(r"<[^>]+>", "", item)) for item in matches]


def _populated_report():
    return EngineeringReportData(
        title="Registry Consistency Report",
        objective="Verify report section numbering.",
        model={"name": "Plate"},
        materials=({"name": "Steel"},),
        boundary_conditions=({"name": "Fixed"},),
        loads=({"name": "Pressure", "value": 1.0},),
        solver={"solver_type": "standard"},
        mesh={"element_count": 100},
        results=({"name": "max_mises", "value": 120.0, "unit": "MPa"},),
        figures=(ReportFigure(path="missing.png", caption="Contour", kind="contour"),),
        engineering_checks=({"name": "yield", "passed": True},),
        acceptance=True,
        assumptions=("Linear elasticity.",),
        limitations=("No plasticity.",),
        classified_facts=(ReportFact(ReportFactClass.RESULT, "max_mises = 120 MPa", "odb"),),
        evidence=({"kind": "odb", "sha256": "abc"},),
        provenance={"run_id": "RUN-1"},
        metadata={
            "language": "en",
            "mechanism_analysis": {"mechanism": "bending"},
            "design_recommendations": {"recommendation": "thicken"},
        },
    )


def test_registry_keys_numbers_and_order_are_stable():
    assert tuple(spec.number for spec in REPORT_SECTIONS) == EXPECTED_NUMBERS
    keys = [spec.key for spec in REPORT_SECTIONS]
    assert len(keys) == len(set(keys))
    assert set(REPORT_SECTION_BY_KEY) == set(keys)
    for spec in REPORT_SECTIONS:
        assert REPORT_SECTION_BY_KEY[spec.key] is spec
        assert spec.title_en and spec.title_zh


def test_bilingual_title_format_keeps_stable_number():
    spec = REPORT_SECTION_BY_KEY["executive_summary"]
    assert section_title(spec, is_zh=False) == "1. Executive Summary"
    assert section_title(spec, is_zh=True) == (
        "1. Executive Summary / \u5de5\u7a0b\u6267\u884c\u6458\u8981"
    )


def test_markdown_and_html_share_the_same_section_order():
    report = _populated_report()
    md_headings = _md_headings(render_markdown(report, language="en"))
    html_headings = _html_headings(render_html(report, language="en"))

    assert md_headings == html_headings
    assert md_headings == [
        "1. Executive Summary",
        "2. Model Information",
        "3. Material",
        "4. Boundary Conditions",
        "5. Loads",
        "6. Solver / Analysis Procedure",
        "7. Mesh",
        "8. Results",
        "9. Figures",
        "10. Engineering Checks",
        "11. Acceptance Criteria",
        "12b. Engineering Mechanism Analysis",
        "13b. Design Recommendations & Countermeasures",
        "16. Assumptions / Limitations",
        "16b. Classified Engineering Facts",
        "17. Evidence",
        "18. Provenance",
        "19. Conclusion",
    ]


def test_missing_optional_sections_do_not_renumber_later_sections():
    report = EngineeringReportData(
        title="Sparse Report",
        assumptions=("Only one assumption is available.",),
    )
    md_headings = _md_headings(render_markdown(report, language="en"))
    html_headings = _html_headings(render_html(report, language="en"))

    assert md_headings == ["16. Assumptions / Limitations", "19. Conclusion"]
    assert html_headings == md_headings
    assert not any(heading.startswith("15.") for heading in md_headings)
    assert not any(heading.startswith("17.") for heading in md_headings)


def test_empty_optional_section_is_omitted_without_gap_compaction():
    report = EngineeringReportData(
        title="Empty Optional Report",
        result_intelligence=(),
        fatigue=None,
        contact_diagnostics=None,
        metadata={"language": "en"},
    )
    headings = _md_headings(render_markdown(report, language="en"))
    assert "8b. Result Intelligence & Derived Metrics" not in headings
    assert "13. Fatigue" not in headings
    assert "14. Contact Diagnostics" not in headings
    assert headings == ["19. Conclusion"]


def test_classified_facts_are_dispatched_by_semantic_key():
    report = EngineeringReportData(
        title="Facts Report",
        classified_facts=(
            ReportFact(ReportFactClass.RESULT, "max_mises = 120 MPa", "odb"),
            ReportFact(ReportFactClass.LIMITATION, "No plasticity modelled.", "model"),
        ),
        metadata={"language": "en"},
    )
    markdown_text = render_markdown(report, language="en")
    html_text = render_html(report, language="en")

    assert "16b. Classified Engineering Facts" in _md_headings(markdown_text)
    assert "16b. Classified Engineering Facts" in _html_headings(html_text)
    for rendered in (markdown_text, html_text):
        assert "Measured Results (RESULT)" in rendered
        assert "Scope / Limitations (LIMITATION)" in rendered
        assert "max_mises = 120 MPa" in rendered
        assert "No plasticity modelled." in rendered


def test_figures_are_dispatched_by_semantic_key():
    report = EngineeringReportData(
        title="Figure Report",
        figures=(ReportFigure(path="missing.png", caption="Contour", kind="contour"),),
        metadata={"language": "en"},
    )
    markdown_text = render_markdown(report, language="en")
    html_text = render_html(report, language="en")

    assert _md_headings(markdown_text) == ["9. Figures", "19. Conclusion"]
    assert _html_headings(html_text) == ["9. Figures", "19. Conclusion"]
    assert "![Contour](missing.png)" in markdown_text
    assert "```json" not in markdown_text
    assert "Contour" in html_text


def test_conclusion_binding_uses_stable_number():
    conclusion = ReportConclusion(
        conclusion_id="acceptance:listed",
        layer=ReportConclusionLayer.ACCEPTANCE,
        statement="Listed criteria passed.",
        status=ReportConclusionStatus.PASS,
        evidence=("criterion:max_mises",),
        scope="Listed criteria only.",
    )
    report = EngineeringReportData(
        title="Binding Report",
        conclusions=(conclusion,),
        metadata={"language": "en"},
    )
    md_headings = _md_headings(render_markdown(report, language="en"))
    html_headings = _html_headings(render_html(report, language="en"))

    assert md_headings == [
        "19. Conclusion",
        "19b. Conclusions & Evidence Binding",
    ]
    assert html_headings == md_headings
    assert not any(heading.startswith("20.") for heading in md_headings)


def test_legacy_report_without_optional_fields_still_renders():
    report = EngineeringReportData(
        title="Legacy Report",
        objective="Legacy objective.",
    )
    md_headings = _md_headings(render_markdown(report, language="en"))
    html_headings = _html_headings(render_html(report, language="en"))

    assert md_headings == ["1. Executive Summary", "19. Conclusion"]
    assert html_headings == md_headings
