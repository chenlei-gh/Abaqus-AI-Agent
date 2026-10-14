"""Delivery gate: a formal report requires an Agent run record, not a prompt."""

import json
from pathlib import Path

import pytest

from abaqus_ai_agent.cli import main
from abaqus_ai_agent.contracts.provenance import (
    AnalysisProvenance,
    attach_delivery_stamp,
    verify_deliverable,
)
from abaqus_ai_agent.diagnostics.solver_patterns import diagnose_inp_contract
from abaqus_ai_agent.reporting.delivery import write_gated_engineering_report
from abaqus_ai_agent.reporting.renderer import render_markdown
from abaqus_ai_agent.contracts.report import EngineeringReportData


def _stamped(**meta):
    provenance = AnalysisProvenance(
        run_id="run-1",
        model_name="Handle",
        job_name="Job-1",
        input_hash="a" * 64,
        output_hash="b" * 64,
        executor="BatchExecutor",
        metadata={
            "agent_issued": True,
            "agent_entry": "solve_requirement",
            "requirement_kind": "natural_language",
            **meta,
        },
    )
    return attach_delivery_stamp(provenance)


def test_report_without_run_stamp_is_blocked(tmp_path, capsys):
    evidence = tmp_path / "handwritten.json"
    evidence.write_text(json.dumps({
        "title": "MS13L",
        "results": [{"name": "max_mises", "value": 120.0}],
        "odb_path": "D:/Vault/Abaqus/Job_Case1.odb",
    }), encoding="utf-8")
    out = tmp_path / "report.md"
    ret = main(["report", str(evidence), "-o", str(out)])
    captured = capsys.readouterr()
    assert ret == 2
    assert not out.exists()
    assert "BLOCKED" in captured.err
    assert "Abaqus-AI-Agent" not in out.name or not out.exists()


def test_unstamped_preview_does_not_claim_agent_authorship(tmp_path, capsys):
    evidence = tmp_path / "handwritten.json"
    evidence.write_text(json.dumps({"title": "Bypass", "results": []}), encoding="utf-8")
    ret = main(["report", str(evidence), "--allow-preview"])
    captured = capsys.readouterr()
    assert ret == 0
    assert "Not authorized to be captioned as prepared by Abaqus-AI-Agent" in captured.out
    assert "Prepared by Abaqus-AI-Agent after JEV routing" not in captured.out


def test_natural_language_solve_without_jev_cannot_be_attributed():
    provenance = _stamped(jev_routed=False, requirement_kind="natural_language")
    gate = verify_deliverable({"provenance": provenance.to_dict(), "results": [{"name": "u", "value": 1.0}], "odb_path": "job.odb"})
    assert gate["status"] == "BLOCKED"
    assert gate["allow_agent_attribution"] is False
    assert "natural_language_requirement_not_jev_routed" in gate["reasons"]


def test_jev_routed_record_may_be_attributed():
    provenance = _stamped(jev_routed=True, jev_mode="offline")
    record = {
        "provenance": provenance.to_dict(),
        "results": [{"name": "u", "value": 1.0}],
        "odb_path": "job.odb",
    }
    gate = verify_deliverable(record)
    assert gate["status"] == "PASS"
    assert gate["allow_agent_attribution"] is True
    report = EngineeringReportData(
        title="Handle",
        provenance=provenance.to_dict(),
        metadata={"deliverable_authorization": gate, "language": "en"},
    )
    text = render_markdown(report, language="en")
    assert "Prepared by Abaqus-AI-Agent after JEV routing" in text
    assert "not a keyed signature" in text


def test_tampered_stamp_is_blocked():
    provenance = _stamped(jev_routed=True)
    raw = provenance.to_dict()
    raw["metadata"]["jev_routed"] = False
    gate = verify_deliverable({"provenance": raw, "odb_path": "job.odb"})
    assert gate["status"] == "BLOCKED"
    assert "run_stamp_mismatch" in gate["reasons"]


def test_results_without_odb_binding_are_blocked():
    provenance = _stamped(jev_routed=True)
    raw = provenance.to_dict()
    raw["output_hash"] = None
    raw["metadata"].pop("delivery_stamp", None)
    provenance = attach_delivery_stamp(AnalysisProvenance(**{
        **raw,
        "action_plan": tuple(raw["action_plan"]),
        "environment": raw["environment"],
        "metadata": raw["metadata"],
    }))
    gate = verify_deliverable({
        "provenance": provenance.to_dict(),
        "results": [{"name": "max_mises", "value": 10.0}],
    })
    assert gate["status"] == "BLOCKED"
    assert "results_not_bound_to_odb" in gate["reasons"]


def test_tool_write_without_stamp_does_not_create_formal_html(tmp_path):
    report = EngineeringReportData(
        title="Bypass report",
        objective="A tool tried to write a formal report without an Agent run record.",
        results=(),
        acceptance=True,
    )
    formal = tmp_path / "engineering_report.html"
    written = write_gated_engineering_report(formal, report=report, allow_diagnostic_draft=True)
    assert written["kind"] == "diagnostic_draft"
    assert not formal.exists()
    draft = Path(written["path"])
    assert draft.exists()
    text = draft.read_text(encoding="utf-8")
    assert "DIAGNOSTIC" in text
    assert "Abaqus-AI-Agent 编制" not in text
    assert "Prepared by Abaqus-AI-Agent after JEV routing" not in text


def test_tool_write_without_stamp_refuses_when_draft_disabled(tmp_path):
    formal = tmp_path / "report.html"
    with pytest.raises(PermissionError):
        write_gated_engineering_report(
            formal,
            content="<html><body>fake deliverable</body></html>",
            allow_diagnostic_draft=False,
        )
    assert not formal.exists()
    assert not list(tmp_path.glob("*.html"))


def test_authorized_markdown_request_is_preview_not_formal_report(tmp_path):
    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record

    issued = issue_agent_run_record(
        run_id="run-qual",
        model_name="Beam",
        job_name="Job-1",
        output_hash="c" * 64,
        jev_routed=False,
        requirement_kind="engineering_intent",
    )
    report = EngineeringReportData(title="Qualification", provenance=issued.to_dict(), results=())
    requested = tmp_path / "report.md"
    written = write_gated_engineering_report(
        requested,
        report=report,
        record=issued,
        odb_sha256="c" * 64,
        allow_diagnostic_draft=False,
    )
    assert written["kind"] == "markdown_preview"
    assert not requested.exists()
    preview = Path(written["path"])
    assert preview.name == "report.preview.md"
    assert "not an engineering deliverable" in preview.read_text(encoding="utf-8")


def test_refused_markdown_request_does_not_file_markdown(tmp_path):
    requested = tmp_path / "engineering_report.md"
    written = write_gated_engineering_report(
        requested,
        content="# fake engineering report",
        allow_diagnostic_draft=True,
    )
    assert written["kind"] == "diagnostic_draft"
    assert not requested.exists()
    assert not list(tmp_path.glob("*.md"))
    draft = Path(written["path"])
    assert draft.suffix == ".html"
    assert "DIAGNOSTIC" in draft.read_text(encoding="utf-8")


def test_engineering_intent_record_may_file_but_not_claim_jev(tmp_path):
    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record

    issued = issue_agent_run_record(
        run_id="run-qual",
        model_name="Beam",
        job_name="Job-1",
        output_hash="c" * 64,
        jev_routed=False,
        requirement_kind="engineering_intent",
    )
    report = EngineeringReportData(
        title="Qualification",
        provenance=issued.to_dict(),
        results=(),
    )
    formal = tmp_path / "report.html"
    written = write_gated_engineering_report(
        formal,
        report=report,
        record=issued,
        odb_sha256="c" * 64,
        allow_diagnostic_draft=False,
    )
    assert written["kind"] == "deliverable"
    assert formal.exists()
    text = formal.read_text(encoding="utf-8")
    assert "Prepared by Abaqus-AI-Agent after JEV routing" not in text
    assert "must not be captioned as a natural-language Agent deliverable" in text


def test_inp_contract_warnings_do_not_fail_legitimate_models():
    legitimate = """
    *ELEMENT, TYPE=C3D8R
    *STATIC
    *CLOAD
    *ELASTIC
    210000, 0.3
    """
    issues = diagnose_inp_contract(legitimate)
    assert issues == ()

    bypass = """
    ** elastoplastic handle
    *ELEMENT, TYPE=C3D4
    *STATIC
    *CLOAD
    *TIE, NAME=Tie_Handle_Pin
    *NSET, NSET=PinFixed
    1, 2, 3
    *BOUNDARY
    PinFixed, ENCASTRE
    *ELASTIC
    2000, 0.4
    """
    # Pin set is small, so oversized-set must not fire.
    flagged = {item.diagnosis_id for item in diagnose_inp_contract(bypass)}
    assert "STATIC_BENDING_TET4_ONLY" in flagged
    assert "PIN_HOLE_TIED_AND_FIXED" in flagged
    assert "ELASTIC_ONLY_CLAIMS_PLASTICITY" in flagged
    assert "OVERSIZED_FIXED_NODE_SET" not in flagged
    assert all(item.severity == "WARNING" for item in diagnose_inp_contract(bypass))


def test_oversized_fixed_set_is_warning_only():
    lines = ["*NSET, NSET=WeldedStop", "1, 2, 3, 4, 5, 6, 7, 8, 9, 10"]
    lines.extend(["11, 12, 13, 14, 15, 16, 17, 18, 19, 20"] * 21)
    lines.extend(["*BOUNDARY", "WeldedStop, ENCASTRE"])
    issues = diagnose_inp_contract("\n".join(lines))
    assert [item.diagnosis_id for item in issues] == ["OVERSIZED_FIXED_NODE_SET"]
    assert issues[0].severity == "WARNING"


def test_official_pipeline_refuses_file_without_agent_run_record(tmp_path, monkeypatch):
    from abaqus_ai_agent.reporting.figure_selector import FigureSelectionResult
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline

    odb = tmp_path / "job.odb"
    odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    monkeypatch.setattr(
        "abaqus_ai_agent.reporting.figure_selector.FigureSelector.select_figures",
        lambda *args, **kwargs: FigureSelectionResult(scenario="none"),
    )
    pipeline = DeterministicReportPipeline()
    with pytest.raises(PermissionError, match="Agent run record refused"):
        pipeline.build_and_render(
            output_dir=tmp_path / "out",
            title="Bypass",
            case_id="bypass",
            run_id="RUN-BYPASS",
            model_info={"name": "Handle"},
            results_info=[{"metric": "max_mises", "value": 120.0}],
            acceptance_info={"status": "PASS", "deliverable": True},
            require_deliverable=True,
            odb_path=odb,
            input_hash="a" * 64,
        )
    assert not (tmp_path / "out" / "report.html").exists()


def test_official_pipeline_refuses_unbound_results(tmp_path, monkeypatch):
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline

    odb = tmp_path / "job.odb"
    odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    provenance = _stamped(jev_routed=True)
    raw = provenance.to_dict()
    raw["output_hash"] = None
    raw["metadata"].pop("delivery_stamp", None)
    unbound = attach_delivery_stamp(AnalysisProvenance(**{
        **raw,
        "action_plan": tuple(raw["action_plan"]),
        "environment": raw["environment"],
        "metadata": raw["metadata"],
    }))
    from abaqus_ai_agent.reporting.figure_selector import FigureSelectionResult
    monkeypatch.setattr(
        "abaqus_ai_agent.reporting.figure_selector.FigureSelector.select_figures",
        lambda *args, **kwargs: FigureSelectionResult(scenario="none"),
    )
    pipeline = DeterministicReportPipeline()
    with pytest.raises(PermissionError, match="output_hash does not match|results_not_bound_to_odb|Agent run record refused"):
        pipeline.build_and_render(
            output_dir=tmp_path / "out",
            title="Unbound",
            case_id="unbound",
            run_id="run-1",
            model_info={"name": "Handle"},
            results_info=[{"metric": "max_mises", "value": 10.0}],
            acceptance_info={"status": "PASS", "deliverable": True},
            require_deliverable=True,
            odb_path=odb,
            input_hash="a" * 64,
            provenance=unbound,
        )
    assert not (tmp_path / "out" / "report.html").exists()


def test_direct_inp_report_is_not_an_agent_deliverable(tmp_path):
    from abaqus_ai_agent.execution.input_modes import solve_user_inp

    inp = tmp_path / "model.inp"
    inp.write_text("*HEADING\n*END STEP\n", encoding="utf-8")

    class _Exec:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            target = Path(workdir) if workdir else Path(input_path).parent
            (target / f"{job_name or Path(input_path).stem}.odb").write_bytes(b"ODB")
            return {"returncode": 0, "stdout": "Job completed", "stderr": ""}

    res = solve_user_inp(
        executor=_Exec(),
        inp_path=inp,
        job_name="DirectJob",
        generate_report=True,
    )
    assert res["status"] == "COMPLETED"
    assert res["report_authorized"] is False
    assert "report_path" not in res
    assert "solve_requirement" in res["report_generation_error"]


def test_ask_states_solver_and_report_are_not_authorized(capsys):
    prompt = "对100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"
    ret = main(["ask", prompt, "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert ret == 0
    assert data["solver_invoked"] is False
    assert data["report_authorized"] is False
