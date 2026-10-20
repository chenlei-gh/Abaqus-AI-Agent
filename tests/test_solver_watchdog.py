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

    py_code = (
        "import subprocess, sys, time, pathlib\n"
        "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
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
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, gc_pid)
        if handle:
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            # STILL_ACTIVE = 259
            assert exit_code.value != 259
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(gc_pid, 0)


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
