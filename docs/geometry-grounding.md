# Geometry grounding

Geometry grounding is the boundary between visual/engineering intent and
native Abaqus geometry. The design deliberately does not allow a vision model
to select an Abaqus Face or Edge by numeric index.

## Current pipeline

1. Abaqus/CAE exposes the active viewport camera and projection.
2. A read-only probe extracts Face centroids, normals, areas and normalized
   screen coordinates.
3. The agent receives an annotated image point.
4. The matching layer converts screen distance into one evidence channel.
5. The policy layer ranks candidates and decides whether confirmation is
   required.
6. Only after grounding is accepted may a later action layer create or modify
   Abaqus regions.

Abaqus documents the View object in terms of camera position, target, up vector,
projection, clipping-plane width/height and view offsets. Parallel projection
is therefore the first supported calibration target. Perspective remains
explicitly unsupported until it is validated against real Abaqus screenshots.
Abaqus/CAE also supports printing a viewport to PNG, which is the snapshot
used by the probe.

## Evidence model

Candidate score is normalized to [0, 1]:

- distance: 0.4
- visual: 0.4
- topology: 0.2

The current MVP only measures distance from the annotated image point.
Unmeasured visual/topology evidence is zero; it is never fabricated.

The confidence value is a policy signal derived from the top candidate and the
gap to the runner-up. It is not geometric proof.

## Safety boundaries

- no model mutation during probing or candidate generation;
- no Face/Edge index guessing from image pixels alone;
- no use of LLM confidence as geometry evidence;
- no assumption that every user image is an Abaqus viewport screenshot;
- ambiguous grounding remains confirmation-required;
- perspective projection is not silently treated as parallel projection.

## Real Abaqus entry point

src/abaqus_ai_agent/adapters/abaqus/grounding_probe.py

From an Abaqus Python console:

    from grounding_probe import run
    data = run(session, r"C:\temp\abaqus_grounding_probe.png")

The returned dictionary is plain Python data and can be transferred through the
existing MCP bridge.

The probe is intentionally read-only. Abaqus documentation also shows
session.printToFile with PNG and a viewport canvas object as a valid kernel-side
pattern.
