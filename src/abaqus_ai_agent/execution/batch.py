import os
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class BatchResult:
    command: Tuple[str, ...]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    workdir: Optional[str] = None

    @property
    def succeeded(self):
        return self.return_code == 0


class BatchExecutor:
    """Thin host-side adapter for Abaqus batch/noGUI execution.

    It deliberately does not pretend to be a live AbaqusExecutor. Use the
    live executor for model mutations that require a persistent CAE session.
    """

    def __init__(self, launcher="abaqus", workdir=None, timeout=3600):
        self.launcher = launcher
        self.workdir = workdir
        self.timeout = timeout

    def _run(self, args, timeout=None):
        command = tuple(str(x) for x in args)
        proc = subprocess.run(
            command, cwd=self.workdir, capture_output=True, text=True,
            timeout=timeout or self.timeout)
        return BatchResult(command, proc.returncode, proc.stdout, proc.stderr,
                           os.path.abspath(self.workdir) if self.workdir else None)

    def run_input(self, input_path, job_name=None, timeout=None):
        path = os.path.abspath(input_path)
        name = job_name or os.path.splitext(os.path.basename(path))[0]
        return self._run((self.launcher, "job=%s" % name, "input=%s" % path),
                         timeout=timeout)

    def run_nogui(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "cae", "noGUI=%s" % path),
                         timeout=timeout)

    def run_python(self, script_path, timeout=None):
        path = os.path.abspath(script_path)
        return self._run((self.launcher, "python", path), timeout=timeout)
