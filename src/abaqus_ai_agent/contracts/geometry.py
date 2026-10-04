from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ImagePoint:
    """Normalized image coordinate, origin at top-left."""
    x: float
    y: float

    def __post_init__(self):
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("image coordinates must be in [0, 1]")


@dataclass(frozen=True)
class ImageRegion:
    center: ImagePoint
    width: float
    height: float

    def __post_init__(self):
        if not 0.0 < self.width <= 1.0 or not 0.0 < self.height <= 1.0:
            raise ValueError("region width and height must be in (0, 1]")


@dataclass(frozen=True)
class ViewProjection:
    viewport_id: str
    projection_type: str
    image_width: int
    image_height: int
    camera_position: Optional[Tuple[float, float, float]] = None
    camera_target: Optional[Tuple[float, float, float]] = None
    up_vector: Optional[Tuple[float, float, float]] = None
    view_width: Optional[float] = None
    view_height: Optional[float] = None
    view_offset_x: float = 0.0
    view_offset_y: float = 0.0
    perspective_angle: Optional[float] = None
    near_plane: Optional[float] = None
    far_plane: Optional[float] = None


@dataclass(frozen=True)
class GeometryCandidate:
    """Candidate Abaqus entity plus independent grounding evidence."""
    entity_type: str
    name: Optional[str]
    index: Optional[int]
    centroid: Optional[Tuple[float, float, float]]
    normal: Optional[Tuple[float, float, float]]
    area: Optional[float]
    distance_score: float
    visual_score: float
    topology_score: float
    screen_polygon: Optional[Tuple[Tuple[float, float], ...]] = None
    screen_path: Optional[Tuple[Tuple[float, float], ...]] = None
    entity_key: Optional[str] = None
    camera_depth: Optional[float] = None
    facing_score: Optional[float] = None
    locator_point: Optional[Tuple[float, float, float]] = None

    def __post_init__(self):
        for name, value in (
            ("distance_score", self.distance_score),
            ("visual_score", self.visual_score),
            ("topology_score", self.topology_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("%s must be in [0, 1]" % name)

    @property
    def total_score(self) -> float:
        return (0.4 * self.distance_score +
                0.4 * self.visual_score +
                0.2 * self.topology_score)


@dataclass(frozen=True)
class GroundingResult:
    """Deterministic grounding result; confidence is a policy signal, not proof."""
    intent_id: str
    candidates: List[GeometryCandidate]
    selected: Optional[GeometryCandidate]
    confidence: float
    requires_confirmation: bool
    evidence: Tuple[Tuple[str, ...], ...]

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class GeometrySelection:
    """A grouped geometric selection ready for Abaqus region binding.

    Targets are executor-neutral locators; integer geometry indices remain
    diagnostics only. region_kind is one of temporary, set, or surface.
    """
    targets: Tuple[dict, ...]
    entity_type: str
    region_kind: str = "temporary"
    name: Optional[str] = None
    surface_side: Optional[str] = None

    def __post_init__(self):
        if not self.targets:
            raise ValueError("geometry selection requires at least one target")
        if self.entity_type not in ("Face", "Edge", "Vertex"):
            raise ValueError("unsupported geometry entity type")
        if self.region_kind not in ("temporary", "set", "surface"):
            raise ValueError("region_kind must be temporary, set, or surface")
        if self.region_kind in ("set", "surface") and not self.name:
            raise ValueError("named selections require a name")
        if self.region_kind == "surface" and self.entity_type not in ("Face", "Edge"):
            raise ValueError("surfaces require Face or Edge targets")
        if self.surface_side not in (None, "side1", "side2"):
            raise ValueError("surface_side must be side1, side2, or None")


@dataclass(frozen=True)
class RegionBinding:
    """Plan for materializing a GeometrySelection in an Abaqus model."""
    region_kind: str
    name: Optional[str]
    entity_type: str
    targets: Tuple[dict, ...]
    surface_side: Optional[str] = None

    def __post_init__(self):
        if self.region_kind not in ("temporary", "set", "surface"):
            raise ValueError("unsupported region kind")
        if self.region_kind != "temporary" and not self.name:
            raise ValueError("named region requires a name")
        if self.region_kind == "surface" and self.entity_type not in ("Face", "Edge"):
            raise ValueError("surface requires Face or Edge")
        if self.surface_side not in (None, "side1", "side2"):
            raise ValueError("surface_side must be side1, side2, or None")


@dataclass(frozen=True)
class RegionReference:
    """Unified, inspectable region reference across the engineering chain.

    Acts as the canonical bridge between high-level geometry selections/bindings
    and native Abaqus region expressions.
    """
    expression: str
    kind: str = "native_expression"  # set, surface, temporary, native_expression
    name: Optional[str] = None
    entity_type: Optional[str] = None
    is_empty: bool = False
    metadata: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        if not self.is_empty and not self.expression:
            raise ValueError("non-empty RegionReference must have a non-empty expression")


def resolve_region(
    target,
    assembly_var: str = "a",
    instance_name: Optional[str] = None,
    fail_closed: bool = True,
) -> RegionReference:
    """Unified Region Resolver.

    Deterministically resolves a RegionReference from:
    - Raw string expressions (e.g. "a.sets['Set-1']", "a.instances['Beam-1'].faces[:1]")
    - RegionBinding
    - GeometrySelection
    - dict with region metadata (e.g. {'set': 'Set-1'}, {'surface': 'Surf-1'})

    Empty or nonexistent regions fail closed by default.
    """
    if target is None:
        if fail_closed:
            raise ValueError("empty or missing region reference")
        return RegionReference(expression="", is_empty=True)

    if isinstance(target, RegionReference):
        if target.is_empty and fail_closed:
            raise ValueError("empty region reference cannot be materialized")
        return target

    if isinstance(target, str):
        expr = target.strip()
        if not expr:
            if fail_closed:
                raise ValueError("empty region expression string")
            return RegionReference(expression="", is_empty=True)
        # Inspect string for common semantic patterns
        kind = "native_expression"
        name = None
        if ".sets['" in expr or '.sets["' in expr:
            kind = "set"
            try:
                name = expr.split(".sets[")[1].split("]")[0].strip("'\"")
            except IndexError:
                pass
        elif ".surfaces['" in expr or '.surfaces["' in expr:
            kind = "surface"
            try:
                name = expr.split(".surfaces[")[1].split("]")[0].strip("'\"")
            except IndexError:
                pass
        return RegionReference(expression=expr, kind=kind, name=name)

    if isinstance(target, RegionBinding):
        if not target.targets and target.region_kind == "temporary":
            if fail_closed:
                raise ValueError("temporary RegionBinding contains no targets")
            return RegionReference(expression="", is_empty=True)
        if target.region_kind == "set":
            expr = f"{assembly_var}.sets['{target.name}']"
            return RegionReference(expression=expr, kind="set", name=target.name, entity_type=target.entity_type)
        if target.region_kind == "surface":
            expr = f"{assembly_var}.surfaces['{target.name}']"
            return RegionReference(expression=expr, kind="surface", name=target.name, entity_type=target.entity_type)
        # Temporary target binding
        expr = f"{assembly_var}.sets['{target.name}']" if target.name else f"{assembly_var}"
        return RegionReference(expression=expr, kind="temporary", name=target.name, entity_type=target.entity_type)

    if isinstance(target, GeometrySelection):
        if not target.targets:
            if fail_closed:
                raise ValueError("GeometrySelection contains no targets")
            return RegionReference(expression="", is_empty=True)
        binding = RegionBinding(
            region_kind=target.region_kind,
            name=target.name,
            entity_type=target.entity_type,
            targets=target.targets,
            surface_side=target.surface_side,
        )
        return resolve_region(binding, assembly_var=assembly_var, instance_name=instance_name, fail_closed=fail_closed)

    if isinstance(target, dict):
        if "region_expression" in target:
            return resolve_region(target["region_expression"], assembly_var=assembly_var, instance_name=instance_name, fail_closed=fail_closed)
        if "set" in target or "set_name" in target:
            name = str(target.get("set") or target.get("set_name"))
            return RegionReference(expression=f"{assembly_var}.sets['{name}']", kind="set", name=name)
        if "surface" in target or "surface_name" in target:
            name = str(target.get("surface") or target.get("surface_name"))
            return RegionReference(expression=f"{assembly_var}.surfaces['{name}']", kind="surface", name=name)
        if "targets" in target:
            if not target["targets"]:
                if fail_closed:
                    raise ValueError("region dict targets list is empty")
                return RegionReference(expression="", is_empty=True)
            name = target.get("name")
            kind = target.get("kind", "temporary")
            entity_type = target.get("entity_type", "Face")
            expr = f"{assembly_var}.sets['{name}']" if name else f"{assembly_var}"
            return RegionReference(expression=expr, kind=kind, name=name, entity_type=entity_type)

    raise TypeError(f"unsupported region target type: {type(target).__name__}")
