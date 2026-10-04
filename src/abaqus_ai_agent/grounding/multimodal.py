"""GA-2B: Multimodal Engineering Perception & Intent Ingestion Engine.

Implements:
1. 2D Engineering drawing & blueprint visual callout parsing.
2. Topological correlation with 3D CAD features (reusing GA-2A projection & GroundedRegion).
3. Mandatory Human-in-the-Loop (HITL) confirmation gate state machine.
4. Fail-closed intent synthesis bridging multimodal observations to canonical IntentCompiler.

Zero Direct Code Generation:
- Vision/multimodal observations strictly translate to typed GroundingObservation
  and verified GroundedRegion instances.
- Raw Abaqus Python scripts are never fabricated by the multimodal layer.
"""

import math
import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.geometry import ImagePoint, ImageRegion, ViewProjection
from ..contracts.multimodal import (
    CalloutType,
    MultimodalSourceType,
    GroundingIntentType,
    HITLStatus,
    VisualCallout,
    BlueprintView,
    GroundingObservation,
    HITLConfirmationDecision,
)
from .feature_grounding import GroundedRegion
from .projection import (
    unproject_point_to_ray,
    select_geometry_by_ray,
    grounded_region_from_ray_selection,
)


class MultimodalGroundingError(Exception):
    """Base error for multimodal grounding issues."""
    pass


class HITLBlockedError(MultimodalGroundingError):
    """Raised when intent compilation is attempted on unconfirmed or rejected observations."""
    def __init__(self, message: str, pending_observation_ids: Sequence[str] = ()):
        super().__init__(message)
        self.pending_observation_ids = tuple(pending_observation_ids)


def parse_drawing_callout(
    callout_id: str,
    text: Optional[str] = None,
    location: Optional[ImagePoint] = None,
    direction_vector: Optional[Tuple[float, float]] = None,
    region_box: Optional[ImageRegion] = None,
    callout_type: Optional[str] = None,
) -> VisualCallout:
    """Parse text and geometric cues from a 2D drawing or image into a structured VisualCallout."""
    if location is None:
        location = ImagePoint(0.5, 0.5)

    c_type = callout_type or (CalloutType.ARROW.value if direction_vector else CalloutType.TEXT.value)

    semantic_intent = None
    magnitude = None
    unit = None

    if text:
        lower = text.lower()

        # Symmetry cues (check before generic constraint words)
        if any(w in lower for w in ("symm", "symmetry", "对称")):
            if "x" in lower:
                semantic_intent = "SYMMETRY_X"
            elif "y" in lower:
                semantic_intent = "SYMMETRY_Y"
            elif "z" in lower:
                semantic_intent = "SYMMETRY_Z"
            else:
                semantic_intent = "SYMMETRY_PLANE"
        # Boundary condition cues
        elif any(w in lower for w in ("fix", "encastre", "clamp", "fixed", "constraint", "support", "固定", "固支", "约束")):
            semantic_intent = "FIXED_SUPPORT"
        elif any(w in lower for w in ("pin", "pinned", "铰支", "简支")):
            semantic_intent = "PINNED_SUPPORT"

        # Load cues
        elif any(w in lower for w in ("pressure", "press", "压强", "压力")):
            semantic_intent = "PRESSURE"
        elif any(w in lower for w in ("force", "load", "traction", "concentrated", "集中力", "载荷", "拉力", "推力")):
            semantic_intent = "CONCENTRATED_FORCE"
        elif any(w in lower for w in ("moment", "torque", "扭矩", "力矩")):
            semantic_intent = "MOMENT"

        # Extract numeric magnitude and unit (e.g. "1000 N", "2.5 MPa", "50 kN", "100 N*mm")
        num_match = re.search(r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([a-zA-Z*^/]+)?", text)
        if num_match:
            try:
                magnitude = float(num_match.group(1))
                extracted_unit = num_match.group(2)
                if extracted_unit:
                    unit = extracted_unit.strip()
            except (ValueError, TypeError):
                pass

    return VisualCallout(
        callout_id=callout_id,
        callout_type=c_type,
        location=location,
        direction_vector=direction_vector,
        region_box=region_box,
        text_content=text,
        semantic_intent=semantic_intent,
        magnitude=magnitude,
        unit=unit,
    )


def correlate_callout_with_cad(
    callout: VisualCallout,
    candidates: Sequence[Any],
    view_projection: Optional[ViewProjection] = None,
    source_type: str = MultimodalSourceType.BLUEPRINT_VIEW.value,
    target_semantic: Optional[str] = None,
    view_id: Optional[str] = None,
) -> GroundingObservation:
    """Correlate a VisualCallout with candidate 3D CAD geometric topology.

    Consumes candidate faces/edges either directly or via 3D perspective raycasting (GA-2A).
    Produces canonical GroundedRegion instances without inventing raw Abaqus syntax.
    """
    obs_id = f"obs_{callout.callout_id}"
    semantic = target_semantic or callout.semantic_intent or "GROUNDED_TARGET"

    # Infer intent type from callout
    if callout.semantic_intent in ("FIXED_SUPPORT", "PINNED_SUPPORT", "SYMMETRY_X", "SYMMETRY_Y", "SYMMETRY_Z", "SYMMETRY_PLANE"):
        intent_type = GroundingIntentType.BOUNDARY_CONDITION.value
    elif callout.callout_type == CalloutType.DIMENSION.value or callout.semantic_intent in ("DIMENSION", "DIAMETER", "RADIUS"):
        intent_type = GroundingIntentType.DIMENSION.value
    else:
        intent_type = GroundingIntentType.LOAD.value

    # Case A: Spatial Raycast via GA-2A if ViewProjection is available
    if view_projection is not None and candidates:
        ray = unproject_point_to_ray(callout.location, view_projection)
        selected_raw = select_geometry_by_ray(ray, candidates, max_distance=10.0, backface_cull=True)
        candidate_regions = tuple(
            grounded_region_from_ray_selection(sel, target_semantic=semantic)
            for sel in selected_raw
        )
    else:
        # Case B: Direct GroundedRegion candidates or dict representations
        resolved_regions = []
        for c in candidates:
            if isinstance(c, GroundedRegion):
                resolved_regions.append(c)
            elif isinstance(c, dict):
                entity_type = c.get("entity_type", "Face")
                index = str(c.get("index", 1))
                anchor = tuple(c.get("point") or c.get("centroid") or (0.0, 0.0, 0.0))
                reg_name = target_semantic or c.get("name") or semantic
                reg_conf = float(c.get("confidence", 0.92))
                reg = GroundedRegion(
                    target_semantic=reg_name,
                    entity_type=entity_type,
                    entity_ids=(index,),
                    anchor_point=anchor,
                    confidence=reg_conf,
                    status="RESOLVED",
                    evidence=("direct_candidate",),
                )
                resolved_regions.append(reg)
        candidate_regions = tuple(resolved_regions)

    # Assess uncertainty and confidence
    uncertainty_reasons = []
    if not candidate_regions:
        uncertainty_reasons.append("ZERO_CANDIDATES_FOUND")
        confidence = 0.0
        selected_region = None
        status = HITLStatus.NEEDS_CONFIRMATION.value
        requires_confirmation = True
    elif len(candidate_regions) > 1:
        uncertainty_reasons.append("AMBIGUOUS_MULTI_CANDIDATE")
        confidence = min(0.60, min(getattr(r, "confidence", 0.60) for r in candidate_regions))
        selected_region = candidate_regions[0]
        status = HITLStatus.NEEDS_CONFIRMATION.value
        requires_confirmation = True
    else:
        # Single candidate
        selected_region = candidate_regions[0]
        cand_conf = getattr(selected_region, "confidence", 0.92)
        confidence = float(cand_conf) if cand_conf is not None else 0.92
        requires_confirmation = confidence < 0.85
        status = HITLStatus.NEEDS_CONFIRMATION.value if requires_confirmation else HITLStatus.PENDING.value

    return GroundingObservation(
        observation_id=obs_id,
        source_type=source_type,
        callout=callout,
        detected_intent_type=intent_type,
        target_topology_type=selected_region.entity_type if selected_region else "Face",
        candidate_regions=candidate_regions,
        selected_region=selected_region,
        confidence=confidence,
        uncertainty_reasons=tuple(uncertainty_reasons),
        requires_confirmation=requires_confirmation,
        status=status,
        view_id=view_id,
    )


class MultimodalHITLWorkflow:
    """Mandatory Human-in-the-Loop (HITL) Gate and Intent Synthesis Manager."""

    def __init__(self, confidence_threshold: float = 0.85):
        self.confidence_threshold = confidence_threshold
        self._observations: Dict[str, GroundingObservation] = {}
        self._decisions: Dict[str, HITLConfirmationDecision] = {}

    def register_observation(self, observation: GroundingObservation) -> GroundingObservation:
        """Register an observation and evaluate mandatory confirmation status."""
        requires_confirm = (
            observation.requires_confirmation
            or observation.confidence < self.confidence_threshold
            or len(observation.candidate_regions) != 1
            or observation.selected_region is None
        )
        status = HITLStatus.NEEDS_CONFIRMATION.value if requires_confirm else HITLStatus.PENDING.value

        updated = replace(
            observation,
            requires_confirmation=requires_confirm,
            status=status,
        )
        self._observations[updated.observation_id] = updated
        return updated

    def get_observation(self, observation_id: str) -> Optional[GroundingObservation]:
        return self._observations.get(observation_id)

    def list_observations(self) -> Sequence[GroundingObservation]:
        return tuple(self._observations.values())

    def confirm(self, decision: HITLConfirmationDecision) -> GroundingObservation:
        """Engineer explicitly confirms or refines a grounding observation."""
        obs = self._observations.get(decision.observation_id)
        if obs is None:
            raise KeyError(f"observation {decision.observation_id} not found")

        # Determine chosen candidate region
        selected_region = obs.selected_region
        if decision.selected_region_semantic:
            for cand in obs.candidate_regions:
                if cand.target_semantic == decision.selected_region_semantic:
                    selected_region = cand
                    break
        elif decision.selected_anchor_point:
            # Match nearest anchor point
            px, py, pz = decision.selected_anchor_point
            best_cand = None
            min_dist = float("inf")
            for cand in obs.candidate_regions:
                cx, cy, cz = cand.anchor_point
                dist = math.hypot(px - cx, py - cy, pz - cz)
                if dist < min_dist:
                    min_dist = dist
                    best_cand = cand
            if best_cand:
                selected_region = best_cand

        if selected_region is None and obs.candidate_regions:
            selected_region = obs.candidate_regions[0]

        # Handle override magnitude/unit on callout if provided
        updated_callout = obs.callout
        if decision.override_magnitude is not None or decision.override_unit is not None:
            mag = decision.override_magnitude if decision.override_magnitude is not None else obs.callout.magnitude
            u = decision.override_unit if decision.override_unit is not None else obs.callout.unit
            updated_callout = replace(obs.callout, magnitude=mag, unit=u)

        updated = replace(
            obs,
            callout=updated_callout,
            selected_region=selected_region,
            status=HITLStatus.CONFIRMED.value,
            requires_confirmation=False,
            confirmed_by=decision.confirmed_by,
        )
        self._observations[updated.observation_id] = updated
        self._decisions[decision.observation_id] = decision
        return updated

    def reject(self, observation_id: str, reason: str, engineer_id: str = "engineer") -> GroundingObservation:
        """Engineer explicitly rejects a grounding observation."""
        obs = self._observations.get(observation_id)
        if obs is None:
            raise KeyError(f"observation {observation_id} not found")

        updated = replace(
            obs,
            status=HITLStatus.REJECTED.value,
            rejection_reason=reason,
            confirmed_by=engineer_id,
        )
        self._observations[updated.observation_id] = updated
        return updated

    def synthesize_specs(
        self,
        fail_closed: bool = True,
    ) -> Tuple[List[Any], List[Any], Dict[str, GroundedRegion]]:
        """Synthesize IntentBoundarySpecs and IntentLoadSpecs from CONFIRMED observations.

        Fail-closed gate: If any observation requires confirmation (NEEDS_CONFIRMATION or PENDING),
        compilation is strictly blocked.
        """
        from ..planning.compiler import IntentBoundarySpec, IntentLoadSpec
        pending_ids = [
            obs.observation_id for obs in self._observations.values()
            if obs.status in (HITLStatus.NEEDS_CONFIRMATION.value, HITLStatus.PENDING.value)
        ]
        if pending_ids and fail_closed:
            raise HITLBlockedError(
                f"Multimodal intent synthesis BLOCKED: {len(pending_ids)} observation(s) pending human confirmation: {pending_ids}",
                pending_observation_ids=pending_ids,
            )

        bcs: List[IntentBoundarySpec] = []
        loads: List[IntentLoadSpec] = []
        grounded_regions: Dict[str, GroundedRegion] = {}

        for obs in self._observations.values():
            if obs.status == HITLStatus.REJECTED.value:
                continue
            if obs.status != HITLStatus.CONFIRMED.value:
                continue

            region = obs.selected_region
            if region is None:
                continue

            region_name = region.target_semantic or f"region_{obs.observation_id}"
            grounded_regions[region_name] = region

            callout = obs.callout
            if obs.detected_intent_type == GroundingIntentType.BOUNDARY_CONDITION.value:
                bc_type = "ENCASTRE"
                if callout.semantic_intent in ("SYMMETRY_X", "SYMMETRY_Y", "SYMMETRY_Z", "SYMMETRY_PLANE"):
                    bc_type = "SYMMETRY"
                elif callout.semantic_intent == "PINNED_SUPPORT":
                    bc_type = "PINNED"

                bcs.append(
                    IntentBoundarySpec(
                        name=f"BC_{obs.observation_id}",
                        bc_type=bc_type,
                        region=region_name,
                        plane=callout.semantic_intent.split("_")[-1] if "SYMMETRY_" in (callout.semantic_intent or "") else None,
                    )
                )
            elif obs.detected_intent_type == GroundingIntentType.LOAD.value:
                load_type = "pressure" if callout.semantic_intent == "PRESSURE" else "concentrated_force"
                mag = callout.magnitude if callout.magnitude is not None else 1000.0
                loads.append(
                    IntentLoadSpec(
                        name=f"Load_{obs.observation_id}",
                        load_type=load_type,
                        region=region_name,
                        magnitude=mag,
                        direction="CF3" if callout.direction_vector and callout.direction_vector[1] < 0 else "CF2",
                    )
                )

        return bcs, loads, grounded_regions
