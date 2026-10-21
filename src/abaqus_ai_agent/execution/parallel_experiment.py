"""Parallel execution specification and experiment record contracts.

Governs multi-core parallel experiments (Abaqus/Standard vs Abaqus/Explicit)
under Controlled Variable conditions (Governance Plan Phase 3.2).

Ensures:
1. numCpus is strictly bounded to supported candidate sets (1, 2, 4, 8) and rejects bool/floats.
2. numDomains is explicitly tracked without assuming it always equals numCpus.
3. Heterogeneous solvers (Standard vs Explicit) and precision levels are tracked as distinct models.
4. Experiment results retain host hardware metadata, timestamps, and input hashes.
5. Strict serialization/deserialization with fail-closed schema validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
import platform
from typing import Any, Dict, Optional, Set

VALID_NUM_CPUS: Set[int] = {1, 2, 4, 8}
VALID_SOLVER_TYPES: Set[str] = {"STANDARD", "EXPLICIT"}


class ParallelExperimentError(ValueError):
    """Raised when parallel experiment configuration or record is invalid."""


def _coerce_int_strictly(val: Any, field_name: str) -> int:
    """Coerce to int strictly rejecting bool, float, or unparseable values."""
    if isinstance(val, bool):
        raise ParallelExperimentError(f"{field_name} must not be a boolean: {val!r}")
    if isinstance(val, int):
        return val
    raise ParallelExperimentError(
        f"{field_name} must be a strict int, got {type(val).__name__}: {val!r}"
    )


def _coerce_optional_float_strictly(val: Any, field_name: str) -> Optional[float]:
    """Coerce to non-negative finite float or None strictly rejecting bool, NaN, inf."""
    if val is None:
        return None
    if isinstance(val, bool):
        raise ParallelExperimentError(f"{field_name} must not be a boolean: {val!r}")
    if not isinstance(val, (int, float)):
        raise ParallelExperimentError(
            f"{field_name} must be numeric, got {type(val).__name__}: {val!r}"
        )
    f_val = float(val)
    if not math.isfinite(f_val):
        raise ParallelExperimentError(
            f"{field_name} must be a finite number, got: {f_val!r}"
        )
    if f_val < 0.0:
        raise ParallelExperimentError(
            f"{field_name} must be non-negative, got: {f_val!r}"
        )
    return f_val


def collect_host_hardware_metadata() -> Dict[str, Any]:
    """Collect non-invasive host hardware metadata for benchmark auditability."""
    meta: Dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "physical_cpu_count": None,
        "total_memory_bytes": None,
    }

    # Attempt to query physical core count if psutil is available
    try:
        import psutil  # type: ignore

        meta["physical_cpu_count"] = psutil.cpu_count(logical=False)
        meta["total_memory_bytes"] = psutil.virtual_memory().total
    except Exception:
        # Fallback for Windows total memory via ctypes if psutil not present
        if platform.system() == "Windows":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    meta["total_memory_bytes"] = int(stat.ullTotalPhys)
            except Exception:
                pass

    return meta


@dataclass(frozen=True)
class ParallelRunSpec:
    """Explicit configuration specification for a parallel solver execution."""

    job_name: str
    model_name: str
    solver_type: str
    num_cpus: int
    num_domains: Optional[int] = None
    precision: str = "SINGLE"

    def __post_init__(self) -> None:
        if not isinstance(self.job_name, str) or not self.job_name.strip():
            raise ParallelExperimentError(
                f"job_name must be non-empty string, got: {self.job_name!r}"
            )
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ParallelExperimentError(
                f"model_name must be non-empty string, got: {self.model_name!r}"
            )

        # solver_type normalization and check
        if not isinstance(self.solver_type, str):
            raise ParallelExperimentError(
                f"solver_type must be string, got: {self.solver_type!r}"
            )
        st_upper = self.solver_type.strip().upper()
        if st_upper not in VALID_SOLVER_TYPES:
            raise ParallelExperimentError(
                f"Invalid solver_type {self.solver_type!r}; must be one of {sorted(VALID_SOLVER_TYPES)}"
            )
        object.__setattr__(self, "solver_type", st_upper)

        # num_cpus validation
        cpus = _coerce_int_strictly(self.num_cpus, "num_cpus")
        if cpus not in VALID_NUM_CPUS:
            raise ParallelExperimentError(
                f"num_cpus must be one of {sorted(VALID_NUM_CPUS)}, got: {cpus}"
            )
        object.__setattr__(self, "num_cpus", cpus)

        # num_domains validation
        if self.num_domains is not None:
            doms = _coerce_int_strictly(self.num_domains, "num_domains")
            if doms < 1:
                raise ParallelExperimentError(
                    f"num_domains must be >= 1, got: {doms}"
                )
            object.__setattr__(self, "num_domains", doms)

        # precision validation
        if not isinstance(self.precision, str) or not self.precision.strip():
            raise ParallelExperimentError(
                f"precision must be non-empty string, got: {self.precision!r}"
            )
        object.__setattr__(self, "precision", self.precision.strip().upper())

    @property
    def effective_domains(self) -> int:
        """Return actual domain decomposition count (defaults to num_cpus)."""
        return self.num_domains if self.num_domains is not None else self.num_cpus

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_name": self.job_name,
            "model_name": self.model_name,
            "solver_type": self.solver_type,
            "num_cpus": self.num_cpus,
            "num_domains": self.num_domains,
            "effective_domains": self.effective_domains,
            "precision": self.precision,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ParallelRunSpec:
        if not isinstance(data, dict):
            raise ParallelExperimentError(
                f"Expected dict for ParallelRunSpec, got: {type(data).__name__}"
            )
        for req in ("job_name", "model_name", "solver_type", "num_cpus"):
            if req not in data:
                raise ParallelExperimentError(
                    f"Missing required field in ParallelRunSpec: {req!r}"
                )
        return cls(
            job_name=data["job_name"],
            model_name=data["model_name"],
            solver_type=data["solver_type"],
            num_cpus=data["num_cpus"],
            num_domains=data.get("num_domains"),
            precision=data.get("precision", "SINGLE"),
        )


@dataclass
class ParallelExperimentResult:
    """Auditable record for a single parallel solver benchmark run."""

    spec: ParallelRunSpec
    run_id: str
    repeat_index: int
    status: str
    t4a_duration_s: Optional[float] = None
    t4b_solver_s: Optional[float] = None
    model_hash: str = ""
    inp_hash: Optional[str] = None
    host_hardware: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    evidence_paths: Dict[str, str] = field(default_factory=dict)
    timestamp_utc: str = ""
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ParallelExperimentError(
                f"run_id must be non-empty string, got: {self.run_id!r}"
            )
        self.repeat_index = _coerce_int_strictly(self.repeat_index, "repeat_index")
        if self.repeat_index < 0:
            raise ParallelExperimentError(
                f"repeat_index must be non-negative, got: {self.repeat_index}"
            )

        if not isinstance(self.status, str) or not self.status.strip():
            raise ParallelExperimentError(
                f"status must be non-empty string, got: {self.status!r}"
            )
        self.status = self.status.strip().upper()

        self.t4a_duration_s = _coerce_optional_float_strictly(
            self.t4a_duration_s, "t4a_duration_s"
        )
        self.t4b_solver_s = _coerce_optional_float_strictly(
            self.t4b_solver_s, "t4b_solver_s"
        )

        if not self.timestamp_utc:
            self.timestamp_utc = datetime.now(timezone.utc).isoformat()
        if not self.host_hardware:
            self.host_hardware = collect_host_hardware_metadata()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "run_id": self.run_id,
            "repeat_index": self.repeat_index,
            "status": self.status,
            "t4a_duration_s": self.t4a_duration_s,
            "t4b_solver_s": self.t4b_solver_s,
            "model_hash": self.model_hash,
            "inp_hash": self.inp_hash,
            "host_hardware": dict(self.host_hardware),
            "environment": dict(self.environment),
            "evidence_paths": dict(self.evidence_paths),
            "timestamp_utc": self.timestamp_utc,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ParallelExperimentResult:
        if not isinstance(data, dict):
            raise ParallelExperimentError(
                f"Expected dict for ParallelExperimentResult, got: {type(data).__name__}"
            )
        for req in ("spec", "run_id", "repeat_index", "status"):
            if req not in data:
                raise ParallelExperimentError(
                    f"Missing required field in ParallelExperimentResult: {req!r}"
                )

        spec_raw = data["spec"]
        if isinstance(spec_raw, dict):
            spec = ParallelRunSpec.from_dict(spec_raw)
        elif isinstance(spec_raw, ParallelRunSpec):
            spec = spec_raw
        else:
            raise ParallelExperimentError(
                f"Invalid spec type in ParallelExperimentResult: {type(spec_raw).__name__}"
            )

        return cls(
            spec=spec,
            run_id=data["run_id"],
            repeat_index=data["repeat_index"],
            status=data["status"],
            t4a_duration_s=data.get("t4a_duration_s"),
            t4b_solver_s=data.get("t4b_solver_s"),
            model_hash=data.get("model_hash", ""),
            inp_hash=data.get("inp_hash"),
            host_hardware=dict(data.get("host_hardware", {})),
            environment=dict(data.get("environment", {})),
            evidence_paths=dict(data.get("evidence_paths", {})),
            timestamp_utc=data.get("timestamp_utc", ""),
            notes=data.get("notes"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> ParallelExperimentResult:
        try:
            data = json.loads(text)
        except Exception as exc:
            raise ParallelExperimentError(
                f"Invalid JSON for ParallelExperimentResult: {exc}"
            ) from exc
        return cls.from_dict(data)
