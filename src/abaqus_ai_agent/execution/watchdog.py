"""Subprocess activity watchdog and stall circuit breaker for Abaqus solver processes.

REQ-P1-056:
- Monitors live process output streams (stdout, stderr) and working directory artifacts (.sta, .msg, .log, .odb, .dat).
- Detects process stalls when a child process produces zero output and zero file modifications for stall_timeout seconds (default 120s).
- Note: stall_timeout is a configurable engineering heuristic policy parameter, not an intrinsic physical or solver constant. Long-running, silent solver jobs should configure a larger threshold or additional heartbeat files.
- Windows: Uses `taskkill /F /T /PID <pid>` to terminate the entire process tree (killing standard.exe / explicit.exe grandchild processes).
- Non-Windows: Uses process group signal SIGKILL.
- Asynchronous daemon threads consume stdout/stderr to prevent Windows pipe deadlocks.
- Raises typed `SolverProcessStalledError` on stall detection.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union


DEFAULT_STALL_TIMEOUT: float = 120.0
DEFAULT_TOTAL_TIMEOUT: float = 3600.0
DEFAULT_MONITORED_EXTENSIONS: Tuple[str, ...] = (
    ".sta", ".msg", ".log", ".odb", ".dat", ".sim", ".fil", ".prt", ".mdl"
)


class SolverProcessStalledError(RuntimeError):
    """Raised when an Abaqus solver or batch process stalls without stream or disk activity."""

    def __init__(
        self,
        message: str,
        *,
        cmd: Sequence[str],
        workdir: Optional[str] = None,
        stall_duration: float = 0.0,
        stall_timeout: float = DEFAULT_STALL_TIMEOUT,
        total_duration: float = 0.0,
        stdout: str = "",
        stderr: str = "",
        monitored_artifacts: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.cmd = tuple(cmd) if isinstance(cmd, (list, tuple)) else (str(cmd),)
        self.workdir = workdir
        self.stall_duration = stall_duration
        self.stall_timeout = stall_timeout
        self.total_duration = total_duration
        self.stdout = stdout
        self.stderr = stderr
        self.monitored_artifacts = monitored_artifacts or {}

    @property
    def last_stdout_line(self) -> str:
        lines = [ln.strip() for ln in self.stdout.splitlines() if ln.strip()]
        return lines[-1] if lines else ""

    @property
    def last_stderr_line(self) -> str:
        lines = [ln.strip() for ln in self.stderr.splitlines() if ln.strip()]
        return lines[-1] if lines else ""

    def diagnostic(self) -> Dict[str, Any]:
        return {
            "category": "solver_stalled",
            "message": str(self),
            "stall_duration": self.stall_duration,
            "stall_timeout": self.stall_timeout,
            "total_duration": self.total_duration,
            "last_stdout_line": self.last_stdout_line,
            "last_stderr_line": self.last_stderr_line,
            "workdir": self.workdir,
            "monitored_artifacts": self.monitored_artifacts,
        }


@dataclass(frozen=True)
class WatchedProcessResult:
    """Outcome of a process executed under watchdog surveillance."""
    command: Tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration: float
    workdir: Optional[str] = None
    stalled: bool = False
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.stalled and not self.timed_out


def kill_process_tree(pid: int) -> None:
    """Terminate the process and all its descendants to prevent orphaned solver processes."""
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except Exception:
            pass
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def _scan_monitored_artifacts(
    workdir_path: Path,
    monitored_extensions: Set[str],
) -> Dict[str, Tuple[float, int]]:
    """Scan the working directory for monitored files and return {filename: (mtime, size)}."""
    snapshot: Dict[str, Tuple[float, int]] = {}
    if not workdir_path.is_dir():
        return snapshot
    try:
        for entry in os.scandir(str(workdir_path)):
            try:
                if entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in monitored_extensions:
                        st = entry.stat()
                        snapshot[entry.name] = (st.st_mtime, st.st_size)
            except OSError:
                continue
    except OSError:
        pass
    return snapshot


def run_with_watchdog(
    cmd: Sequence[str],
    *,
    cwd: Optional[Union[str, Path]] = None,
    timeout: Optional[float] = DEFAULT_TOTAL_TIMEOUT,
    stall_timeout: Optional[float] = DEFAULT_STALL_TIMEOUT,
    poll_interval: float = 0.25,
    monitored_extensions: Sequence[str] = DEFAULT_MONITORED_EXTENSIONS,
    env: Optional[Dict[str, str]] = None,
    shell: bool = False,
) -> WatchedProcessResult:
    """Execute a subprocess under activity and stall watchdog surveillance.

    Args:
        cmd: Command and arguments sequence.
        cwd: Working directory for process execution and file monitoring.
        timeout: Hard timeout in seconds (None or <= 0 disables hard timeout).
        stall_timeout: Idle duration threshold before triggering stall breaker.
        poll_interval: Interval between monitoring checks in seconds.
        monitored_extensions: File extensions to watch for heartbeat in cwd.
        env: Environment variables.
        shell: Whether to invoke via system shell.

    Returns:
        WatchedProcessResult on completion.

    Raises:
        SolverProcessStalledError: If the process stalls for `stall_timeout` seconds.
        subprocess.TimeoutExpired: If total runtime exceeds `timeout`.
    """
    effective_cmd = tuple(str(x) for x in cmd)
    workdir_path = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    workdir_path.mkdir(parents=True, exist_ok=True)

    monitored_ext_set = {e.lower() for e in monitored_extensions}
    current_artifacts = _scan_monitored_artifacts(workdir_path, monitored_ext_set)

    start_time = time.monotonic()
    lock = threading.Lock()
    last_activity_time = [start_time]
    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def _reader(stream, container: List[str]):
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                with lock:
                    container.append(line)
                    last_activity_time[0] = time.monotonic()
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(workdir_path),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "shell": shell,
    }
    if env is not None:
        popen_kwargs["env"] = env

    if os.name != "nt" and not shell:
        # Create a new process group on POSIX to enable clean tree killing
        popen_kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(effective_cmd, **popen_kwargs)

    t_stdout = threading.Thread(target=_reader, args=(proc.stdout, stdout_lines), daemon=True)
    t_stderr = threading.Thread(target=_reader, args=(proc.stderr, stderr_lines), daemon=True)
    t_stdout.start()
    t_stderr.start()

    effective_stall_timeout = float(stall_timeout) if (stall_timeout and stall_timeout > 0) else None
    effective_total_timeout = float(timeout) if (timeout and timeout > 0) else None

    stalled = False
    timed_out = False
    return_code: Optional[int] = None

    try:
        while True:
            # 1. Check if process has terminated
            return_code = proc.poll()
            if return_code is not None:
                break

            now = time.monotonic()

            # 2. Check total hard timeout
            if effective_total_timeout and (now - start_time) >= effective_total_timeout:
                return_code = proc.poll()
                if return_code is not None:
                    break
                timed_out = True
                break

            # 3. Check disk file activity in workdir
            new_artifacts = _scan_monitored_artifacts(workdir_path, monitored_ext_set)
            disk_changed = False
            for fname, (mtime, size) in new_artifacts.items():
                old = current_artifacts.get(fname)
                if old is None or mtime > old[0] or size != old[1]:
                    disk_changed = True
                    break

            if disk_changed:
                current_artifacts = new_artifacts
                with lock:
                    last_activity_time[0] = now

            # 4. Check stall inactivity
            with lock:
                idle_duration = now - last_activity_time[0]

            if effective_stall_timeout and idle_duration >= effective_stall_timeout:
                return_code = proc.poll()
                if return_code is not None:
                    break
                stalled = True
                break

            time.sleep(poll_interval)

    finally:
        if stalled or timed_out:
            kill_process_tree(proc.pid)
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                pass

        # Wait briefly for reader threads to consume remaining buffered output
        t_stdout.join(timeout=1.0)
        t_stderr.join(timeout=1.0)

    total_duration = time.monotonic() - start_time
    captured_stdout = "".join(stdout_lines)
    captured_stderr = "".join(stderr_lines)

    if stalled:
        with lock:
            final_stall_duration = time.monotonic() - last_activity_time[0]
        raise SolverProcessStalledError(
            f"Process stalled for {final_stall_duration:.1f}s exceeding threshold {effective_stall_timeout:.1f}s "
            f"without stream output or disk activity in {workdir_path}",
            cmd=effective_cmd,
            workdir=str(workdir_path),
            stall_duration=final_stall_duration,
            stall_timeout=effective_stall_timeout or DEFAULT_STALL_TIMEOUT,
            total_duration=total_duration,
            stdout=captured_stdout,
            stderr=captured_stderr,
            monitored_artifacts={k: {"mtime": v[0], "size": v[1]} for k, v in current_artifacts.items()},
        )

    if timed_out:
        raise subprocess.TimeoutExpired(
            effective_cmd,
            timeout=effective_total_timeout,
            output=captured_stdout,
            stderr=captured_stderr,
        )

    return WatchedProcessResult(
        command=effective_cmd,
        returncode=return_code if return_code is not None else -1,
        stdout=captured_stdout,
        stderr=captured_stderr,
        duration=total_duration,
        workdir=str(workdir_path),
        stalled=False,
        timed_out=False,
    )
