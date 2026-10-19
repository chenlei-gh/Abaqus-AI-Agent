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
        #
        # Structural signals (fmbd, connectors) are authoritative. The text fallback must stay
        # narrow: a contact model is routinely described with a "slider" block, and a sliding
        # block under friction is not a kinematic mechanism. Only words that name a mechanism
        # as such are accepted.
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
                if any(
                    k in text_corpus
                    for k in ("mechanism", "kinematic", "linkage", "fmbd", "hinge")
                ):
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
                    rationale=(
                        "Unconstrained rigid-body motion can singularize the stiffness matrix. "
                        "Adding ENCASTRE changes the physical problem and requires explicit confirmation."
                    ),
                    risk_level=RemediationRisk.HIGH,
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
                        "Static stabilization dissipation ALLSD/ALLSE must be checked against an explicit threshold."
                    ),
                    parameters={
                        "initial_inc": 0.01,
                        "min_inc": 1e-8,
                        "max_num_inc": 500,
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 2e-4,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale=(
                        "Smaller increments and artificial damping can change the solved problem. "
                        "The 5% static dissipation ratio is a proposed policy for this remediation, "
                        "not proof the physics is unchanged; the acceptance gate requires it to be explicit. "
                        "Application requires explicit confirmation."
                    ),
                    risk_level=RemediationRisk.HIGH,
                )
            )

        # 4. Contact chatter OR a singular contact that never engaged -> contact
        # stabilization/damping. Both mean "the pair is not transmitting stiffness".
        # CONTACT_CHATTER is preferred when present because it names the oscillating
        # mechanism explicitly; CONTACT_OPENING covers the gap-closure failures that
        # emit no status transitions at all.
        if "CONTACT_CHATTER" in issue_ids or "CONTACT_OPENING" in issue_ids:
            source_id = "CONTACT_CHATTER" if "CONTACT_CHATTER" in issue_ids else "CONTACT_OPENING"
            remediations.append(
                RemediationAction(
                    action_id=f"rem_contact_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.CONTACT_STABILIZATION,
                    diagnosis_id=source_id,
                    description="Enable contact stabilization damping to eliminate opening/closing oscillation (static dissipation ratio against ALLSE is policy-checked).",
                    parameters={
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 1e-4,
                        "contact_damping": True,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale=(
                        "Contact damping changes interfacial dissipation. "
                        "Application requires explicit confirmation."
                    ),
                    risk_level=RemediationRisk.HIGH,
                )
            )

        # 5. Negative Eigenvalue (if not already addressed by BC or Step Controls)
        if "NEGATIVE_EIGENVALUE" in issue_ids and not any(r.category == RemediationCategory.STEP_CONTROLS for r in remediations):
            remediations.append(
                RemediationAction(
                    action_id=f"rem_eigen_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.DAMPING,
                    diagnosis_id="NEGATIVE_EIGENVALUE",
                    description="Activate automatic stabilization damping to assist non-positive-definite stiffness phases (static dissipation ratio against ALLSE is policy-checked).",
                    parameters={
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 1e-4,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale=(
                        "Automatic damping can hide or alter a physical instability. "
                        "Application requires explicit confirmation."
                    ),
                    risk_level=RemediationRisk.HIGH,
                )
            )

        # 6. Solver Stalled / Watchdog Tripped
        if "SOLVER_STALLED" in issue_ids and not any(
            r.category in (RemediationCategory.STEP_CONTROLS, RemediationCategory.CONTACT_STABILIZATION)
            for r in remediations
        ):
            remediations.append(
                RemediationAction(
                    action_id=f"rem_stall_{uuid.uuid4().hex[:6]}",
                    category=RemediationCategory.STEP_CONTROLS,
                    diagnosis_id="SOLVER_STALLED",
                    description=(
                        "Solver stalled without activity. Refine step controls with smaller initial increment "
                        "and enable stabilization damping to resolve stagnation."
                    ),
                    parameters={
                        "initial_inc": 0.01,
                        "min_inc": 1e-8,
                        "max_num_inc": 500,
                        "stabilization_method": "DAMPING_FACTOR",
                        "stabilization_magnitude": 2e-4,
                        "max_dissipation_ratio": 0.05,
                    },
                    rationale=(
                        "Process stall typically indicates severe convergence cutback deadlock or contact chattering. "
                        "Application requires explicit confirmation."
                    ),
                    risk_level=RemediationRisk.HIGH,
                )
            )

        return tuple(remediations)

    @classmethod
    def apply_remediations(
        cls,
        intent: EngineeringIntent,
        remediations: Sequence[RemediationAction],
    ) -> EngineeringIntent:
        """Derive an enriched EngineeringIntent incorporating the proposed remediations.

        Remediation categories are kept disjoint on purpose: step-level controls,
        contact-level stabilization and the stabilization-energy acceptance
        threshold are three different Abaqus control paths. Merging them into a
        single ``step_controls`` bag made ``contact_damping`` look applied while
        no contact control object ever received it.
        """
        updated_bcs: list[Any] = list(intent.boundary_conditions or ())
        updated_metadata = dict(intent.metadata or {})
        step_controls = dict(updated_metadata.get("step_controls", {}))
        contact_stabilization = dict(updated_metadata.get("contact_stabilization", {}))
        applied_records = list(updated_metadata.get("applied_remediations", []))

        def absorb_threshold(parameters: Dict[str, Any], action_id: str) -> None:
            ratio = parameters.pop("max_dissipation_ratio", None)
            if ratio is None:
                return
            updated_metadata["stabilization_energy_threshold"] = float(ratio)
            updated_metadata.setdefault(
                "stabilization_energy_threshold_source", "remediation:%s" % action_id
            )

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

            elif rem.category == RemediationCategory.CONTACT_STABILIZATION:
                params = dict(rem.parameters)
                absorb_threshold(params, rem.action_id)
                # ``stabilization_method`` is a StaticStep symbol; contact
                # stabilization is driven by stabilizeChoice instead.
                params.pop("stabilization_method", None)
                if params.pop("contact_damping", False):
                    contact_stabilization["stabilize_choice"] = "AUTOMATIC"
                magnitude = params.pop("stabilization_magnitude", None)
                if magnitude is not None:
                    contact_stabilization["damp_factor"] = float(magnitude)
                for key in ("stabilize_choice", "damp_coef", "damp_factor", "target_step"):
                    if params.get(key) is not None:
                        contact_stabilization[key] = params[key]
                applied_records.append(rem.to_dict())

            elif rem.category in (RemediationCategory.STEP_CONTROLS, RemediationCategory.DAMPING):
                params = dict(rem.parameters)
                absorb_threshold(params, rem.action_id)
                step_controls.update(params)
                applied_records.append(rem.to_dict())

        updated_metadata["step_controls"] = step_controls
        if contact_stabilization:
            updated_metadata["contact_stabilization"] = contact_stabilization
        updated_metadata["applied_remediations"] = applied_records

        from dataclasses import replace
        return replace(
            intent,
            boundary_conditions=tuple(updated_bcs),
            metadata=updated_metadata,
        )
