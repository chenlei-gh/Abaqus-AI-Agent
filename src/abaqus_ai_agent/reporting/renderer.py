import html
import json

def _plain(value):
    if value is None: return None
    if hasattr(value, "__dataclass_fields__"):
        return {name: _plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, dict): return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_plain(v) for v in value]
    return value


def _format_markdown_table(headers, rows):
    if not rows:
        return ""
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(val)))
    header_line = "| " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    separator_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    data_lines = [
        "| " + " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator_line] + data_lines)


def _render_custom_table_for_section(heading, value):
    lines = []
    # 8. Results -> Metrics Table
    if heading.startswith("8. Results") and isinstance(value, (tuple, list)) and value:
        rows = []
        for m in value:
            name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else str(m))
            v = getattr(m, "value", None) if hasattr(m, "value") else (m.get("value") if isinstance(m, dict) else "-")
            u = getattr(m, "unit", "") if hasattr(m, "unit") else (m.get("unit", "") if isinstance(m, dict) else "")
            src = getattr(m, "source", "odb") if hasattr(m, "source") else (m.get("source", "odb") if isinstance(m, dict) else "odb")
            rows.append([name, v, u, src])
        if rows:
            lines += [_format_markdown_table(["Metric Name", "Value", "Unit", "Source"], rows), ""]

    # 11. Acceptance Criteria -> Integrity Audit & Criteria Table
    elif heading.startswith("11. Acceptance") and value is not None:
        # 11a. Render Integrity & Gate Audit if available
        gates = getattr(value, "gates", None) or (value.get("gates") if isinstance(value, dict) else None)
        justs = getattr(value, "gate_justifications", None) or (value.get("gate_justifications") if isinstance(value, dict) else {})
        missing_m = getattr(value, "missing_required_metrics", None) or (value.get("missing_required_metrics") if isinstance(value, dict) else ())
        res_val = getattr(value, "result_validity", "VALID") if hasattr(value, "result_validity") else (value.get("result_validity", "VALID") if isinstance(value, dict) else "VALID")
        odb_st = getattr(value, "odb_status", "valid") if hasattr(value, "odb_status") else (value.get("odb_status", "valid") if isinstance(value, dict) else "valid")
        audit_sum = getattr(value, "audit_summary", "") if hasattr(value, "audit_summary") else (value.get("audit_summary", "") if isinstance(value, dict) else "")

        if gates and isinstance(gates, dict):
            # Render Dimension Summary Table
            s_status = "completed" if gates.get("execution") == "PASS" else "aborted / failed"
            req_status = "All Required Metrics Extracted" if not missing_m else f"MISSING: {', '.join(missing_m)}"
            integrity_rows = [
                ["Solver Execution", s_status, gates.get("execution", "-")],
                ["ODB Storage Artifact", odb_st, gates.get("odb", "PASS" if s_status == "completed" else "FAIL")],
                ["Required Physical Outputs", req_status, "PASS" if not missing_m else "FAIL (RESULT_INVALID)"],
                ["Engineering Result Validity", res_val, "PASS" if res_val == "VALID" else "REJECTED"],
            ]
            lines += ["### Verification Integrity & Audit Summary", "", _format_markdown_table(["Verification Dimension", "Actual State / Output", "Gate Verdict"], integrity_rows), ""]

            # Render Verification Gates Table
            gate_rows = []
            for g_name, g_status in gates.items():
                note = justs.get(g_name, "Verified against physics contract" if g_status == "PASS" else ("Omitted / Not requested" if g_status == "SKIPPED" else "Gate verification blocked or failed"))
                gate_rows.append([g_name, str(g_status), note])
            if gate_rows:
                lines += ["### Verification Gates Detailed Audit", "", _format_markdown_table(["Gate Name", "Status", "Engineering Justification / Note"], gate_rows), ""]

        crit_list = None
        if hasattr(value, "criteria"):
            crit_list = value.criteria
        elif isinstance(value, dict) and "criteria" in value:
            crit_list = value.get("criteria")

        if crit_list and isinstance(crit_list, (list, tuple)):
            rows = []
            for c in crit_list:
                name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else "criterion")
                target = getattr(c, "target_description", None) or getattr(c, "target", None) or (c.get("target") if isinstance(c, dict) else None)
                if target is None and isinstance(c, dict) and "limit" in c:
                    op = c.get("operator", "")
                    lim = c.get("limit")
                    target = f"{op} {lim}".strip()
                if target is None:
                    target = "-"
                actual = getattr(c, "actual", None) if hasattr(c, "actual") else (c.get("actual") if isinstance(c, dict) else "-")
                passed = getattr(c, "passed", None) if hasattr(c, "passed") else (c.get("passed") if isinstance(c, dict) else None)
                verdict = "PASS" if passed is True else ("FAIL" if passed is False else "N/A")
                rows.append([name, target, actual, verdict])
            if rows:
                lines += ["### Deterministic Criteria Evaluation", "", _format_markdown_table(["Criterion Name", "Requirement / Limit", "Actual Value", "Status"], rows), ""]
        elif crit_list and isinstance(crit_list, dict):
            rows = []
            for name, val in crit_list.items():
                verdict = "PASS" if val is True else ("FAIL" if val is False else str(val))
                rows.append([name, "Must be True" if isinstance(val, bool) else "-", str(val), verdict])
            if rows:
                lines += ["### Deterministic Criteria Evaluation", "", _format_markdown_table(["Criterion Name", "Requirement / Limit", "Actual Value", "Status"], rows), ""]

    # 13. Fatigue -> Key Fatigue Metrics Table
    elif heading.startswith("13. Fatigue") and isinstance(value, dict) and value:
        rows = [[k, str(v)] for k, v in value.items() if not isinstance(v, (dict, list, tuple))]
        if rows:
            lines += [_format_markdown_table(["Fatigue Parameter", "Value"], rows), ""]

    # 15. Mechanism Kinematics & Topology -> Mechanism Summary Table
    elif heading.startswith("15. Mechanism") and isinstance(value, dict) and value:
        rows = [[k, str(v)] for k, v in value.items() if not isinstance(v, (dict, list, tuple))]
        if rows:
            lines += [_format_markdown_table(["Topological Parameter", "Value"], rows), ""]

    return lines

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
        ("15. Mechanism Kinematics & Topology", report.mechanism),
        ("16. Assumptions / Limitations", (report.assumptions, report.limitations)),
        ("17. Evidence", report.evidence), ("18. Provenance", report.provenance)]
    for heading, value in sections:
        if value in (None, {}, (), [], ""): continue
        lines += ["## %s" % heading, ""]
        if heading == "9. Figures":
            for figure in value:
                lines += ["![%s](%s)" % (figure.caption or figure.kind, figure.path), ""]
        else:
            tbl_lines = _render_custom_table_for_section(heading, value)
            if tbl_lines:
                lines += tbl_lines
            lines += ["```json", json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str), "```", ""]
    lines += ["## 19. Conclusion", "", _conclusion(report), ""]
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
    audit_summary = ""
    result_validity = "VALID"
    missing_metrics = ()
    missing_gates = ()

    if isinstance(acceptance, bool):
        passed = acceptance
        warnings = ()
        failures = ()
    elif isinstance(acceptance, dict):
        passed = acceptance.get("passed", False)
        warnings = tuple(acceptance.get("warnings") or ())
        failures = tuple(acceptance.get("failures") or ())
        audit_summary = acceptance.get("audit_summary", "")
        result_validity = acceptance.get("result_validity", "VALID")
        missing_metrics = tuple(acceptance.get("missing_required_metrics") or ())
        missing_gates = tuple(acceptance.get("missing_required_gates") or ())
    elif acceptance is not None:
        passed = getattr(acceptance, "passed", False)
        warnings = tuple(getattr(acceptance, "warnings", ()) or ())
        failures = tuple(getattr(acceptance, "failures", ()) or ())
        audit_summary = getattr(acceptance, "audit_summary", "")
        result_validity = getattr(acceptance, "result_validity", "VALID")
        missing_metrics = tuple(getattr(acceptance, "missing_required_metrics", ()) or ())
        missing_gates = tuple(getattr(acceptance, "missing_required_gates", ()) or ())
    else:
        return "No acceptance verdict is asserted because no structured acceptance result was supplied."

    prefix = f"**Audit Summary**: {audit_summary}\n\n" if audit_summary else ""

    if passed:
        if warnings:
            return f"{prefix}Acceptance criteria passed based on the structured evidence supplied to this report; warnings remain: {', '.join(warnings)}."
        return f"{prefix}Acceptance criteria passed based on the structured evidence supplied to this report."

    detail_parts = []
    if result_validity == "RESULT_INVALID":
        detail_parts.append("Engineering conclusion is REJECTED (RESULT_INVALID): Required physical outputs or mandatory verification gates were not satisfied.")
    if missing_metrics:
        detail_parts.append(f"Missing required physical metrics: {', '.join(missing_metrics)}.")
    if missing_gates:
        detail_parts.append(f"Missing mandatory verification gates: {', '.join(missing_gates)}.")
    if failures:
        detail_parts.append(f"Failures: {', '.join(failures)}.")

    detail = (" " + " ".join(detail_parts)) if detail_parts else ""
    return f"{prefix}Acceptance criteria were not fully satisfied by the structured evidence supplied to this report.{detail}"
