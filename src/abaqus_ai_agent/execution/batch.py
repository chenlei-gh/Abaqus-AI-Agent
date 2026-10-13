import os
from pathlib import Path
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple


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
    command: Tuple[str, ...]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    workdir: Optional[str] = None

    @property
    def succeeded(self) -> bool:
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


class BatchExecutor:
    """Thin host-side adapter for Abaqus batch/noGUI execution.

    It deliberately does not pretend to be a live AbaqusExecutor. Use the
    live executor for model mutations that require a persistent CAE session.
    """

    def __init__(self, launcher="abaqus", workdir=None, timeout=3600):
        self.launcher = launcher
        self.workdir = workdir
        self.timeout = timeout

    @property
    def resolved_launcher(self) -> str:
        return resolve_default_launcher(self.launcher)

    def _run(self, args, timeout=None):
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
        proc = subprocess.run(
            command, cwd=effective_workdir, capture_output=True, text=True,
            timeout=timeout or self.timeout)
        return BatchResult(command, proc.returncode, proc.stdout, proc.stderr,
                           effective_workdir)

    def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
        path = os.path.abspath(input_path)
        name = job_name or os.path.splitext(os.path.basename(path))[0]
        orig_workdir = self.workdir
        try:
            if workdir:
                self.workdir = str(workdir)
            return self._run((self.launcher, "job=%s" % name, "input=%s" % path),
                             timeout=timeout)
        finally:
            self.workdir = orig_workdir

    def run_nogui(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "cae", "noGUI=%s" % path),
                         timeout=timeout)

    def run_python(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "python", path), timeout=timeout)
