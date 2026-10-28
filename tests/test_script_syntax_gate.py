"""Offline negative tests for the pre-launch script syntax gate.

These tests do not claim a live Abaqus run. They only prove that an existing
illegal script never reaches the launcher, and that a legal script is not
blocked by the gate.
"""

from abaqus_ai_agent.actions.builders import material_elastic, python_action
from abaqus_ai_agent.actions.runner import execute
from abaqus_ai_agent.execution.batch import BatchExecutor
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.errors import AbaqusExecutionError
from abaqus_ai_agent.execution.script_syntax import check_python_source, check_script_file


class _Boom:
    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("launcher must not start for a syntax error")


def test_missing_script_is_not_a_syntax_failure(tmp_path):
    assert check_script_file(str(tmp_path / "missing.py")) is None


def test_existing_syntax_error_does_not_call_launcher(tmp_path, monkeypatch):
    script = tmp_path / "bad.py"
    script.write_text("def broken(:\n    return 1\n", encoding="utf-8")
    boom = _Boom()
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.watchdog.run_with_watchdog", boom)
    result = BatchExecutor(workdir=str(tmp_path)).run_nogui(str(script))
    assert boom.calls == 0
    assert result.return_code != 0
    assert result.completion_evidence == "syntax_blocked"
    assert result.settled is True
    assert "bad.py" in result.stderr
    assert ":" in result.stderr or "line" in result.stderr.lower() or "1" in result.stderr


def test_legal_script_is_not_blocked(tmp_path, monkeypatch):
    script = tmp_path / "ok.py"
    script.write_text("x = 1\nprint(x)\n", encoding="utf-8")
    called = {}

    class _Ok:
        returncode = 0
        stdout = "ok"
        stderr = ""
        duration = 0.01

    def _run(*args, **kwargs):
        called["yes"] = True
        return _Ok()

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.watchdog.run_with_watchdog", _run)
    result = BatchExecutor(workdir=str(tmp_path), settle_timeout=0).run_nogui(str(script))
    assert called.get("yes") is True
    assert result.completion_evidence != "syntax_blocked"
    assert result.succeeded


def test_non_python_path_is_not_rewritten_as_syntax(tmp_path):
    assert check_script_file(str(tmp_path / "deck.inp")) is None


def test_action_fragment_syntax_error_does_not_reach_executor():
    seen = []

    def _execute(code, timeout=120):
        seen.append(code)
        return {"ok": True}

    action = python_action("Model-1", "def broken(:\n    pass\n")
    try:
        execute(InProcessExecutor(_execute), action)
    except AbaqusExecutionError as exc:
        assert exc.category == "syntax"
        assert exc.source_line is not None and exc.source_line >= 1
        assert "broken" in (exc.code_excerpt or "")
        assert "<action:python>" in str(exc)
    else:
        raise AssertionError("syntax error must not be sent to the executor")
    assert seen == []


def test_legal_action_fragment_still_executes():
    seen = []

    def _execute(code, timeout=120):
        seen.append(code)
        return {"ok": True}

    action = material_elastic("Model-1", "Steel", 210000.0, 0.3)
    result = execute(InProcessExecutor(_execute), action)
    assert result == {"ok": True}
    assert seen and "Elastic" in seen[0]


def test_compile_reports_file_line_and_excerpt():
    error = check_python_source("ok = 1\ndef broken(:\n    pass\n", "sample.py")
    assert error is not None
    assert error.path == "sample.py"
    assert error.line == 2
    assert "broken" in error.excerpt
    payload = error.to_dict()
    assert payload["category"] == "syntax"
