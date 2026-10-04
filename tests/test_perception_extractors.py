"""Unit tests for P1.1 DimensionExtractor and BoundaryLoadExtractor.

Tests:
- Dimension and tolerance parsing (linear, diameter, radius, tolerances).
- Fail-closed out-of-bounds coordinate rejection (strict rejection, no clamping).
- Fail-closed zero direction vector rejection (strict rejection, no default invented).
- Orthogonality: dimensions decoupled from mechanical load / support conditions.
- Canonical VisualCallout emission conforming to multimodal contracts.
"""

import pytest

from abaqus_ai_agent.contracts.geometry import ImagePoint, ImageRegion
from abaqus_ai_agent.contracts.multimodal import CalloutType, VisualCallout
from abaqus_ai_agent.perception.boundary_load_extractor import BoundaryLoadExtractor
from abaqus_ai_agent.perception.contracts import (
    ObservationProvenance,
    RawDimensionObservation,
    RawSymbolObservation,
    RawTextObservation,
)
from abaqus_ai_agent.perception.dimension_extractor import DimensionExtractor


@pytest.fixture
def sample_provenance() -> ObservationProvenance:
    return ObservationProvenance(
        source_path="test_drawing.pdf",
        page_index=0,
        source_dimensions=(1000.0, 800.0),
        extraction_method="test",
        provider_id="mock",
    )


def test_dimension_extractor_valid_dimensions(sample_provenance: ObservationProvenance):
    extractor = DimensionExtractor()

    raw_dims = [
        RawDimensionObservation(
            text="100 ± 0.05 mm",
            location=(0.25, 0.35),
            span_start=(0.2, 0.35),
            span_end=(0.3, 0.35),
            nominal_value=100.0,
            tolerance_upper=0.05,
            tolerance_lower=-0.05,
            unit="mm",
            confidence=0.98,
            provenance=sample_provenance,
        ),
        RawDimensionObservation(
            text="Ø25 mm",
            location=(0.6, 0.4),
            confidence=0.95,
            provenance=sample_provenance,
        ),
        RawDimensionObservation(
            text="R12.5",
            location=(0.8, 0.2),
            confidence=0.92,
            provenance=sample_provenance,
        ),
    ]

    callouts, rejected = extractor.extract(raw_dims)

    assert len(rejected) == 0
    assert len(callouts) == 3

    # Check 1: 100mm linear dimension
    c0 = callouts[0]
    assert c0.callout_type == CalloutType.DIMENSION.value
    assert c0.location.x == 0.25
    assert c0.location.y == 0.35
    assert c0.magnitude == 100.0
    assert c0.unit == "mm"
    assert c0.semantic_intent == "DIMENSION"
    assert isinstance(c0.region_box, ImageRegion)
    assert c0.metadata["tolerance_upper"] == 0.05

    # Check 2: Ø25 diameter
    c1 = callouts[1]
    assert c1.callout_type == CalloutType.DIMENSION.value
    assert c1.semantic_intent == "DIAMETER"
    assert c1.magnitude == 25.0
    assert c1.unit == "mm"

    # Check 3: R12.5 radius
    c2 = callouts[2]
    assert c2.callout_type == CalloutType.DIMENSION.value
    assert c2.semantic_intent == "RADIUS"
    assert c2.magnitude == 12.5


def test_dimension_extractor_fail_closed_coordinate_rejection(sample_provenance: ObservationProvenance):
    """P1.1 Redline: Coordinates outside [0, 1] MUST be rejected, NEVER silently clamped."""
    extractor = DimensionExtractor()

    invalid_dims = [
        # x > 1.0
        RawDimensionObservation(
            text="50 mm",
            location=(1.05, 0.5),
            provenance=sample_provenance,
        ),
        # y < 0.0
        RawDimensionObservation(
            text="20 mm",
            location=(0.5, -0.02),
            provenance=sample_provenance,
        ),
        # span_start out of bounds
        RawDimensionObservation(
            text="80 mm",
            location=(0.5, 0.5),
            span_start=(-0.1, 0.5),
            span_end=(0.8, 0.5),
            provenance=sample_provenance,
        ),
    ]

    callouts, rejected = extractor.extract(invalid_dims)

    assert len(callouts) == 0
    assert len(rejected) == 3
    for rej in rejected:
        assert rej.reason == "COORDINATE_OUT_OF_BOUNDS"
        assert "clamping forbidden" in rej.detail or "out of normalized" in rej.detail


def test_boundary_load_extractor_valid_symbols(sample_provenance: ObservationProvenance):
    extractor = BoundaryLoadExtractor()

    raw_symbols = [
        # Downward concentrated force arrow
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.5, 0.1),
            direction=(0.0, -10.0),  # Should be normalized
            text_content="F = 5000 N",
            confidence=0.99,
            provenance=sample_provenance,
        ),
        # Fixed support symbol
        RawSymbolObservation(
            symbol_type="FIXED",
            location=(0.1, 0.9),
            text_content="Fixed base",
            confidence=0.95,
            provenance=sample_provenance,
        ),
        # Pressure symbol
        RawSymbolObservation(
            symbol_type="PRESSURE",
            location=(0.7, 0.7),
            direction=(0.0, -1.0),
            text_content="p = 2.5 MPa",
            confidence=0.94,
            provenance=sample_provenance,
        ),
        # Pinned support
        RawSymbolObservation(
            symbol_type="PINNED",
            location=(0.9, 0.9),
            text_content="Pinned end",
            confidence=0.93,
            provenance=sample_provenance,
        ),
    ]

    callouts, rejected = extractor.extract(raw_symbols)

    assert len(rejected) == 0
    assert len(callouts) == 4

    # Check 1: Force arrow
    f_callout = callouts[0]
    assert f_callout.callout_type == CalloutType.ARROW.value
    assert f_callout.semantic_intent == "CONCENTRATED_FORCE"
    assert f_callout.direction_vector == (0.0, -1.0)
    assert f_callout.magnitude == 5000.0
    assert f_callout.unit == "N"

    # Check 2: Fixed support
    fix_callout = callouts[1]
    assert fix_callout.callout_type == CalloutType.SYMBOL.value
    assert fix_callout.semantic_intent == "FIXED_SUPPORT"
    assert fix_callout.direction_vector is None

    # Check 3: Pressure
    p_callout = callouts[2]
    assert p_callout.callout_type == CalloutType.ARROW.value
    assert p_callout.semantic_intent == "PRESSURE"
    assert p_callout.magnitude == 2.5
    assert p_callout.unit == "MPa"

    # Check 4: Pinned support
    pin_callout = callouts[3]
    assert pin_callout.callout_type == CalloutType.SYMBOL.value
    assert pin_callout.semantic_intent == "PINNED_SUPPORT"


def test_boundary_load_extractor_fail_closed_zero_vector(sample_provenance: ObservationProvenance):
    """P1.1 Redline: Zero direction vectors MUST be rejected, NEVER given default invented direction."""
    extractor = BoundaryLoadExtractor()

    invalid_symbols = [
        # Exactly (0.0, 0.0)
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.5, 0.5),
            direction=(0.0, 0.0),
            text_content="F = 1000 N",
            provenance=sample_provenance,
        ),
        # Coordinate out of bounds
        RawSymbolObservation(
            symbol_type="FIXED",
            location=(-0.05, 0.5),
            text_content="Fixed",
            provenance=sample_provenance,
        ),
    ]

    callouts, rejected = extractor.extract(invalid_symbols)

    assert len(callouts) == 0
    assert len(rejected) == 2
    reasons = [r.reason for r in rejected]
    assert "ZERO_DIRECTION_VECTOR" in reasons
    assert "COORDINATE_OUT_OF_BOUNDS" in reasons


def test_extractor_orthogonality(sample_provenance: ObservationProvenance):
    """Ensure dimension extractor does not misclassify load cues, and vice-versa."""
    dim_extractor = DimensionExtractor()
    load_extractor = BoundaryLoadExtractor()

    text_blocks = [
        RawTextObservation(
            text="F = 20 kN downward",
            box=(0.1, 0.1, 0.15, 0.3),
            provenance=sample_provenance,
        ),
        RawTextObservation(
            text="L = 500 mm",
            box=(0.8, 0.4, 0.85, 0.6),
            provenance=sample_provenance,
        ),
        RawTextObservation(
            text="Fixed support base",
            box=(0.9, 0.1, 0.95, 0.3),
            provenance=sample_provenance,
        ),
    ]

    # Dimension extractor should ONLY pick up L = 500 mm
    dim_callouts, _ = dim_extractor.extract(dimensions=(), text_blocks=text_blocks)
    assert len(dim_callouts) == 1
    assert dim_callouts[0].magnitude == 500.0
    assert dim_callouts[0].unit == "mm"

    # Load extractor should pick up F = 20 kN and Fixed support
    load_callouts, _ = load_extractor.extract(symbols=(), text_blocks=text_blocks)
    assert len(load_callouts) == 2
    intents = {c.semantic_intent for c in load_callouts}
    assert "CONCENTRATED_FORCE" in intents
    assert "FIXED_SUPPORT" in intents
