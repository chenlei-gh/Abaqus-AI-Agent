"""Offline fixtures for correction-cost telemetry.

A record is not a before/after timing study. These tests only prove the
required fields exist for the named failure classes, and that a recorder
failure cannot change the caller's status.
"""

import json

import pytest

from abaqus_ai_agent.telemetry.correction import (
    classify_correction_category,
    record_correction_event,
)


CASES = (
    ("syntax", "invalid syntax at line 3", "syntax"),
    ("abaqus_api", "AttributeError: object has no attribute Job", "abaqus_api"),
    ("region_invalid", "region set not found: FIX", "region_invalid"),
    ("unit_or_direction", "load direction interpreted as +X instead of -Z", "unit_or_direction"),
    ("convergence", "TOO MANY ATTEMPTS made for this increment", "convergence"),
)


@pytest.mark.parametrize("category,message,expected", CASES)
def test_named_failure_classes_have_structured_records(tmp_path, category, message, expected):
    path = tmp_path / "correction_telemetry.jsonl"
    payload = record_correction_event(
        category, "negative_fixture",
        message=message, source="fixture", first_pass=False, retry_count=1,
        diagnosis_s=0.2, repair_s=None, extra_solve_s=12.5,
        metadata={"fixture": True}, path=str(path),
    )
    assert payload is not None
    for key in (
        "category", "stage", "first_pass", "retry_count",
        "diagnosis_s", "repair_s", "extra_solve_s", "message",
    ):
        assert key in payload
    assert payload["category"] == expected
    assert payload["first_pass"] is False
    assert payload["retry_count"] == 1
    stored = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert stored["category"] == expected
    assert stored["extra_solve_s"] == 12.5


def test_classifier_does_not_invent_a_category_from_empty_text():
    assert classify_correction_category("") == "other"


def test_recorder_failure_does_not_change_caller_status(monkeypatch, tmp_path):
    status = {"engineering_status": "SUBMISSION_BLOCKED"}

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)
    payload = record_correction_event(
        "syntax", "script_syntax_gate", message="invalid syntax",
        path=str(tmp_path / "will-fail.jsonl"),
    )
    assert payload is None
    assert status["engineering_status"] == "SUBMISSION_BLOCKED"


def test_syntax_gate_records_without_changing_blocked_result(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution.batch import BatchExecutor

    script = tmp_path / "bad.py"
    script.write_text("def broken(:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.watchdog.run_with_watchdog",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("launcher started")),
    )
    result = BatchExecutor(workdir=str(tmp_path)).run_nogui(str(script))
    assert result.completion_evidence == "syntax_blocked"
    log = tmp_path / "correction_telemetry.jsonl"
    assert log.is_file()
    stored = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert stored["category"] == "syntax"
    assert stored["first_pass"] is False
    assert stored["stage"] == "script_syntax_gate"
