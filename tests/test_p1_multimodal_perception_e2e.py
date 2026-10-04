"""End-to-end integration test for P1.1 Multimodal Engineering Perception.

Proves the complete canonical pipeline:
Engineering Blueprint (PDF / Raster)
  -> Ingestion (DocumentIngestionPipeline)
  -> Raw Observations (Provider-neutral Vision)
  -> Validation & Clean Funnel (DimensionExtractor & BoundaryLoadExtractor)
  -> Canonical VisualCallout
  -> GA-2A CAD Grounding (correlate_callout_with_cad)
  -> GA-2B HITL Confirmation Gate (MultimodalHITLWorkflow)
  -> Intent Synthesis (IntentBoundarySpec / IntentLoadSpec)
  -> Unified EngineeringIntent
  -> P1.0 Product Main Entry (AbaqusAIAgent.solve_requirement)

Architectural Invariants Verified:
- Strict Fail-Closed HITL Gate: Unconfirmed callout blocks execution.
- No Silent Repair: Invalid coordinates (<0 or >1) and zero vectors are rejected.
- Single-Exit Product Acceptance: Directly verifies P1.0 solve_requirement integration.
"""

from pathlib import Path
import pytest
from PIL import Image

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.contracts.geometry import ImagePoint, ImageRegion
from abaqus_ai_agent.contracts.multimodal import (
    CalloutType,
    HITLConfirmationDecision,
    HITLStatus,
    VisualCallout,
)
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.grounding.multimodal import (
    HITLBlockedError,
    MultimodalHITLWorkflow,
    correlate_callout_with_cad,
)
from abaqus_ai_agent.perception.contracts import (
    ObservationProvenance,
    RawDimensionObservation,
    RawSymbolObservation,
    RawTextObservation,
)
from abaqus_ai_agent.perception.ingestion import IngestedPage
from abaqus_ai_agent.perception.perception_pipeline import PerceptionPipeline
from abaqus_ai_agent.perception.provider import MockVisionProvider
from abaqus_ai_agent.planning.compiler import (
    EngineeringIntent,
    IntentGeometrySpec,
)


from abaqus_ai_agent.execution.client import AbaqusExecutor


class MockExecutor(AbaqusExecutor):
    def __init__(self):
        self.executed_commands = []

    def execute(self, code, timeout=120):
        self.executed_commands.append(code)
        return {"status": "completed"}

    def inspect_odb(self, path):
        return {"status": "available", "steps": ["Step-1"]}


def _setup_blueprint_page(tmp_path: Path) -> IngestedPage:
    """Create a test engineering drawing page."""
    img_path = tmp_path / "cantilever_blueprint.png"
    img = Image.new("RGB", (1200, 900), color=(255, 255, 255))
    img.save(img_path, format="PNG")

    return IngestedPage(
        page_index=0,
        width=1200.0,
        height=900.0,
        is_vector=False,
        source_path=str(img_path),
    )


def test_p1_multimodal_perception_to_solve_requirement_full_chain(tmp_path: Path):
    """End-to-end qualification of drawing ingestion to solve_requirement compilation."""
    page = _setup_blueprint_page(tmp_path)
    prov = page.build_provenance(extraction_method="vision_ocr", provider_id="test_provider")

    # 1. Vision Provider outputs raw engineering observations
    raw_texts = [
        RawTextObservation(
            text="Material: Steel Q235",
            box=(0.02, 0.02, 0.05, 0.20),
            confidence=0.99,
            provenance=prov,
        )
    ]
    raw_symbols = [
        # Fixed root constraint at left base
        RawSymbolObservation(
            symbol_type="FIXED",
            location=(0.05, 0.50),
            text_content="Fixed base",
            confidence=0.96,
            provenance=prov,
        ),
        # Concentrated downward load at tip
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.95, 0.50),
            direction=(0.0, -1.0),
            text_content="F = 1000 N",
            confidence=0.97,
            provenance=prov,
        ),
    ]
    raw_dimensions = [
        # Span length dimension
        RawDimensionObservation(
            text="L = 100 mm",
            location=(0.50, 0.85),
            span_start=(0.05, 0.85),
            span_end=(0.95, 0.85),
            nominal_value=100.0,
            unit="mm",
            confidence=0.98,
            provenance=prov,
        )
    ]

    provider = MockVisionProvider(
        text_blocks=raw_texts,
        symbols=raw_symbols,
        dimensions=raw_dimensions,
    )
    pipeline = PerceptionPipeline(provider=provider)

    # 2. Process page through Perception Pipeline
    perception_result = pipeline.process_page(page)

    assert perception_result.valid_callout_count == 3
    assert len(perception_result.rejected_observations) == 0
    assert perception_result.confidence.overall_confidence >= 0.95

    # 3. Correlate VisualCallouts with candidate 3D CAD features (GA-2A)
    cad_candidates = [
        GroundedRegion(
            target_semantic="RootFace",
            entity_type="Face",
            entity_ids=("1",),
            anchor_point=(0.0, 5.0, 5.0),
            confidence=0.95,
            status="RESOLVED",
        ),
        GroundedRegion(
            target_semantic="TipFace",
            entity_type="Face",
            entity_ids=("2",),
            anchor_point=(100.0, 5.0, 5.0),
            confidence=0.95,
            status="RESOLVED",
        ),
    ]

    grounding_observations = pipeline.correlate_with_cad(
        perception_result=perception_result,
        cad_candidates=cad_candidates,
    )
    assert len(grounding_observations) == 3

    # 4. Mandatory Human-in-the-Loop Confirmation Gate (GA-2B)
    hitl_workflow = MultimodalHITLWorkflow(confidence_threshold=0.85)
    for obs in grounding_observations:
        hitl_workflow.register_observation(obs)

    # Multi-candidate observations must fail-closed if synthesize_specs is called prematurely
    with pytest.raises(HITLBlockedError):
        hitl_workflow.synthesize_specs()

    # Engineer reviews and confirms the grounding decisions
    for obs in hitl_workflow.list_observations():
        # Match callout to correct semantic region
        if obs.callout.semantic_intent == "FIXED_SUPPORT":
            decision = HITLConfirmationDecision(
                observation_id=obs.observation_id,
                decision="CONFIRM",
                confirmed_by="lead_engineer",
                selected_region_semantic="RootFace",
            )
        elif obs.callout.semantic_intent == "CONCENTRATED_FORCE":
            decision = HITLConfirmationDecision(
                observation_id=obs.observation_id,
                decision="CONFIRM",
                confirmed_by="lead_engineer",
                selected_region_semantic="TipFace",
            )
        else:
            # Dimension callout
            decision = HITLConfirmationDecision(
                observation_id=obs.observation_id,
                decision="CONFIRM",
                confirmed_by="lead_engineer",
            )
        hitl_workflow.confirm(decision)

    # 5. Synthesize engineering specs from confirmed observations
    bc_specs, load_specs, grounded_regions = hitl_workflow.synthesize_specs()
    assert len(bc_specs) == 1
    assert len(load_specs) == 1

    # 6. Build canonical EngineeringIntent incorporating synthesized specs
    intent = EngineeringIntent(
        id="INTENT-P1-1-CANONICAL",
        kind="linear_static",
        description="Cantilever beam analysis from 2D blueprint perception",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.30},
        boundary_conditions=tuple(bc_specs),
        loads=tuple(load_specs),
    )

    geom = IntentGeometrySpec(
        shape="cantilever_box",
        length=100.0,
        width=10.0,
        height=10.0,
    )

    # 7. Execute through P1.0 Product Main Entry solve_requirement()
    agent = AbaqusAIAgent(MockExecutor())
    task_result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        submit_job=False,  # Offline compilation & preflight verification
    )

    # Verify task result is structurally sound and preflight passed
    assert task_result.capability.capability_id == "linear_static"
    assert task_result.plan is not None
    assert len(task_result.plan.actions) >= 5  # model, part, section, step, bc, load, mesh
    # In offline mode with submit_job=False, execution correctly reports EXECUTION_FAILED (fail-closed, no false COMPLETED)
    assert task_result.status.value in ("FAILED", "BLOCKED")
    assert any("EXECUTION_FAILED" in err for err in task_result.errors)


def test_p1_multimodal_fail_closed_negative_probes(tmp_path: Path):
    """Negative probes verifying that malformed perception observations are strictly blocked."""
    page = _setup_blueprint_page(tmp_path)
    prov = page.build_provenance(extraction_method="vision_ocr", provider_id="test_provider")

    # Probe 1: Illegal coordinates (out of bounds)
    # Probe 2: Zero direction vector
    malformed_symbols = [
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(1.05, 0.5),  # Out of bounds (> 1.0)
            direction=(0.0, -1.0),
            text_content="F = 1000 N",
            provenance=prov,
        ),
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.5, 0.5),
            direction=(0.0, 0.0),  # Zero vector
            text_content="F = 2000 N",
            provenance=prov,
        ),
    ]

    pipeline = PerceptionPipeline(provider=MockVisionProvider(symbols=malformed_symbols))
    result = pipeline.process_page(page)

    assert result.valid_callout_count == 0
    assert len(result.rejected_observations) == 2

    rejection_reasons = {r.reason for r in result.rejected_observations}
    assert "COORDINATE_OUT_OF_BOUNDS" in rejection_reasons
    assert "ZERO_DIRECTION_VECTOR" in rejection_reasons

    # Probe 3: Unconfirmed HITL observation must block synthesis
    workflow = MultimodalHITLWorkflow(confidence_threshold=0.85)
    valid_callout = VisualCallout(
        callout_id="c_probe3",
        callout_type=CalloutType.ARROW.value,
        location=ImagePoint(0.5, 0.5),
        direction_vector=(0.0, -1.0),
        text_content="F = 1000 N",
        semantic_intent="CONCENTRATED_FORCE",
        magnitude=1000.0,
        unit="N",
    )
    raw_obs = correlate_callout_with_cad(
        callout=valid_callout,
        candidates=[
            GroundedRegion(
                target_semantic="Face1",
                entity_type="Face",
                entity_ids=("1",),
                anchor_point=(0.0, 0.0, 0.0),
                confidence=0.50,  # Below threshold
            )
        ],
    )
    obs = workflow.register_observation(raw_obs)

    assert obs.requires_confirmation is True
    with pytest.raises(HITLBlockedError):
        workflow.synthesize_specs()
