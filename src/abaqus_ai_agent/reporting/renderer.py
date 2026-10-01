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
        ("8. Results", report.results), ("9. Engineering Checks", report.engineering_checks),
        ("10. Acceptance Criteria", report.acceptance),
        ("11. Sensitivity / Uncertainty", (report.sensitivity, report.uncertainty)),
        ("12. Fatigue", report.fatigue), ("13. Contact Diagnostics", report.contact_diagnostics),
        ("14. Assumptions / Limitations", (report.assumptions, report.limitations)),
        ("15. Evidence", report.evidence), ("16. Provenance", report.provenance)]
    for heading, value in sections:
        if value in (None, {}, (), [], ""): continue
        lines += ["## %s" % heading, "", "```json", json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str), "```", ""]
    lines += ["## 17. Conclusion", "", _conclusion(report), ""]
    return "\n".join(lines)

def render_html(report):
    return "<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body><pre>%s</pre></body></html>" % (html.escape(report.title), html.escape(render_markdown(report)))

def render_pdf(report, output_path):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        raise RuntimeError("PDF rendering requires optional dependency: reportlab")
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(html.escape(report.title), styles["Title"]), Spacer(1, 12)]
    for line in render_markdown(report).splitlines():
        if line.startswith("## "): story.append(Paragraph(html.escape(line[3:]), styles["Heading2"]))
        elif line and not line.startswith("# ") and not line.startswith("```"): story.append(Preformatted(line, styles["Code"]))
    doc.build(story)
    return output_path

def _conclusion(report):
    acceptance = report.acceptance
    if acceptance is not None and getattr(acceptance, "passed", False):
        return "Acceptance criteria passed based on the structured evidence supplied to this report."
    if acceptance is not None:
        return "Acceptance criteria were not fully satisfied by the structured evidence supplied to this report."
    return "No acceptance verdict is asserted because no structured acceptance result was supplied."
