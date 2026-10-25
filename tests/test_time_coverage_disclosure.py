"""T-P7: evidence-bound time-coverage disclosure.

These tests pin the contract that a report never infers a complete transient
process from frame count, file existence, or exit status alone.
"""

import contextlib
import io
import json
from pathlib import Path

from abaqus_ai_agent.contracts.report import ReportFigure
from abaqus_ai_agent.contracts.time_coverage import (
    TimeCoverageStatus,
    build_time_coverage,
)
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.artifacts import inspect_job_diagnostics
from abaqus_ai_agent.reporting.adaptive_template import AdaptiveReportBuilder
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown


def _coverage(**kwargs):
    defaults = {
        "target_time": 30.0,
        "target_source": "step_contract:action_plan[Step-1].time_period",
        "odb_source": "odb:Step-1.frames[-1].frameValue",
        "start_time": 0.0,
        "start_source": "odb:Step-1.frames[0].frameValue",
    }
    defaults.update(kwargs)
    return build_time_coverage(**defaults)


def _report(tmp_path, coverage=None, figure_metadata=None):
    animation = tmp_path / "deformation.gif"
    animation.write_bytes(b"GIF89a")
    figure = ReportFigure(
        kind="animation",
        path=str(animation),
        caption="Deformation animation",
        metadata=dict(figure_metadata or {"is_animation": True}),
    )
    report = AdaptiveReportBuilder().build_report_data(
        title="Coverage report",
        case_id="case",
        run_id="run",
        model_info={"name": "Model"},
        results_info=[],
        acceptance_info={"status": "PASS", "deliverable": True},
        figures=[figure],
        time_coverage=coverage,
    )
    return report, figure


def test_complete_coverage_claims_complete_duration():
    coverage = _coverage(odb_time=30.0)
    assert coverage.status is TimeCoverageStatus.COMPLETE
    assert coverage.ratio() == 1.0
    assert coverage.limitation_statement() is None


def test_early_termination_is_partial_with_source_and_ratio(tmp_path):
    coverage = _coverage(odb_time=16.43)
    assert coverage.status is TimeCoverageStatus.PARTIAL
    assert coverage.ratio() == 16.43 / 30.0
    statement = coverage.limitation_statement()
    assert "16.43" in statement and "30" in statement
    assert "54.8%" in statement
    assert "odb:Step-1.frames[-1].frameValue" in statement

    report, _figure = _report(tmp_path, coverage)
    assert report.metadata["time_coverage"]["status"] == "PARTIAL"
    assert any("Time-coverage limitation" in item for item in report.limitations)
    limitation_facts = [f for f in report.classified_facts if f.category.value == "LIMITATION"]
    assert any(f.source == "run.metadata.time_coverage" for f in limitation_facts)


def test_sta_is_controlled_fallback_when_odb_time_is_missing():
    coverage = build_time_coverage(
        target_time=30.0,
        target_source="step_contract:action_plan[Step-1].time_period",
        odb_time=None,
        odb_source="unavailable",
        sta_time=16.43,
        sta_source=".sta:STEP TIME last value",
    )
    assert coverage.status is TimeCoverageStatus.PARTIAL
    assert coverage.reached_time == 16.43
    assert coverage.reached_source == ".sta:STEP TIME last value"
    assert "odb_time_unavailable" in coverage.reasons


def test_odb_and_sta_conflict_never_produces_ratio():
    coverage = build_time_coverage(
        target_time=30.0,
        odb_time=16.43,
        odb_source="odb:Step-1.frames[-1].frameValue",
        sta_time=30.0,
        sta_source=".sta:STEP TIME last value",
    )
    assert coverage.status is TimeCoverageStatus.CONFLICT
    assert coverage.ratio() is None
    statement = coverage.limitation_statement()
    assert "disagree" in statement
    assert "16.43" in statement and "30" in statement
    assert "no coverage ratio" in statement


def test_missing_evidence_is_unknown_and_not_complete():
    coverage = build_time_coverage(target_time=30.0)
    assert coverage.status is TimeCoverageStatus.UNKNOWN
    assert coverage.ratio() is None
    assert coverage.reached_time is None
    assert "Completeness" in coverage.limitation_statement()


def test_missing_target_is_unknown_even_with_reached_time():
    coverage = build_time_coverage(
        target_time=None,
        odb_time=16.43,
        odb_source="odb:Step-1.frames[-1].frameValue",
    )
    assert coverage.status is TimeCoverageStatus.UNKNOWN
    assert coverage.ratio() is None
    assert "target_time_unavailable" in coverage.reasons


def test_animation_caption_uses_recorded_start_time():
    coverage = _coverage(start_time=5.0, odb_time=16.43)
    caption = coverage.animation_caption()
    assert "5 to 16.43" in caption
    assert "0 to" not in caption
    assert "starts at 5" in coverage.limitation_statement()


def test_animation_caption_does_not_assume_zero_when_start_missing():
    coverage = _coverage(
        start_time=None,
        start_source="unavailable",
        odb_time=16.43,
    )
    caption = coverage.animation_caption()
    assert "reached 16.43" in caption
    assert "0 to" not in caption


def test_frame_count_alone_never_infers_time_or_ratio():
    coverage = build_time_coverage(
        target_time=30.0,
        odb_time=None,
        odb_source="odb:Step-1.frames[-1].frameValue",
    )
    assert coverage.status is TimeCoverageStatus.UNKNOWN
    assert coverage.ratio() is None
    assert "16.43" not in coverage.animation_caption()


def test_animation_caption_is_shared_by_markdown_and_html(tmp_path):
    report, figure = _report(tmp_path, _coverage(odb_time=16.43))
    markdown = render_markdown(report)
    html = render_html(report)

    assert "54.8%" in markdown
    assert "does not show the full target duration" in markdown
    assert "54.8%" in html
    assert "does not show the full target duration" in html
    assert figure.metadata["time_coverage"]["status"] == "PARTIAL"


def test_complete_animation_caption_has_no_partial_warning(tmp_path):
    report, _figure = _report(tmp_path, _coverage(odb_time=30.0))
    markdown = render_markdown(report)
    html = render_html(report)
    assert "complete target duration" in markdown
    assert "does not show the full target duration" not in markdown
    assert "complete target duration" in html
    assert not report.limitations


def test_legacy_report_without_coverage_is_unchanged(tmp_path):
    report, _figure = _report(tmp_path, None)
    markdown = render_markdown(report)
    html = render_html(report)
    assert "time_coverage" not in report.metadata
    assert not report.limitations
    assert "Time coverage" not in markdown
    assert "Time coverage" not in html


def test_report_status_classification_does_not_change_acceptance():
    coverage = _coverage(odb_time=16.43)
    report = AdaptiveReportBuilder().build_report_data(
        title="Coverage report",
        case_id="case",
        run_id="run",
        model_info={"name": "Model"},
        results_info=[],
        acceptance_info={"status": "PASS", "deliverable": True},
        time_coverage=coverage,
    )
    assert report.acceptance["status"] == "PASS"


class _ExecutingDiagnosticsExecutor:
    def __init__(self, workdir):
        self.workdir = str(workdir)

    def execute(self, code, timeout=120):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exec(compile(code, "<diagnostics>", "exec"), {"__name__": "__test__"})
        return buffer.getvalue()


def test_sta_diagnostics_extracts_step_and_total_time(tmp_path):
    workdir = tmp_path / "sta"
    workdir.mkdir()
    (workdir / "Job.sta").write_text(
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n"
        "  STEP TIME 1.643e-02\n"
        "  TOTAL TIME 3.000e+01\n",
        encoding="utf-8",
    )
    diagnostics = inspect_job_diagnostics(
        _ExecutingDiagnosticsExecutor(workdir), "Job",
        workdir=str(workdir), tail_lines=10,
    )
    sta = diagnostics[".sta"]
    assert sta["step_time"] == 0.01643
    assert sta["total_time"] == 30.0
    assert sta["coverage_time"] == 0.01643
    assert sta["time_ambiguous"] is False


def test_sta_diagnostics_extracts_tabular_step_and_total_columns(tmp_path):
    workdir = tmp_path / "sta_tabular"
    workdir.mkdir()
    (workdir / "Job.sta").write_text(
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n"
        " STEP  INC  ATT  STEP TIME   TOTAL TIME\n"
        "    1    0    0  0.000e+00   0.000e+00\n"
        "    1    1    1  1.000e-02   1.000e-02\n"
        "    2    1    1  2.500e+00   2.510e+00\n",
        encoding="utf-8",
    )
    diagnostics = inspect_job_diagnostics(
        _ExecutingDiagnosticsExecutor(workdir), "Job",
        workdir=str(workdir), tail_lines=10,
    )
    sta = diagnostics[".sta"]
    assert sta["step_time"] == 2.5
    assert sta["total_time"] == 2.51
    assert sta["coverage_time"] == 2.5
    assert sta["time_step_count"] == 2
    assert sta["time_ambiguous"] is False


class _CoverageExecutor:
    def __init__(self, workdir, job_name, odb_payload, sta_text):
        self.workdir = str(workdir)
        self.job_name = job_name
        self.odb_payload = odb_payload
        self._is_mock = True
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / f"{job_name}.odb").write_bytes(b"odb")
        (workdir / f"{job_name}.sta").write_text(sta_text, encoding="utf-8")
        (workdir / f"{job_name}.msg").write_text("", encoding="utf-8")

    def execute(self, code, timeout=120):
        if "result[suffix]" in code:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exec(compile(code, "<diagnostics>", "exec"), {"__name__": "__test__"})
            return buffer.getvalue()
        if "waitForCompletion" in code or "print(mdb.jobs" in code:
            return "COMPLETED"
        return ""
    def inspect_odb(self, path):
        return self.odb_payload

    def snapshot(self):
        return None


def _run_coverage_case(tmp_path, odb_payload, sta_text=""):
    workdir = tmp_path / "run"
    job_name = "Job_TP7"
    executor = _CoverageExecutor(workdir, job_name, odb_payload, sta_text)
    return AnalysisRunner(executor).run(
        "Model", job_name, workdir=str(workdir), require_production=False,
        action_plan=(
            {"action_type": "dynamic_explicit_step",
             "parameters": {"name": "Step-1", "time_period": 30.0}},
        ),
    )


def test_analysis_run_records_time_coverage_and_evidence(tmp_path):
    run = _run_coverage_case(
        tmp_path,
        {
            "status": "available", "steps": ["Step-1"], "instances": [],
            "step_frames": {"Step-1": 3},
            "step_times": {"Step-1": {"first_frame_value": 0.0,
                                      "last_frame_value": 16.43,
                                      "frame_count": 3}},
        },
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n",
    )
    coverage = run.metadata["time_coverage"]
    assert coverage["status"] == "PARTIAL"
    assert coverage["target_time"] == 30.0
    assert coverage["reached_time"] == 16.43
    assert coverage["reached_source"].startswith("odb:Step-1")
    assert any(e.kind == "time_coverage" for e in run.evidence.items)
    assert run.verification["time_coverage"]["status"] == "PARTIAL"


def test_analysis_run_uses_sta_when_odb_has_no_frame_time(tmp_path):
    run = _run_coverage_case(
        tmp_path,
        {
            "status": "available", "steps": ["Step-1"], "instances": [],
            "step_frames": {"Step-1": 3},
        },
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n  STEP TIME 16.43\n",
    )
    coverage = run.metadata["time_coverage"]
    assert coverage["status"] == "PARTIAL"
    assert coverage["reached_time"] == 16.43
    assert coverage["reached_source"].startswith(".sta:")
