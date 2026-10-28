"""Batch settle (P1-4) and kernel namespace isolation (P1-5) tests."""

import threading
import time

from abaqus_ai_agent.execution.batch import (
    BatchExecutor,
    BatchResult,
    await_quiescence,
    await_script_completion,
    completion_sentinel_code,
)
from abaqus_ai_agent.execution.jobs import (
    JobState,
    classify_job_status,
    completion_wait_transport_timeout,
    wait_for_completion_code,
)
from abaqus_ai_agent.execution.kernel_namespace import KernelNamespace


# --- run_input command contract ---------------------------------------------

def test_run_input_requests_the_interactive_run_mode(tmp_path, monkeypatch):
    """``background`` is the documented default, so it must be overridden.

    A background submission hands the job off and returns, which leaves the
    watchdog supervising a launcher that already exited.
    """
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""
        duration = 0.01

    def _fake(cmd, **kwargs):
        seen["cmd"] = tuple(cmd)
        seen["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(watchdog_module, "run_with_watchdog", _fake)
    executor = BatchExecutor(workdir=str(tmp_path), settle_timeout=0)
    executor.run_input(str(tmp_path / "deck.inp"), job_name="DeckJob")

    assert seen["cmd"][1:] == (
        "job=DeckJob", "input=%s" % (tmp_path / "deck.inp").resolve(), "interactive")


def test_run_input_enables_evidence_gated_stall_relaxation(tmp_path, monkeypatch):
    """A foreground solve is now actually watched, so the default 120 s stall
    window would kill a legitimately silent implicit solve."""
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""
        duration = 0.01

    def _fake(cmd, **kwargs):
        seen["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(watchdog_module, "run_with_watchdog", _fake)
    BatchExecutor(workdir=str(tmp_path), settle_timeout=0).run_input(
        str(tmp_path / "deck.inp"), job_name="DeckJob")

    assert seen["kwargs"]["adaptive_heartbeat"] is True
    assert seen["kwargs"]["job_name"] == "DeckJob"


# --- bounded kernel wait ------------------------------------------------------

def test_wait_snippet_is_bounded_and_compiles():
    code = wait_for_completion_code("Job-1", 90)
    compile(code, "<test>", "exec")
    assert "waitForCompletion(timeOut=90)" in code
    # No bare call: the unbounded form must not survive anywhere in the snippet.
    assert "waitForCompletion()" not in code


def test_wait_snippet_bounds_missing_timeout():
    assert "timeOut=3600" in wait_for_completion_code("Job-1", None)


def test_wait_snippet_binds_result_channel():
    """Printing alone is not enough: the transport's own envelope carries a
    ``status`` key, and reading that envelope would report every job as
    ``COMPLETED`` no matter what the kernel said."""
    code = wait_for_completion_code("Job-1", 60)
    compile(code, "<test>", "exec")
    assert "result = {'status': _ai_status}" in code


def test_wait_snippet_status_survives_transport_envelope():
    """End-to-end through the real kernel namespace and classifier.

    ``KernelNamespace.execute`` returns ``{"status": "COMPLETED", "stdout": …}``
    for a fragment that only prints. Classifying that envelope reported an
    ABORTED job as COMPLETED; the snippet must win via the ``result`` channel.
    """
    class _Job:
        def __init__(self, state):
            self.status = state

        def waitForCompletion(self, timeOut=None):
            return None

    class _Mdb:
        def __init__(self, state):
            self.jobs = {"Job-1": _Job(state)}

    for state in ("ABORTED", "TERMINATED", "COMPLETED"):
        namespace = KernelNamespace(seed_code="")
        namespace.namespace["mdb"] = _Mdb(state)
        envelope = namespace.execute(wait_for_completion_code("Job-1", 60), "<test>")
        assert classify_job_status("Job-1", envelope).state.value == state


def test_transport_timeout_exceeds_kernel_wait_bound():
    """The kernel owns the documented timeout; the transport must not pre-empt it."""
    assert completion_wait_transport_timeout(60) > 60
    assert completion_wait_transport_timeout(None) > 3600


# --- status classification ----------------------------------------------------

def test_datacheck_status_is_not_an_analysis_completion():
    """``CHECK_COMPLETED`` contains ``COMPLETED``; substring matching would
    promote a datacheck to a finished analysis."""
    assert classify_job_status("J", "CHECK_COMPLETED").state is JobState.UNKNOWN
    assert classify_job_status("J", "CHECK_RUNNING").state is JobState.RUNNING
    assert classify_job_status("J", "COMPLETED").state is JobState.COMPLETED
    assert classify_job_status("J", "ABORTED").state is JobState.ABORTED


def test_symbolic_constant_status_is_unwrapped():
    status = classify_job_status("J", "SymbolicConstant<COMPLETED>")
    assert status.state is JobState.COMPLETED


def test_status_diagnostics_record_a_datacheck_promotion_risk():
    status = classify_job_status("J", "CHECK_COMPLETED")
    assert any("datacheck" in note for note in status.diagnostics)


# --- await_quiescence ---------------------------------------------------------

def test_quiescence_settles_on_idle_dir(tmp_path):
    settled, note = await_quiescence(tmp_path, quiet_period=0.3, timeout=5.0, poll=0.1)
    assert settled and note is None


def test_quiescence_times_out_while_files_keep_changing(tmp_path):
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            (tmp_path / "active.dat").write_text(str(i), encoding="utf-8")
            i += 1
            time.sleep(0.05)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        settled, note = await_quiescence(tmp_path, quiet_period=0.4, timeout=0.8, poll=0.1)
    finally:
        stop.set()
        t.join()
    assert not settled
    assert "still changing" in note


def test_run_settles_artifacts_after_launcher_exit(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
        duration = 0.01

    monkeypatch.setattr(watchdog_module, "run_with_watchdog", lambda *a, **k: _Proc())
    executor = BatchExecutor(workdir=str(tmp_path), settle_timeout=5.0)
    result = executor._run(["abaqus", "cae", "noGUI=x.py"])
    assert result.succeeded
    assert result.settled is True


def test_run_flags_unsettled_artifacts(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""
        duration = 0.01

    monkeypatch.setattr(watchdog_module, "run_with_watchdog", lambda *a, **k: _Proc())
    executor = BatchExecutor(workdir=str(tmp_path), settle_timeout=0.5)

    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            (tmp_path / "growing.dat").write_text(str(i), encoding="utf-8")
            i += 1
            time.sleep(0.05)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        result = executor._run(["abaqus", "job=x"])
    finally:
        stop.set()
        t.join()
    assert result.succeeded  # process-level only
    assert result.settled is False
    assert result.settle_note


# --- official noGUI completion semantics (P1-LAUNCHER-02) ----------------------

class _OkProc:
    returncode = 0
    stdout = ""
    stderr = ""
    duration = 0.01


def test_sentinel_is_a_valid_last_statement(tmp_path):
    marker = tmp_path / "done.flag"
    code = "x = 1\n" + completion_sentinel_code(marker)
    compile(code, "<test>", "exec")
    assert code.rstrip().endswith("_ai_done.close()")


def test_sentinel_absent_means_no_completion_evidence(tmp_path, monkeypatch):
    """The launcher exiting is not the documented completion event.

    Regression guard for the old contract: a quiet workdir plus rc=0 was
    treated as settled even though nothing proved the script reached its end.
    """
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    monkeypatch.setattr(watchdog_module, "run_with_watchdog", lambda *a, **k: _OkProc())
    executor = BatchExecutor(workdir=str(tmp_path), settle_timeout=5.0)
    result = executor.run_nogui(
        str(tmp_path / "s.py"),
        completion_sentinel=tmp_path / "never.flag",
        timeout=0.3,
    )
    assert result.succeeded
    assert result.settled is False
    assert result.completion_evidence == "none"
    assert "did not appear" in result.settle_note


def test_sentinel_present_is_recorded_as_completion_evidence(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    marker = tmp_path / "done.flag"
    marker.write_text("completed", encoding="utf-8")
    monkeypatch.setattr(watchdog_module, "run_with_watchdog", lambda *a, **k: _OkProc())
    executor = BatchExecutor(workdir=str(tmp_path), settle_timeout=5.0)
    result = executor.run_nogui(
        str(tmp_path / "s.py"), completion_sentinel=marker, timeout=2)
    assert result.settled is True
    assert result.completion_evidence == "script_completed"


def test_blocked_sentinel_is_not_reported_as_completed(tmp_path, monkeypatch):
    """A deliberate early stop ends the script but did not complete it."""
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    marker = tmp_path / "done.flag"
    marker.write_text("blocked", encoding="utf-8")
    monkeypatch.setattr(watchdog_module, "run_with_watchdog", lambda *a, **k: _OkProc())
    result = BatchExecutor(workdir=str(tmp_path), settle_timeout=5.0).run_nogui(
        str(tmp_path / "s.py"), completion_sentinel=marker, timeout=2)
    assert result.completion_evidence == "script_blocked"


def test_without_sentinel_evidence_is_only_quiescence(tmp_path, monkeypatch):
    """Backwards compatibility: callers that pass no sentinel keep the old
    behaviour, and the result says quiescence is all that was checked."""
    from abaqus_ai_agent.execution import watchdog as watchdog_module

    monkeypatch.setattr(watchdog_module, "run_with_watchdog", lambda *a, **k: _OkProc())
    result = BatchExecutor(workdir=str(tmp_path), settle_timeout=5.0).run_nogui(
        str(tmp_path / "s.py"))
    assert result.settled is True
    assert result.completion_evidence == "quiescence_only"


def test_await_script_completion_reports_timeout(tmp_path):
    state, note = await_script_completion(
        tmp_path / "absent.flag", timeout=0.2, poll=0.05)
    assert state is None
    assert note


# --- KernelNamespace ------------------------------------------------------------

def test_namespace_persists_variables_across_fragments():
    ns = KernelNamespace()
    ns.execute("helper_value = 41")
    out = ns.execute('print({"v": helper_value + 1})')
    assert out == {"v": 42}


def test_namespace_does_not_leak_into_caller_globals():
    sentinel = object()
    globals()["LOG"] = sentinel
    try:
        ns = KernelNamespace(seed_code=("LOG = 'kernel-value'",))
        ns.execute('result = {"log_seen": LOG}')
        # caller's LOG is untouched; the kernel value stayed in the namespace
        assert globals()["LOG"] is sentinel
        assert ns.namespace["LOG"] == "kernel-value"
    finally:
        globals().pop("LOG", None)


def test_result_channel_is_cleared_between_fragments():
    ns = KernelNamespace()
    first = ns.execute('result = {"a": 1}')
    assert first == {"a": 1}
    # Second fragment sets no result: the previous one must not leak through.
    second = ns.execute("x = 5")
    assert second == {"status": "COMPLETED"}


def test_stdout_dict_last_line_contract():
    ns = KernelNamespace()
    out = ns.execute('print({"status": "COMPLETED", "n": 7})')
    assert out == {"status": "COMPLETED", "n": 7}
def test_star_import_stays_inside_namespace(tmp_path, monkeypatch):
    """Reproduces the 2026-10-27 LOG incident mechanism with a fake
    abaqusConstants module: a star import inside the namespace must not
    clobber caller globals, and the star names must land in the namespace."""
    import sys
    import types

    fake = types.ModuleType("abaqusConstants")
    fake.LOG = "SymbolicConstant<LOG>"
    fake.ON = "SymbolicConstant<ON>"
    fake.__all__ = ["LOG", "ON"]
    monkeypatch.setitem(sys.modules, "abaqusConstants", fake)

    sentinel = object()
    globals()["LOG"] = sentinel
    try:
        ns = KernelNamespace()
        out = ns.execute(
            "from abaqusConstants import *\n"
            "result = {\"log_seen\": LOG, \"on_seen\": ON}"
        )
        assert out == {"log_seen": "SymbolicConstant<LOG>", "on_seen": "SymbolicConstant<ON>"}
        assert globals()["LOG"] is sentinel
        assert ns.namespace["LOG"] == "SymbolicConstant<LOG>"
    finally:
        globals().pop("LOG", None)


def test_fragment_exception_propagates_and_restores_stdout(capsys):
    import sys

    ns = KernelNamespace()
    ns.execute("kept = 1")
    try:
        ns.execute("raise ValueError('boom')")
    except ValueError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("fragment exception must propagate")
    # stdout restored: this print must reach the real stdout, not a dead buffer
    print("stdout-alive-marker")
    assert "stdout-alive-marker" in capsys.readouterr().out
    # namespace survived the failed fragment and remains usable
    out = ns.execute("result = {\"kept\": kept}")
    assert out == {"kept": 1}


def test_failed_fragment_does_not_leave_stale_result():
    ns = KernelNamespace()
    assert ns.execute("result = {\"a\": 1}") == {"a": 1}
    try:
        ns.execute("undefined_name_boom")
    except NameError:
        pass
    # result was cleared before the failing fragment; a later clean fragment
    # must not observe the pre-failure value
    assert ns.execute("y = 2") == {"status": "COMPLETED"}


def test_seed_code_does_not_touch_caller_globals():
    ns = KernelNamespace(seed_code=("SEEDED = 7",))
    assert "SEEDED" not in globals()
    assert ns.execute("result = {\"v\": SEEDED}") == {"v": 7}
