"""Solver-parameter resolution with adaptive resource arbitration.

Provides both strict explicit parameter forwarding and evidence-driven adaptive
resource allocation (CPU, memory, domain decomposition, and license token bounds).

Design Principles:
1. Explicit caller options always override adaptive suggestions (source="explicit").
2. Evidence-adjusted parameters (source="evidence_adjusted") require non-empty, verified
   host hardware, model scale, solver physics, or license token evidence before
   being sent to mdb.Job (sent_to_solver=True).
3. Safe defaults (source="safe_default") never modify solver options silently.
4. License token translation uses Dassault/Abaqus standard formula: floor(5 * N^0.422).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import platform
from typing import Any, Dict, Optional, Tuple


_EXPLICIT_JOB_KEYS = ("numCpus", "numDomains")
_REFUSED_WITHOUT_EVIDENCE = ("memory", "memoryPolicy", "precision", "mp_mode")
_ADAPTIVE_ALLOWED_KEYS = (
    "numCpus",
    "numDomains",
    "memory",
    "memoryUnits",
    "explicitPrecision",
    "nodalOutputPrecision",
    "multiprocessingMode",
    "adaptive",
)

_VALID_MEMORY_UNITS = ("PERCENTAGE", "MEGA_BYTES", "GIGA_BYTES")
_VALID_PRECISIONS = ("SINGLE", "FULL", "DOUBLE", "DOUBLE_PLUS_PACK", "DOUBLE_CONSTRAINT_ONLY")


@dataclass(frozen=True)
class SolverParameterDecision:
    """Auditable ledger record for a solver parameter configuration decision."""

    name: str
    value: object
    source: str  # "explicit", "safe_default", "evidence_adjusted", "refused"
    evidence: str
    reason: str
    sent_to_solver: bool

    def __post_init__(self) -> None:
        valid_sources = ("explicit", "safe_default", "evidence_adjusted", "refused")
        if self.source not in valid_sources:
            raise ValueError(f"unsupported decision source: {self.source}")
        if self.source == "evidence_adjusted":
            if not self.evidence or self.evidence == "none":
                raise ValueError("evidence-adjusted decision must provide non-empty evidence")
        elif self.source in ("safe_default", "refused"):
            if self.sent_to_solver:
                raise ValueError(f"{self.source} parameters must not be sent to solver")


def tokens_required_for_cpus(num_cpus: int, feature: str = "standard") -> int:
    """Calculate standard Dassault/Abaqus license tokens required for N CPUs.

    Standard Abaqus formula:
      tokens = floor(5 * num_cpus^0.422) for standard/explicit solver.

    Standard token tiers:
      1 CPU  -> 5 tokens
      2 CPUs -> 6 tokens
      3 CPUs -> 7 tokens
      4 CPUs -> 8 tokens
      6 CPUs -> 10 tokens
      8 CPUs -> 12 tokens
      16 CPUs -> 16 tokens
      24 CPUs -> 19 tokens
      32 CPUs -> 21 tokens
    """
    if isinstance(num_cpus, bool) or not isinstance(num_cpus, int) or num_cpus < 1:
        raise ValueError(f"num_cpus must be a positive int, got {num_cpus!r}")
    return int(math.floor(5.0 * (float(num_cpus) ** 0.422)))


def max_cpus_for_tokens(available_tokens: int, feature: str = "standard") -> int:
    """Calculate maximum allowable solver CPUs under available license tokens.

    Inverse of tokens_required_for_cpus.
    Returns 0 if available_tokens < 5 (cannot launch solver).
    """
    if isinstance(available_tokens, bool) or not isinstance(available_tokens, int):
        raise ValueError(f"available_tokens must be an int, got {available_tokens!r}")
    if available_tokens < 5:
        return 0

    cpus = 1
    while tokens_required_for_cpus(cpus + 1, feature=feature) <= available_tokens:
        cpus += 1
    return cpus


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive int, got {value!r}")
    return value


def _collect_host_memory_bytes() -> Optional[int]:
    """Collect total physical memory bytes with cross-platform fallback."""
    try:
        import psutil  # type: ignore
        return int(psutil.virtual_memory().total)
    except Exception:
        pass

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
                return int(stat.ullTotalPhys)
        except Exception:
            pass
    return None


def calculate_adaptive_cpus(
    *,
    host_hardware: Optional[Dict[str, Any]] = None,
    solver_type: str = "STANDARD",
    element_count: Optional[int] = None,
    available_tokens: Optional[int] = None,
    caller_max_cpus: Optional[int] = None,
) -> Tuple[int, str, str]:
    """Adaptively determine optimal CPU count based on hardware, solver physics, and license tokens.

    Returns:
        (selected_cpus, evidence_str, reason_str)
    """
    hardware = dict(host_hardware or {})
    logical_cpus = hardware.get("logical_cpu_count") or os.cpu_count() or 1
    physical_cpus = hardware.get("physical_cpu_count")

    # 1. Host capacity & system headroom (reserve at least 2 cores or 20% for OS & telemetry)
    if physical_cpus and physical_cpus > 0:
        base_capacity = physical_cpus
        core_type = f"physical={physical_cpus}"
    else:
        base_capacity = max(1, logical_cpus // 2) if logical_cpus > 2 else logical_cpus
        core_type = f"logical={logical_cpus}"

    system_headroom = max(1, min(base_capacity, logical_cpus - 2))

    # 2. Physics & Model Scale heuristic
    solver_upper = solver_type.strip().upper()
    if element_count is not None and element_count > 0:
        if element_count < 5000:
            physics_target = 1
            scale_desc = f"small model ({element_count} elements), single-core avoids IPC overhead"
        elif element_count < 50000:
            physics_target = min(4, system_headroom)
            scale_desc = f"medium model ({element_count} elements), multi-core 2-4 optimal"
        else:
            physics_target = min(8, system_headroom)
            scale_desc = f"large model ({element_count} elements), 4-8 cores recommended"
    else:
        # Default engineering heuristic when mesh size is not provided prior to meshing
        physics_target = min(4, system_headroom)
        scale_desc = "unmeshed/implicit baseline (capped at 4 to balance sparse solver efficiency)"

    candidates = [physics_target, system_headroom]

    # 3. License token constraint
    license_desc = "unconstrained"
    if available_tokens is not None:
        lic_cap = max_cpus_for_tokens(available_tokens)
        candidates.append(max(1, lic_cap))
        license_desc = f"available_tokens={available_tokens} (max_lic_cpus={lic_cap})"

    # 4. Caller max cap
    if caller_max_cpus is not None:
        candidates.append(max(1, caller_max_cpus))

    chosen = min(candidates)
    # Snap to standard engineering core candidates: 1, 2, 4, 8
    standard_core_tiers = (1, 2, 4, 8)
    chosen_core = 1
    for tier in standard_core_tiers:
        if tier <= chosen:
            chosen_core = tier

    evidence = f"host_cpus({core_type}), license({license_desc}), solver={solver_upper}"
    reason = f"selected {chosen_core} CPUs: {scale_desc}, preserving host headroom"
    return chosen_core, evidence, reason


def calculate_adaptive_memory(
    *,
    host_hardware: Optional[Dict[str, Any]] = None,
    target_percentage: int = 75,
) -> Tuple[int, str, str, str]:
    """Adaptively configure solver memory allocation limit to prevent disk thrashing.

    Returns:
        (memory_value, memory_units, evidence_str, reason_str)
    """
    total_bytes = (host_hardware or {}).get("total_memory_bytes") or _collect_host_memory_bytes()
    percentage = max(20, min(90, int(target_percentage)))

    if total_bytes and total_bytes > 0:
        total_gb = round(total_bytes / (1024 ** 3), 1)
        evidence = f"host_physical_memory={total_gb}GB ({total_bytes} bytes)"
        reason = f"allocate {percentage}% physical memory to Abaqus solver cache to minimize disk I/O paging"
    else:
        evidence = "host_physical_memory_unverified"
        reason = f"apply standard engineering safe allocation of {percentage}% memory"

    return percentage, "PERCENTAGE", evidence, reason


def resolve_job_kwargs(
    job_options: Optional[Dict[str, Any]] = None,
    *,
    adaptive: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Tuple[SolverParameterDecision, ...]]:
    """Resolve caller options into mdb.Job keyword arguments and audit decisions.

    Args:
        job_options: Explicit options supplied by the caller.
        adaptive: If True, or if job_options contains {"adaptive": True}, activates
                  evidence-driven adaptive calculation for unsupplied parameters.
        context: Optional dictionary containing hardware, solver_type, element_count,
                 available_tokens, etc.

    Returns:
        (job_kwargs, decisions_tuple)
    """
    options = dict(job_options or {})
    ctx = dict(context or {})

    # Detect adaptive mode flag
    is_adaptive = bool(adaptive or options.pop("adaptive", False))

    if is_adaptive:
        allowed = set(_ADAPTIVE_ALLOWED_KEYS)
    else:
        allowed = set(_EXPLICIT_JOB_KEYS) | set(_REFUSED_WITHOUT_EVIDENCE)

    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError("unsupported solver job option(s): %s" % ", ".join(unknown))

    kwargs: Dict[str, Any] = {}
    decisions: list[SolverParameterDecision] = []

    # Non-adaptive mode: refuse unverified parameters to protect legacy explicit contract
    if not is_adaptive:
        for name in _REFUSED_WITHOUT_EVIDENCE:
            if name not in options:
                continue
            decisions.append(SolverParameterDecision(
                name=name,
                value=options[name],
                source="refused",
                evidence="none",
                reason="no verified consumption path; refusing to apply or invent a solver setting",
                sent_to_solver=False,
            ))

    # 1. numCpus Resolution
    requested_cpus = options.get("numCpus")
    if requested_cpus is not None:
        valid_cpus = _positive_int("numCpus", requested_cpus)
        kwargs["numCpus"] = valid_cpus
        decisions.append(SolverParameterDecision(
            name="numCpus",
            value=valid_cpus,
            source="explicit",
            evidence="caller",
            reason="caller supplied numCpus; forwarded unchanged",
            sent_to_solver=True,
        ))
    elif is_adaptive:
        # Evidence-adjusted adaptive CPU resolution
        adap_cpus, adap_ev, adap_reason = calculate_adaptive_cpus(
            host_hardware=ctx.get("host_hardware"),
            solver_type=ctx.get("solver_type", "STANDARD"),
            element_count=ctx.get("element_count"),
            available_tokens=ctx.get("available_tokens"),
            caller_max_cpus=ctx.get("caller_max_cpus"),
        )
        kwargs["numCpus"] = adap_cpus
        decisions.append(SolverParameterDecision(
            name="numCpus",
            value=adap_cpus,
            source="evidence_adjusted",
            evidence=adap_ev,
            reason=adap_reason,
            sent_to_solver=True,
        ))
    else:
        decisions.append(SolverParameterDecision(
            name="numCpus",
            value=None,
            source="safe_default",
            evidence="omitted",
            reason="caller did not set numCpus; Abaqus default of 1 is left unchanged",
            sent_to_solver=False,
        ))

    # 2. numDomains Resolution
    requested_domains = options.get("numDomains")
    if requested_domains is not None:
        valid_doms = _positive_int("numDomains", requested_domains)
        kwargs["numDomains"] = valid_doms
        decisions.append(SolverParameterDecision(
            name="numDomains",
            value=valid_doms,
            source="explicit",
            evidence="caller",
            reason="caller supplied numDomains; forwarded unchanged",
            sent_to_solver=True,
        ))
    elif is_adaptive and "numCpus" in kwargs and ctx.get("solver_type", "").upper() == "EXPLICIT":
        # In Explicit dynamics, domain decomposition count matches CPU count by default
        explicit_domains = kwargs["numCpus"]
        kwargs["numDomains"] = explicit_domains
        decisions.append(SolverParameterDecision(
            name="numDomains",
            value=explicit_domains,
            source="evidence_adjusted",
            evidence=f"solver=EXPLICIT, numCpus={explicit_domains}",
            reason="domain decomposition count adaptively matched to active CPU count for Explicit",
            sent_to_solver=True,
        ))
    else:
        reason = "numDomains was not supplied; not inferred from numCpus" if "numCpus" in kwargs else "omitted"
        decisions.append(SolverParameterDecision(
            name="numDomains",
            value=None,
            source="safe_default",
            evidence="omitted",
            reason=reason,
            sent_to_solver=False,
        ))

    # 3. memory & memoryUnits Resolution
    if is_adaptive:
        requested_memory = options.get("memory")
        requested_mem_units = options.get("memoryUnits")
        if requested_memory is not None:
            valid_mem = _positive_int("memory", requested_memory)
            kwargs["memory"] = valid_mem
            mem_units = str(requested_mem_units).upper() if requested_mem_units else "PERCENTAGE"
            if mem_units not in _VALID_MEMORY_UNITS:
                raise ValueError(f"memoryUnits must be one of {_VALID_MEMORY_UNITS}, got: {requested_mem_units!r}")
            kwargs["memoryUnits"] = mem_units
            decisions.append(SolverParameterDecision(
                name="memory",
                value=valid_mem,
                source="explicit",
                evidence="caller",
                reason=f"caller supplied memory={valid_mem} {mem_units}; forwarded unchanged",
                sent_to_solver=True,
            ))
        else:
            mem_val, mem_u, mem_ev, mem_reason = calculate_adaptive_memory(
                host_hardware=ctx.get("host_hardware"),
                target_percentage=ctx.get("target_memory_percentage", 75),
            )
            kwargs["memory"] = mem_val
            kwargs["memoryUnits"] = mem_u
            decisions.append(SolverParameterDecision(
                name="memory",
                value=mem_val,
                source="evidence_adjusted",
                evidence=mem_ev,
                reason=mem_reason,
                sent_to_solver=True,
            ))
    elif "memory" not in options:
        decisions.append(SolverParameterDecision(
            name="memory",
            value=None,
            source="safe_default",
            evidence="omitted",
            reason="caller did not specify memory; Abaqus solver default memory policy retained",
            sent_to_solver=False,
        ))

    # 4. precision (explicitPrecision) Resolution
    if is_adaptive:
        requested_precision = options.get("explicitPrecision")
        if requested_precision is not None:
            p_str = str(requested_precision).strip().upper()
            if p_str not in _VALID_PRECISIONS:
                raise ValueError(f"explicitPrecision must be one of {_VALID_PRECISIONS}, got: {requested_precision!r}")
            kwargs["explicitPrecision"] = p_str
            decisions.append(SolverParameterDecision(
                name="explicitPrecision",
                value=p_str,
                source="explicit",
                evidence="caller",
                reason=f"caller specified explicitPrecision={p_str}; forwarded unchanged",
                sent_to_solver=True,
            ))
        elif ctx.get("solver_type", "").upper() == "EXPLICIT":
            # Adaptive check for Explicit solver precision
            is_large_strain = ctx.get("large_deformation", False) or ctx.get("has_contact", False)
            adap_prec = "DOUBLE_PLUS_PACK" if is_large_strain else "SINGLE"
            kwargs["explicitPrecision"] = adap_prec
            decisions.append(SolverParameterDecision(
                name="explicitPrecision",
                value=adap_prec,
                source="evidence_adjusted",
                evidence=f"solver=EXPLICIT, large_deformation_or_contact={is_large_strain}",
                reason=f"adaptive precision set to {adap_prec} to prevent numerical divergence in explicit dynamics",
                sent_to_solver=True,
            ))

    # 5. multiprocessingMode
    if is_adaptive and "multiprocessingMode" in options:
        requested_mp_mode = options.get("multiprocessingMode")
        kwargs["multiprocessingMode"] = requested_mp_mode
        decisions.append(SolverParameterDecision(
            name="multiprocessingMode",
            value=requested_mp_mode,
            source="explicit",
            evidence="caller",
            reason=f"caller specified multiprocessingMode={requested_mp_mode}",
            sent_to_solver=True,
        ))

    return kwargs, tuple(decisions)


def resolve_explicit_job_kwargs(
    job_options: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Tuple[SolverParameterDecision, ...]]:
    """Legacy compatibility entry point for non-adaptive explicit parameter forwarding.

    Behaves strictly as explicit-only forwarding without adaptive deduction.
    """
    return resolve_job_kwargs(job_options, adaptive=False)
