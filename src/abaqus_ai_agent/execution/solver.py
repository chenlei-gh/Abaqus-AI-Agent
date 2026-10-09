"""Universal Abaqus batch job solver execution engine and lifecycle controller.

Zero Tolerance for Fake Logs:
- When live Abaqus executable is present, launches native batch execution (`abaqus job=... interactive`).
- When offline or dry-running, NEVER synthesizes fake .sta, .msg, .dat, .log, or .odb files.
- Fail-closed if require_live is True and Abaqus cannot be executed.
- Parses authentic solver output diagnostics and validates genuine binary ODB existence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class AbaqusBatchJob:
    """Specification of a batch Abaqus solver execution job."""
    job_name: str
    inp_path: Path
    workdir: Path
    global_odb: Optional[Path] = None
    cpus: int = 1
    gpus: int = 0
    double_precision: bool = False
    interactive: bool = True
    timeout_seconds: int = 1800
    submodel: bool = False


@dataclass(frozen=True)
class AbaqusJobResult:
    """Outcome of an authentic Abaqus batch job execution."""
    job_name: str
    state: str  # "COMPLETED", "ABORTED", "ERROR", "TIMEOUT", "DRY_RUN"
    returncode: int
    workdir: Path
    is_live: bool
    odb_path: Optional[Path] = None
    sta_path: Optional[Path] = None
    msg_path: Optional[Path] = None
    dat_path: Optional[Path] = None
    log_path: Optional[Path] = None
    diagnostics: List[str] = field(default_factory=list)
    artifacts: Dict[str, Path] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.state == "COMPLETED" and self.is_live and self.odb_path is not None and self.odb_path.is_file()


def parse_solver_diagnostics(workdir: Path, job_name: str) -> List[str]:
    """Parse authentic .msg, .sta, and .dat logs for solver error messages and convergence issues."""
    diags: List[str] = []
    
    msg_file = workdir / f"{job_name}.msg"
    if msg_file.is_file():
        try:
            content = msg_file.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                line_upper = line.upper()
                if "***ERROR" in line_upper or "***FATAL" in line_upper:
                    diags.append(f"MSG_ERROR: {line.strip()}")
                elif "THE ANALYSIS HAS NOT BEEN COMPLETED" in line_upper:
                    diags.append("MSG: Analysis not completed")
        except Exception as e:
            diags.append(f"MSG_READ_ERR: {e}")

    sta_file = workdir / f"{job_name}.sta"
    if sta_file.is_file():
        try:
            content = sta_file.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                if "THE ANALYSIS HAS NOT BEEN COMPLETED" in line.upper():
                    diags.append("STA: Analysis not completed")
                elif "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in line.upper():
                    diags.append("STA: Analysis completed successfully")
        except Exception as e:
            diags.append(f"STA_READ_ERR: {e}")

    return diags


def is_authentic_binary_odb(path: Path) -> bool:
    """Validate that an ODB file is not empty and is not a plaintext JSON or text mock."""
    if not path.is_file():
        return False
    size = path.stat().st_size
    if size < 1024:
        return False
    try:
        header = path.read_bytes()[:32].strip()
        # Plaintext JSON / XML / YAML mocks start with {, [, <, or comment
        if header.startswith((b"{", b"[", b"<", b"#", b"--")):
            return False
        return True
    except Exception:
        return False


def find_abaqus_executable(launcher_cmd: Optional[str] = None) -> Optional[str]:
    """Find authentic Abaqus executable or return None if offline."""
    if launcher_cmd:
        if shutil.which(launcher_cmd) or os.path.isfile(launcher_cmd):
            return launcher_cmd
        return None
    cmd = shutil.which("abaqus")
    if cmd:
        return cmd
    if os.name == "nt":
        default_nt_path = Path("C:/SIMULIA/Commands/abaqus.BAT")
        if default_nt_path.is_file():
            return str(default_nt_path)
    return None


def execute_abaqus_batch_job(
    job: AbaqusBatchJob,
    *,
    require_live: bool = False,
    launcher_cmd: Optional[str] = None,
) -> AbaqusJobResult:
    """Execute an authentic Abaqus job or report strict dry-run without synthesizing fake logs.

    Contract:
    1. If live Abaqus executable is available, builds CLI and invokes subprocess.
    2. Validates returncode == 0, examines solver diagnostics, and ensures genuine binary ODB was produced.
    3. If Abaqus is unavailable:
       - If require_live is True, raises RuntimeError (Fail-Closed).
       - If require_live is False, returns state="DRY_RUN", is_live=False, without writing fake logs.
    """
    job.workdir.mkdir(parents=True, exist_ok=True)

    # Locate Abaqus CLI
    abaqus_cmd = find_abaqus_executable(launcher_cmd)

    if not abaqus_cmd:
        if require_live:
            raise RuntimeError(
                f"Abaqus solver executable not found in PATH or environment for job '{job.job_name}'. "
                f"require_live=True forbids mock/synthetic execution."
            )
        # Authentic Dry-Run: Return without writing any fake solver files
        return AbaqusJobResult(
            job_name=job.job_name,
            state="DRY_RUN",
            returncode=-1,
            workdir=job.workdir,
            is_live=False,
            diagnostics=["Solver executable 'abaqus' not found; dry-run mode (no synthetic logs generated)."],
        )

    # Build execution arguments
    cmd: List[str] = [
        abaqus_cmd,
        f"job={job.job_name}",
        f"input={job.inp_path.name}",
    ]
    if job.interactive:
        cmd.append("interactive")
    if job.cpus > 1:
        cmd.append(f"cpus={job.cpus}")
    if job.gpus > 0:
        cmd.append(f"gpus={job.gpus}")
    if job.double_precision:
        cmd.append("double")
    if job.submodel and job.global_odb:
        cmd.append(f"globalmodel={job.global_odb.name}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=job.workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=job.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return AbaqusJobResult(
            job_name=job.job_name,
            state="TIMEOUT",
            returncode=-1,
            workdir=job.workdir,
            is_live=True,
            diagnostics=[f"Solver execution timed out after {job.timeout_seconds}s"],
        )
    except Exception as exc:
        return AbaqusJobResult(
            job_name=job.job_name,
            state="ERROR",
            returncode=-1,
            workdir=job.workdir,
            is_live=True,
            diagnostics=[f"Subprocess invocation failure: {exc}"],
        )

    # Inspect generated artifacts
    odb_path = job.workdir / f"{job.job_name}.odb"
    sta_path = job.workdir / f"{job.job_name}.sta"
    msg_path = job.workdir / f"{job.job_name}.msg"
    dat_path = job.workdir / f"{job.job_name}.dat"
    log_path = job.workdir / f"{job.job_name}.log"

    diags = parse_solver_diagnostics(job.workdir, job.job_name)

    artifacts: Dict[str, Path] = {}
    for p, name in [
        (odb_path, "odb"),
        (sta_path, "sta"),
        (msg_path, "msg"),
        (dat_path, "dat"),
        (log_path, "log"),
    ]:
        if p.is_file():
            artifacts[name] = p

    # Evaluate authentic job outcome
    if proc.returncode != 0:
        state = "ABORTED"
        diags.append(f"Solver process exited with non-zero returncode {proc.returncode}")
    elif not odb_path.is_file() or not is_authentic_binary_odb(odb_path):
        state = "ERROR"
        diags.append("Solver completed returncode 0 but did not produce a valid binary .odb artifact")
    elif any("MSG: Analysis not completed" in d or "STA: Analysis not completed" in d for d in diags):
        state = "ABORTED"
    else:
        state = "COMPLETED"

    return AbaqusJobResult(
        job_name=job.job_name,
        state=state,
        returncode=proc.returncode,
        workdir=job.workdir,
        is_live=True,
        odb_path=odb_path if (odb_path.is_file() and is_authentic_binary_odb(odb_path)) else None,
        sta_path=sta_path if sta_path.is_file() else None,
        msg_path=msg_path if msg_path.is_file() else None,
        dat_path=dat_path if dat_path.is_file() else None,
        log_path=log_path if log_path.is_file() else None,
        diagnostics=diags,
        artifacts=artifacts,
    )
