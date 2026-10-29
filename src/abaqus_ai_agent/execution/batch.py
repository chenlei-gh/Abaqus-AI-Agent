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
    #: Which evidence produced ``settled``. ``"script_completed"`` means the
    #: kernel itself recorded that the noGUI script reached its end (the signal
    #: the execution procedure documents); ``"script_blocked"`` means the script
    #: stopped deliberately before finishing (pre-solve approval gate);
    #: ``"quiescence_only"`` means no script-side signal was requested and only
    #: workdir quiescence was checked; ``"none"`` means no post-exit check ran.
    #: Callers must not read ``"quiescence_only"`` as proof that the script
    #: completed.
    completion_evidence: str = "none"

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


def await_script_completion(marker_path, timeout=3600.0, poll=1.0):
    """Wait for the CAE kernel's own end-of-script evidence.

    The execution procedure documents that ``noGUI`` "runs the commands in the
    file and exits upon their completion" and that the kernel terminates when
    the script finishes. On this host the launcher returns before the kernel
    terminates, so the launcher's exit code is not that completion event. A
    sentinel written by the kernel as its last action is: it exists only if the
    script actually reached its end, and it survives the launcher's exit.

    Returns ``(state, note)`` where ``state`` is the sentinel's recorded outcome
    (``"completed"`` for a full run, ``"blocked"`` for a deliberate early stop
    such as the pre-solve approval gate) or ``None`` when the budget expired.
    ``None`` means there is no evidence the script finished, so callers must not
    treat the run as finished. The outcome is read from the file rather than
    assumed, because a blocked run also ends deliberately but is not a completed
    delivery -- conflating the two would report an approval stop as a result.
    """
    path = Path(marker_path)
    budget = float(timeout) if timeout and float(timeout) > 0 else 0.0
    start = time.monotonic()
    while True:
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace").strip(), None
            except OSError:
                pass
        elapsed = time.monotonic() - start
        if elapsed >= budget:
            return None, ("script completion sentinel %r did not appear within "
                          "%.1fs after launcher exit" % (path.name, elapsed))
        time.sleep(poll)


def completion_sentinel_code(marker_path):
    """Return the trailing snippet that makes a noGUI script self-report.

    Append this to the very end of a generated CAE script and pass the same
    path as ``run_nogui(completion_sentinel=...)``. It must be last: the
    documented contract is that the script runs to completion, so only reaching
    this statement proves it did. A script that raises never writes it, which is
    the intent -- an aborted script is not a completed one.
    """
    return (
        "\n# AIAgent: kernel-side completion evidence. The launcher on this host\n"
        "# returns before the kernel terminates, so this write -- not the exit\n"
        "# code -- is the documented end-of-script signal.\n"
        "_ai_done = open(%r, 'w')\n"
        "_ai_done.write('completed')\n"
        "_ai_done.close()\n" % str(marker_path)
    )


def blocked_sentinel_code(marker_path):
    """Return a snippet recording a deliberate early stop before the tail.

    Used by scripts that can stop on purpose (e.g. the pre-solve approval gate)
    and then raise. Without this the command would look like an abnormal exit
    and the caller would wait out the whole solve budget for a sentinel that by
    design will never be written.
    """
    return (
        "_ai_stop = open(%r, 'w')\n"
        "_ai_stop.write('blocked')\n"
        "_ai_stop.close()\n" % str(marker_path)
    )


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

    def _run(self, args, timeout=None, job_name=None, adaptive_heartbeat=False,
             completion_sentinel=None, completion_timeout=None):
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
            from ..paths import is_agent_or_repo_launch_dir
            if is_agent_or_repo_launch_dir(cand):
                should_isolate = True
            elif os.path.isfile(os.path.join(cand, "pyproject.toml")) and os.path.isdir(os.path.join(cand, "src")):
                should_isolate = True
            else:
                norm_parts = os.path.normpath(cand).split(os.sep)
                if any(p in ("machine_validation", "validation_assets", "test_assets", "src", "legacy_job_artifacts") for p in norm_parts):
                    should_isolate = True

        if should_isolate:
            from ..paths import resolve_project_workdir
            effective_workdir = os.path.abspath(os.path.join(str(resolve_project_workdir()), f"batch_{uuid.uuid4().hex[:8]}"))
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
        evidence = "none"
        if completion_sentinel and proc.returncode == 0:
            # The script-side signal outlives the launcher, so it is waited for
            # on the caller's solve budget (not the short quiescence window):
            # a correct multi-minute run must not be reported as unsettled just
            # because the launcher handed off early.
            budget = completion_timeout if completion_timeout is not None else timeout
            state, note = await_script_completion(
                completion_sentinel,
                timeout=budget if budget is not None else self.timeout,
            )
            if state is None:
                settled, settle_note = False, note
            else:
                evidence = "script_" + state
        if settled and proc.returncode == 0 and self.settle_timeout and self.settle_timeout > 0:
            quiescent, quiescence_note = await_quiescence(
                effective_workdir, timeout=self.settle_timeout
            )
            if not quiescent:
                settled, settle_note = False, quiescence_note
            elif evidence == "none":
                evidence = "quiescence_only"
        return BatchResult(command, proc.returncode, proc.stdout, proc.stderr,
                           effective_workdir, proc.duration,
                           settled=settled, settle_note=settle_note,
                           completion_evidence=evidence)

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

    def run_nogui(self, script_path, timeout=None, completion_sentinel=None):
        """Run a script without the CAE GUI.

        ``noGUI`` is the one CAE path with no foreground option, and adding one
        is not possible: the CAE execution procedure states that with ``noGUI``
        "Abaqus/CAE ignores any other command line options that you provide".
        The documented completion event is therefore the script finishing (the
        kernel terminates afterwards), not the launcher exiting -- and on this
        host the launcher can exit first.

        Pass ``completion_sentinel`` (see ``completion_sentinel_code``) to wait
        for the kernel's own end-of-script evidence, bounded by ``timeout``.
        Without it the call keeps its previous contract: only workdir
        quiescence is checked, and ``completion_evidence`` says so.

        An existing ``.py`` that fails ``compile()`` is returned as a structured
        syntax failure and does not start the launcher. A missing path is not a
        syntax verdict: that contract stays with the watchdog.
        """
        path = os.path.abspath(script_path)
        syntax_failure = self._syntax_gate(path)
        if syntax_failure is not None:
            return syntax_failure
        return self._run((self.launcher, "cae", "noGUI=%s" % path),
                         timeout=timeout,
                         completion_sentinel=completion_sentinel)

    def _syntax_gate(self, path):
        """Return a failed BatchResult, or None when the launcher may start."""
        try:
            from .script_syntax import check_script_file
            from ..telemetry.correction import record_correction_event
        except Exception:
            return None
        try:
            error = check_script_file(path)
        except Exception:
            return None
        if error is None:
            return None
        try:
            record_correction_event(
                "syntax", "script_syntax_gate",
                message=error.format(), source=error.path, first_pass=False,
                metadata=error.to_dict(), workdir=self.workdir,
            )
        except Exception:
            pass
        detail = error.format()
        return BatchResult(
            command=(self.launcher, "cae", "noGUI=%s" % path),
            return_code=2,
            stdout="",
            stderr=detail,
            workdir=self.workdir,
            duration=0.0,
            settled=True,
            settle_note=detail,
            completion_evidence="syntax_blocked",
        )

    def run_python(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "python", path), timeout=timeout)
