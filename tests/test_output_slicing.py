"""Structured tool-output slice tests (Governance Plan 阶段 2 第 2 项).

Contract: a success returns one sentence plus elapsed time; a failure returns the
deepest stack frame and the assertion line only, with the full log preserved on disk.

Layer of evidence: unit tests on synthetic subprocess text. No real solver process.
"""

from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from abaqus_ai_agent.execution.output_slicing import (
    MAX_FAILURE_CHARS,
    MAX_SUCCESS_CHARS,
    build_failure_slice,
    parse_failure,
    persist_full_output,
    slice_traceback_text,
    summarize_success,
)


def test_success_message_is_one_line_with_elapsed():
    msg = summarize_success("ODB extraction", 42.35)
    assert msg == "ODB extraction succeeded in 42.4 ms"
    assert "\n" not in msg


def test_success_message_is_bounded():
    msg = summarize_success("Job", 1.0, detail="x" * 1000)
    assert len(msg) <= MAX_SUCCESS_CHARS


def test_failure_slice_picks_deepest_frame():
    blob = (
        'Traceback (most recent call last):\n'
        '  File "run.py", line 10, in main\n'
        "    dispatch()\n"
        '  File "engine.py", line 55, in dispatch\n'
        "    extract()\n"
        '  File "odb_extract.py", line 909, in extract\n'
        "    value = frame.fieldOutputs['S']\n"
        "KeyError: 'S'\n"
    )
    sl = parse_failure(blob)

    assert sl.exception_type == "KeyError"
    assert sl.exception_message == "'S'"
    assert sl.frame_file == "odb_extract.py"
    assert sl.frame_line == 909
    assert sl.frame_function == "extract"


def test_failure_slice_extracts_assertion_line():
    blob = (
        'Traceback (most recent call last):\n'
        '  File "test_x.py", line 7, in test_thing\n'
        "    assert value < limit\n"
        "AssertionError: 12.5 >= 10\n"
    )
    sl = parse_failure(blob)

    assert sl.exception_type == "AssertionError"
    assert "assert value < limit" in sl.assertion_line


def test_failure_message_is_bounded_even_for_huge_logs():
    blob = "\n".join(f'  File "f{i}.py", line {i}, in g{i}' for i in range(5000))
    blob += "\nValueError: " + "x" * 20000 + "\n"

    msg = slice_traceback_text(blob)
    assert len(msg) <= MAX_FAILURE_CHARS
    assert "ValueError" in msg


def test_failure_slice_never_echoes_whole_log():
    blob = (
        "noise line\n" * 500
        + 'Traceback (most recent call last):\n'
        + '  File "solver.py", line 3, in run\n'
        + "    1/0\n"
        + "ZeroDivisionError: division by zero\n"
    )
    msg = slice_traceback_text(blob)
    assert "noise line" not in msg
    assert "ZeroDivisionError" in msg


def test_empty_output_still_yields_a_typed_failure():
    sl = parse_failure("")
    assert sl.exception_type == "Failure"
    assert "empty output" in sl.exception_message


def test_build_failure_slice_includes_returncode_and_evidence_path(tmp_path: Path):
    log = persist_full_output(
        stdout="some stdout\n",
        stderr='Traceback (most recent call last):\n  File "a.py", line 2, in b\nRuntimeError: boom\n',
        target=tmp_path / "extract_log.txt",
    )
    assert log is not None and log.is_file()

    sl = build_failure_slice(
        returncode=1,
        stdout="some stdout\n",
        stderr=log.read_text(encoding="utf-8").split("=== STDERR ===")[1],
        operation="ODB extraction",
        evidence_path=log,
    )
    msg = sl.to_message()

    assert "RuntimeError: boom" in msg
    assert str(log) in msg
    assert sl.extra["returncode"] == 1


def test_build_failure_slice_falls_back_to_returncode_when_no_exception():
    sl = build_failure_slice(
        returncode=3,
        stdout="",
        stderr="*** ERROR: license unavailable\n",
        operation="Job submit",
    )
    assert "returncode 3" in sl.to_message()


def test_full_output_is_preserved_on_disk(tmp_path: Path):
    stdout = "line-A\n" * 200
    stderr = "line-B\n" * 200
    target = tmp_path / "logs" / "run.txt"

    log = persist_full_output(stdout, stderr, target)

    assert log == target
    content = target.read_text(encoding="utf-8")
    assert "line-A" in content and "line-B" in content
    assert content.count("line-A") == 200
