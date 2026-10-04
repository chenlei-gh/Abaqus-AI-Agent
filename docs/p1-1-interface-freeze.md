# P1.1 Interface Freeze — Corrected Contract Boundary

**Status:** FROZEN  
**Date:** 2026-10-04  
**Scope:** P1.1 perception/ingestion only

## 1. Canonical chain

```
Document/Image
  -> Ingestion
  -> Raw Observation
  -> Candidate + provenance + confidence
  -> VisualCallout
  -> existing GA-2A grounding
  -> existing GA-2B HITL
  -> EngineeringIntent
  -> existing P1.0 solve_requirement()
```

P1.1 MUST NOT introduce a second grounding, HITL, intent, evidence, acceptance, solver, or UI subsystem.

## 2. Existing contracts are authoritative

### VisualCallout
`VisualCallout` is the canonical perception output. Its `location` is an `ImagePoint` and therefore must already be in normalized [0,1] coordinates. P1.1 MUST NOT silently clamp invalid coordinates; invalid provider output is rejected as an invalid observation and retains provenance.

`region_box` must be `ImageRegion`, not a four-value bounding-box tuple. A zero `direction_vector` is invalid.

### GroundingObservation
Grounding remains the existing GA-2B responsibility. P1.1 supplies `VisualCallout`; it does not define a parallel geometry result type. Existing `GroundedRegion` is the canonical downstream region representation.

### HITL
`MultimodalHITLWorkflow` remains the only confirmation gate. P1.1 must not duplicate its state machine or invent a second confirmation threshold.

The existing workflow currently uses a 0.85 default threshold. P1.1 perception confidence may be multidimensional, but it MUST NOT silently redefine the existing workflow policy. The bridge may request confirmation; final blocking remains the existing HITL workflow.

## 3. Perception-layer contracts

P1.1 may add provider-neutral raw-observation contracts, but these are transient perception evidence, not engineering facts.

Minimum provenance fields:

- source identifier/path
- page/frame identifier
- source coordinate system and dimensions
- extraction method/provider
- provider/model identifier when applicable
- provider confidence(s)
- bounding geometry
- raw text or symbol payload where available

Provider output must follow:

```
Raw Observation
  -> structural validation
  -> semantic normalization
  -> VisualCallout candidate
  -> existing grounding/HITL
```

A provider MUST NEVER emit Abaqus Python, Abaqus region expressions, or final engineering acceptance claims.

## 4. PDF ingestion

PDF handling is explicitly two-path:

1. native/vector text and geometry extraction when available;
2. rasterization/OCR fallback for scanned or unsupported content.

The implementation must preserve page-local coordinates and a reversible mapping to source coordinates. A fixed 300 DPI is an implementation default, not a semantic contract.

## 5. Extractor boundaries

Keep geometry/dimension extraction separate from mechanical boundary/load interpretation:

- `DimensionExtractor`: dimensions, tolerances, datum/leader geometry.
- `BoundaryLoadExtractor`: load arrows, pressure/traction cues, support/constraint symbols.

Neither extractor may directly construct solver actions.

## 6. Confidence policy

No universal hard-coded `0.95` or `0.90` acceptance rule is frozen in P1.1.

Confidence is evidence metadata. It may contain independent dimensions such as:

- OCR/text confidence
- symbol/geometry confidence
- unit/semantic confidence
- spatial/CAD alignment confidence
- ambiguity indicators

Risk-sensitive confirmation is resolved by the existing grounding/HITL policy. High-risk or ambiguous observations must remain fail-closed.

## 7. No silent repair

The perception layer may normalize representation, but must not silently convert uncertain data into engineering truth.

Examples:

- invalid coordinates -> reject/flag, do not clamp;
- zero direction vector -> reject/flag, do not invent a direction;
- uncertain unit -> unresolved/confirmation, do not guess;
- ambiguous geometry -> existing grounding/HITL confirmation.

## 8. Scope of P1.1 implementation

Allowed new package:

```
src/abaqus_ai_agent/perception/
  __init__.py
  contracts.py
  provider.py
  ingestion.py
  dimension_extractor.py
  boundary_load_extractor.py
  perception_pipeline.py
```

This is an implementation boundary, not permission to create parallel domain contracts already owned by `contracts/multimodal.py`, `contracts/geometry.py`, `grounding/`, `planning/compiler.py`, `acceptance.py`, or `evidence_manifest.py`.

## 9. Required tests

At minimum:

- vector-text PDF extraction and provenance;
- scanned-image fallback;
- multi-page coordinate preservation;
- invalid coordinate rejection;
- zero-vector rejection;
- dimension extraction;
- load/support extraction;
- unit ambiguity fail-closed;
- provider-neutral mock path;
- VisualCallout compatibility;
- existing GA-2A grounding compatibility;
- existing GA-2B HITL blocking/confirmation;
- P1.0 solve_requirement integration without bypassing existing gates.

## 10. Real-machine boundary

P1.1 perception unit tests remain offline and deterministic. A real Abaqus 2025 test is required only for the final end-to-end qualification proving:

```
real drawing/image
 -> perception
 -> VisualCallout
 -> grounding
 -> HITL confirmation
 -> EngineeringIntent
 -> P1.0 solve_requirement
 -> Abaqus 2025
 -> ODB
 -> Evidence V2
 -> Acceptance
```

Physical ODB binaries remain outside Git; persisted manifests/evidence remain the CI-verifiable credential when the binary is unavailable on clean CI machines.
