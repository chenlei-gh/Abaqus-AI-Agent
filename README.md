# Abaqus AI Agent

> **Open-source AI engineering agent for Abaqus/CAE — from engineering intent to validated native Abaqus actions, solver evidence, and acceptance.**

[中文文档 / Chinese](README_CN.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## Overview

**Abaqus AI Agent** is an engineering-analysis agent for working with existing Abaqus/CAE models and native Abaqus capabilities.

It is designed to connect:

**engineering requirements → engineering intent → model inspection → geometry grounding → validated native actions → Abaqus execution → job/ODB evidence → result extraction → acceptance**

The project deliberately keeps the AI layer separate from the Abaqus solver. It does not attempt to replace Abaqus, invent a new finite-element solver, or turn arbitrary natural-language prompts into unverified geometry.

The core principle is:

> **An engineering answer is not accepted merely because an Abaqus Python call succeeded. It must be supported by model state, job artifacts, ODB data, result extraction, and explicit acceptance criteria.**

## What it does

### Engineering analysis actions

The current action layer covers:

- materials:
  - elasticity
  - density
  - plasticity
  - conductivity
  - specific heat
  - thermal expansion
- sections and section assignment
- analysis steps:
  - Static
  - Explicit Dynamics
  - Implicit Dynamics
  - Frequency
  - Heat Transfer
  - Coupled Temperature-Displacement
- step-level controls:
  - time period
  - maximum increments
  - initial/minimum/maximum increment
  - time incrementation method
  - stabilization
  - solution technique / reform kernel where applicable
- amplitudes:
  - Tabular
  - Smooth Step
  - Periodic
  - Equally Spaced
- loads:
  - Gravity
  - Pressure
  - Concentrated Force
  - Body Force
  - Body Heat Flux
  - Surface Heat Flux
- predefined fields:
  - Initial Temperature
  - Initial Stress
- boundary conditions:
  - Fixed / Encastre
  - Displacement
  - Symmetry
  - Temperature
- assembly instance operations:
  - inspection
  - translation
  - rotation
  - linear pattern
- mesh intent:
  - seeding
  - mesh generation
  - element-type intent
- interaction intent:
  - tie
  - contact
- job creation and submission
- INP export
- ODB field CSV export
- mesh-convergence evaluation
- contract-level fatigue workflow for post-processing existing Abaqus stress histories
- deterministic solver selection from engineering intent
- normalized engineering metrics from ODB result extraction
- source-first engineering report data with Markdown/HTML and optional PDF rendering
- analysis-type post-processing profiles linking solver strategy to default results/checks/plots

The action layer is intentionally extensible rather than exhaustive. Abaqus exposes a very large, release-dependent Python API; the project therefore also provides a controlled native-Python escape hatch.

### Live Abaqus execution

The execution layer supports:

- `AbaqusExecutor` abstraction
- JSON/TCP bridge execution
- in-process execution for tests
- model inspection
- job submission and status inspection
- ODB inspection
- viewport capture helpers
- batch `.inp` execution
- `cae noGUI` execution
- Abaqus Python execution
- session/runtime capability reporting
- bounded solver diagnostics
- job artifact collection

The native Python escape hatch is important: typed actions cover common, stable engineering operations without artificially limiting access to the broader Abaqus API.

### Geometry grounding

The project treats geometry selection as an evidence problem rather than a naming problem.

Current capabilities include:

- normalized image/intent contracts
- live Face/Edge descriptors
- viewport camera/projection extraction
- calibrated parallel-projection screen grounding
- candidate scoring and ranking
- confirmation policy
- JSON-safe evidence serialization
- read-only viewport PNG probing

A key safety rule is:

> **An image annotation is not evidence that a particular Abaqus Face/Edge index is the intended region.**

For example, `Face[17]` is not accepted merely because a model happens to contain a face with that index. The region must be grounded from viewport/image evidence or explicitly supplied by the user.

### Engineering credibility foundations

The repository also includes deterministic engineering-credibility primitives:

- explicit result-acceptance gating;
- reaction/load balance and energy-ratio sanity checks;
- RF, energy and contact ODB evidence extraction;
- evidence-to-engineering-check adapters;
- successive-change and Richardson/GCI numerical verification;
- a declarative benchmark catalog;
- sensitivity and uncertainty contracts;
- provenance and artifact-manifest hashing;
- bounded correction policies with explicit repair authorization.

These primitives are evidence mechanisms, not claims of physical correctness by themselves. Real benchmark execution and release-specific validation remain dependent on a licensed Abaqus runtime.

### Planning, validation, and evidence

The project provides:

- experiment input contracts
- engineering plans
- blocker and assumption reporting
- action validation
- preflight checks
- static-analysis planning
- model snapshots and state diffs
- job-status classification
- ODB metadata normalization
- field/history/frame result extraction
- acceptance evaluation
- evidence packaging
- `AbaqusAIAgent` orchestration facade

## Engineering closure

A central design goal is to close the engineering evidence loop:

```text
Acceptance Criteria
        ↓
Result Requirements
        ↓
Required Abaqus Outputs
        ↓
Job Execution
        ↓
Artifacts + ODB
        ↓
Result Extraction
        ↓
Acceptance Evaluation
        ↓
Evidence
```

This prevents a common failure mode in AI-assisted engineering tools:

```text
"Python returned successfully"
        ≠
"Abaqus model is correct"
        ≠
"Solver completed successfully"
        ≠
"Required result exists"
        ≠
"Engineering requirement is satisfied"
```

Each stage is treated as separate evidence.

## Architecture

The repository intentionally uses an action- and evidence-centric architecture rather than introducing a large autonomous orchestration layer.

```text
User / Engineering Requirements
            │
            ▼
     EngineeringIntent
            │
            ▼
     AnalysisWorkflow
            │
            ├───────────────┐
            ▼               ▼
     ModelSnapshot      Viewport / Image
            │               │
            └───────┬───────┘
                    ▼
             Geometry Grounding
                    │
                    ▼
            Validated Action
                    │
                    ▼
                 Preflight
                    │
                    ▼
                Executor
                    │
                    ▼
                 Abaqus
                    │
             ┌──────┴──────┐
             ▼             ▼
            Job         Model State
             │
             ▼
       Artifacts / Diagnostics
             │
             ▼
            ODB
             │
             ▼
      Result Requirements
             │
             ▼
      Field / History / Frame
          Extraction
             │
             ▼
         Acceptance
             │
             ▼
           Evidence
```

### Architectural boundaries

The repository separates:

| Layer | Responsibility |
|---|---|
| Contracts | Stable representations of engineering intent, model state, results, runtime information, and evidence |
| Actions | Small, explicit native-Abaqus operations |
| Builders | User-facing construction of actions |
| Validation | Parameter and semantic validation before execution |
| Preflight | Checks against the current model/runtime state |
| Script generation | Conversion of actions into Abaqus Python |
| Execution | Bridge, in-process, or batch execution |
| Inspection | Model/session/job/ODB observation |
| Results | Deterministic extraction of field/history/frame values |
| Acceptance | Requirement-specific engineering checks |
| Evidence | Machine-readable trace of what was executed and what was observed |

No single component is expected to know everything about the engineering workflow.

## Design principles

### 1. Native Abaqus first

The agent operates through Abaqus's native model and analysis interfaces wherever possible.

It does not create a parallel finite-element representation that can silently diverge from Abaqus.

### 2. Explicit actions

Actions are small and inspectable.

An action can be:

- validated,
- previewed,
- executed,
- compared with expected model state,
- associated with evidence.

### 3. Evidence before claims

The agent should distinguish:

- API invocation evidence
- model-state evidence
- job execution evidence
- solver artifact evidence
- ODB evidence
- result evidence
- acceptance evidence

These are not interchangeable.

### 4. Geometry must be grounded

Visual references must be mapped to actual Abaqus regions through explicit evidence.

The project does not silently assume that an index, name, or ordering is a stable visual identity.

### 5. No fake solver capabilities

A capability is not considered implemented merely because an API-shaped class exists.

For example, the current fatigue capability is a **contract/workflow for post-processing existing Abaqus stress histories**, not a claim that the repository contains a complete fatigue solver.

### 6. Release-aware compatibility

Abaqus Python environments are release-dependent. The external package targets modern Python, while generated Abaqus-side scripts intentionally avoid unnecessary modern Python-only syntax.

Exact native API compatibility must be verified against the installed Abaqus release.

## Installation

The external package targets **Python 3.9+**.

Clone the repository:

```bash
git clone https://github.com/chenlei-gh/Abaqus-AI-Agent.git
cd Abaqus-AI-Agent
```

Install the package:

```bash
python -m pip install -e .
```

Install test dependencies:

```bash
python -m pip install -e ".[test]"
```

Run the test suite:

```bash
python -m pytest -q
```

The normal test suite does not require a licensed Abaqus installation.

## Minimal usage

A typical workflow is conceptually:

```python
from abaqus_ai_agent.actions import static_step
from abaqus_ai_agent.actions.runner import preview

action = static_step(
    "Model-1",
    time_period=1.0,
    max_num_inc=100,
)

print(preview(action))
```

The generated script is an explicit Abaqus-native operation. It can be validated before being sent to a live Abaqus execution boundary.

For operations not yet represented by a typed builder:

```python
from abaqus_ai_agent.actions import python_action

action = python_action(
    "Model-1",
    "print(list(mdb.models.keys()))",
)
```

This escape hatch is deliberate: the action layer should not become a bottleneck for legitimate Abaqus APIs.

## Current capability status

| Area | Status |
|---|---|
| Core action contracts | Implemented |
| Materials / sections | Implemented |
| Static analysis | Implemented |
| Explicit dynamics | Implemented |
| Implicit dynamics | Implemented |
| Heat transfer | Implemented |
| Coupled temperature-displacement | Implemented |
| Amplitudes | Implemented |
| Gravity | Implemented |
| Initial temperature / stress | Implemented |
| Assembly instance operations | Implemented |
| INP export | Implemented |
| ODB CSV export | Implemented |
| Result extraction | Implemented |
| Mesh convergence | Implemented |
| Geometry grounding | Implemented for calibrated viewport/projection paths |
| Fatigue | Contract/workflow for existing stress histories |
| Arbitrary native Abaqus API access | Implemented through Python escape hatch |
| Full automatic arbitrary-photo geometry registration | Not claimed |
| Full standalone fatigue solver | Not implemented |
| CAD/Part/Sketch/Extrude generation | Intentionally deferred |
| Tosca / topology optimization automation | Intentionally deferred |

## Testing and CI

GitHub Actions runs the Python test suite on:

- pushes to `main`
- pushes to `feature/**`
- pull requests

The CI environment uses Python 3.11 and runs:

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

The repository keeps Abaqus-dependent validation separate from ordinary CI because Abaqus requires a licensed runtime and a release-specific environment.

## Abaqus R2018 / B28 validation

The project is designed to be validated against real Abaqus installations rather than declaring compatibility from API names alone.

For **Abaqus V5 R2018 / B28**, the validation sequence is:

1. generated-script smoke tests;
2. model creation / inspection;
3. `writeInput` verification;
4. small solver job;
5. job artifact inspection;
6. ODB opening;
7. result extraction;
8. CSV/evidence generation;
9. failure classification.

Compatibility should only be called **verified** after the relevant workflow has actually executed on B28.

In particular:

> **A successful Python process or exit code is not, by itself, proof that CNEXT, the intended Abaqus command, the solver job, or the expected ODB result succeeded.**

## Safety and failure boundaries

The agent intentionally refuses several unsafe assumptions:

- an ungrounded image coordinate is not an executable region;
- an Abaqus Python call returning normally is not solver-success evidence;
- a completed job is not automatically engineering acceptance;
- an ODB existing is not proof that the required result is correct;
- an API-compatible-looking parameter is not automatically release-compatible;
- model-specific contact, mesh, and release-specific operations must remain explicit when they cannot be validated generically.

These boundaries are part of the architecture, not optional documentation.

## Project scope

### In scope

- AI-assisted engineering-analysis workflows around Abaqus/CAE
- model inspection and state grounding
- native Abaqus actions
- validation and preflight
- job execution and diagnostics
- ODB/result extraction
- acceptance and evidence
- controlled extension through native Abaqus Python

### Deliberately out of scope for the current core

- replacing Abaqus's solver
- pretending to support every Abaqus API through typed wrappers
- unrestricted autonomous geometry mutation from images
- claiming a full fatigue solver without implementing the underlying numerical methods
- CAD authoring as the primary purpose of this repository
- topology optimization as a substitute for engineering requirements

## Roadmap

The near-term engineering path is:

1. keep the action/validation/evidence chain stable;
2. complete the B28 smoke-test harness;
3. execute the smoke suite on a real Abaqus R2018/B28 machine;
4. classify and fix real release-specific incompatibilities;
5. expand only the capabilities justified by real engineering workflows.

Potential future areas include:

- richer geometry grounding
- more result extraction patterns
- broader native Abaqus action coverage
- stronger job diagnostics
- more complete fatigue post-processing
- additional release-specific adapters

New capabilities should preserve the existing action → validation → execution → evidence boundaries.

## Reference projects and ecosystem

The live-execution boundary is informed by public Abaqus automation/MCP projects, including:

- [Abaqus-Control-MCP](https://github.com/forxyo/abaqus-control-mcp)
- [CAE-Agent-Hub](https://github.com/chenlei-gh/CAE-Agent-Hub)

Those projects demonstrate useful patterns such as live Abaqus bridges, arbitrary Python execution, model inspection, job monitoring, ODB inspection, and viewport interaction.

This repository builds on the general idea of a live Abaqus execution boundary while emphasizing explicit geometry grounding, validation, result requirements, acceptance, and evidence.

## Repository structure

```text
Abaqus-AI-Agent/
├── src/
│   └── abaqus_ai_agent/
│       ├── actions/          # Explicit Abaqus operations and script generation
│       ├── adapters/         # Live Abaqus/model adapters
│       ├── contracts/        # Engineering, model, result and runtime contracts
│       ├── execution/        # Executors, jobs, artifacts and batch execution
│       ├── validation/       # Validation and preflight
│       └── workflow/         # Analysis workflow definitions
├── tests/                    # Unit and contract tests
├── .github/workflows/        # CI
├── pyproject.toml
├── LICENSE
├── README.md                 # English documentation
└── README_CN.md              # Chinese documentation
```

## Contributing

Contributions are welcome when they preserve the project's engineering boundaries.

A useful contribution should normally include:

- a clear capability or defect description;
- explicit validation behavior;
- tests for deterministic logic;
- release-specific assumptions where applicable;
- evidence requirements for live Abaqus behavior;
- no unsupported claim of solver or engineering correctness.

For release-specific Abaqus APIs, prefer documenting the exact Abaqus version tested.

## License

Apache-2.0.

The repository's original license is preserved. Third-party integrations, documentation, and dependencies should retain their respective attribution and license requirements.

---

**Documentation:** [English](README.md) · [中文](README_CN.md)
