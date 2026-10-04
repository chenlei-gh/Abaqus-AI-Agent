from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .results import PhysicsResultProfile, get_physics_result_profile


class CapabilityStatus(str, Enum):
    """What the Agent can legitimately claim about an engineering operation."""

    SUPPORTED = "supported"
    ASSISTED = "assisted"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    EXECUTABLE = "executable_unverified"


@dataclass(frozen=True)
class CapabilityResult:
    """Standardized cross-cutting boundary contract across GA modules.
    
    Prevents ambiguous capabilities by requiring explicit status, clear reasoning,
    optional evidence, and actionable next steps.
    """

    capability: str
    status: CapabilityStatus
    reason: str
    evidence: Optional[Dict[str, Any]] = None
    required_user_input: Optional[str] = None
    next_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_supported(self) -> bool:
        return self.status == CapabilityStatus.SUPPORTED

    @property
    def is_blocked(self) -> bool:
        return self.status == CapabilityStatus.BLOCKED

    @property
    def needs_assistance(self) -> bool:
        return self.status == CapabilityStatus.ASSISTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "reason": self.reason,
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "required_user_input": self.required_user_input,
            "next_action": self.next_action,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityResult":
        st_raw = data.get("status", "unsupported")
        try:
            status = CapabilityStatus(st_raw)
        except (ValueError, TypeError):
            status = CapabilityStatus.UNSUPPORTED

        return cls(
            capability=str(data.get("capability", "unknown")),
            status=status,
            reason=str(data.get("reason", "")),
            evidence=data.get("evidence"),
            required_user_input=data.get("required_user_input"),
            next_action=data.get("next_action"),
            metadata=dict(data.get("metadata", {})),
        )


ALL_L4_CAPABILITIES: Tuple[str, ...] = (
    "linear_static",
    "nonlinear_static",
    "contact_frictional",
    "bolt_pretension",
    "steady_thermal",
    "thermal_structural",
    "modal_frequency",
    "preloaded_modal",
    "explicit_dynamic",
    "implicit_dynamic",
    "high_cycle_fatigue",
    "multi_step_procedure",
    "spatial_field_loading",
    "kinematic_connectors",
    "flexible_multibody",
    "assembly_tie_interaction",
    "mesh_quality_gci",
    "material_constitutive",
    "multimodal_grounding",
    "acceptance_reporting",
)


@dataclass(frozen=True)
class CapabilityResolution:
    """Deterministic capability mapping and physical profile resolution for an EngineeringIntent."""
    capability_id: str
    physics_domain: str
    status: CapabilityStatus
    profile: PhysicsResultProfile
    qualification_level: str = "L4"
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_supported(self) -> bool:
        return self.status == CapabilityStatus.SUPPORTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "physics_domain": self.physics_domain,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "qualification_level": self.qualification_level,
            "reason": self.reason,
            "required_fields": list(self.profile.required_fields),
            "required_metrics": list(self.profile.required_metrics),
            "required_gates": list(self.profile.required_gates),
            "metadata": dict(self.metadata),
        }


def resolve_capability(intent: Any) -> CapabilityResolution:
    """Map an EngineeringIntent to its canonical 20-L4 capability and PhysicsResultProfile.

    Decouples natural language / multimodal intent routing from physical capability resolution.
    Strictly fail-closed against unsupported physics domains (e.g. CFD, electromagnetics).
    """
    kind = str(getattr(intent, "kind", None) or getattr(intent, "analysis_type", None) or "linear_static").lower().strip()
    fmbd = getattr(intent, "fmbd", None)
    connectors = getattr(intent, "connectors", None)
    fatigue = getattr(intent, "fatigue", None)
    contacts = getattr(intent, "contacts", None)
    meta = getattr(intent, "metadata", {}) or {}

    # Check for unsupported explicit non-FEA physics
    unsupported_domains = ("cfd", "aerodynamics", "acoustics", "electromagnetics", "fluid", "particle")
    for unsupp in unsupported_domains:
        if unsupp in kind:
            return CapabilityResolution(
                capability_id=f"unsupported_{unsupp}",
                physics_domain="unsupported",
                status=CapabilityStatus.UNSUPPORTED,
                profile=get_physics_result_profile("static"),
                qualification_level="NONE",
                reason=f"Physics domain '{kind}' is outside the 20 L4 verified Abaqus FEA engineering capabilities.",
            )

    # 1. Flexible Multibody Dynamics (FMBD)
    if fmbd is not None or kind in ("fmbd", "flexible_multibody", "rigid_flexible_coupling"):
        return CapabilityResolution(
            capability_id="flexible_multibody",
            physics_domain="fmbd",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("fmbd"),
            qualification_level="L4",
            reason="Qualified under GA-M4 (Flexible Multibody Dynamics, coupling, and joint verification).",
        )

    # 2. Kinematic Connectors & Joints
    if (connectors and len(connectors) > 0) or kind in ("connector", "kinematic_connector", "kinematic_connectors"):
        return CapabilityResolution(
            capability_id="kinematic_connectors",
            physics_domain="connector",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("connector"),
            qualification_level="L4",
            reason="Qualified under GA-C4 (CONN3D2 kinematic connector element and relative articulation).",
        )

    # 3. High-Cycle Fatigue
    if fatigue is not None or kind in ("fatigue", "fatigue_damage", "high_cycle_fatigue"):
        return CapabilityResolution(
            capability_id="high_cycle_fatigue",
            physics_domain="fatigue",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("fatigue"),
            qualification_level="L4",
            reason="Qualified under GA-F4 (High-cycle S-N, Goodman mean-stress correction, and Miner damage).",
        )

    # 4. Bolt Pretension & Service
    if meta.get("bolt_pretensions") or kind in ("bolt_pretension", "bolt_service"):
        return CapabilityResolution(
            capability_id="bolt_pretension",
            physics_domain="multi_step",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("multi_step"),
            qualification_level="L4",
            reason="Qualified under GA-2.6.2 (Two-stage APPLY_FORCE -> FIX_LENGTH bolt lifecycle).",
        )

    # 5. Spatial Field Loading
    if meta.get("fields") or kind in ("spatial_field", "spatial_field_loading", "field_loading"):
        return CapabilityResolution(
            capability_id="spatial_field_loading",
            physics_domain="static",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("static"),
            qualification_level="L4",
            reason="Qualified under GA-2.6.2 (Analytic expression spatial load fields).",
        )

    # 6. Multi-Step Procedure
    if meta.get("steps") or meta.get("procedure") or kind in ("multi_step", "multi_step_procedure"):
        return CapabilityResolution(
            capability_id="multi_step_procedure",
            physics_domain="multi_step",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("multi_step"),
            qualification_level="L4",
            reason="Qualified under GA-2.6.2 (Multi-step procedure DAG with state inheritance).",
        )

    # 7. Contact & Friction
    if (contacts and len(contacts) > 0) or meta.get("interactions") or kind in ("contact", "contact_frictional", "frictional_contact"):
        return CapabilityResolution(
            capability_id="contact_frictional",
            physics_domain="contact",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("contact"),
            qualification_level="L4",
            reason="Qualified under Phase 1 (Surface-to-surface frictional contact interaction).",
        )

    # 8. Sequential Thermal-Structural
    if kind in ("thermal_structural", "thermal_stress", "sequential_thermal_stress"):
        return CapabilityResolution(
            capability_id="thermal_structural",
            physics_domain="thermal_structural",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("thermal_structural"),
            qualification_level="L4",
            reason="Qualified under Phase 2 (Sequential thermal-structural coupling).",
        )

    # 9. Steady Thermal
    if kind in ("thermal", "steady_thermal", "heat_transfer", "thermal_steady"):
        return CapabilityResolution(
            capability_id="steady_thermal",
            physics_domain="thermal",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("thermal"),
            qualification_level="L4",
            reason="Qualified under Phase 2 (Steady heat conduction and convection).",
        )

    # 10. Preloaded Modal
    if kind in ("preloaded_modal", "preloaded_frequency"):
        return CapabilityResolution(
            capability_id="preloaded_modal",
            physics_domain="preloaded_modal",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("preloaded_modal"),
            qualification_level="L4",
            reason="Qualified under Phase 2 (Base state preloading followed by frequency extraction).",
        )

    # 11. Modal / Frequency
    if kind in ("modal", "modal_frequency", "frequency", "eigenvalue"):
        return CapabilityResolution(
            capability_id="modal_frequency",
            physics_domain="modal",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("modal"),
            qualification_level="L4",
            reason="Qualified under Phase 2 (Lanczos eigenvalue frequency extraction).",
        )

    # 12. Explicit Dynamics
    if kind in ("explicit_dynamic", "explicit", "dynamic_explicit"):
        return CapabilityResolution(
            capability_id="explicit_dynamic",
            physics_domain="explicit_dynamic",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("explicit_dynamic"),
            qualification_level="L4",
            reason="Qualified under Phase 3 (Abaqus/Explicit wave propagation and impact).",
        )

    # 13. Implicit Dynamics
    if kind in ("implicit_dynamic", "transient_dynamic", "dynamic"):
        return CapabilityResolution(
            capability_id="implicit_dynamic",
            physics_domain="static",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("static"),
            qualification_level="L4",
            reason="Qualified under Phase 3 (Implicit dynamic transient integration).",
        )

    # 14. Nonlinear Static / Plasticity
    if kind in ("nonlinear_static", "plasticity", "large_deflection"):
        return CapabilityResolution(
            capability_id="nonlinear_static",
            physics_domain="static",
            status=CapabilityStatus.SUPPORTED,
            profile=get_physics_result_profile("static"),
            qualification_level="L4",
            reason="Qualified under Phase 1 (Nlgeom large deformation and von Mises plasticity).",
        )

    # 15. Default / Linear Static
    return CapabilityResolution(
        capability_id="linear_static",
        physics_domain="static",
        status=CapabilityStatus.SUPPORTED,
        profile=get_physics_result_profile("static"),
        qualification_level="L4",
        reason="Qualified under Phase 1 (Standard linear static stress and deformation analysis).",
    )
