"""Environment-misuse remedy tests.

Three failures recur when Abaqus is driven from a generic shell and each one
costs a round-trip because the traceback names the symptom but not the fix:
wrong interpreter (no ``odbAccess``), launcher missing from ``PATH``, and the
cp936/GBK default encoding rejecting UTF-8 text.

Layer of evidence: unit tests on synthetic failure text. No real solver process.
"""

from __future__ import annotations

import pytest

from abaqus_ai_agent.execution.environment_hints import diagnose_environment
from abaqus_ai_agent.execution.output_slicing import (
    build_failure_slice,
    slice_traceback_text,
)


def test_missing_odb_access_names_the_abaqus_interpreter():
    text = (
        "Traceback (most recent call last):\n"
        '  File "probe.py", line 1, in <module>\n'
        "    from odbAccess import openOdb\n"
        "ModuleNotFoundError: No module named 'odbAccess'\n"
    )
    hint = diagnose_environment(text)
    assert "Abaqus interpreter" in hint
    assert "python" in hint


def test_launcher_not_on_path_names_absolute_invocation():
    hint = diagnose_environment("bash: abaqus: command not found\n")
    assert "PATH" in hint
    assert "absolute path" in hint


def test_launcher_not_on_path_windows_wording():
    text = (
        "'abaqus' is not recognized as an internal or external command,\n"
        "operable program or batch file.\n"
    )
    hint = diagnose_environment(text)
    assert "absolute path" in hint


def test_cp936_default_encoding_names_the_encoding_fix():
    text = (
        "Traceback (most recent call last):\n"
        '  File "<stdin>", line 3, in <module>\n'
        "UnicodeDecodeError: 'gbk' codec can't decode byte 0xad in position 37: "
        "illegal multibyte sequence\n"
    )
    hint = diagnose_environment(text)
    assert 'encoding="utf-8"' in hint


def test_unrelated_failure_yields_no_hint():
    text = "Traceback (most recent call last):\nKeyError: 'S'\n"
    assert diagnose_environment(text) == ""


def test_empty_text_yields_no_hint():
    assert diagnose_environment("") == ""
    assert diagnose_environment(None) == ""


def test_operation_prefix_is_applied():
    hint = diagnose_environment("bash: abaqus: command not found", operation="ODB extraction")
    assert hint.startswith("ODB extraction: ")


def test_failure_slice_carries_remedy_for_environment_misuse(tmp_path):
    sl = build_failure_slice(
        returncode=1,
        stdout="",
        stderr="ModuleNotFoundError: No module named 'odbAccess'\n",
        operation="ODB extraction",
        evidence_path=tmp_path / "log.txt",
    )
    msg = sl.to_message()
    assert "remedy:" in msg
    assert "odbAccess" in sl.exception_message


def test_failure_slice_has_no_remedy_for_ordinary_failure():
    sl = build_failure_slice(
        returncode=1,
        stdout="",
        stderr="RuntimeError: mesh is empty\n",
        operation="Solve",
    )
    assert "remedy" not in sl.extra
    assert "remedy:" not in sl.to_message()


def test_slice_traceback_text_appends_remedy():
    text = "UnicodeDecodeError: 'gbk' codec can't decode byte 0xad in position 37"
    msg = slice_traceback_text(text)
    assert "remedy:" in msg
    assert 'encoding="utf-8"' in msg


@pytest.mark.parametrize(
    "module",
    ["abaqusConstants", "regionToolset", "part", "material", "visualization"],
)
def test_multiple_abaqus_modules_are_recognised(module):
    hint = diagnose_environment(
        f"ModuleNotFoundError: No module named '{module}'\n"
    )
    assert "Abaqus interpreter" in hint
