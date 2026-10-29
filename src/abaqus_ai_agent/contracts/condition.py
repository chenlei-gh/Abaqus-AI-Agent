"""Evidence-backed surface treatment and contact-loading contracts.

These records do not invent plating thickness, modulus, cracking strain,
indenter size, friction, or a regulation mapping. A value without a traceable
source stays UNKNOWN and cannot authorize a formal engineering conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


EVIDENCE_STATUSES = ("VERIFIED", "USER_SPECIFIED", "ASSUMED", "UNKNOWN")
AUTHORIZING_STATUSES = ("VERIFIED", "USER_SPECIFIED")
FAILURE_MODES = ("substrate_yield", "coating_crack", "interface_debond")
LOAD_APPLICATIONS = (
    "concentrated_force",
    "pressure",
    "surface_traction",
    "rigid_indenter_contact",
    "displacement_controlled_contact",
)
INDEPENDENT_CONTACT_APPLICATIONS = (
    "rigid_indenter_contact",
    "displacement_controlled_contact",
)
# Punch motion is applied at a reference point along one global axis. A skewed
# axis is not refused here; it is refused where the punch is built, because
# nothing in this contract carries a direction vector.
_UNIT_DIRECTIONS = (
    "X", "Y", "Z", "-X", "-Y", "-Z",
    "+X", "+Y", "+Z",
    "CF1", "CF2", "CF3",
    "-CF1", "-CF2", "-CF3",
)

# Words that make a physical loading claim. They do not by themselves prove
# that a rigid indenter, a bonded patch, or a verified coating exists.
CONTACT_LOADING_CUES = (
    "压块",
    "压头",
    "顶块",
    "顶住",
    "接触加载",
    "接触施力",
    "不是固定连接",
    "非固定连接",
    "不固定连接",
    "indenter",
    "contact loading",
    "push block",
    "not bonded",
    "not a fixed connection",
)
COATING_CUES = (
    "电镀",
    "镀层",
    "镀铬",
    "镀镍",
    "表面处理",
    "electroplat",
    "chrome plate",
    "nickel plate",
    "plating",
    "plated",
    "coating",
    "coated",
)
REGULATION_CUES = (
    "ece r21",
    "gb 11552",
    "gb/t",
    "法规",
    "标准规定",
    "regulation",
    "regulatory",
)


class ConditionContractError(ValueError):
    """A surface or loading contract contradicts its own evidence status."""


def _norm_status(value: Any) -> str:
    text = str(value or "UNKNOWN").strip().upper()
    if text not in EVIDENCE_STATUSES:
        raise ConditionContractError(
            "evidence_status must be VERIFIED, USER_SPECIFIED, ASSUMED, or UNKNOWN, got %r" % (value,)
        )
    return text


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _positive(name: str, value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    if number <= 0:
        raise ConditionContractError("%s must be positive when supplied" % name)
    return number


def mentions_contact_loading(*texts: Any) -> bool:
    blob = " ".join(_clean(text).lower() for text in texts if text)
    return any(cue in blob for cue in CONTACT_LOADING_CUES)


def mentions_coating(*texts: Any) -> bool:
    blob = " ".join(_clean(text).lower() for text in texts if text)
    return any(cue in blob for cue in COATING_CUES)


def mentions_unverified_regulation(*texts: Any) -> bool:
    blob = " ".join(_clean(text).lower() for text in texts if text)
    return any(cue in blob for cue in REGULATION_CUES)


@dataclass(frozen=True)
class SurfaceTreatmentSpec:
    """A coating claim that must keep its source separate from its numbers.

    Thickness, modulus, and a cracking strain are optional evidence. They are
    never inferred from the word "plating". ASSUMED and UNKNOWN cannot support
    a formal coating-safety conclusion.
    """

    name: str
    evidence_status: str = "UNKNOWN"
    source: str = ""
    covered_region: str = ""
    region_resolved: bool = False
    thickness: Optional[float] = None
    thickness_unit: str = ""
    elastic_modulus: Optional[float] = None
    modulus_unit: str = ""
    critical_tensile_strain: Optional[float] = None
    interface_model: str = ""
    representation: str = ""
    failure_modes: Tuple[str, ...] = ()
    user_confirmed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = _norm_status(self.evidence_status)
        object.__setattr__(self, "evidence_status", status)
        object.__setattr__(self, "name", _clean(self.name) or "surface_treatment")
        object.__setattr__(self, "source", _clean(self.source))
        object.__setattr__(self, "covered_region", _clean(self.covered_region))
        object.__setattr__(self, "thickness", _positive("thickness", self.thickness))
        object.__setattr__(self, "elastic_modulus", _positive("elastic_modulus", self.elastic_modulus))
        if self.critical_tensile_strain is not None and float(self.critical_tensile_strain) <= 0:
            raise ConditionContractError("critical_tensile_strain must be positive when supplied")
        modes = tuple(_clean(mode) for mode in self.failure_modes if _clean(mode))
        unknown = [mode for mode in modes if mode not in FAILURE_MODES]
        if unknown:
            raise ConditionContractError("unsupported coating failure mode: %s" % ", ".join(unknown))
        object.__setattr__(self, "failure_modes", modes)
        if status in AUTHORIZING_STATUSES and not self.source:
            raise ConditionContractError(
                "VERIFIED or USER_SPECIFIED surface treatment requires a traceable source"
            )
        if status == "VERIFIED" and not self.user_confirmed and not self.source:
            raise ConditionContractError("VERIFIED surface treatment requires source evidence")

    @property
    def authorizes_formal_conclusion(self) -> bool:
        return (
            self.evidence_status in AUTHORIZING_STATUSES
            and bool(self.source)
            and bool(self.covered_region)
            and self.region_resolved
            and self.thickness is not None
            and self.elastic_modulus is not None
            and bool(self.failure_modes)
            and "coating_crack" in self.failure_modes
            and "substrate_yield" in self.failure_modes
        )

    def gaps(self) -> Tuple[str, ...]:
        gaps = []
        if self.evidence_status not in AUTHORIZING_STATUSES:
            gaps.append("surface_treatment_evidence_%s" % self.evidence_status.lower())
        if not self.source:
            gaps.append("surface_treatment_source_missing")
        if not self.covered_region or not self.region_resolved:
            gaps.append("surface_treatment_region_unresolved")
        if self.thickness is None:
            gaps.append("surface_treatment_thickness_unknown")
        if self.elastic_modulus is None:
            gaps.append("surface_treatment_modulus_unknown")
        if "substrate_yield" not in self.failure_modes or "coating_crack" not in self.failure_modes:
            gaps.append("surface_treatment_failure_modes_not_separated")
        if self.representation.lower() in {"skin", "shell", "shell_on_solid"} and "interface_debond" in self.failure_modes and not self.interface_model:
            gaps.append("surface_treatment_debond_not_modeled")
        return tuple(gaps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "evidence_status": self.evidence_status,
            "source": self.source,
            "covered_region": self.covered_region,
            "region_resolved": self.region_resolved,
            "thickness": self.thickness,
            "thickness_unit": self.thickness_unit,
            "elastic_modulus": self.elastic_modulus,
            "modulus_unit": self.modulus_unit,
            "critical_tensile_strain": self.critical_tensile_strain,
            "interface_model": self.interface_model,
            "representation": self.representation,
            "failure_modes": list(self.failure_modes),
            "user_confirmed": self.user_confirmed,
            "authorizes_formal_conclusion": self.authorizes_formal_conclusion,
            "gaps": list(self.gaps()),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ContactLoadingSpec:
    """How a load actually enters the part.

    A concentrated force is not evidence of a rigid indenter. A regulation name
    is not a fixture size. Friction and indenter dimensions stay unset until a
    source is supplied.
    """

    name: str
    application: str = "concentrated_force"
    evidence_status: str = "UNKNOWN"
    source: str = ""
    target_region: str = ""
    region_resolved: bool = False
    indenter_geometry: str = ""
    indenter_width: Optional[float] = None
    indenter_length: Optional[float] = None
    dimension_unit: str = ""
    direction: str = ""
    control: str = ""
    # Placement and actuation. Evidence (source, region, friction provenance) is
    # validated by ``authorizes_formal_model``; these fields describe *where* and
    # *how much*, and are validated where the punch is actually built. Both stay
    # unset until supplied: no standoff, size, or stroke is ever inferred.
    contact_point: Optional[Tuple[float, float, float]] = None
    standoff: Optional[float] = None
    magnitude: Optional[float] = None
    magnitude_unit: str = ""
    mesh_size: Optional[float] = None
    # Analytic-profile punches (a revolved cylindrical flat-bottom) are the only
    # rigid shapes CAE can build without any mesh at all. Their profile is
    # smooth except at the rim, so the rim radius has to be declared when it
    # exists; it is never invented, because it changes the contact area.
    indenter_edge_radius: Optional[float] = None
    # Which assembly instance owns ``target_region``. A face id alone does not
    # say, and picking an instance from list order would put the punch on the
    # wrong part silently.
    target_instance: str = ""
    friction_coefficient: Optional[float] = None
    friction_source: str = ""
    regulation_mapping: str = ""
    regulation_verified: bool = False
    user_confirmed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        application = _clean(self.application).lower()
        if application not in LOAD_APPLICATIONS:
            raise ConditionContractError("unsupported load application: %r" % (self.application,))
        status = _norm_status(self.evidence_status)
        object.__setattr__(self, "application", application)
        object.__setattr__(self, "evidence_status", status)
        object.__setattr__(self, "name", _clean(self.name) or "contact_loading")
        object.__setattr__(self, "source", _clean(self.source))
        object.__setattr__(self, "target_region", _clean(self.target_region))
        object.__setattr__(self, "target_instance", _clean(self.target_instance))
        object.__setattr__(self, "indenter_width", _positive("indenter_width", self.indenter_width))
        object.__setattr__(self, "indenter_length", _positive("indenter_length", self.indenter_length))
        object.__setattr__(self, "standoff", _positive("standoff", self.standoff))
        object.__setattr__(self, "magnitude", _positive("magnitude", self.magnitude))
        object.__setattr__(self, "mesh_size", _positive("mesh_size", self.mesh_size))
        object.__setattr__(
            self, "indenter_edge_radius", _positive("indenter_edge_radius", self.indenter_edge_radius)
        )
        point = self.contact_point
        if point is not None:
            try:
                coords = tuple(float(value) for value in point)
            except (TypeError, ValueError):
                raise ConditionContractError(
                    "contact_point must be three finite numbers, got %r" % (point,)
                ) from None
            if len(coords) != 3:
                raise ConditionContractError(
                    "contact_point must have three components, got %d" % len(coords)
                )
            object.__setattr__(self, "contact_point", coords)
        if self.friction_coefficient is not None and float(self.friction_coefficient) < 0:
            raise ConditionContractError("friction_coefficient must be non-negative")
        if status in AUTHORIZING_STATUSES and not self.source:
            raise ConditionContractError(
                "VERIFIED or USER_SPECIFIED contact loading requires a traceable source"
            )
        if self.regulation_mapping and not self.regulation_verified:
            raise ConditionContractError(
                "A regulation name cannot be stored as a fixture mapping unless regulation_verified=True"
            )

    @property
    def is_independent_contact(self) -> bool:
        return self.application in INDEPENDENT_CONTACT_APPLICATIONS

    @property
    def authorizes_formal_model(self) -> bool:
        if self.evidence_status not in AUTHORIZING_STATUSES or not self.source:
            return False
        if not self.target_region or not self.region_resolved or not self.direction or not self.control:
            return False
        if not self.is_independent_contact:
            return False
        if self.indenter_width is None or self.indenter_length is None or not self.indenter_geometry:
            return False
        if self.friction_coefficient is not None and not self.friction_source:
            return False
        return True

    def gaps(self) -> Tuple[str, ...]:
        gaps = []
        if not self.is_independent_contact:
            gaps.append("contact_loading_represented_as_%s" % self.application)
        if self.evidence_status not in AUTHORIZING_STATUSES:
            gaps.append("contact_loading_evidence_%s" % self.evidence_status.lower())
        if not self.source:
            gaps.append("contact_loading_source_missing")
        if not self.target_region or not self.region_resolved:
            gaps.append("contact_loading_region_unresolved")
        if not self.direction:
            gaps.append("contact_loading_direction_unknown")
        if not self.control:
            gaps.append("contact_loading_control_unknown")
        if self.indenter_width is None or self.indenter_length is None or not self.indenter_geometry:
            gaps.append("contact_loading_indenter_size_unknown")
        if self.friction_coefficient is not None and not self.friction_source:
            gaps.append("contact_loading_friction_source_missing")
        if self.regulation_mapping and not self.regulation_verified:
            gaps.append("contact_loading_regulation_unverified")
        return tuple(gaps)

    def placement_gaps(self) -> Tuple[str, ...]:
        """Inputs needed to actually build the punch, separate from evidence.

        Evidence asks "is this claim traceable?". Placement asks "where is the
        punch and how is it driven?". A spec can be fully traceable and still be
        unbuildable, so the compiler checks both and neither fills a default.
        """
        gaps = []
        if self.contact_point is None:
            gaps.append("contact_loading_contact_point_missing")
        if self.standoff is None:
            gaps.append("contact_loading_standoff_missing")
        if not str(self.magnitude_unit).strip():
            gaps.append("contact_loading_magnitude_unit_missing")
        control = str(self.control or "").strip().lower()
        if control in ("force", "load"):
            if self.magnitude is None:
                gaps.append("contact_loading_force_magnitude_missing")
        elif control in ("displacement", "displacement_controlled", "stroke"):
            if self.magnitude is None:
                gaps.append("contact_loading_stroke_missing")
        else:
            gaps.append("contact_loading_control_unknown")
        if str(self.direction or "").strip().upper() not in _UNIT_DIRECTIONS:
            gaps.append("contact_loading_direction_not_axis_aligned")
        return tuple(gaps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "application": self.application,
            "evidence_status": self.evidence_status,
            "source": self.source,
            "target_region": self.target_region,
            "region_resolved": self.region_resolved,
            "indenter_geometry": self.indenter_geometry,
            "indenter_width": self.indenter_width,
            "indenter_length": self.indenter_length,
            "dimension_unit": self.dimension_unit,
            "direction": self.direction,
            "control": self.control,
            "contact_point": list(self.contact_point) if self.contact_point is not None else None,
            "standoff": self.standoff,
            "magnitude": self.magnitude,
            "magnitude_unit": self.magnitude_unit,
            "mesh_size": self.mesh_size,
            "indenter_edge_radius": self.indenter_edge_radius,
            "target_instance": self.target_instance,
            "friction_coefficient": self.friction_coefficient,
            "friction_source": self.friction_source,
            "regulation_mapping": self.regulation_mapping,
            "regulation_verified": self.regulation_verified,
            "user_confirmed": self.user_confirmed,
            "authorizes_formal_model": self.authorizes_formal_model,
            "gaps": list(self.gaps()),
            "metadata": dict(self.metadata),
        }


def surface_treatment_from_mapping(raw: Any) -> Optional[SurfaceTreatmentSpec]:
    if raw is None:
        return None
    if isinstance(raw, SurfaceTreatmentSpec):
        return raw
    if not isinstance(raw, dict):
        raise ConditionContractError("surface treatment must be a mapping or SurfaceTreatmentSpec")
    modes = raw.get("failure_modes") or ()
    return SurfaceTreatmentSpec(
        name=str(raw.get("name") or "surface_treatment"),
        evidence_status=str(raw.get("evidence_status") or "UNKNOWN"),
        source=str(raw.get("source") or ""),
        covered_region=str(raw.get("covered_region") or raw.get("region") or ""),
        region_resolved=bool(raw.get("region_resolved")),
        thickness=raw.get("thickness"),
        thickness_unit=str(raw.get("thickness_unit") or ""),
        elastic_modulus=raw.get("elastic_modulus"),
        modulus_unit=str(raw.get("modulus_unit") or ""),
        critical_tensile_strain=raw.get("critical_tensile_strain"),
        interface_model=str(raw.get("interface_model") or ""),
        representation=str(raw.get("representation") or ""),
        failure_modes=tuple(modes),
        user_confirmed=bool(raw.get("user_confirmed")),
        metadata=dict(raw.get("metadata") or {}),
    )


def contact_loading_from_mapping(raw: Any) -> Optional[ContactLoadingSpec]:
    if raw is None:
        return None
    if isinstance(raw, ContactLoadingSpec):
        return raw
    if not isinstance(raw, dict):
        raise ConditionContractError("contact loading must be a mapping or ContactLoadingSpec")
    return ContactLoadingSpec(
        name=str(raw.get("name") or "contact_loading"),
        application=str(raw.get("application") or raw.get("type") or "concentrated_force"),
        evidence_status=str(raw.get("evidence_status") or "UNKNOWN"),
        source=str(raw.get("source") or ""),
        target_region=str(raw.get("target_region") or raw.get("region") or ""),
        region_resolved=bool(raw.get("region_resolved")),
        indenter_geometry=str(raw.get("indenter_geometry") or ""),
        indenter_width=raw.get("indenter_width"),
        indenter_length=raw.get("indenter_length"),
        dimension_unit=str(raw.get("dimension_unit") or ""),
        direction=str(raw.get("direction") or ""),
        control=str(raw.get("control") or ""),
        contact_point=raw.get("contact_point"),
        standoff=raw.get("standoff"),
        magnitude=raw.get("magnitude"),
        magnitude_unit=str(raw.get("magnitude_unit") or ""),
        mesh_size=raw.get("mesh_size"),
        indenter_edge_radius=raw.get("indenter_edge_radius"),
        target_instance=str(raw.get("target_instance") or ""),
        friction_coefficient=raw.get("friction_coefficient"),
        friction_source=str(raw.get("friction_source") or ""),
        regulation_mapping=str(raw.get("regulation_mapping") or ""),
        regulation_verified=bool(raw.get("regulation_verified")),
        user_confirmed=bool(raw.get("user_confirmed")),
        metadata=dict(raw.get("metadata") or {}),
    )


def parse_surface_treatments(raw: Any) -> Tuple[SurfaceTreatmentSpec, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (SurfaceTreatmentSpec, dict)):
        parsed = surface_treatment_from_mapping(raw)
        return () if parsed is None else (parsed,)
    return tuple(item for item in (surface_treatment_from_mapping(x) for x in raw) if item is not None)


def parse_contact_loadings(raw: Any) -> Tuple[ContactLoadingSpec, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (ContactLoadingSpec, dict)):
        parsed = contact_loading_from_mapping(raw)
        return () if parsed is None else (parsed,)
    return tuple(item for item in (contact_loading_from_mapping(x) for x in raw) if item is not None)
