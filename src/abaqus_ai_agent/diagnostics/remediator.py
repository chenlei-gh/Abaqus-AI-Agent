"""P1.4 Solver Failure Remediation Generator & Applicator."""

import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.diagnostics import (
    RemediationAction,
    RemediationCategory,
    RemediationRisk,
)
from ..contracts.intent import EngineeringIntent
from .solver_patterns import DiagnosticIssue


class SolverRemediator:
    """Generates and applies auditable engineering remediations based on diagnostic issues."""

    @classmethod
    def generate_remediations(
        cls,
        issues: Sequence[DiagnosticIssue],
        intent: Optional[EngineeringIntent] = None,
        plan: Optional[Any] = None,
    ) -> Tuple[RemediationAction, ...]:
        """Produce structured RemediationActions ranked by relevance and risk."""
        remediations: List[RemediationAction] = []
        issue_ids = {iss.diagnosis_id for iss in issues}

        # 1. License issues cannot be healed by mutating engineering models
        if "LICENSE_DENIED" in issue_ids:
            remediations.append(
                RemediationAction(
                    action_id=f"rem_lic_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.UNRESOLVED,
                    diagnosis_id="LICENSE_DENIED",
                    description="Abaqus license tokens unavailable; automated solver retry is forbidden.",
                    parameters={"retry_allowed": False},
                    rationale="Model mutations cannot resolve infrastructure licensing denials.",
                    risk_level=RemediationRisk.HIGH,
                )
            )
            return tuple(remediations)

        # 2. Semantic Preservation Guard: Mechanism / Kinematics / FMBD / Connectors
        # If the intent explicitly models a kinematic mechanism, connectors, or flexible multi-body dynamics,
        # zero pivots or numerical singularities often arise from internal kinematic degrees of freedom or contact release.
        # Enforcing a blanket 6-DOF ENCASTRE boundary condition would falsely "lock" degrees of freedom that are intended
        # to move, altering the physical problem (False-Healing). This must be blocked and classified as UNRESOLVED / PROHIBITED.
        is_mechanism = False
        if intent:
            if getattr(intent, "fmbd", None) is not None:
                is_mechanism = True
            elif getattr(intent, "connectors", None):
                is_mechanism = True
            else:
                text_corpus = (
                    f"{getattr(intent, 'kind', '')} "
                    f"{getattr(intent, 'analysis_type', '')} "
                    f"{getattr(intent, 'description', '')}"
                ).lower()
                if any(k in text_corpus for k in ("mechanism", "kinematic", "linkage", "fmbd", "hinge", "slider")):
                    is_mechanism = True

        if "ZERO_PIVOT" in issue_ids or "NUMERICAL_SINGULARITY" in issue_ids:
            if is_mechanism:
                remediations.append(
                    RemediationAction(
                        action_id=f"rem_sem_{uuid.uuid4().hex[:6]}",
                        category=RemediationCategory.UNRESOLVED,
                        diagnosis_id="ZERO_PIVOT" if "ZERO_PIVOT" in issue_ids else "NUMERICAL_SINGULARITY",
                        description=(
                            "Mechanism/kinematic model degrees of freedom cannot be resolved by applying blanket ENCASTRE fixity. "
                            "Automated boundary condition lock is blocked to prevent false healing and alteration of the physical system."
                        ),
                        parameters={"retry_allowed": False, "false_healing_blocked": True},
                        rationale="Locking intended degrees of freedom in a mechanism/connector model distorts the engineering problem.",
                        risk_level=RemediationRisk.HIGH,
                    )
                )
                return tuple(remediations)

            target_region = "FixedFace"
            if intent and intent.boundary_conditions:
                # Use existing fixed region if available, else standard reference
                for bc in intent.boundary_conditions:
                    b_reg = getattr(bc, "region", None) or (bc.get("region") if isinstance(bc, dict) else None)
                    if b_reg:
                        target_region = b_reg
                        break

            remediations.append(
                RemediationAction(
                    action_id=f"rem_bc_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.BOUNDARY_CONDITION,
                    diagnosis_id="ZERO_PIVOT" if "ZERO_PIVOT" in issue_ids else "NUMERICAL_SINGULARITY",
                    description=(
                        f"Enforce full 6-DOF Encastre constraint on region '{target_region}' "
                        "to eliminate unconstrained rigid body motions causing zero pivot/singularity."
                    ),
                    parameters={
                        "region": target_region,
                        "bc_type": "ENCASTRE",
                        "name": f"BC_Remediated_{uuid.uuid4().hex[:4]}",
                    },
                    rationale="Unconstrained structural rigid body motion causes singular tangent stiffness matrix.",
                    risk_level=RemediationRisk.LOW,
                )
            )

        # 3. Cutback exhaustion / Minimum increment exceeded -> Step controls & stabilization
        if "TIME_INCREMENT_LESS_THAN_MINIMUM" in issue_ids or "TOO_MANY_CUTBACKS" in issue_ids:
            remediations.append(
                RemediationAction(
                    action_id=f"rem_step_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.STEP_CONTROLS,
                    diagnosis_id=(
                        "TIME_INCREMENT_LESS_THAN_MINIMUM"
                        if "TIME_INCREMENT_LESS_THAN_MINIMUM" in issue_ids
                        else "TOO_MANY_CUTBACKS"
                    ),
                    description=(
                        "Refine non-linear step incrementation: reduce initial_inc to 0.01, "
                        "lower min_inc to 1e-8, increase max_num_inc to 500, and activate artificial damping stabilization. "
                        "Energy dissipation ratio ALLSD/ALLIE must remain <= 5%."
                    ),
                    parameters={
                        "initial_inc": 0.01,
                        "min_inc": 1e-8,
                        "max_num_inc": 500,
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 2e-4,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale="Relaxing increment floor and providing numerical dissipation stabilizes convergence without distorting physics (dissipation <= 5%).",
                    risk_level=RemediationRisk.LOW,
                )
            )

        # 4. Contact Chatter -> Contact stabilization / damping
        if "CONTACT_CHATTER" in issue_ids:
            remediations.append(
                RemediationAction(
                    action_id=f"rem_contact_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.CONTACT_STABILIZATION,
                    diagnosis_id="CONTACT_CHATTER",
                    description="Enable contact stabilization damping to eliminate opening/closing oscillation (dissipation ratio <= 5%).",
                    parameters={
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 1e-4,
                        "contact_damping": True,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale="Transient contact open/close chattering requires viscous damping near interfacial gap closure.",
                    risk_level=RemediationRisk.LOW,
                )
            )

        # 5. Negative Eigenvalue (if not already addressed by BC or Step Controls)
        if "NEGATIVE_EIGENVALUE" in issue_ids and not any(r.category == RemediationCategory.STEP_CONTROLS for r in remediations):
            remediations.append(
                RemediationAction(
                    action_id=f"rem_eigen_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.DAMPING,
                    diagnosis_id="NEGATIVE_EIGENVALUE",
                    description="Activate automatic stabilization damping to assist non-positive-definite stiffness phases (dissipation ratio <= 5%).",
                    parameters={
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 1e-4,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale="Local instabilities or geometric pre-buckling manifest as negative eigenvalues.",
                    risk_level=RemediationRisk.LOW,
                )
            )

        return tuple(remediations)

    @classmethod
    def apply_remediations(
        cls,
        intent: EngineeringIntent,
        remediations: Sequence[RemediationAction],
    ) -> EngineeringIntent:
        """Derive an enriched EngineeringIntent incorporating the proposed remediations."""
        updated_bcs: list[Any] = list(intent.boundary_conditions or ())
        updated_metadata = dict(intent.metadata or {})
        step_controls = dict(updated_metadata.get("step_controls", {}))
        applied_records = list(updated_metadata.get("applied_remediations", []))

        for rem in remediations:
            if rem.category == RemediationCategory.BOUNDARY_CONDITION:
                params = rem.parameters
                reg = params.get("region", "FixedFace")
                bc_name = params.get("name", "BC_Healed")
                # Add or reinforce encastre boundary condition
                updated_bcs.append({
                    "name": bc_name,
                    "type": "ENCASTRE",
                    "region": reg,
                })
                applied_records.append(rem.to_dict())

            elif rem.category in (RemediationCategory.STEP_CONTROLS, RemediationCategory.DAMPING, RemediationCategory.CONTACT_STABILIZATION):
                step_controls.update(rem.parameters)
                applied_records.append(rem.to_dict())

        updated_metadata["step_controls"] = step_controls
        updated_metadata["applied_remediations"] = applied_records

        from dataclasses import replace
        return replace(
            intent,
            boundary_conditions=tuple(updated_bcs),
            metadata=updated_metadata,
        )
