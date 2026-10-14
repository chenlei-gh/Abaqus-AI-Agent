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
    """Deterministic capability mapping and physical profile resolution for an EngineeringIntent.

    ``qualification_level`` is a workflow capability label, not a certificate that
    this project, this run, or this machine has been qualified. Historical L4
    evidence lives in audited bundles and must not be copied onto a new job.
    """
    capability_id: str
    physics_domain: str
    status: CapabilityStatus
    profile: PhysicsResultProfile
    qualification_level: str = "WORKFLOW"
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


def _workflow_resolution(
    capability_id: str,
    physics_domain: str,
    profile_name: str,
    workflow_note: str,
) -> CapabilityResolution:
    """Route a supported workflow without claiming this job is already qualified."""
    return CapabilityResolution(
        capability_id=capability_id,
        physics_domain=physics_domain,
        status=CapabilityStatus.SUPPORTED,
        profile=get_physics_result_profile(profile_name),
        qualification_level="WORKFLOW",
        reason=(
            f"Workflow capability '{capability_id}' is implemented ({workflow_note}). "
            "This label is not a machine-validation certificate for the current project."
        ),
        metadata={
            "label_kind": "workflow_capability",
            "machine_validation_certificate": False,
            "qualification_scope": "workflow_only",
        },
    )


def resolve_capability(intent: Any) -> CapabilityResolution:
    """Map an EngineeringIntent to a workflow capability and PhysicsResultProfile.

    Decouples natural language / multimodal intent routing from physical capability resolution.
    Strictly fail-closed against unsupported physics domains (e.g. CFD, electromagnetics).
    A supported workflow is not evidence that this project has passed machine validation.
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
                reason=(
                    f"Physics domain '{kind}' is outside the implemented Abaqus FEA workflows. "
                    "This is a routing refusal, not a machine-validation certificate."
                ),
            )

    # 1. Flexible Multibody Dynamics (FMBD)
    if fmbd is not None or kind in ("fmbd", "flexible_multibody", "rigid_flexible_coupling"):
        return _workflow_resolution(
            "flexible_multibody", "fmbd", "fmbd",
            "flexible multibody coupling and joint workflow",
        )

    # 2. Kinematic Connectors & Joints
    if (connectors and len(connectors) > 0) or kind in ("connector", "kinematic_connector", "kinematic_connectors"):
        return _workflow_resolution(
            "kinematic_connectors", "connector", "connector",
            "CONN3D2 kinematic connector workflow",
        )

    # 3. High-Cycle Fatigue
    if fatigue is not None or kind in ("fatigue", "fatigue_damage", "high_cycle_fatigue"):
        return _workflow_resolution(
            "high_cycle_fatigue", "fatigue", "fatigue",
            "high-cycle S-N, mean-stress correction, and Miner damage workflow",
        )

    # 4. Bolt Pretension & Service
    if meta.get("bolt_pretensions") or kind in ("bolt_pretension", "bolt_service"):
        return _workflow_resolution(
            "bolt_pretension", "multi_step", "multi_step",
            "two-stage bolt pretension workflow",
        )

    # 5. Spatial Field Loading
    if meta.get("fields") or kind in ("spatial_field", "spatial_field_loading", "field_loading"):
        return _workflow_resolution(
            "spatial_field_loading", "static", "static",
            "analytic spatial load-field workflow",
        )

    # 6. Multi-Step Procedure
    if meta.get("steps") or meta.get("procedure") or kind in ("multi_step", "multi_step_procedure"):
        return _workflow_resolution(
            "multi_step_procedure", "multi_step", "multi_step",
            "multi-step procedure workflow",
        )

    # 7. Contact & Friction
    if (contacts and len(contacts) > 0) or meta.get("interactions") or kind in ("contact", "contact_frictional", "frictional_contact"):
        return _workflow_resolution(
            "contact_frictional", "contact", "contact",
            "surface-to-surface frictional contact workflow",
        )

    # 8. Sequential Thermal-Structural
    if kind in ("thermal_structural", "thermal_stress", "sequential_thermal_stress"):
        return _workflow_resolution(
            "thermal_structural", "thermal_structural", "thermal_structural",
            "sequential thermal-structural workflow",
        )

    # 9. Steady Thermal
    if kind in ("thermal", "steady_thermal", "heat_transfer", "thermal_steady"):
        return _workflow_resolution(
            "steady_thermal", "thermal", "thermal",
            "steady heat conduction and convection workflow",
        )

    # 10. Preloaded Modal
    if kind in ("preloaded_modal", "preloaded_frequency"):
        return _workflow_resolution(
            "preloaded_modal", "preloaded_modal", "preloaded_modal",
            "preload followed by frequency extraction workflow",
        )

    # 11. Modal / Frequency
    if kind in ("modal", "modal_frequency", "frequency", "eigenvalue"):
        return _workflow_resolution(
            "modal_frequency", "modal", "modal",
            "eigenvalue frequency extraction workflow",
        )

    # 12. Explicit Dynamics
    if kind in ("explicit_dynamic", "explicit", "dynamic_explicit"):
        return _workflow_resolution(
            "explicit_dynamic", "explicit_dynamic", "explicit_dynamic",
            "Abaqus/Explicit dynamic workflow",
        )

    # 13. Implicit Dynamics
    if kind in ("implicit_dynamic", "transient_dynamic", "dynamic"):
        return _workflow_resolution(
            "implicit_dynamic", "static", "static",
            "implicit dynamic transient workflow",
        )

    # 14. Nonlinear Static / Plasticity
    if kind in ("nonlinear_static", "plasticity", "large_deflection"):
        return _workflow_resolution(
            "nonlinear_static", "static", "static",
            "large-deformation and plasticity workflow",
        )

    # 15. Assembly & Kinematic Tie Interaction
    if kind in ("assembly_tie_interaction", "tie", "assembly_tie") or meta.get("tie_interactions"):
        return _workflow_resolution(
            "assembly_tie_interaction", "contact", "contact",
            "assembly surface tie workflow",
        )

    # 16. Mesh Quality & Grid Convergence Index (GCI)
    if kind in ("mesh_quality_gci", "mesh_convergence", "mesh_quality") or meta.get("mesh_convergence"):
        return _workflow_resolution(
            "mesh_quality_gci", "static", "static",
            "mesh quality and grid-convergence workflow",
        )

    # 17. Material Constitutive Intelligence & Grounding
    if kind in ("material_constitutive", "constitutive", "material_intelligence") or meta.get("constitutive_model"):
        return _workflow_resolution(
            "material_constitutive", "static", "static",
            "constitutive material workflow",
        )

    # 18. Multimodal Engineering Grounding
    if kind in ("multimodal_grounding", "grounding", "visual_grounding") or meta.get("grounded_regions"):
        return _workflow_resolution(
            "multimodal_grounding", "static", "static",
            "visual grounding workflow",
        )

    # 19. Acceptance & Evidence Reporting
    if kind in ("acceptance_reporting", "acceptance", "evidence_reporting") or meta.get("unforgeable_report"):
        return _workflow_resolution(
            "acceptance_reporting", "static", "static",
            "acceptance gate and evidence-manifest workflow",
        )

    # 20. Default / Linear Static
    return _workflow_resolution(
        "linear_static", "static", "static",
        "linear static stress and deformation workflow",
    )
