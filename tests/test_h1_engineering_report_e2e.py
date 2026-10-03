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
    assert evidence["markdown_size_bytes"] > 5000
    assert evidence["html_size_bytes"] > 5000

    # Verify report file contents
    md_path = ROOT / evidence["markdown_report_path"] if not Path(evidence["markdown_report_path"]).is_absolute() else Path(evidence["markdown_report_path"])
    html_path = ROOT / evidence["html_report_path"] if not Path(evidence["html_report_path"]).is_absolute() else Path(evidence["html_report_path"])
    assert md_path.exists()
    assert html_path.exists()

    md_content = md_path.read_text(encoding="utf-8")
    assert "3D Cantilever Beam Linear Static Engineering Analysis Report" in md_content
    assert "## 1. Executive Summary" in md_content
    assert "| Metric Name" in md_content
    assert "| Criterion Name" in md_content
    assert "tip_displacement_lower" in md_content
    assert "PASS" in md_content
