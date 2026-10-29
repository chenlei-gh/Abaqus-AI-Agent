"""Engineering Mesh Parameter Reasoning & Inference for P1.2.

S1 blocks a missing size. S2 records only local constraints that have an
analysis intent, geometric evidence, and an Abaqus edge-seed mapping. S5 does
not switch the production default. S6 classifies adaptive remeshing but never
emits a production action.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence, Tuple

from ..contracts.intent import EngineeringIntent
from ..contracts.mesh import LocalSeed
from ..planning.compiler import IntentMeshSpec


class MeshBaselineBlocked(ValueError):
    """Raised when automatic meshing has no verified size and must not invent one."""


class MeshConstraintBlocked(ValueError):
    """Raised when a required local constraint cannot be executed."""


PRIMARY_WALL_SOURCES = ("USER_SPECIFIED", "MEASURED")


class PrimaryWallBlocked(ValueError):
    """Raised when a seed is coarser than a verified primary wall, or the wall is missing."""


_EDGE_INTENTS = {
    "hole": ("hole_resolution", "hole", "stress_concentration"),
    "fillet": ("fillet_resolution", "fillet", "fatigue", "stress_concentration"),
    "gap": ("gap_resolution", "contact_resolution", "contact"),
}

# Official 2025 adaptive remeshing is Standard-only and procedure-limited.
# https://docs.software.vt.edu/abaqusv2025/English/SIMACAEANLRefMap/simaanl-c-adpover.htm
# https://docs.software.vt.edu/abaqusv2025/English/SIMACAECAERefMap/simacae-c-mgnconcadaptivitysteps.htm
_STANDARD_ADAPTIVE_PROCEDURES = frozenset({
    "static",
    "static_general",
    "quasi_static",
    "heat_transfer",
    "fully_coupled_thermal_stress",
    "coupled_temp_displacement",
    "coupled_pore_fluid_diffusion_stress",
    "coupled_thermal_electrical",
})
_STANDARD_ADAPTIVE_SHAPES = frozenset({
    "TRI", "QUAD", "TET",
    "CPE3", "CPE4", "CPS3", "CPS4", "CAX3", "CAX4",
    "S3", "S4", "S4R", "C3D4", "C3D10", "C3D10M",
})


@dataclass(frozen=True)
class UnsupportedConstraint:
    feature: str
    reason: str
    code: str = "UNSUPPORTED_CONSTRAINT"


@dataclass(frozen=True)
class EdgeSeedConstraint:
    feature: str
    analysis_intent: str
    region_expression: str
    size: Optional[float] = None
    number: Optional[int] = None
    constraint: str = "FREE"
    evidence: Tuple[str, ...] = ()
    execution: str = "seedEdgeBySize"
    executed: bool = False
    observed_edges: Tuple[str, ...] = ()

    def as_local_seed(self) -> LocalSeed:
        return LocalSeed(
            region_expression=self.region_expression,
            size=self.size,
            number=self.number,
            constraint=self.constraint,
        )


@dataclass(frozen=True)
class MeshSizeDecision:
    """A traceable sizing decision. READY is not mesh-quality evidence."""

    baseline_size: Optional[float]
    baseline_source: Optional[str]
    edge_constraints: Tuple[EdgeSeedConstraint, ...] = ()
    unsupported: Tuple[UnsupportedConstraint, ...] = ()
    status: str = "BLOCKED"
    explicit_stable_increment_risk: Optional[Mapping[str, Any]] = None
    production_default: str = "NOT_SWITCHED"
    adaptive_capability: str = "EXCLUDED"
    primary_wall_thickness: Optional[float] = None
    primary_wall_source: Optional[str] = None
    executable_baseline_size: Optional[float] = None
    capped_local_seed_sizes: Tuple[float, ...] = ()

    def __post_init__(self):
        if self.status not in ("READY", "BLOCKED", "INVALID"):
            raise ValueError("status must be READY, BLOCKED, or INVALID")
        if self.production_default != "NOT_SWITCHED":
            raise ValueError("S5 has no comparison evidence; production_default stays NOT_SWITCHED")
        if self.status == "READY":
            if self.baseline_size is None or self.baseline_source not in (
                "USER_SPECIFIED", "ABAQUS_DEFAULT_SIZE",
            ):
                raise ValueError("READY requires a traced positive baseline")
            if not _positive(self.baseline_size):
                raise ValueError("READY baseline must be a positive finite number")
            if self.unsupported:
                raise ValueError("required unsupported constraints cannot be READY")


def infer_mesh_specification(
    intent: EngineeringIntent,
    geometry: Any = None,
    explicit_mesh: Optional[IntentMeshSpec] = None,
) -> Tuple[IntentMeshSpec, Optional[Any]]:
    """Return an explicit mesh spec, or block when no verified size exists.

    A caller-supplied positive size is ``USER_SPECIFIED``. Bounding-box ratios are
    not a production seed and are not substituted here. A missing size used to
    become 2.5 mm; that path now raises ``MeshBaselineBlocked``.
    """
    del geometry  # Bounding-box geometry is intentionally not a seed source.
    if explicit_mesh is not None:
        return explicit_mesh, None

    if intent.mesh_requirements:
        if isinstance(intent.mesh_requirements, IntentMeshSpec):
            return intent.mesh_requirements, None
        if isinstance(intent.mesh_requirements, dict):
            size = intent.mesh_requirements.get("global_size") or intent.mesh_requirements.get("target_size")
            etype = intent.mesh_requirements.get("element_type", "C3D8R")
            if size is not None and float(size) > 0:
                return IntentMeshSpec(
                    element_type=str(etype),
                    global_size=float(size),
                    deviation_factor=float(intent.mesh_requirements.get("deviation_factor", 0.1)),
                    primary_wall_thickness=intent.mesh_requirements.get("primary_wall_thickness"),
                    primary_wall_thickness_source=intent.mesh_requirements.get("primary_wall_thickness_source"),
                ), None

    raise MeshBaselineBlocked(
        "No USER_SPECIFIED mesh size. Bounding-box ratios are not a production seed, "
        "and ABAQUS_DEFAULT_SIZE has not been read for this part. "
        "Refusing the 2.5 mm fallback."
    )


def resolve_primary_wall_thickness(
    thickness: Optional[float],
    source: Optional[str],
) -> Tuple[Optional[float], Optional[str], Optional[UnsupportedConstraint]]:
    """Accept only a traced positive wall. 7 mm, 10 mm, and 2.5 mm are not measurements."""
    if thickness is None and source is None:
        return None, None, UnsupportedConstraint(
            "primary_wall",
            "no USER_SPECIFIED or MEASURED primary wall thickness; refusing 7/10/2.5 mm and bounding-box fallbacks",
            "MISSING_PRIMARY_WALL",
        )
    if source not in PRIMARY_WALL_SOURCES or not _positive(thickness):
        return None, None, UnsupportedConstraint(
            "primary_wall",
            "primary wall thickness must be a positive finite USER_SPECIFIED or MEASURED value",
            "INVALID_PRIMARY_WALL",
        )
    return float(thickness), source, None


def cap_seed_to_primary_wall(seed: Optional[float], wall: Optional[float]) -> Optional[float]:
    """Executable seed cannot be coarser than the verified primary wall."""
    if not _positive(seed) or not _positive(wall):
        return seed
    if float(seed) > float(wall):
        return float(wall)
    return float(seed)


def decide_mesh_sizing(
    *,
    baseline_size: Optional[float],
    baseline_source: Optional[str],
    analysis_intents: Sequence[str] = (),
    features: Sequence[Mapping[str, Any]] = (),
    element_family: str = "C3D8R",
    solver: str = "STANDARD",
    procedure: str = "static",
    partition_proven: bool = False,
    primary_wall_thickness: Optional[float] = None,
    primary_wall_source: Optional[str] = None,
    local_seed_sizes: Sequence[float] = (),
) -> MeshSizeDecision:
    """Build the S2-S6 decision without emitting Abaqus actions.

    Missing analysis intent does not create a seed. A thickness request without
    a proven partition is ``BLOCKED``. Bias, volume size fields, and adaptive
    remeshing are recorded as unsupported and do not become production actions.
    """
    intents = {_norm(item) for item in analysis_intents if _norm(item)}
    unsupported = []
    edges = []

    wall, wall_source, wall_error = resolve_primary_wall_thickness(
        primary_wall_thickness, primary_wall_source,
    )

    if baseline_source not in (None, "USER_SPECIFIED", "ABAQUS_DEFAULT_SIZE"):
        return MeshSizeDecision(
            baseline_size=None,
            baseline_source=None,
            unsupported=(UnsupportedConstraint("baseline", "unrecognized size source", "INVALID"),),
            status="INVALID",
            adaptive_capability=_adaptive_status(solver, procedure, element_family),
            primary_wall_thickness=wall,
            primary_wall_source=wall_source,
        )
    if baseline_size is None or not _positive(baseline_size) or baseline_source is None:
        unsupported.append(UnsupportedConstraint(
            "baseline",
            "no verified USER_SPECIFIED or ABAQUS_DEFAULT_SIZE baseline",
            "MISSING_BASELINE",
        ))

    executable = cap_seed_to_primary_wall(baseline_size, wall) if _positive(baseline_size) and wall else None
    capped_locals = tuple(
        float(cap_seed_to_primary_wall(item, wall)) for item in local_seed_sizes if _positive(item) and wall
    )

    for feature in features:
        kind = _norm(feature.get("kind") or feature.get("feature"))
        if kind == "thickness":
            unsupported.append(_thickness_constraint(feature, element_family, partition_proven))
            continue
        if kind in ("volume_size_field", "body_size_field"):
            unsupported.append(UnsupportedConstraint(
                kind,
                "continuous body size field cannot be injected through seedPart or edge seeds",
            ))
            continue
        if kind == "bias":
            unsupported.append(UnsupportedConstraint(
                "bias",
                "seedEdgeByBias is not enabled until direction evidence and tests exist",
            ))
            continue
        if kind not in _EDGE_INTENTS:
            unsupported.append(UnsupportedConstraint(kind or "unknown", "feature kind has no executable mapping"))
            continue
        if not intents.intersection(_EDGE_INTENTS[kind]):
            continue
        edge = _edge_constraint(kind, feature, intents)
        if isinstance(edge, UnsupportedConstraint):
            unsupported.append(edge)
        else:
            if edge.size is not None:
                edge = replace(edge, size=float(cap_seed_to_primary_wall(edge.size, wall)))
            edges.append(edge)

    if wall_error is not None:
        unsupported.append(wall_error)

    blocking = [item for item in unsupported if item.code != "NOT_REQUESTED"]
    status = "READY" if not blocking and _positive(baseline_size) and baseline_source and wall else "BLOCKED"
    if wall_error is not None and wall_error.code == "INVALID_PRIMARY_WALL":
        status = "INVALID"
    return MeshSizeDecision(
        baseline_size=float(baseline_size) if _positive(baseline_size) else None,
        baseline_source=baseline_source if _positive(baseline_size) else None,
        edge_constraints=tuple(edges),
        unsupported=tuple(blocking),
        status=status,
        explicit_stable_increment_risk=_explicit_risk(executable if executable is not None else baseline_size, edges, solver),
        production_default="NOT_SWITCHED",
        adaptive_capability=_adaptive_status(solver, procedure, element_family),
        primary_wall_thickness=wall,
        primary_wall_source=wall_source,
        executable_baseline_size=float(executable) if executable is not None else None,
        capped_local_seed_sizes=capped_locals,
    )


def adaptive_remeshing_capability(
    solver: str,
    procedure: str,
    element_shape: str,
) -> str:
    """S6 classification. Neither status authorizes a production action."""
    return _adaptive_status(solver, procedure, element_shape)


def edge_seed_readback_script(part_expr: str, planned: Sequence[EdgeSeedConstraint]) -> str:
    """Emit getEdgeSeeds readback. Planned edges are not coverage evidence."""
    del planned
    return (
        "_abqai_edge_coverage = []\n"
        "for _abqai_edge in %s.edges:\n"
        "    try:\n"
        "        _abqai_seed = %s.getEdgeSeeds(_abqai_edge)\n"
        "    except Exception as _abqai_exc:\n"
        "        _abqai_seed = {'status': 'UNREAD', 'error': type(_abqai_exc).__name__}\n"
        "    if _abqai_seed:\n"
        "        _abqai_edge_coverage.append({\n"
        "            'edge': getattr(_abqai_edge, 'index', None),\n"
        "            'seed': _abqai_seed,\n"
        "            'evidence': 'getEdgeSeeds',\n"
        "            'coverage': 'OBSERVED_NOT_SOLVED',\n"
        "        })\n"
        "if not _abqai_edge_coverage:\n"
        "    raise RuntimeError('edge_seed_coverage_missing: planned edge seeds have no getEdgeSeeds evidence')\n"
        % (part_expr, part_expr)
    )


def _edge_constraint(kind, feature, intents):
    region = feature.get("region_expression") or feature.get("edge")
    if not region or not str(region).strip():
        return UnsupportedConstraint(kind, "analysis intent is present but the target edge is not located")
    size = feature.get("size")
    number = feature.get("number")
    if (size is None) == (number is None):
        return UnsupportedConstraint(kind, "executable edge seed needs exactly one of size or number")
    if size is not None and not _positive(size):
        return UnsupportedConstraint(kind, "edge size is not a positive finite number", "INVALID")
    if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 1):
        return UnsupportedConstraint(kind, "edge number is not an integer >= 1", "INVALID")
    chosen = sorted(intents.intersection(_EDGE_INTENTS[kind]))[0]
    evidence = tuple(str(item) for item in feature.get("evidence", ()) or ())
    if not evidence:
        evidence = ("geometric_reference:%s" % region,)
    return EdgeSeedConstraint(
        feature=kind,
        analysis_intent=chosen,
        region_expression=str(region),
        size=float(size) if size is not None else None,
        number=int(number) if number is not None else None,
        constraint=str(feature.get("constraint") or "FREE").upper(),
        evidence=evidence,
        execution="seedEdgeByNumber" if number is not None else "seedEdgeBySize",
        executed=False,
    )


def _thickness_constraint(feature, element_family, partition_proven):
    family = str(element_family or "").upper()
    if family.startswith("S") or "SHELL" in family:
        return UnsupportedConstraint(
            "thickness",
            "through-thickness layer counts do not apply to shell elements",
        )
    if not partition_proven or not feature.get("thickness_direction_edges"):
        return UnsupportedConstraint(
            "thickness",
            "through-thickness layers require a proven partition; an edge seed is not layer evidence",
        )
    return UnsupportedConstraint(
        "thickness",
        "partition evidence was supplied but no verified thickness-direction mesh exists",
    )


def _explicit_risk(baseline_size, edges, solver):
    if str(solver or "").upper() != "EXPLICIT":
        return None
    sizes = [float(baseline_size)] if _positive(baseline_size) else []
    sizes.extend(edge.size for edge in edges if edge.size is not None)
    if not sizes:
        return {
            "status": "NOT_ESTIMATED",
            "source": "no positive element size",
            "solver_reported_stable_increment": None,
            "job_submitted": False,
        }
    return {
        "status": "ESTIMATED_ONLY",
        "minimum_element_size": min(sizes),
        "minimum_element_size_source": "baseline_or_planned_edge_seed",
        "note": "estimated from element size; not the solver-reported stable time increment",
        "solver_reported_stable_increment": None,
        "job_submitted": False,
    }


def _adaptive_status(solver, procedure, element_shape):
    solver_name = str(solver or "").upper()
    if "EXPLICIT" in solver_name or "ALE" in solver_name:
        return "EXCLUDED"
    procedure_name = _norm(procedure)
    shape_name = str(element_shape or "").upper()
    if (
        solver_name == "STANDARD"
        and procedure_name in _STANDARD_ADAPTIVE_PROCEDURES
        and shape_name in _STANDARD_ADAPTIVE_SHAPES
    ):
        return "RESEARCH_ONLY"
    return "EXCLUDED"


def _positive(value):
    return (
        value is not None
        and not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _norm(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
