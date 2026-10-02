import html
import json

def _plain(value):
    if value is None: return None
    if hasattr(value, "__dataclass_fields__"):
        return {name: _plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, dict): return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_plain(v) for v in value]
    return value

def render_markdown(report):
    lines = ["# %s" % report.title, ""]
    if report.objective: lines += ["## 1. Executive Summary", "", report.objective, ""]
    sections = [
        ("2. Model Information", report.model), ("3. Material", report.materials),
        ("4. Boundary Conditions", report.boundary_conditions), ("5. Loads", report.loads),
        ("6. Solver / Analysis Procedure", report.solver), ("7. Mesh", report.mesh),
        ("8. Results", report.results),
        ("9. Figures", report.figures), ("10. Engineering Checks", report.engineering_checks),
        ("11. Acceptance Criteria", report.acceptance),
        ("12. Sensitivity / Uncertainty", (report.sensitivity, report.uncertainty)),
        ("13. Fatigue", report.fatigue), ("14. Contact Diagnostics", report.contact_diagnostics),
        ("15. Assumptions / Limitations", (report.assumptions, report.limitations)),
        ("16. Evidence", report.evidence), ("17. Provenance", report.provenance)]
    for heading, value in sections:
        if value in (None, {}, (), [], ""): continue
        lines += ["## %s" % heading, ""]
        if heading == "9. Figures":
            for figure in value:
                lines += ["![%s](%s)" % (figure.caption or figure.kind, figure.path), ""]
        else:
            lines += ["```json", json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str), "```", ""]
    lines += ["## 18. Conclusion", "", _conclusion(report), ""]
    return "\n".join(lines)

def render_html(report):
    body = html.escape(render_markdown(report))
    figures = "".join("<figure><img src=\"%s\" alt=\"%s\" style=\"max-width:100%%\"><figcaption>%s</figcaption></figure>" % (html.escape(f.path, quote=True), html.escape(f.caption or f.kind, quote=True), html.escape(f.caption or f.kind)) for f in report.figures)
    return "<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body><pre>%s</pre>%s</body></html>" % (html.escape(report.title), body, figures)

def render_analysis_report(run, title=None, objective=""):
    """Render markdown and html deliverables directly from an AnalysisRun."""
    from ..contracts.report import EngineeringReportData

    report = EngineeringReportData.from_analysis(run, title=title, objective=objective)
    return {
        "report_data": report,
        "markdown": render_markdown(report),
        "html": render_html(report),
    }

def render_pdf(report, output_path):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, Image
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        raise RuntimeError("PDF rendering requires optional dependency: reportlab")
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(html.escape(report.title), styles["Title"]), Spacer(1, 12)]
    for line in render_markdown(report).splitlines():
        if line.startswith("## "): story.append(Paragraph(html.escape(line[3:]), styles["Heading2"]))
        elif line and not line.startswith("# ") and not line.startswith("```") and not line.startswith("!["): story.append(Preformatted(line, styles["Code"]))
    for figure in report.figures:
        try:
            story.append(Image(figure.path, width=500, height=300))
            if figure.caption: story.append(Paragraph(html.escape(figure.caption), styles["BodyText"]))
        except Exception:
            story.append(Preformatted("Figure unavailable: %s" % figure.path, styles["Code"]))
    doc.build(story)
    return output_path

def _conclusion(report):
    acceptance = report.acceptance
    passed = acceptance if isinstance(acceptance, bool) else getattr(acceptance, "passed", False)
    warnings = tuple(getattr(acceptance, "warnings", ()) or ()) if acceptance is not None else ()
    failures = tuple(getattr(acceptance, "failures", ()) or ()) if acceptance is not None else ()
    if acceptance is not None and passed:
        if warnings:
            return "Acceptance criteria passed based on the structured evidence supplied to this report; warnings remain: %s." % ", ".join(warnings)
        return "Acceptance criteria passed based on the structured evidence supplied to this report."
    if acceptance is not None:
        detail = (" Failures: %s." % ", ".join(failures)) if failures else ""
        return "Acceptance criteria were not fully satisfied by the structured evidence supplied to this report.%s" % detail
    return "No acceptance verdict is asserted because no structured acceptance result was supplied."
