# Abaqus AI Agent

Open-source engineering agent for Abaqus/CAE.

## Target workflow

Experiment requirements + material data + annotated image + existing Abaqus
model → engineering intent → geometry grounding → validated Abaqus actions →
solve → ODB evidence.

The project deliberately separates:

- intent: what the experiment requires;
- grounding: which native Abaqus geometry the intent refers to;
- action: what Abaqus mutation is proposed;
- execution: how the native API is invoked;
- evidence: what the solver actually produced.

## Current status

Early MVP foundation. The current implementation focuses on the hardest
boundary: mapping an annotated image location to real Abaqus geometry without
letting an AI model invent a Face/Edge index.

Implemented:

- normalized image and engineering-intent contracts;
- normalized geometry-candidate scoring;
- candidate ranking and confirmation policy;
- Abaqus viewport/camera extraction;
- read-only Face centroid/normal/area extraction;
- parallel-projection screen grounding;
- real Abaqus viewport PNG probe;
- JSON-safe grounding serialization;
- unit tests for the pure-Python grounding layer.

Not yet claimed:

- perspective projection;
- arbitrary external photos mapped directly to CAD geometry;
- automatic mutation of BC/load regions;
- full solve/ODB workflow.

The next integration step is to validate the read-only probe against real Abaqus
screenshots, then add image-region evidence and explicit confirmation before
any model mutation.

License: Apache-2.0. The repository license is preserved as provided.
