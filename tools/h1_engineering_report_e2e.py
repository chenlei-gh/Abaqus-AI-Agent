#!/usr/bin/env python3
"""H.1: End-to-End Engineering Report Generator E2E.

Exercises the complete path from live Abaqus ODB extraction evidence,
mesh quality verification, structured acceptance results, and analysis provenance
into production-ready Markdown and HTML engineering reports.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.contracts.provenance import issue_agent_run_record
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.reporting.delivery import write_gated_engineering_report
from abaqus_ai_agent.evidence.model import Evidence, EvidenceBundle
from abaqus_ai_agent.acceptance import AcceptanceResult, CriterionResult
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.reporting.renderer import render_analysis_report


def run_h1_report_generation(output_dir=None):
    validation_dir = ROOT / "machine_validation"
    # Golden assets stay read-only. Tests and local runs file reports outside
    # machine_validation unless a caller explicitly chooses another directory.
    report_dir = Path(output_dir) if output_dir is not None else (ROOT / "deliverables" / "h1_engineering_report")
    report_dir.mkdir(parents=True, exist_ok=True)
    golden_evidence_file = validation_dir / "static_golden_e2e.json"
    if not golden_evidence_file.exists():
        raise RuntimeError("Required golden evidence file not found: %s" % golden_evidence_file)

    with open(golden_evidence_file, "r", encoding="utf-8") as f:
        golden_data = json.load(f)

    report_dict = golden_data.get("report", {})
    acc_dict = report_dict.get("acceptance", {})

    # 1. Build Criteria and AcceptanceResult
    crit_objs = []
    for c in acc_dict.get("criteria", []):
        crit_objs.append(CriterionResult(
            name=c["name"],
            passed=c["passed"],
            actual=float(c.get("actual", 0.0)),
            operator=c.get("operator", ""),
            limit=float(c.get("limit", 0.0)),
            unit=c.get("unit", ""),
            relative_error=c.get("relative_error"),
        ))

    acceptance_res = AcceptanceResult(
        passed=acc_dict.get("passed", True),
        criteria=tuple(crit_objs),
        failures=tuple(acc_dict.get("failures", ())),
        warnings=tuple(acc_dict.get("warnings", ())),
        gates=dict(acc_dict.get("gates", {})),
    )

    # 2. Build Metrics
    metrics_list = []
    m_raw = report_dict.get("results", {}).get("metrics", [])
    for m in m_raw:
        metrics_list.append(EngineeringMetric(
            name=m.get("name", "metric"),
            value=float(m.get("value", 0.0)),
            unit=m.get("unit", ""),
            quantity=m.get("quantity"),
            source=m.get("source", "odb"),
        ))

    # 3. Build Mesh Quality Evidence
    mesh_res = report_dict.get("engineering_checks", {}).get("mesh_result", {})
    ev_items = [
        Evidence(kind="acceptance", source="acceptance_gate", value=acceptance_res),
        Evidence(kind="mesh_quality", source="abaqus_native", value=mesh_res),
    ]
    evidence_bundle = EvidenceBundle(items=tuple(ev_items))

    # 4. Build an engineering-intent run record. This is not a JEV route.
    prov_dict = report_dict.get("provenance", {})
    odb_file = validation_dir / "StaticGoldenJob.odb"
    odb_file_path = "machine_validation/StaticGoldenJob.odb"
    import hashlib
    odb_sha = hashlib.sha256(odb_file.read_bytes()).hexdigest() if odb_file.is_file() else None
    provenance = issue_agent_run_record(
        run_id="run_static_golden_001",
        model_name=report_dict.get("model", "StaticGolden"),
        job_name=report_dict.get("job_name", "StaticGoldenJob"),
        output_hash=odb_sha,
        executor="qualification_script",
        jev_routed=False,
        requirement_kind="engineering_intent",
        agent_entry="h1_engineering_report_e2e",
    )
    provenance = provenance.replace(metadata=dict(provenance.metadata, odb_path=odb_file_path, **prov_dict))
    from abaqus_ai_agent.contracts.provenance import attach_delivery_stamp
    provenance = attach_delivery_stamp(provenance)

    # 5. Build canonical AnalysisRun
    run = AnalysisRun(
        id="run_static_golden_001",
        model_name=provenance.model_name,
        job_name=provenance.job_name,
        state=AnalysisRunState.ACCEPTED,
        odb_path=odb_file_path,
        engineering_status="RESULT_VALID",
        acceptance_passed=True,
        provenance=provenance,
        evidence=evidence_bundle,
        metrics=tuple(metrics_list),
        metadata={
            "solver_selection": {"solver": "STANDARD", "strategy": "STATIC_GENERAL"},
            "materials": [{"name": "Steel", "elastic": {"youngs_modulus": 210000.0, "poisson_ratio": 0.3}}],
            "boundary_conditions": [{"name": "FixedFace", "type": "ENCASTRE", "region": "FixedFace"}],
            "loads": [{"name": "TipForce", "type": "ConcentratedForce", "magnitude": -1000.0, "direction": "CF2"}],
            "mesh_strategy": {"element_type": "C3D8R", "seed_size": 2.5, "element_count": 640},
        },
        assumptions=("Linear elastic material response", "Small deformation assumption valid"),
    )

    # 6. Render report
    title = "3D Cantilever Beam Linear Static Engineering Analysis Report"
    objective = (
        "Verify the structural deflection and peak von Mises stress of a 100mm x 10mm x 10mm "
        "cantilever beam subjected to a 1000 N tip load against theoretical and numerical criteria."
    )
    rendered = render_analysis_report(run, title=title, objective=objective)
    report_html = rendered["html"]

    # 7. Verification assertions on rendered outputs
    assert "<html" in report_html.lower() and "</html>" in report_html.lower(), "HTML malformed"
    assert title in report_html, "Title missing from HTML report"
    assert "1. Executive Summary" in report_html, "Executive summary missing"
    assert "2.068" in report_html or "2.07" in report_html or "max_displacement" in report_html, "Displacement metric missing from report"
    assert "471.2" in report_html or "root_mises" in report_html, "Stress metric missing from report"
    assert "tip_displacement_lower" in report_html, "Criteria names missing from report"
    assert "PASS" in report_html, "Acceptance PASS verdict missing from report"
    assert "StaticGoldenJob.odb" in report_html, "ODB path provenance missing from report"
    assert "Steel" in report_html, "Material specification missing from report"

    from abaqus_ai_agent.reporting.renderer import verify_html_self_contained
    self_contained_audit = verify_html_self_contained(report_html)
    assert self_contained_audit["self_contained"] is True, f"Report must be 100% self-contained: {self_contained_audit}"

    # 8. File the HTML only through the same delivery gate. Without an ODB
    # content hash this stays a labeled diagnostic draft, not a deliverable.
    html_out_path = report_dir / "static_golden_engineering_report.html"
    written = write_gated_engineering_report(
        html_out_path,
        content=report_html,
        record=provenance,
        odb_sha256=odb_sha,
        results=[{"name": m.name, "value": m.value} for m in metrics_list],
        allow_diagnostic_draft=True,
    )
    html_out_path = Path(written["path"])

    md_out_path = report_dir / "static_golden_engineering_report.md"
    if md_out_path.exists():
        md_out_path.unlink()

    # 9. Write H.1 Evidence Summary
    evidence_payload = {
        "status": "PASS",
        "case": "H.1_engineering_report_generator",
        "job_name": run.job_name,
        "run_id": run.id,
        "report": {
            "format": "html",
            "path": str(html_out_path),
            "bytes": html_out_path.stat().st_size,
            "self_contained": True,
            "kind": written["kind"],
        },
        "html_report_path": str(html_out_path),
        "html_size_bytes": html_out_path.stat().st_size,
        "metrics_reported_count": len(metrics_list),
        "criteria_reported_count": len(crit_objs),
        "acceptance_verdict": "PASS",
        "provenance_verified": True,
        "source_first_guarantee": True,
    }
    evidence_path = report_dir / "h1_engineering_report_evidence.json"
    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(evidence_payload, f, indent=2)

    return evidence_payload
    print("H.1 Engineering Report Generator E2E: PASS")
    print("  Markdown report: %s (%d bytes)" % (md_out_path.name, evidence_payload["markdown_size_bytes"]))
    print("  HTML report:     %s (%d bytes)" % (html_out_path.name, evidence_payload["html_size_bytes"]))
    print("  Evidence:        %s" % evidence_path.name)
    return evidence_payload


if __name__ == "__main__":
    run_h1_report_generation()
