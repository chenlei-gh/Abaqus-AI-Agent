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

    # 8b. Result Intelligence & Derived Metrics
    elif heading.startswith("8b. Result Intelligence") and value is not None:
        val_dict = value.to_dict() if hasattr(value, "to_dict") else (value if isinstance(value, dict) else {})
        # 8b-1. Spatial Hotspots
        hotspots = val_dict.get("hotspots") or ()
        if hotspots:
            h_rows = []
            for h in hotspots:
                r = f"#{h.get('rank', '-')}"
                fld = f"{h.get('field_name', '-')}:{h.get('component', '-')}"
                val_str = f"{float(h.get('value', 0.0)):.4g}"
                u = h.get("unit", "")
                elem = str(h.get("element_label") or "-")
                node = str(h.get("node_label") or "-")
                coords = h.get("coordinates") or [0.0, 0.0, 0.0]
                coord_str = f"({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})" if len(coords) >= 3 else str(coords)
                h_rows.append([r, fld, val_str, u, elem, node, coord_str])
            lines += ["### Localized Spatial Field Hotspots (Top-K)", "", _format_markdown_table(["Rank", "Field:Component", "Peak Value", "Unit", "Element", "Node", "Coordinates (X,Y,Z)"], h_rows), ""]

        # 8b-2. Derived Engineering Metrics
        dm = val_dict.get("derived_metrics") or {}
        if dm:
            # Force Balance
            fb = dm.get("force_balance")
            if fb:
                fb_rows = [[
                    f"{float(fb.get('applied_magnitude', 0.0)):.4g} {fb.get('unit', 'N')}",
                    f"{float(fb.get('reaction_magnitude', 0.0)):.4g} {fb.get('unit', 'N')}",
                    f"{float(fb.get('balance_error_percent', 0.0)):.3f}%",
                    "BALANCED" if fb.get("is_balanced") else "EQUILIBRIUM_DRIFT",
                ]]
                lines += ["### Global Static Equilibrium & Reaction Force Balance", "", _format_markdown_table(["Applied Resultant", "Reaction Resultant", "Balance Error", "Equilibrium Status"], fb_rows), ""]

            # Energy Stability
            es = dm.get("energy_stability")
            if es:
                es_rows = [
                    ["Total Energy Drift Ratio", f"{float(es.get('total_energy_drift_ratio', 0.0)):.4%}", "Numerical ETOTAL Conservation"],
                    ["Kinetic / Internal Energy", f"{float(es.get('kinetic_energy_ratio', 0.0)):.4%}" if es.get("kinetic_energy_ratio") is not None else "N/A", "Dynamic Energy Ratio"],
                    ["Energy Stability Verdict", "STABLE" if es.get("is_stable") else "DRIFT_EXCEEDED", es.get("notes", "")],
                ]
                lines += ["### Energy Balance & Numerical Stability", "", _format_markdown_table(["Energy Dimension", "Evaluated Value", "Physical Annotation"], es_rows), ""]

            # Factor of Safety
            sf = dm.get("safety_factor")
            if sf:
                sf_rows = [[
                    f"{sf.get('stress_component', 'Mises')} Stress",
                    f"{float(sf.get('max_stress', 0.0)):.4g} {sf.get('unit', 'MPa')}",
                    f"{float(sf.get('yield_strength', 0.0)):.4g} {sf.get('unit', 'MPa')} ({sf.get('material_name', 'Q235')})",
                    f"{float(sf.get('factor_of_safety', 0.0)):.3f}",
                    f"{float(sf.get('margin_of_safety', 0.0)):+.3f}",
                ]]
                lines += ["### Structural Factor of Safety (Derived Engineering Fact)", "", _format_markdown_table(["Evaluated Field", "Peak Stress", "Yield Strength", "Factor of Safety (FoS)", "Margin of Safety (MoS)"], sf_rows), ""]

        # 8b-3. XY Response Curves
        curves = val_dict.get("curves") or ()
        if curves:
            c_rows = []
            for c in curves:
                cname = c.get("curve_name", "-")
                pts = c.get("point_count", 0)
                min_v = f"{float(c.get('min_y', 0.0)):.4g}"
                max_v = f"{float(c.get('max_y', 0.0)):.4g}"
                peak_v = f"{float(c.get('peak_abs_y', 0.0)):.4g}"
                u = c.get("y_unit", "")
                c_rows.append([cname, str(pts), min_v, max_v, peak_v, u])
            lines += ["### Parametric & Time-History Response Curves", "", _format_markdown_table(["Curve Name", "Points", "Min Y", "Max Y", "Peak |Y|", "Unit"], c_rows), ""]

    # 11. Acceptance Criteria -> Integrity Audit & Criteria Table
    elif heading.startswith("11. Acceptance") and value is not None:
        # 11a. Render Integrity & Gate Audit if available
        gates = getattr(value, "gates", None) or (value.get("gates") if isinstance(value, dict) else None)
        raw_justs = getattr(value, "gate_justifications", None) or (value.get("gate_justifications") if isinstance(value, dict) else None)
        justs = raw_justs if isinstance(raw_justs, dict) else {}
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
            if "evidence_sufficiency" in gates:
                ev_gate = gates["evidence_sufficiency"]
                ev_stat = getattr(value, "evidence_status", None) or (value.get("evidence_status") if isinstance(value, dict) else None)
                if ev_gate == "PASS":
                    ev_desc = "Verified Authentic & Intact (SHA-256 Provenance Confirmed)"
                elif ev_stat and ev_stat != "NOT_SPECIFIED":
                    ev_desc = f"FAIL ({ev_stat})"
                else:
                    ev_desc = f"FAIL ({ev_gate})"
                integrity_rows.append(["Evidence & Artifact Integrity", ev_desc, ev_gate])
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

    # 14b. Solver Diagnostics & Self-Healing Audit
    elif heading.startswith("14b. Solver Diagnostics") and value is not None:
        sh_dict = value.to_dict() if hasattr(value, "to_dict") else (value if isinstance(value, dict) else {})
        healed_str = "YES (Self-Healed)" if sh_dict.get("healed") else "NO (Unresolved / Escalated)"
        summary_rows = [
            ["Self-Healing Outcome", healed_str],
            ["Total Healing Attempts", str(sh_dict.get("total_attempts", 0))],
            ["Initial Solver Status", str(sh_dict.get("initial_status", "-"))],
            ["Final Engineering Status", str(sh_dict.get("final_status", "-"))],
        ]
        lines += ["### Self-Healing Lifecycle Summary", "", _format_markdown_table(["Attribute", "Value"], summary_rows), ""]

        # Diagnosed Issues
        issues = sh_dict.get("diagnosed_issues") or ()
        if issues:
            iss_rows = []
            for iss in issues:
                i_id = iss.get("diagnosis_id", "-")
                sev = iss.get("severity", "-")
                cause = iss.get("likely_cause", "-")
                rem = iss.get("suggested_remediation", "-")
                iss_rows.append([i_id, sev, cause, rem])
            lines += ["### Diagnosed Solver Issues", "", _format_markdown_table(["Diagnosis ID", "Severity", "Likely Cause", "Suggested Remediation"], iss_rows), ""]

        # Remediations Applied
        remeds = sh_dict.get("remediations_applied") or ()
        if remeds:
            rem_rows = []
            for r in remeds:
                r_id = r.get("action_id", "-")
                cat = r.get("category", "-")
                desc = r.get("description", "-")
                risk = r.get("risk_level", "-")
                rem_rows.append([r_id, cat, desc, risk])
            lines += ["### Remediations Applied & Model Mutations", "", _format_markdown_table(["Action ID", "Category", "Description", "Risk Level"], rem_rows), ""]

        # Healing Attempts & RunDiff
        attempts = sh_dict.get("attempts") or ()
        if attempts:
            att_rows = []
            for a in attempts:
                num = str(a.get("attempt_number", "-"))
                trigs = ", ".join(a.get("trigger_issues", ()))
                out = a.get("outcome", "-")
                pre_id = a.get("pre_run_id", "-")
                post_id = a.get("post_run_id", "-")
                att_rows.append([num, trigs, f"{pre_id} -> {post_id}", out])
            lines += ["### Iterative Healing Attempts", "", _format_markdown_table(["Attempt #", "Trigger Issues", "Run Transition", "Outcome"], att_rows), ""]

    # 15. Mechanism Kinematics & Topology -> Mechanism Summary Table
    elif heading.startswith("15. Mechanism") and isinstance(value, dict) and value:
        rows = [[k, str(v)] for k, v in value.items() if not isinstance(v, (dict, list, tuple))]
        if rows:
            lines += [_format_markdown_table(["Topological Parameter", "Value"], rows), ""]

    # 17. Evidence -> Evidence Manifest V2 Table
    elif heading.startswith("17. Evidence") and value is not None:
        manifest_data = None
        if hasattr(value, "schema_version") and getattr(value, "schema_version") == "evidence_manifest_v2":
            manifest_data = value.to_dict()
        elif isinstance(value, dict) and (value.get("schema_version") == "evidence_manifest_v2" or "artifacts" in value):
            manifest_data = value
        elif isinstance(value, (list, tuple)):
            for item in value:
                v = getattr(item, "value", item)
                if isinstance(v, dict) and (v.get("schema_version") == "evidence_manifest_v2" or "artifacts" in v):
                    manifest_data = v
                    break

        if manifest_data and isinstance(manifest_data, dict):
            run_id = manifest_data.get("run_id", "-")
            case_id = manifest_data.get("case_id", "-")
            val = manifest_data.get("validity", "VALID")
            sig = manifest_data.get("audit_signature", "-")
            sig_display = f"{sig[:16]}... (SHA-256)" if sig and len(sig) > 16 else (sig or "-")
            summary_rows = [
                ["Run ID", run_id],
                ["Case ID", case_id],
                ["Created At", manifest_data.get("created_at", "-")],
                ["Evidence Validity", val],
                ["Audit Signature", sig_display],
            ]
            lines += ["### Evidence Manifest Summary", "", _format_markdown_table(["Manifest Property", "Value"], summary_rows), ""]

            arts = manifest_data.get("artifacts") or {}
            if isinstance(arts, dict) and arts:
                art_rows = []
                for a_name, a_info in sorted(arts.items()):
                    if isinstance(a_info, dict):
                        role = a_info.get("role", "-")
                        exists = "YES" if a_info.get("exists") else "NO"
                        size = str(a_info.get("size_bytes", 0))
                        sha = a_info.get("sha256", "-")
                        sha_short = f"{sha[:12]}..." if sha and len(sha) > 12 else (sha or "-")
                        art_rows.append([a_name, role, exists, size, sha_short])
                if art_rows:
                    lines += ["### Cryptographic Artifact Provenance", "", _format_markdown_table(["Artifact Name", "Role", "Exists", "Size (bytes)", "SHA-256"], art_rows), ""]

    return lines

def render_markdown(report):
    lines = ["# %s" % report.title, ""]
    if report.objective: lines += ["## 1. Executive Summary", "", report.objective, ""]
    sections = [
        ("2. Model Information", report.model), ("3. Material", report.materials),
        ("4. Boundary Conditions", report.boundary_conditions), ("5. Loads", report.loads),
        ("6. Solver / Analysis Procedure", report.solver), ("7. Mesh", report.mesh),
        ("8. Results", report.results),
        ("8b. Result Intelligence & Derived Metrics", getattr(report, "result_intelligence", None)),
        ("9. Figures", report.figures), ("10. Engineering Checks", report.engineering_checks),
        ("11. Acceptance Criteria", report.acceptance),
        ("12. Sensitivity / Uncertainty", (report.sensitivity, report.uncertainty)),
        ("13. Fatigue", report.fatigue), ("14. Contact Diagnostics", report.contact_diagnostics),
        ("14b. Solver Diagnostics & Self-Healing Audit", getattr(report, "self_healing", None)),
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
    if any("evidence_tampered" in f for f in failures):
        detail_parts.append("EVIDENCE TAMPER DETECTED: Artifact checksum mismatch against manifest provenance.")
    if any("evidence_incomplete" in f for f in failures):
        detail_parts.append("EVIDENCE INCOMPLETE: Mandatory solver artifacts are missing from disk.")
    if any("evidence_stale" in f for f in failures):
        detail_parts.append("EVIDENCE STALE: Run ID mismatch or timestamp expired; stale evidence reuse is prohibited.")
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
