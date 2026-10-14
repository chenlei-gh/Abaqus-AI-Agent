"""Main-path gates that must not depend on an external script.

Formal delivery is HTML. A purely elastic deck past yield is RESULT_INVALID.
A percentile does not replace the peak. These tests do not touch project reports.
"""

import json
from pathlib import Path

import pytest

from abaqus_ai_agent.acceptance import build_elastic_validity, evaluate_result_acceptance
from abaqus_ai_agent.cli import _build_parser
from abaqus_ai_agent.contracts.report import EngineeringReportData
from abaqus_ai_agent.execution.input_modes import solve_user_inp
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.reporting.renderer import render_html


ELASTIC_C3D4 = """*HEADING
*ELEMENT, TYPE=C3D4
*MATERIAL, NAME=PCABS
*ELASTIC
1900., 0.38
*STATIC
*CLOAD
"""


def test_report_cli_defaults_to_html_and_rejects_markdown_as_report_html(tmp_path, capsys):
    parser = _build_parser()
    args = parser.parse_args(["report", "evidence.json"])
    assert args.format == "html"

    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"case_id": "probe", "results": {"max_mises": 1.0}}', encoding="utf-8")
    from abaqus_ai_agent.cli import main

    with pytest.raises(SystemExit):
        parser.parse_args(["report", str(evidence), "--format", "markdown"])

    from abaqus_ai_agent.cli import handle_report
    import argparse

    requested = tmp_path / "MS13L内开拉手总成CAE计算分析报告.md"
    bypass = handle_report(argparse.Namespace(
        evidence_file=str(evidence),
        format="markdown",
        output=str(requested),
        title=None,
        allow_preview=True,
    ))
    assert bypass == 2
    assert not requested.exists()
    assert not list(tmp_path.glob("*.md"))
    assert not list(tmp_path.glob("*.html"))
    err = capsys.readouterr().err
    assert "Markdown" in err


def test_authorized_report_cli_writes_html_not_markdown(tmp_path, capsys):
    from abaqus_ai_agent.cli import main
    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record

    issued = issue_agent_run_record(
        run_id="run-cli-html",
        model_name="Handle",
        job_name="Job-1",
        output_hash="c" * 64,
        jev_routed=False,
        requirement_kind="engineering_intent",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        '{"case_id": "probe", "odb_path": "job.odb", "results": {"max_mises": 1.0}, "provenance": '
        + __import__("json").dumps(issued.to_dict(), ensure_ascii=False)
        + "}",
        encoding="utf-8",
    )
    requested = tmp_path / "customer" / "report"
    loaded = json.loads(evidence.read_text(encoding="utf-8"))
    assert loaded["provenance"]["metadata"]["delivery_stamp"]
    ret = main(["report", str(evidence), "-o", str(requested)])
    captured = capsys.readouterr()
    written = requested.with_suffix(".html")
    assert ret == 0, captured.err
    assert written.is_file()
    assert "<html" in written.read_text(encoding="utf-8").lower()
    assert not list(tmp_path.rglob("*.md"))
    assert not list(tmp_path.rglob("*.markdown"))


def test_build_elastic_validity_uses_peak_not_a_smaller_percentile():
    payload = build_elastic_validity(
        inp_text=ELASTIC_C3D4,
        yield_strength=27.1,
        values={"max_mises": 33.93, "mises_p995": 20.0},
    )
    assert payload["is_purely_elastic"] is True
    assert payload["max_stress"] == 33.93
    assert payload["percentile_995"] == 20.0

    result = evaluate_result_acceptance(
        "completed",
        values={"max_mises": 33.93, "mises_p995": 20.0},
        elastic_validity=payload,
    )
    assert result.deliverable is False
    assert str(result.result_validity) == "RESULT_INVALID"
    assert any("elastic_range_exceeded" in item for item in result.failures)


def test_percentile_above_peak_cannot_be_ignored():
    payload = build_elastic_validity(
        inp_text=ELASTIC_C3D4,
        yield_strength=27.1,
        values={"max_mises": 10.0, "mises_p995": 40.0},
    )
    assert payload["max_stress"] == 40.0
    result = evaluate_result_acceptance("completed", elastic_validity=payload)
    assert result.deliverable is False


def test_plastic_deck_is_not_failed_by_elastic_range_rule():
    deck = ELASTIC_C3D4 + "*PLASTIC\n27.1, 0.0\n"
    payload = build_elastic_validity(
        inp_text=deck,
        yield_strength=27.1,
        values={"max_mises": 80.0},
    )
    assert payload["is_purely_elastic"] is False
    result = evaluate_result_acceptance("completed", elastic_validity=payload)
    assert not any("elastic_range_exceeded" in item for item in result.failures)


def test_html_report_keeps_peak_and_percentile():
    report = EngineeringReportData(
        title="Probe",
        results=(
            {"name": "max_mises", "value": 33.93, "unit": "MPa"},
            {"name": "mises_p995", "value": 20.0, "unit": "MPa"},
        ),
    )
    html = render_html(report)
    assert "33.93" in html
    assert "20.0" in html
    assert "99.5" in html
    assert "不能掩盖峰值" in html or "must not hide" in html


def test_pipeline_blocks_official_html_when_claim_contradicts_deck(tmp_path):
    pipeline = DeterministicReportPipeline()
    out = tmp_path / "delivery"
    try:
        pipeline.build_and_render(
            output_dir=out,
            title="Claimed plastic",
            case_id="probe",
            run_id="run-probe",
            model_info={"element_type": "C3D10M", "analysis_type": "弹塑性"},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            require_deliverable=True,
            inp_text=ELASTIC_C3D4,
        )
    except PermissionError as exc:
        assert "deliverable is False" in str(exc)
    else:
        raise AssertionError("contradictory deck claim must not write an official report")
    assert not (out / "report.html").exists()


def test_solve_user_inp_auto_blocks_elastic_over_yield_without_writing_html(tmp_path):
    inp = tmp_path / "Job-1.inp"
    inp.write_text(ELASTIC_C3D4, encoding="utf-8")

    class _Exec:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            target = Path(workdir) if workdir else Path(input_path).parent
            (target / ("%s.odb" % (job_name or Path(input_path).stem))).write_bytes(b"ODB")
            return {"returncode": 0, "stdout": "Job completed", "stderr": ""}

    res = solve_user_inp(
        executor=_Exec(),
        inp_path=inp,
        job_name="Job-1",
        generate_report=True,
    )
    # The solver double does not extract stress. Re-enter the same report seam
    # with the extracted peak and known yield; the gate must still refuse HTML.
    res["max_mises"] = 33.93
    res["yield_strength"] = 27.1
    from abaqus_ai_agent.execution.input_modes import _attach_delivery_report_if_requested
    _attach_delivery_report_if_requested(res, generate_report=True)
    assert res["report_authorized"] is False
    assert res["formal_report_written"] is False
    assert "report_md_path" not in res
    assert res["elastic_validity"]["is_purely_elastic"] is True
    assert any("exceeded yield" in res["report_generation_error"] for _ in (0,))
    assert not list(tmp_path.rglob("report.html"))
    assert not list(tmp_path.rglob("report.md"))
