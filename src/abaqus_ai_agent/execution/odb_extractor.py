"""Universal Headless ODB Result Extractor & Evidence Lineage Binding Engine.

Executes authentic finite element result extractions directly from binary .odb
databases using native Abaqus Python (headless `abaqus python <script.py>`),
without requiring a GUI or persistent CAE session.

Contract & Fail-Closed Discipline:
1. Reuses authentic extraction script generation from `execution.results` and `execution.odb`.
2. Validates genuine binary ODB presence; immediately blocks on corrupt, empty, or mock JSON files.
3. Manages independent subprocess execution (`abaqus python`) with strict timeouts and error classification.
4. Enforces strict causal lineage binding: embeds `run_id`, `input_hash`, `odb_path`,
   `odb_sha256`, and verified physical units into every `ResultExtraction` and `Evidence` record.
5. Strictly zero tolerance for synthetic fallback: missing fields, corrupt ODBs, or process
   failures raise explicit typed exceptions and NEVER return synthetic benchmark constants.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from .client import AbaqusExecutor
from .results import extract_requirement
from .solver import find_abaqus_executable, is_authentic_binary_odb
from ..contracts.results import (
    ResultExtraction,
    ResultRequirement,
    requirements_from_criteria,
)
from ..evidence.model import Evidence


class OdbExtractionError(RuntimeError):
    """Base exception for all authentic ODB extraction failures."""
    pass


class OdbFileNotFoundError(OdbExtractionError):
    """Raised when the requested ODB file does not exist on disk."""
    pass


class OdbCorruptOrInvalidError(OdbExtractionError):
    """Raised when the target file is not an authentic binary ODB (e.g. empty, JSON mock)."""
    pass


class AbaqusLauncherNotFoundError(OdbExtractionError):
    """Raised when no authentic Abaqus executable can be resolved to run abaqus python."""
    pass


class ExtractionExecutionError(OdbExtractionError):
    """Raised when the abaqus python extraction process times out or exits with an error."""
    pass


class ExtractionFieldNotFoundError(OdbExtractionError):
    """Raised when requested steps, frames, fields, or history outputs are missing from the ODB."""
    pass


@dataclass(frozen=True)
class OdbExtractionReport:
    """Complete container of authentically extracted physical results and causal evidence."""
    run_id: str
    input_hash: str
    odb_path: Path
    odb_sha256: str
    extractions: Tuple[ResultExtraction, ...]
    metrics: Dict[str, float]
    evidence: Tuple[Evidence, ...]
    timestamp: float = field(default_factory=time.time)

    def get_extraction(self, value_key: str) -> Optional[ResultExtraction]:
        for ext in self.extractions:
            req = ext.requirement
            if req.value_key == value_key or req.name == value_key:
                return ext
        return None


class HeadlessAbaqusPythonExecutor(AbaqusExecutor):
    """Host-side adapter that executes Python snippets inside native Abaqus Python.

    Invokes `abaqus python <temp_script.py>` in a controlled subprocess,
    capturing stdout JSON envelopes and mapping solver tracebacks to typed exceptions.
    Supports dependency-injected `custom_runner` for hermetic unit testing.
    """

    def __init__(
        self,
        launcher_cmd: Optional[str] = None,
        workdir: Optional[Union[str, Path]] = None,
        timeout: int = 120,
        custom_runner: Optional[Callable[[str], Any]] = None,
    ):
        self.launcher_cmd = launcher_cmd
        self.workdir = Path(workdir).resolve() if workdir else Path(".").resolve()
        self.timeout = timeout
        self.custom_runner = custom_runner

    def execute(self, code: str, timeout: Optional[int] = None) -> Any:
        if self.custom_runner is not None:
            return self.custom_runner(code)

        effective_timeout = timeout or self.timeout
        resolved_launcher = find_abaqus_executable(self.launcher_cmd)
        if not resolved_launcher:
            raise AbaqusLauncherNotFoundError(
                f"Abaqus executable not found (launcher_cmd={self.launcher_cmd!r}). "
                "Authentic ODB extraction requires an authentic Abaqus installation."
            )

        self.workdir.mkdir(parents=True, exist_ok=True)
        script_id = uuid.uuid4().hex[:12]
        script_file = self.workdir / f"_odb_extract_{script_id}.py"

        try:
            script_file.write_text(code, encoding="utf-8")
            cmd = [resolved_launcher, "python", str(script_file.name)]
            use_shell = (os.name == "nt")

            proc = subprocess.run(
                cmd,
                cwd=str(self.workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=effective_timeout,
                shell=use_shell,
            )

            if proc.returncode != 0:
                err_msg = (
                    f"Abaqus Python extraction failed with returncode {proc.returncode}.\n"
                    f"STDOUT:\n{proc.stdout.strip()}\n"
                    f"STDERR:\n{proc.stderr.strip()}"
                )
                if "KeyError" in proc.stderr or "KeyError" in proc.stdout:
                    raise ExtractionFieldNotFoundError(err_msg)
                raise ExtractionExecutionError(err_msg)

            raw_out = proc.stdout.strip()
            if not raw_out:
                if proc.stderr:
                    raise ExtractionExecutionError(f"Abaqus Python returned empty output. STDERR:\n{proc.stderr}")
                raise ExtractionExecutionError("Abaqus Python extraction produced no output.")

            # Decode JSON payload from stdout lines
            last_line = raw_out.splitlines()[-1].strip()
            try:
                return json.loads(last_line)
            except Exception:
                # If last line is not pure JSON, attempt to evaluate or return payload string
                return raw_out

        except subprocess.TimeoutExpired as exc:
            raise ExtractionExecutionError(
                f"Headless Abaqus Python extraction timed out after {effective_timeout}s: {exc}"
            )
        finally:
            try:
                if script_file.exists():
                    script_file.unlink()
            except Exception:
                pass


def compute_file_sha256(path: Union[str, Path]) -> str:
    """Compute deterministic SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_odb_results(
    odb_path: Union[str, Path],
    requirements_or_criteria: Sequence[Union[ResultRequirement, Dict[str, Any]]],
    *,
    run_id: str,
    input_hash: str,
    workdir: Optional[Union[str, Path]] = None,
    launcher_cmd: Optional[str] = None,
    custom_runner: Optional[Callable[[str], Any]] = None,
    timeout_seconds: int = 120,
) -> OdbExtractionReport:
    """Authentically extract finite element results from an ODB with full causal binding.

    Parameters:
    - odb_path: Path to target .odb database.
    - requirements_or_criteria: List of ResultRequirement objects or criteria dictionaries.
    - run_id: Authoritative execution run identifier for causal binding.
    - input_hash: Authoritative SHA-256 digest of the INP model input file.
    - workdir: Scratch directory for temporary extraction scripts.
    - launcher_cmd: Optional path to custom Abaqus launcher command.
    - custom_runner: Optional hook for in-memory / testing executor.
    - timeout_seconds: Maximum time allowed per extraction operation.

    Returns:
    - OdbExtractionReport with validated metrics, extractions, and evidence objects.

    Raises:
    - OdbFileNotFoundError: If the ODB file does not exist.
    - OdbCorruptOrInvalidError: If the ODB is empty or not authentic binary format.
    - OdbExtractionError: If any requirement extraction fails (Fail-Closed).
    """
    odb = Path(odb_path).resolve()
    if not odb.is_file():
        raise OdbFileNotFoundError(f"Target ODB file does not exist: {odb}")

    if not is_authentic_binary_odb(odb):
        raise OdbCorruptOrInvalidError(
            f"Target file {odb} is not an authentic binary ODB. "
            "Empty files, plaintext JSON, and synthetic mocks are strictly prohibited."
        )

    odb_sha256 = compute_file_sha256(odb)
    eff_workdir = Path(workdir).resolve() if workdir else odb.parent

    # Normalize inputs to typed ResultRequirement objects
    normalized_reqs: List[ResultRequirement] = []
    criteria_to_convert: List[Dict[str, Any]] = []

    for item in requirements_or_criteria:
        if isinstance(item, ResultRequirement):
            normalized_reqs.append(item)
        elif isinstance(item, dict):
            criteria_to_convert.append(item)
        else:
            raise TypeError(f"Unsupported requirement specification type: {type(item)}")

    if criteria_to_convert:
        converted = requirements_from_criteria(criteria_to_convert)
        normalized_reqs.extend(converted)

    if not normalized_reqs:
        return OdbExtractionReport(
            run_id=run_id,
            input_hash=input_hash,
            odb_path=odb,
            odb_sha256=odb_sha256,
            extractions=(),
            metrics={},
            evidence=(),
        )

    executor = HeadlessAbaqusPythonExecutor(
        launcher_cmd=launcher_cmd,
        workdir=eff_workdir,
        timeout=timeout_seconds,
        custom_runner=custom_runner,
    )

    extractions: List[ResultExtraction] = []
    metrics: Dict[str, float] = {}
    evidence_list: List[Evidence] = []

    # Support high-level extraction delegator and testing patches
    from .results import extract_requirements
    source_items: List[ResultExtraction] = []
    try:
        candidate_extractions, _ = extract_requirements(executor, str(odb), requirements_or_criteria)
        if candidate_extractions:
            source_items = list(candidate_extractions)
    except Exception:
        source_items = []

    if not source_items:
        for req in normalized_reqs:
            try:
                extraction = extract_requirement(executor, str(odb), req)
                source_items.append(extraction)
            except Exception as exc:
                raise OdbExtractionError(
                    f"Fail-closed: Failed to extract authentic result for {req.value_key} from {odb}: {exc}"
                ) from exc

    for extraction in source_items:
        req = extraction.requirement
        val = extraction.value
        if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
            raise OdbExtractionError(
                f"Extracted non-numeric or infinite value ({val}) for {req.value_key}."
            )

        # Causal lineage binding: enrich extraction locator with execution and ODB provenance
        bound_locator = dict(extraction.locator or {})
        bound_locator["run_id"] = run_id
        bound_locator["input_hash"] = input_hash
        bound_locator["odb_path"] = str(odb)
        bound_locator["odb_sha256"] = odb_sha256
        bound_locator["extraction_timestamp"] = time.time()

        # Enrich evidence records with provenance
        bound_evidences: List[Evidence] = []
        for ev in extraction.evidence:
            ev_meta = dict(getattr(ev, "metadata", {}) or {})
            ev_meta["run_id"] = run_id
            ev_meta["input_hash"] = input_hash
            ev_meta["odb_sha256"] = odb_sha256
            ev_meta["unit"] = req.unit
            ev_meta["value_key"] = req.value_key

            bound_ev = Evidence(
                kind=getattr(ev, "kind", "odb_result"),
                source="odb",
                locator=str(bound_locator),
                value=float(val),
                unit=req.unit,
                metadata=ev_meta,
            )
            bound_evidences.append(bound_ev)
            evidence_list.append(bound_ev)

        bound_extraction = ResultExtraction(
            requirement=req,
            value=float(val),
            locator=bound_locator,
            evidence=tuple(bound_evidences),
        )
        extractions.append(bound_extraction)
        metrics[req.value_key] = float(val)

    return OdbExtractionReport(
        run_id=run_id,
        input_hash=input_hash,
        odb_path=odb,
        odb_sha256=odb_sha256,
        extractions=tuple(extractions),
        metrics=metrics,
        evidence=tuple(evidence_list),
    )
