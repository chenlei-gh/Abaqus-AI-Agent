"""P1.2 Intent Reasoning Engine: Unified Orchestrator for Parameter Reasoning & HITL."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from ..contracts.intent import EngineeringIntent
from ..contracts.intent_reasoning import (
    InferenceRiskLevel,
    InferredParameter,
    IntentReasoningResult,
    PlausibilityCheckResult,
    PlausibilitySeverity,
    ReasoningStatus,
)
from ..planning.compiler import IntentMeshSpec
from .material_catalog import match_engineering_material
from .mesh_inference import infer_mesh_specification
from .plausibility import audit_engineering_plausibility


class IntentReasoningEngine:
    """Professional CAE engineering reasoning, parameter synthesis, and fail-closed governance gate."""

    @classmethod
    def reason(
        cls,
        intent: EngineeringIntent,
        geometry: Any = None,
        material: Any = None,
        mesh: Any = None,
        grounded_regions: Any = None,
        strict_hitl: bool = True,
    ) -> IntentReasoningResult:
        """Execute comprehensive intent reasoning, parameter completion, and engineering plausibility checks."""
        inferences: List[InferredParameter] = []
        blockers: List[str] = []
        clarifications: List[str] = []

        # -------------------------------------------------------------
        # 1. Geometry Prerequisite Check
        # -------------------------------------------------------------
        has_geom = (
            geometry is not None
            or (intent.metadata and ("geometry" in intent.metadata or "dimensions" in intent.metadata))
        )
        if not has_geom:
            geom_msg = (
                "Cannot compile engineering intent: missing geometry specification. "
                "Provide geometry via intent.metadata['geometry'] or explicit geometry parameter."
            )
            blockers.append(geom_msg)
            clarifications.append(geom_msg)

        # -------------------------------------------------------------
        # 2. Material Common-Sense Matching & Property Completion
        # -------------------------------------------------------------
        raw_mat = material if material is not None else intent.material
        resolved_mat, mat_inf = match_engineering_material(raw_mat)
        if mat_inf is not None:
            inferences.append(mat_inf)

        if resolved_mat is None:
            # Check if material is an arbitrary dictionary with required numbers
            if isinstance(raw_mat, dict) and ("elastic_modulus" in raw_mat or "youngs_modulus" in raw_mat):
                resolved_mat = raw_mat
            else:
                mat_msg = (
                    "Cannot compile engineering intent: missing material specification. "
                    "Provide material via intent.material or explicit material parameter."
                )
                blockers.append(mat_msg)
                clarifications.append(mat_msg)

        # -------------------------------------------------------------
        # 3. Geometric & Physics-Driven Mesh Specification Inference
        # -------------------------------------------------------------
        resolved_mesh, mesh_inf = infer_mesh_specification(intent, geometry=geometry, explicit_mesh=mesh)
        if mesh_inf is not None:
            inferences.append(mesh_inf)

        # -------------------------------------------------------------
        # 4. Engineering Physical Plausibility & Consistency Auditing
        # -------------------------------------------------------------
        plausibility_results = audit_engineering_plausibility(
            intent=intent,
            material=resolved_mat,
            geometry=geometry,
        )

        for check in plausibility_results:
            if not check.passed:
                if check.severity == PlausibilitySeverity.CRITICAL:
                    blockers.append(f"{check.check_name}: {check.message}")
                    clarifications.append(f"[{check.check_name.upper()}] {check.message}")
                elif check.severity == PlausibilitySeverity.WARNING:
                    # Warnings logged to inferences
                    inferences.append(
                        InferredParameter(
                            parameter_name=check.check_name,
                            inferred_value="WARNING",
                            source="engineering_plausibility_audit",
                            risk_level=InferenceRiskLevel.MEDIUM,
                            rationale=check.message,
                        )
                    )

        # -------------------------------------------------------------
        # 5. Tiered HITL Decision Gate & State Determination
        # -------------------------------------------------------------
        has_critical = any(not c.passed and c.severity == PlausibilitySeverity.CRITICAL for c in plausibility_results)
        if blockers or has_critical:
            status = ReasoningStatus.BLOCKED
            clarification_prompt = "\n".join(clarifications) if clarifications else "Model definition contains critical engineering inconsistencies."
            return IntentReasoningResult(
                status=status,
                enriched_intent=intent,
                inferred_mesh=resolved_mesh,
                inferred_material=resolved_mat,
                inferences=tuple(inferences),
                plausibility_checks=plausibility_results,
                clarification_prompt=clarification_prompt,
                blockers=tuple(blockers),
                metadata={"inferences_count": len(inferences)},
            )

        # -------------------------------------------------------------
        # 5. Enrich Intent with Inferred Specifications
        # -------------------------------------------------------------
        enriched_metadata = dict(intent.metadata or {})
        enriched_metadata["reasoning_inferences"] = [inf.to_dict() for inf in inferences]
        enriched_metadata["plausibility_passed"] = True

        enriched_intent = replace(
            intent,
            material=resolved_mat if resolved_mat is not None else intent.material,
            metadata=enriched_metadata,
        )

        has_medium_risk = any(inf.risk_level == InferenceRiskLevel.MEDIUM for inf in inferences)
        status = ReasoningStatus.ASSISTED if has_medium_risk else ReasoningStatus.RESOLVED

        return IntentReasoningResult(
            status=status,
            enriched_intent=enriched_intent,
            inferred_mesh=resolved_mesh,
            inferred_material=resolved_mat,
            inferences=tuple(inferences),
            plausibility_checks=plausibility_results,
            clarification_prompt=None,
            blockers=(),
            metadata={"inferences_count": len(inferences)},
        )
