import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Tuple


def resolve_default_launcher(launcher: str = "abaqus") -> str:
    """Resolve a robust default Abaqus launcher path, especially on Windows."""
    if os.environ.get("ABAQUS_BAT"):
        return os.environ["ABAQUS_BAT"]
    if os.environ.get("ABAQUS_COMMAND"):
        return os.environ["ABAQUS_COMMAND"]

    if os.name == "nt" and launcher in ("abaqus", "abaqus.bat"):
        # Check standard SIMULIA paths first
        candidate = r"C:\SIMULIA\Commands\abaqus.bat"
        if os.path.exists(candidate):
            return candidate
        which_bat = shutil.which("abaqus.bat")
        if which_bat:
            return which_bat
        which_cmd = shutil.which("abaqus")
        if which_cmd:
            return which_cmd

    return launcher


@dataclass(frozen=True)
class BatchResult:
    """Host process result for a batch command.

    This object carries process execution facts only. ``succeeded`` describes
    the host process, not an Abaqus solve; callers must use solver terminal
    evidence before treating a job as completed or its ODB as valid.
    """
    command: Tuple[str, ...]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    workdir: Optional[str] = None
    #: Wall-clock seconds spent in the watched process, or ``None`` when the caller
    #: constructed the result without a measurement (tests, stubs, hand-built fakes).
    #: ``None`` means "not measured", never "took no time": a real run always has a
    #: positive duration, and a fast run still reports a small float. This is
    #: ``WatchedProcessResult.duration`` passed through, not a re-measurement.
    duration: Optional[float] = None
    #: False when the launcher exited with rc=0 but the workdir kept changing
    #: beyond the settle budget: on Windows the CAE kernel can outlive the
    #: launcher, so an early rc=0 is not terminal evidence. Callers that gate
    #: on real completion must require ``settled`` in addition to
    #: ``succeeded``. Defaults to True so hand-built results in tests keep
    #: their previous meaning.
    settled: bool = True
    settle_note: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        """Process-level success only (exit code zero); never solver success."""
        return self.return_code == 0

    @property
    def returncode(self) -> int:
        return self.return_code

    def __getitem__(self, key: str) -> Any:
        if key in ("returncode", "return_code"):
            return self.return_code
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in ("returncode", "return_code"):
            return self.return_code
        if hasattr(self, key):
            return getattr(self, key)
        return default


def _dir_snapshot(path):
    snap = {}
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    st = entry.stat()
                    snap[entry.name] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    pass
    except OSError:
        pass
    return snap


def await_quiescence(workdir, quiet_period=1.5, timeout=30.0, poll=0.5):
    """Wait until no file in ``workdir`` changes for ``quiet_period`` seconds.

    The watched launcher process can exit before the detached CAE kernel has
    flushed its artifacts. This bounded poll is the host-side terminal check
    for that window: it returns ``(settled, note)`` where ``settled=False``
    means the workdir was still changing when the budget expired, i.e. there
    is no terminal evidence either way and callers must not treat the run as
    finished.
    """
    start = time.monotonic()
    last = _dir_snapshot(workdir)
    last_change = start
    while True:
        time.sleep(poll)
        current = _dir_snapshot(workdir)
        now = time.monotonic()
        if current != last:
            last = current
            last_change = now
        if now - last_change >= quiet_period:
            return True, None
        if now - start >= timeout:
            return False, "workdir still changing %.1fs after launcher exit" % (now - start)


class BatchExecutor:
    """Thin host-side adapter for Abaqus batch/noGUI execution.

    It deliberately does not pretend to be a live AbaqusExecutor. Use the
    live executor for model mutations that require a persistent CAE session.
    """

    def __init__(self, launcher="abaqus", workdir=None, timeout=3600, stall_timeout=120,
                 settle_timeout=30.0):
        self.launcher = launcher
        self.workdir = workdir
        self.timeout = timeout
        self.stall_timeout = stall_timeout
        # Post-exit artifact settling budget. 0 disables the quiescence wait.
        self.settle_timeout = settle_timeout

    @property
    def resolved_launcher(self) -> str:
        return resolve_default_launcher(self.launcher)

    def _run(self, args, timeout=None, job_name=None, adaptive_heartbeat=False):
        raw_cmd = [str(x) for x in args]
        if raw_cmd and raw_cmd[0] == self.launcher:
            raw_cmd[0] = self.resolved_launcher
        command = tuple(raw_cmd)
        effective_workdir = self.workdir
        should_isolate = False
        if not effective_workdir:
            should_isolate = True
        else:
            cand = os.path.abspath(effective_workdir)
            if os.path.isfile(os.path.join(cand, "pyproject.toml")) and os.path.isdir(os.path.join(cand, "src")):
                should_isolate = True
            else:
                norm_parts = os.path.normpath(cand).split(os.sep)
                if any(p in ("machine_validation", "validation_assets", "test_assets", "src", "legacy_job_artifacts") for p in norm_parts):
                    should_isolate = True

        if should_isolate:
            from ..paths import resolve_runs_root
            effective_workdir = os.path.abspath(os.path.join(str(resolve_runs_root()), f"batch_{uuid.uuid4().hex[:8]}"))
            os.makedirs(effective_workdir, exist_ok=True)
            self.workdir = effective_workdir
        else:
            effective_workdir = os.path.abspath(effective_workdir)
            os.makedirs(effective_workdir, exist_ok=True)
        from .watchdog import run_with_watchdog
        eff_stall = getattr(self, "stall_timeout", 120)
        proc = run_with_watchdog(
            command,
            cwd=effective_workdir,
            timeout=timeout or self.timeout,
            stall_timeout=eff_stall,
            adaptive_heartbeat=adaptive_heartbeat,
            job_name=job_name,
        )
        settled, settle_note = True, None
        if proc.returncode == 0 and self.settle_timeout and self.settle_timeout > 0:
            settled, settle_note = await_quiescence(
                effective_workdir, timeout=self.settle_timeout
            )
        return BatchResult(command, proc.returncode, proc.stdout, proc.stderr,
                           effective_workdir, proc.duration,
                           settled=settled, settle_note=settle_note)

    def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
        """Run a solve from an input deck.

        ``interactive`` is passed explicitly: the Abaqus execution procedure runs
        ``job=`` jobs in ``background`` by default, and a background submission
        returns as soon as the job is handed off, leaving the watchdog watching a
        launcher that already exited. ``interactive`` is what the execution
        procedure documents as running the job in the foreground, with the log
        (Standard) or status and log (Explicit) going to the screen. This is the
        same option ``solver.execute_abaqus_batch_job`` already passes; the two
        solve paths must not disagree about it.
        """
        path = os.path.abspath(input_path)
        name = job_name or os.path.splitext(os.path.basename(path))[0]
        orig_workdir = self.workdir
        try:
            if workdir:
                self.workdir = str(workdir)
            return self._run((self.launcher, "job=%s" % name, "input=%s" % path,
                              "interactive"),
                             timeout=timeout, job_name=name, adaptive_heartbeat=True)
        finally:
            self.workdir = orig_workdir

    def run_nogui(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "cae", "noGUI=%s" % path),
                         timeout=timeout)

    def run_python(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "python", path), timeout=timeout)
