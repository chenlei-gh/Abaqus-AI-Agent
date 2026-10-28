"""Executor-neutral mesh inspection and quality result contracts."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# Canonical status vocabulary (C-2 §4). `unsupported` and `not_run` are new and
# exist so that "the check could not answer" never reads as "the mesh is fine".
MESH_QUALITY_STATUSES = (
    "pass",
    "warning",
    "fail",
    "unsupported",
    "not_run",
    "expired",
)

# Severity answers a different question than status: what does this mean for
# delivery? A warning may be advisory or blocking; that is a policy decision.
MESH_QUALITY_SEVERITIES = ("none", "advisory", "blocking")

_STATUS_ALIASES = {
    "pass": "pass",
    "passed": "pass",
    "ok": "pass",
    "warning": "warning",
    "warn": "warning",
    "advisory": "warning",
    "fail": "fail",
    "failed": "fail",
    # `BLOCKED` used to mean both "fatal defect" and "evidence insufficient".
    # The canonical vocabulary splits those, so the legacy value maps to the
    # fatal branch and callers must re-classify evidence gaps as not_run.
    "blocked": "fail",
    "unsupported": "unsupported",
    "not_supported": "unsupported",
    "unsupported_checks": "unsupported",
    "not_run": "not_run",
    "not_run_not_checked": "not_run",
    "not_checked": "not_run",
    "unknown": "not_run",
    "skipped": "not_run",
    "expired": "expired",
    "stale": "expired",
}


def normalize_mesh_quality_status(value: Any, default: str = "not_run") -> str:
    """Map any producer's status spelling onto the canonical vocabulary.

    Producers historically disagreed: the CAE script wrote lowercase
    ``pass/warning/fail/unknown``, the INP auditor wrote uppercase
    ``PASS/WARNING/BLOCKED``, and the acceptance gate only accepted the exact
    string ``"pass"``. An unrecognized value must not silently become a pass.
    """
    if value is None:
        return default
    token = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return default
    if token in _STATUS_ALIASES:
        return _STATUS_ALIASES[token]
    # Tolerate decorated values such as "mesh_quality:warning" or "PASS(0)".
    for alias, canonical in _STATUS_ALIASES.items():
        if alias in token:
            return canonical
    return default


def default_severity_for_status(status: str) -> str:
    """Return the severity a status implies when no domain policy overrides it.

    A warning is advisory by default: it is a real result that deserves to be
    reported, not a fatal defect. A domain that cannot tolerate it must say so
    explicitly by setting ``severity="blocking"``.

    `unsupported`, `not_run`, and `expired` are advisory here, not blocking:
    whether a missing check stops delivery depends on whether the domain requires
    that check. The acceptance gate upgrades them to blocking when it does.
    """
    canonical = normalize_mesh_quality_status(status)
    if canonical == "pass":
        return "none"
    if canonical == "fail":
        return "blocking"
    return "advisory"


@dataclass(frozen=True)
class MeshSummary:
    part: str
    node_count: int
    element_count: int
    element_types: Tuple[str, ...] = field(default_factory=tuple)
    quality_status: str = "unknown"
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.node_count < 0 or self.element_count < 0:
            raise ValueError("mesh counts cannot be negative")
        if self.quality_status not in ("unknown", "pass", "warning", "fail"):
            raise ValueError("invalid quality_status")


@dataclass(frozen=True)
class MeshQualityPolicy:
    max_aspect_ratio: Optional[float] = None
    max_skew: Optional[float] = None
    min_jacobian: Optional[float] = None
    min_angle: Optional[float] = None
    max_angle: Optional[float] = None
    max_angular_deviation: Optional[float] = None
    max_geometric_deviation_factor: Optional[float] = None
    analysis_checks: bool = True

    def __post_init__(self):
        if self.max_aspect_ratio is not None and self.max_aspect_ratio <= 0:
            raise ValueError("max_aspect_ratio must be positive")
        for name in (
            "max_skew",
            "min_jacobian",
            "min_angle",
            "max_angle",
            "max_angular_deviation",
            "max_geometric_deviation_factor",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError("%s cannot be negative" % name)
        if self.max_geometric_deviation_factor is not None and self.max_geometric_deviation_factor == 0:
            raise ValueError("max_geometric_deviation_factor must be positive")


@dataclass(frozen=True)
class MeshQualityResult:
    """One mesh quality verdict, bound to the run that produced it.

    `status` says what the check found; `severity` says what that means for
    delivery. They are not the same question, and neither is inferred from the
    other without a policy.

    The binding fields (job_name, run_id, input_sha256, odb_sha256, part_name)
    exist so a stale result cannot be read as evidence for a new solve. A
    result that does not match the current run is `expired`, not `pass`.
    """
    status: str
    metrics: Dict[str, float] = field(default_factory=dict)
    violations: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    evidence: Tuple[str, ...] = field(default_factory=tuple)
    source: str = "unsupported"
    failed_element_count: int = 0
    warning_element_count: int = 0
    quality_scope: Optional[str] = None
    severity: Optional[str] = None
    kind: str = "mesh_quality"
    schema: str = "result_item_v1"
    job_name: Optional[str] = None
    model_name: Optional[str] = None
    part_name: Optional[str] = None
    run_id: Optional[str] = None
    input_sha256: Optional[str] = None
    odb_sha256: Optional[str] = None
    created_at: Optional[str] = None
    unsupported_checks: Tuple[str, ...] = field(default_factory=tuple)
    execution_error: Optional[str] = None

    def __post_init__(self):
        if self.status not in MESH_QUALITY_STATUSES:
            raise ValueError(
                "invalid status %r; expected one of %s" % (self.status, MESH_QUALITY_STATUSES)
            )
        if any(not isinstance(k, str) or not isinstance(v, (int, float)) for k, v in self.metrics.items()):
            raise ValueError("metrics must map strings to numeric values")
        if self.failed_element_count < 0 or self.warning_element_count < 0:
            raise ValueError("element counts cannot be negative")
        if self.severity is not None and self.severity not in MESH_QUALITY_SEVERITIES:
            raise ValueError(
                "invalid severity %r; expected one of %s" % (self.severity, MESH_QUALITY_SEVERITIES)
            )

    @property
    def passed(self):
        """A pass is only a pass. A warning is a separate, non-fatal verdict."""
        return self.status == "pass"

    @property
    def effective_severity(self) -> str:
        return self.severity or default_severity_for_status(self.status)

    @property
    def blocks_delivery(self) -> bool:
        return self.effective_severity == "blocking"

    @property
    def is_answerable(self) -> bool:
        """False when the check could not speak to this model at all."""
        return self.status not in ("unsupported", "not_run", "expired")

    def to_dict(self) -> Dict[str, Any]:
        """Stable serialization so callers never fall back to `str(result)`."""
        return {
            "kind": self.kind,
            "schema": self.schema,
            "status": self.status,
            "severity": self.effective_severity,
            "metrics": dict(self.metrics),
            "violations": list(self.violations),
            "warnings": list(self.warnings),
            "evidence": list(self.evidence),
            "source": self.source,
            "failed_element_count": self.failed_element_count,
            "warning_element_count": self.warning_element_count,
            "quality_scope": self.quality_scope,
            "job_name": self.job_name,
            "model_name": self.model_name,
            "part_name": self.part_name,
            "run_id": self.run_id,
            "input_sha256": self.input_sha256,
            "odb_sha256": self.odb_sha256,
            "created_at": self.created_at,
            "unsupported_checks": list(self.unsupported_checks),
            "execution_error": self.execution_error,
        }

    @classmethod
    def from_mapping(cls, payload: Dict[str, Any]) -> "MeshQualityResult":
        """Build from a producer's dict, normalizing its status spelling.

        Producers wrote `gate_status` or `status` in mutually incompatible
        casing, so both keys are accepted and normalized onto one vocabulary.
        """
        data = dict(payload or {})
        raw_status = data.get("status")
        if raw_status is None:
            raw_status = data.get("gate_status")
        unsupported = data.get("unsupported_checks") or ()
        metrics = {
            str(k): float(v)
            for k, v in (data.get("metrics") or data.get("governing_metrics") or {}).items()
            if isinstance(v, (int, float))
        }
        return cls(
            status=normalize_mesh_quality_status(
                raw_status,
                default="unsupported" if unsupported else "not_run",
            ),
            metrics=metrics,
            violations=tuple(str(v) for v in (data.get("violations") or ())),
            warnings=tuple(str(w) for w in (data.get("warnings") or ())),
            evidence=tuple(str(e) for e in (data.get("evidence") or ())),
            source=str(data.get("source") or data.get("audit_source") or "unsupported"),
            failed_element_count=int(data.get("failed_element_count") or 0),
            warning_element_count=int(data.get("warning_element_count") or 0),
            quality_scope=data.get("quality_scope"),
            severity=data.get("severity"),
            job_name=data.get("job_name"),
            model_name=data.get("model_name"),
            part_name=data.get("part_name") or data.get("part"),
            run_id=data.get("run_id"),
            input_sha256=data.get("input_sha256"),
            odb_sha256=data.get("odb_sha256"),
            created_at=data.get("created_at"),
            unsupported_checks=tuple(str(u) for u in unsupported),
            execution_error=data.get("execution_error"),
        )


@dataclass(frozen=True)
class MeshQualityBinding:
    """What a mesh quality result must agree with to count as current evidence.

    Hash equality is the point. Two ODBs of identical size can differ in
    content, so size and filename are never accepted as identity.
    """
    job_name: Optional[str] = None
    run_id: Optional[str] = None
    input_sha256: Optional[str] = None
    odb_sha256: Optional[str] = None
    part_names: Tuple[str, ...] = ()


def mesh_quality_expiry_reasons(
    result: Any,
    binding: MeshQualityBinding,
) -> Tuple[str, ...]:
    """Return why a result is not evidence for the run described by `binding`.

    Only *disagreement* expires a result. A caller that never recorded the ODB
    hash has an incomplete record, not a contradictory one; that gap is reported
    by `mesh_quality_binding_gaps` so it can be requested without silently
    converting a real result into a failure.
    """
    if isinstance(result, dict):
        result = MeshQualityResult.from_mapping(result)
    reasons = []
    for field_name in ("job_name", "run_id", "input_sha256", "odb_sha256"):
        expected = getattr(binding, field_name, None)
        observed = getattr(result, field_name, None)
        if expected and observed and str(expected) != str(observed):
            reasons.append("%s_mismatch" % field_name)
    if binding.part_names:
        part = getattr(result, "part_name", None)
        if part and str(part) not in {str(p) for p in binding.part_names}:
            reasons.append("part_name_not_in_assembly")
    return tuple(reasons)


def mesh_quality_binding_gaps(
    result: Any,
    binding: MeshQualityBinding,
) -> Tuple[str, ...]:
    """Return the declared binding keys the result does not record at all."""
    if isinstance(result, dict):
        result = MeshQualityResult.from_mapping(result)
    gaps = []
    for field_name in ("job_name", "run_id", "input_sha256", "odb_sha256"):
        if getattr(binding, field_name, None) and not getattr(result, field_name, None):
            gaps.append("%s_unbound" % field_name)
    return tuple(gaps)


# Criteria that describe element *shape* and therefore produce a
# failedElements count that a threshold can turn into a real verdict.
#
# `ANALYSIS_CHECKS` is deliberately absent: measured on Abaqus 2025 with C3D10M,
# the same mesh that failed `ASPECT_RATIO` on 124/166 elements reported
# `failedElements=0, warningElements=152` for `ANALYSIS_CHECKS`. A domain that
# configures only `analysis_checks=True` can therefore never be blocked by it.
SHAPE_THRESHOLD_FIELDS = (
    "max_aspect_ratio",
    "min_angle",
    "max_angle",
)


@dataclass(frozen=True)
class DomainMeshQualityPolicy:
    """Shape thresholds a physics domain must submit to make its mesh gate real.

    The values are engineering defaults, not physical constants. They are
    grounded in one measured pair (Abaqus 2025, C3D10M free tet):

    - acceptable mesh: aspect 2.28, min angle 26.97 deg, max angle 114.75 deg
    - unusable mesh:   aspect 12.58, min angle 2.61 deg, max angle 173.70 deg

    These defaults separate those two cases on all three criteria. A domain with
    stricter requirements should override them rather than rely on this table.
    """
    max_aspect_ratio: Optional[float] = 8.0
    min_angle: Optional[float] = 15.0
    max_angle: Optional[float] = 160.0

    def __post_init__(self):
        for name in SHAPE_THRESHOLD_FIELDS:
            value = getattr(self, name)
            if value is not None and float(value) <= 0:
                raise ValueError("%s must be positive, got %r" % (name, value))

    @property
    def configured_fields(self) -> Tuple[str, ...]:
        return tuple(n for n in SHAPE_THRESHOLD_FIELDS if getattr(self, n) is not None)

    def is_answerable(self) -> bool:
        """Whether at least one shape threshold can produce a failing verdict."""
        return bool(self.configured_fields)

    def to_dict(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in SHAPE_THRESHOLD_FIELDS}


# One canonical default is used for every solid/continuum domain. Per-domain
# overrides live here rather than being scattered through the compiler, so the
# policy that a gate depends on has exactly one home.
_DOMAIN_MESH_QUALITY_OVERRIDES: Dict[str, DomainMeshQualityPolicy] = {}

DEFAULT_DOMAIN_MESH_QUALITY_POLICY = DomainMeshQualityPolicy()


def resolve_domain_mesh_quality_policy(
    domain: Optional[str],
) -> DomainMeshQualityPolicy:
    """Return the shape thresholds a domain must use for its mesh gate."""
    key = str(domain or "").strip().lower()
    return _DOMAIN_MESH_QUALITY_OVERRIDES.get(key, DEFAULT_DOMAIN_MESH_QUALITY_POLICY)


# Official 2025 tetrahedron continuation floor. Shape factor is the ratio of
# element volume to the optimal tetrahedron volume; 0 means a degenerate
# element. The CAE default highlight limit for tetrahedra is 0.0001. Passing
# this floor means "may continue to checks", not "the mesh is converged".
# Source: Verifying your mesh, Abaqus/CAE 2025.
TET_SHAPE_FACTOR_FLOOR = 0.0001


def tet_partition_controls() -> Dict[str, Any]:
    """Documented controls for one free tetrahedron partition.

    ``algorithm`` is intentionally absent. For free tetrahedra the only
    documented algorithm value is ``NON_DEFAULT``, which selects the pre-6.4
    mesher. Omitting the argument is how the default algorithm is selected.
    ``sizeGrowth=MODERATE`` applies only to that default mesher.
    """
    return {
        "elem_shape": "TET",
        "technique": "FREE",
        "size_growth": "MODERATE",
        "algorithm": None,
        "boundary_preview": True,
    }


def tet_mesh_script(part_expr: str) -> str:
    """One tetrahedron partition: default mesher, moderate growth, preview stop.

    A failed boundary preview raises before the interior mesh is generated.
    The caller must not wrap this in a seed-size retry loop.
    """
    return (
        "{part}.setMeshControls(regions={part}.cells, elemShape=TET, "
        "technique=FREE, sizeGrowth=MODERATE)\n"
        "{part}.generateMesh(boundaryPreview=ON)\n"
        "_abqai_boundary = {part}.verifyMeshQuality(criterion=SHAPE_FACTOR, "
        "threshold={floor}, elemShape=TET)\n"
        "_abqai_boundary_failed = len(_abqai_boundary.get('failedElements', ()))\n"
        "if _abqai_boundary_failed:\n"
        "    raise RuntimeError('tet_boundary_preview_rejected: ' + "
        "str(_abqai_boundary_failed) + ' boundary elements below shape factor "
        "{floor}; interior mesh not generated')\n"
        "{part}.generateMesh()\n"
    ).format(part=part_expr, floor=repr(TET_SHAPE_FACTOR_FLOOR))


def mesh_submission_blockers(mesh_quality: Any) -> Tuple[str, ...]:
    """Why this mesh must not be submitted.

    ``ANALYSIS_CHECKS`` alone is not a gate: a measured bad C3D10M mesh can
    report ``failedElements=0`` for that criterion. Zero or negative volume is
    represented by the documented tetrahedron shape-factor floor. A missing
    result is also a stop: absence of evidence is not permission to submit.
    """
    if mesh_quality is None:
        return ("mesh_quality_missing",)
    if isinstance(mesh_quality, dict):
        result = MeshQualityResult.from_mapping(mesh_quality)
    elif isinstance(mesh_quality, MeshQualityResult):
        result = mesh_quality
    else:
        payload = {}
        for key in (
            "status", "metrics", "violations", "warnings", "evidence",
            "failed_element_count", "unsupported_checks", "execution_error",
        ):
            if hasattr(mesh_quality, key):
                payload[key] = getattr(mesh_quality, key)
        if not payload:
            return ("mesh_quality_unreadable",)
        result = MeshQualityResult.from_mapping(payload)

    blockers = []
    if result.status in ("fail", "unsupported", "not_run", "expired"):
        blockers.append("mesh_quality_%s" % result.status)
    if result.failed_element_count > 0:
        blockers.append("failed_elements:%d" % result.failed_element_count)
    if any("analysis_checks" == item or item.endswith(":analysis_checks") for item in result.violations):
        blockers.append("analysis_checks_failed")
    shape = result.metrics.get("shape_factor")
    if shape is not None and float(shape) < TET_SHAPE_FACTOR_FLOOR:
        blockers.append("shape_factor_below_floor:%s" % shape)
    if any("shape_factor" in item for item in result.violations):
        blockers.append("shape_factor_failed")
    if any("zero_volume" in item or "negative_volume" in item for item in result.violations):
        blockers.append("nonpositive_volume")
    if result.execution_error:
        blockers.append("mesh_quality_execution_error")
    return tuple(dict.fromkeys(blockers))


def mesh_quality_gate_configuration_errors(
    domain: Optional[str],
    required_gates: Tuple[str, ...] = (),
    policy: Optional[DomainMeshQualityPolicy] = None,
) -> Tuple[str, ...]:
    """Return why `mesh_quality` may not be a required gate for this domain.

    Making the gate mandatory is only honest when the domain submits at least one
    shape threshold. Requiring the gate while configuring `analysis_checks=True`
    alone would leave a gem that can observe the mesh but never reject it.
    """
    if "mesh_quality" not in tuple(required_gates or ()):
        return ()
    effective = policy or resolve_domain_mesh_quality_policy(domain)
    if effective.is_answerable():
        return ()
    return (
        "mesh_quality_gate_required_without_shape_threshold:%s" % (domain or "unknown"),
    )


ABAQUS_NATIVE_SHAPE_METRICS = (
    "max_aspect_ratio",
    "max_skew",
    "min_jacobian",
    "min_angle",
    "max_angle",
)
ABAQUS_ANALYSIS_CHECKS = (
    "max_angular_deviation",
    "max_geometric_deviation_factor",
)
DERIVED_QUALITY_METRICS = (
    "transition_ratio",
    "aspect_ratio_mean",
    "volume_skew",
)


def classify_mesh_quality_metrics(metrics: Dict[str, float]) -> Dict[str, Tuple[str, ...]]:
    """Classify mesh quality metrics into native, analysis-only, derived, and unsupported."""
    native, analysis, derived, unsupported = [], [], [], []
    for k in metrics.keys():
        if k in ABAQUS_NATIVE_SHAPE_METRICS:
            native.append(k)
        elif k in ABAQUS_ANALYSIS_CHECKS:
            analysis.append(k)
        elif k in DERIVED_QUALITY_METRICS:
            derived.append(k)
        else:
            unsupported.append(k)
    return {
        "native": tuple(sorted(native)),
        "analysis": tuple(sorted(analysis)),
        "derived": tuple(sorted(derived)),
        "unsupported": tuple(sorted(unsupported)),
    }
