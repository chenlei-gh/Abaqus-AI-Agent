"""Unit and negative regression tests for Abaqus solver process stall watchdog (REQ-P1-056)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from abaqus_ai_agent.execution.watchdog import (
    SolverProcessStalledError,
    WatchedProcessResult,
    kill_process_tree,
    run_with_watchdog,
)
from abaqus_ai_agent.execution.batch import BatchExecutor
from abaqus_ai_agent.execution.solver import AbaqusBatchJob, execute_abaqus_batch_job
from abaqus_ai_agent.diagnostics.solver_patterns import diagnose_solver_artifacts
from abaqus_ai_agent.diagnostics.remediator import SolverRemediator


def test_watchdog_normal_process_completes_cleanly(tmp_path):
    """A fast-completing process succeeds without triggering stall or timeout."""
    cmd = [sys.executable, "-c", "import sys; sys.stdout.write('hello\\n'); sys.stderr.write('err\\n')"]
    res = run_with_watchdog(cmd, cwd=tmp_path, timeout=10.0, stall_timeout=5.0)

    assert isinstance(res, WatchedProcessResult)
    assert res.returncode == 0
    assert res.succeeded
    assert "hello" in res.stdout
    assert "err" in res.stderr
    assert not res.stalled
    assert not res.timed_out


def test_watchdog_trips_on_stalled_silent_process(tmp_path):
    """A child process that sits silent without output or file activity trips the stall breaker."""
    # Process sleeps for 10 seconds without output
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    start = time.monotonic()

    with pytest.raises(SolverProcessStalledError) as exc_info:
        run_with_watchdog(
            cmd,
            cwd=tmp_path,
            timeout=10.0,
            stall_timeout=0.8,
            poll_interval=0.1,
        )

    elapsed = time.monotonic() - start
    err = exc_info.value

    # Verify stall circuit breaker tripped quickly (around 0.8s ~ 2.0s, well before 10s)
    assert elapsed < 5.0
    assert err.stall_timeout == 0.8
    assert err.stall_duration >= 0.7
    assert err.diagnostic()["category"] == "solver_stalled"
    assert "without stream output or disk activity" in str(err)


def test_watchdog_stream_heartbeat_prevents_false_stall(tmp_path):
    """Continuous stream output updates last_activity and prevents false stall triggers."""
    # Process runs for 1.5 seconds, emitting a line every 0.25 seconds
    py_code = (
        "import time, sys\n"
        "for i in range(5):\n"
        "    time.sleep(0.25)\n"
        "    sys.stdout.write('heartbeat %d\\n' % i)\n"
        "    sys.stdout.flush()\n"
    )
    cmd = [sys.executable, "-c", py_code]

    # stall_timeout is 0.7s (< total 1.5s runtime). Because it pulses every 0.25s, stall must NOT trip.
    res = run_with_watchdog(
        cmd,
        cwd=tmp_path,
        timeout=10.0,
        stall_timeout=0.7,
        poll_interval=0.1,
    )

    assert res.succeeded
    assert "heartbeat 4" in res.stdout


def test_watchdog_monitored_file_heartbeat_prevents_false_stall(tmp_path):
    """File updates to monitored extensions (.sta, .msg, .log) refresh heartbeat even if stdout is silent."""
    py_code = (
        "import time, pathlib\n"
        "sta = pathlib.Path('Job-test.sta')\n"
        "for i in range(5):\n"
        "    time.sleep(0.25)\n"
        "    with open(sta, 'a') as f:\n"
        "        f.write('increment %d\\n' % i)\n"
    )
    cmd = [sys.executable, "-c", py_code]

    res = run_with_watchdog(
        cmd,
        cwd=tmp_path,
        timeout=10.0,
        stall_timeout=0.7,
        poll_interval=0.1,
        monitored_extensions=(".sta",),
    )

    assert res.succeeded
    sta_path = tmp_path / "Job-test.sta"
    assert sta_path.is_file()
    assert "increment 4" in sta_path.read_text(encoding="utf-8")


def test_watchdog_hard_timeout_fires_when_process_exceeds_total_limit(tmp_path):
    """If process produces output but exceeds total hard timeout, TimeoutExpired is raised."""
    # Infinite chatter
    py_code = (
        "import time, sys\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
        "    sys.stdout.write('chatter\\n')\n"
        "    sys.stdout.flush()\n"
    )
    cmd = [sys.executable, "-c", py_code]

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        run_with_watchdog(
            cmd,
            cwd=tmp_path,
            timeout=1.0,
            stall_timeout=5.0,
            poll_interval=0.1,
        )

    assert exc_info.value.timeout == 1.0


def test_batch_executor_watchdog_integration(tmp_path):
    """BatchExecutor forwards stall_timeout and raises SolverProcessStalledError on deadlock."""
    silent_script = tmp_path / "silent.py"
    silent_script.write_text("import time; time.sleep(10)", encoding="utf-8")

    executor = BatchExecutor(
        launcher=sys.executable,
        workdir=str(tmp_path),
        timeout=10,
        stall_timeout=0.8,
    )

    with pytest.raises(SolverProcessStalledError) as exc_info:
        executor._run([sys.executable, str(silent_script)])

    assert exc_info.value.stall_timeout == 0.8


def test_execute_abaqus_batch_job_records_stall_diagnostics(tmp_path, monkeypatch):
    """execute_abaqus_batch_job catches SolverProcessStalledError and returns ABORTED with SOLVER_STALLED diag."""
    inp = tmp_path / "test.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")

    job = AbaqusBatchJob(
        job_name="StalledJob",
        inp_path=inp,
        workdir=tmp_path,
        timeout_seconds=10,
        stall_timeout_seconds=1,
    )

    def mock_run_with_watchdog(*args, **kwargs):
        raise SolverProcessStalledError(
            "Process stalled for 1.2s",
            cmd=args[0] if args else kwargs.get("cmd", ()),
            workdir=str(tmp_path),
            stall_duration=1.2,
            stall_timeout=1.0,
            stdout="iter 1 started\n",
        )

    monkeypatch.setattr("abaqus_ai_agent.execution.watchdog.run_with_watchdog", mock_run_with_watchdog)
    monkeypatch.setattr("abaqus_ai_agent.execution.solver.find_abaqus_executable", lambda x: "dummy_abaqus")

    result = execute_abaqus_batch_job(job)
    assert result.state == "ABORTED"
    assert result.returncode == -1
    assert any("SOLVER_STALLED" in d for d in result.diagnostics)
    assert any("iter 1 started" in d for d in result.diagnostics)


def test_diagnostics_and_remediator_recognize_solver_stalled():
    """Diagnostic patterns and remediator propose step controls and stabilization on SOLVER_STALLED."""
    log_text = "SOLVER_STALLED: Process stalled for 125.0s exceeding threshold 120.0s\n"
    issues = diagnose_solver_artifacts(log_text=log_text, job_status="ABORTED")

    issue_ids = [i.id for i in issues]
    assert "SOLVER_STALLED" in issue_ids

    rems = SolverRemediator.generate_remediations(issues)
    assert any(r.diagnosis_id == "SOLVER_STALLED" for r in rems)
    stall_rem = next(r for r in rems if r.diagnosis_id == "SOLVER_STALLED")
    assert stall_rem.parameters.get("initial_inc") == 0.01
    assert stall_rem.parameters.get("stabilization_magnitude") == 2e-4


def test_watchdog_terminates_entire_process_tree_on_stall(tmp_path):
    """When a process stalls, watchdog terminates the parent and all spawned descendants."""
    parent_script = tmp_path / "parent.py"
    pid_file = tmp_path / "grandchild.pid"
    hb_file = tmp_path / "grandchild_hb.txt"

    # Grandchild continuously pulses heartbeat every 0.05s while alive
    py_code = (
        "import subprocess, sys, time, pathlib\n"
        "gc_code = 'import time, pathlib, sys\\n' \\\n"
        "          'hb = pathlib.Path(sys.argv[1])\\n' \\\n"
        "          'for i in range(1200):\\n' \\\n"
        "          '    hb.write_text(str(i), encoding=\"utf-8\")\\n' \\\n"
        "          '    time.sleep(0.05)\\n'\n"
        f"gc = subprocess.Popen([sys.executable, '-c', gc_code, r'{hb_file}'])\n"
        f"pathlib.Path(r'{pid_file}').write_text(str(gc.pid), encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    parent_script.write_text(py_code, encoding="utf-8")

    with pytest.raises(SolverProcessStalledError):
        run_with_watchdog(
            [sys.executable, str(parent_script)],
            cwd=tmp_path,
            timeout=10.0,
            stall_timeout=0.8,
            poll_interval=0.1,
        )

    assert pid_file.is_file()
    gc_pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert gc_pid > 0

    time.sleep(0.5)

    # 1. Functional evidence: Heartbeat file stops updating
    assert hb_file.is_file()
    hb_val_1 = hb_file.read_text(encoding="utf-8").strip()
    time.sleep(0.2)
    hb_val_2 = hb_file.read_text(encoding="utf-8").strip()
    assert hb_val_1 == hb_val_2, f"Grandchild code still running: hb progressed from {hb_val_1} to {hb_val_2}"

    # 2. Operating system API verification: No dangling active process
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, gc_pid)
        if handle:
            try:
                exit_code = ctypes.c_ulong()
                ret = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                assert ret != 0, f"GetExitCodeProcess failed with error: {ctypes.GetLastError()}"
                # STILL_ACTIVE = 259
                assert exit_code.value != 259, f"Grandchild process {gc_pid} is STILL_ACTIVE (259)"
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            err = ctypes.GetLastError()
            # 87: ERROR_INVALID_PARAMETER (PID does not exist / fully reaped)
            # Fail closed: Any other error (e.g. 5 Access Denied meaning process still exists) is a failure
            assert err == 87, f"OpenProcess failed with unexpected error code: {err} (cannot verify termination)"
    else:
        try:
            os.kill(gc_pid, 0)
            status_path = Path(f"/proc/{gc_pid}/status")
            if status_path.is_file():
                text = status_path.read_text(encoding="utf-8")
                assert "State:\tZ" in text or "State:\tX" in text
            else:
                time.sleep(0.5)
                with pytest.raises(ProcessLookupError):
                    os.kill(gc_pid, 0)
        except ProcessLookupError:
            pass


class _MockControlledProc:
    """Mock process allowing deterministic sequencing of poll() returns and stdout/stderr streams."""
    def __init__(self, poll_sequence, pid=88888, out_lines=("mock output\n",)):
        import io
        self.poll_sequence = list(poll_sequence)
        self.pid = pid
        self.stdout = io.StringIO("".join(out_lines))
        self.stderr = io.StringIO("")
        self.killed = False

    def poll(self):
        if self.poll_sequence:
            return self.poll_sequence.pop(0)
        return 0

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


@pytest.mark.parametrize("exit_code,expected_succeeded", [(0, True), (2, False)])
def test_watchdog_hard_timeout_boundary_exit_captured_by_secondary_poll(monkeypatch, exit_code, expected_succeeded):
    """If process is running at loop start but finishes with exit_code before hard timeout trips, secondary poll captures it."""
    # Sequence: first poll is None (running), second poll (at timeout check) returns exit_code
    mock_proc = _MockControlledProc([None, exit_code])
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)

    res = run_with_watchdog(["dummy_cmd"], timeout=0.001, poll_interval=0.01)
    assert res.returncode == exit_code
    assert res.succeeded is expected_succeeded
    assert res.timed_out is False
    assert res.stalled is False


@pytest.mark.parametrize("exit_code,expected_succeeded", [(0, True), (1, False)])
def test_watchdog_stall_boundary_exit_captured_by_secondary_poll(monkeypatch, exit_code, expected_succeeded):
    """If process is running at loop start but finishes with exit_code before stall breaker trips, secondary poll captures it."""
    # Sequence: first poll is None (running), second poll (at stall check) returns exit_code
    mock_proc = _MockControlledProc([None, exit_code])
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)

    res = run_with_watchdog(["dummy_cmd"], timeout=10.0, stall_timeout=0.001, poll_interval=0.01)
    assert res.returncode == exit_code
    assert res.succeeded is expected_succeeded
    assert res.stalled is False
    assert res.timed_out is False


def test_watchdog_secondary_poll_still_running_trips_timeout_and_stall(monkeypatch):
    """If secondary poll confirms process is genuinely still running, TimeoutExpired and SolverProcessStalledError are raised."""
    # 1. Total timeout path
    mock_proc_to = _MockControlledProc([None, None, None])
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc_to)
    with pytest.raises(subprocess.TimeoutExpired):
        run_with_watchdog(["dummy_cmd"], timeout=0.001, poll_interval=0.01)

    # 2. Stall timeout path
    mock_proc_stall = _MockControlledProc([None, None, None])
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc_stall)
    with pytest.raises(SolverProcessStalledError) as exc_info:
        run_with_watchdog(["dummy_cmd"], timeout=10.0, stall_timeout=0.001, poll_interval=0.01)
    assert exc_info.value.diagnostic()["category"] == "solver_stalled"


def test_watchdog_hard_timeout_takes_precedence_over_stall_when_simultaneous(monkeypatch):
    """When both hard timeout and stall timeout expire at the same check, hard timeout takes precedence."""
    mock_proc = _MockControlledProc([None, None, None])
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)

    with pytest.raises(subprocess.TimeoutExpired):
        run_with_watchdog(["dummy_cmd"], timeout=0.001, stall_timeout=0.001, poll_interval=0.01)


def test_watchdog_boundary_exit_prioritized_over_timeout_and_stall(tmp_path):
    """If process completes exactly at the boundary of timeout or stall check, normal exit takes precedence."""
    py_code = "import time, sys; time.sleep(0.15); sys.stdout.write('done\\n'); sys.exit(0)"
    cmd = [sys.executable, "-c", py_code]

    res = run_with_watchdog(
        cmd,
        cwd=tmp_path,
        timeout=10.0,
        stall_timeout=0.25,
        poll_interval=0.05,
    )
    assert res.succeeded
    assert res.returncode == 0
    assert "done" in res.stdout
    assert not res.stalled
    assert not res.timed_out


def test_watchdog_burst_output_rapid_exit_drains_cleanly(tmp_path):
    """Processes that burst large stdout/stderr and exit immediately do not cause deadlock or truncated reads."""
    py_code = (
        "import sys\n"
        "for i in range(1000):\n"
        "    sys.stdout.write(f'out line {i}\\n')\n"
        "    sys.stderr.write(f'err line {i}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.flush()\n"
        "sys.exit(0)\n"
    )
    cmd = [sys.executable, "-c", py_code]
    res = run_with_watchdog(cmd, cwd=tmp_path, timeout=5.0, stall_timeout=3.0)
    assert res.succeeded
    assert res.returncode == 0
    assert "out line 999" in res.stdout
    assert "err line 999" in res.stderr
    assert len(res.stdout.splitlines()) == 1000
    assert len(res.stderr.splitlines()) == 1000
