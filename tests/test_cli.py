"""Tests for Abaqus-AI-Agent command-line interface (CLI)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from abaqus_ai_agent.cli import main

ROOT = Path(__file__).resolve().parent.parent
MACHINE_VALIDATION = ROOT / "machine_validation"


def run_cli_in_process(args):
    """Run CLI main function in-process and capture exit code."""
    return main(args)


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "inspect" in captured.out
    assert "matrix" in captured.out
    assert "diff" in captured.out
    assert "diagnose" in captured.out
    assert "report" in captured.out
    assert "fmbd" in captured.out


def test_cli_inspect(capsys):
    ret = main(["inspect", "--json"])
    assert ret in (0, 1)  # 0 if abaqus launcher exists in PATH, 1 if missing
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "launcher" in data
    assert "available" in data
    assert "runtime_version" in data


def test_cli_matrix_list(capsys):
    ret = main(["matrix", "--list", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    cases = json.loads(captured.out)
    assert len(cases) == 13
    case_ids = {c["case_id"] for c in cases}
    assert "static_cantilever" in case_ids
    assert "fmbd5_crank_slider" in case_ids
    assert "explicit_dynamic" in case_ids
    assert "fatigue_real_odb" in case_ids


def test_cli_matrix_validate_all(capsys):
    if not MACHINE_VALIDATION.is_dir():
        pytest.skip("machine_validation dir not found")
    ret = main(["matrix", "--validate", "all", "--workdir", str(MACHINE_VALIDATION), "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["all_passed"] is True
    assert len(result["results"]) == 13
    for r in result["results"]:
        assert r["passed"] is True
        assert r["status"] == "PASS"


def test_cli_matrix_validate_single(capsys):
    if not MACHINE_VALIDATION.is_dir():
        pytest.skip("machine_validation dir not found")
    ret = main(["matrix", "--validate", "static_cantilever", "--workdir", str(MACHINE_VALIDATION), "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["all_passed"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["case_id"] == "static_cantilever"


def test_cli_matrix_unknown_case(capsys):
    ret = main(["matrix", "--validate", "nonexistent_case"])
    assert ret == 2
    captured = capsys.readouterr()
    assert "Unknown golden case" in captured.err


def test_cli_diff(tmp_path, capsys):
    f1 = tmp_path / "run1.json"
    f2 = tmp_path / "run2.json"
    f1.write_text(json.dumps({
        "status": "PASS",
        "solver": "standard",
        "metrics": {"max_stress": 200.0, "tip_disp": 1.5},
    }), encoding="utf-8")
    f2.write_text(json.dumps({
        "status": "PASS",
        "solver": "standard",
        "metrics": {"max_stress": 210.0, "tip_disp": 1.5},
    }), encoding="utf-8")

    ret = main(["diff", str(f1), str(f2), "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    diff = json.loads(captured.out)
    assert diff["status_changed"] is False
    assert diff["metric_differences"]["max_stress"]["delta"] == 10.0
    assert pytest.approx(diff["metric_differences"]["max_stress"]["relative_change"]) == 0.05
    assert diff["metric_differences"]["tip_disp"]["delta"] == 0.0


def test_cli_diagnose_clean(tmp_path, capsys):
    log_file = tmp_path / "job.log"
    log_file.write_text("Abaqus JOB clean completed normally without errors.\n", encoding="utf-8")
    ret = main(["diagnose", str(log_file), "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    issues = json.loads(captured.out)
    assert len(issues) == 0


def test_cli_diagnose_errors(tmp_path, capsys):
    msg_file = tmp_path / "job.msg"
    msg_file.write_text(
        "***ERROR: ZERO PIVOT DETECTED AT NODE 456\n"
        "***ERROR: Abaqus license was denied by flexnet\n",
        encoding="utf-8",
    )
    ret = main(["diagnose", str(msg_file), "--json"])
    assert ret == 1
    captured = capsys.readouterr()
    issues = json.loads(captured.out)
    assert len(issues) >= 2
    diag_ids = {i["diagnosis_id"] for i in issues}
    assert "ZERO_PIVOT" in diag_ids
    assert "LICENSE_DENIED" in diag_ids


def test_cli_report(tmp_path, capsys):
    ev_file = tmp_path / "ev.json"
    ev_file.write_text(json.dumps({
        "case_id": "test_case",
        "title": "Test Structural Verification",
        "summary": "Verification of cantilever tip displacement",
        "metrics": {"tip_disp": 2.05},
        "acceptance": {"criteria": [], "passed": True},
    }), encoding="utf-8")

    # Test Markdown
    ret = main(["report", str(ev_file), "--format", "markdown"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "# Test Structural Verification" in captured.out
    assert "## 1. Executive Summary" in captured.out

    # Test HTML output to file
    out_html = tmp_path / "report.html"
    ret = main(["report", str(ev_file), "--format", "html", "-o", str(out_html)])
    assert ret == 0
    assert out_html.is_file()
    assert "<!doctype html>" in out_html.read_text(encoding="utf-8")


def test_cli_fmbd_topology(capsys):
    ret = main(["fmbd", "--case", "fmbd7", "--verify-topology", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    topo = json.loads(captured.out)
    assert topo["is_valid"] is True
    assert topo["num_bodies"] == 4
    assert topo["num_flexible_bodies"] == 2
    assert topo["num_joints"] == 4
    assert topo["is_closed_loop"] is True
    assert topo["mobility_rigid_planar"] == 1


def test_cli_fmbd_compile(capsys):
    ret = main(["fmbd", "--case", "fmbd7", "--compile", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    comp = json.loads(captured.out)
    assert comp["case"] == "fmbd7"
    assert comp["action_count"] == 27
    action_types = [a["action_type"] for a in comp["actions"]]
    assert "material_elastic" in action_types
    assert "rigid_body" in action_types
    assert "coupling_constraint" in action_types
    assert "wire_connector" in action_types


def test_cli_memory_list_and_search(tmp_path, capsys):
    from abaqus_ai_agent.run_index import RunIndex
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
    from abaqus_ai_agent.contracts.metrics import EngineeringMetric

    index = RunIndex()
    run1 = AnalysisRun(
        id="run-cli-1",
        model_name="ModelA",
        job_name="JobA",
        state=AnalysisRunState.ACCEPTED,
        solver="standard",
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(EngineeringMetric("mises", 200.0, "MPa"),),
    )
    run2 = AnalysisRun(
        id="run-cli-2",
        model_name="ModelB",
        job_name="JobB",
        state=AnalysisRunState.FAILED,
        solver="explicit",
        engineering_status="diverged",
        acceptance_passed=False,
    )
    index.add_run(run1)
    index.add_run(run2)

    mem_dir = tmp_path / "runs_dir"
    index.save_to_directory(mem_dir)

    # 1. Test memory manifest
    ret = main(["memory", "--dir", str(mem_dir), "--manifest", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    manifest_data = json.loads(captured.out)
    assert manifest_data["total_runs"] == 2

    # 2. Test search with filter --solver explicit
    ret = main(["memory", "--dir", str(mem_dir), "--solver", "explicit", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["matched"] == 1
    assert res["runs"][0]["id"] == "run-cli-2"

    # 3. Test filter --passed
    ret = main(["memory", "--dir", str(mem_dir), "--passed"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "run-cli-1" in captured.out
    assert "run-cli-2" not in captured.out
