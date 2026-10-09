import json
from pathlib import Path
from tools.h1_engineering_report_e2e import run_h1_report_generation

ROOT = Path(__file__).resolve().parent.parent

def test_h1_engineering_report_generator_e2e():
    evidence = run_h1_report_generation()
    assert evidence["status"] == "PASS"
    assert evidence["acceptance_verdict"] == "PASS"
    assert evidence["metrics_reported_count"] >= 3
    assert evidence["criteria_reported_count"] >= 3
    assert evidence["html_size_bytes"] > 5000

    report_meta = evidence.get("report", {})
    assert report_meta.get("format") == "html"
    assert report_meta.get("self_contained") is True

    # Verify single-file HTML report existence & purge of legacy .md
    html_path = ROOT / evidence["html_report_path"] if not Path(evidence["html_report_path"]).is_absolute() else Path(evidence["html_report_path"])
    md_path = ROOT / "machine_validation" / "static_golden_engineering_report.md"
    assert html_path.exists()
    assert not md_path.exists(), "Legacy markdown report must not exist on disk."

    html_content = html_path.read_text(encoding="utf-8")
    assert "3D Cantilever Beam Linear Static Engineering Analysis Report" in html_content
    assert "1. Executive Summary" in html_content
    assert "tip_displacement_lower" in html_content
    assert "PASS" in html_content
