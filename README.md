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

- materials: elasticity, density, plasticity, conductivity, specific heat, thermal expansion;
- sections and section assignment;
- analysis steps: Static, Explicit Dynamics, Implicit Dynamics, Frequency, Heat Transfer, Coupled Temperature-Displacement;
- step-level controls: time period, maximum/initial/minimum/maximum increments, time incrementation, stabilization, solution technique and reform kernel where applicable;
- amplitudes: Tabular, Smooth Step, Periodic, Equally Spaced;
- loads: Gravity, Pressure, Concentrated Force, Body Force, Body Heat Flux, Surface Heat Flux;
- predefined fields: Initial Temperature, Initial Stress;
- boundary conditions: Fixed/Encastre, Displacement, Symmetry, Temperature;
- assembly instance operations: inspection, translation, rotation, linear pattern;
- mesh intent: global/local seeding, biased seeding by size or number, mesh controls, explicit sweep-path assignment, semantic element-strategy mapping for the supported continuum subset, legacy native element-type assignment, mesh generation, native Abaqus mesh-quality verification;
- interaction intent: tie and contact;
- job creation and submission;
- INP export and ODB field CSV export;
- mesh-convergence evaluation with explicit engineering QoI metadata;
- deterministic fatigue post-processing for existing Abaqus scalar stress histories: Rainflow cycle counting, half/full-cycle weighting, explicit range/amplitude/mean semantics, Goodman/Gerber/Soderberg/Walker mean-stress correction, log-log S-N interpolation, and Palmgren-Miner damage;
- bounded probabilistic uncertainty execution with reproducible sampling/statistics;
- deterministic experimental validation against explicit measured observations.

The action layer is intentionally extensible rather than exhaustive. Abaqus exposes a very large, release-dependent Python API; the project therefore also provides a controlled native-Python escape hatch.

### Live Abaqus execution

The execution layer supports:

- `AbaqusExecutor` abstraction;
- JSON/TCP bridge execution;
- in-process execution for tests;
- model inspection;
- job submission and status inspection;
- ODB inspection;
- viewport capture helpers;
- batch `.inp` execution;
- `cae noGUI` execution;
- Abaqus Python execution;
- session/runtime capability reporting;
- bounded solver diagnostics;
- job artifact collection.

The native Python escape hatch is important: typed actions cover common, stable engineering operations without artificially limiting access to the broader Abaqus API.

### Geometry grounding

The project treats geometry selection as an evidence problem rather than a naming problem.

Current capabilities include normalized image/intent contracts, live Face/Edge descriptors, viewport camera/projection extraction, calibrated parallel-projection screen grounding, candidate scoring/ranking, confirmation policy, JSON-safe evidence serialization, and read-only viewport PNG probing.

A key safety rule is:

> **An image annotation is not evidence that a particular Abaqus Face/Edge index is the intended region.**

## Engineering credibility foundations

The repository includes deterministic engineering-credibility primitives for explicit result-acceptance gating, reaction/load balance, energy-ratio sanity checks, RF/energy/contact ODB evidence, evidence-to-engineering-check adapters, successive-change and Richardson/GCI numerical verification, engineering QoI-aware mesh convergence, declarative benchmarks, sensitivity/uncertainty contracts, provenance and artifact-manifest hashing, bounded correction policies with explicit repair authorization, and native mesh-verification evidence preserving raw failed/warning element labels.

These are evidence mechanisms, not claims of physical correctness by themselves. Real benchmark execution and release-specific validation remain dependent on a licensed Abaqus runtime.

### Planning, validation, and evidence

The project provides experiment input contracts, engineering plans, blocker/assumption reporting, action validation, preflight checks, static-analysis planning, model snapshots/state diffs, job-status classification, ODB metadata normalization, field/history/frame extraction, acceptance evaluation, evidence packaging, and the `AbaqusAIAgent` orchestration facade.

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

The project deliberately distinguishes:

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
             │             │
             ▼             ▼
       Artifacts /     State Diff
       Diagnostics         │
             │             │
             └──────┬──────┘
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

The agent operates through Abaqus's native model and analysis interfaces wherever possible. It does not create a parallel finite-element representation that can silently diverge from Abaqus.

### 2. Explicit actions

Actions are small and inspectable. An action can be validated, previewed, executed, compared with expected model state, and associated with evidence.

### 3. Evidence before claims

The agent distinguishes API invocation evidence, model-state evidence, job execution evidence, solver artifact evidence, ODB evidence, result evidence, and acceptance evidence. These are not interchangeable.

### 4. Geometry must be grounded

Visual references must be mapped to actual Abaqus regions through explicit evidence. The project does not silently assume that an index, name, or ordering is a stable visual identity.

### 5. No fake solver capabilities

A capability is not considered implemented merely because an API-shaped class exists. Current fatigue is a deterministic post-processing engine for existing scalar Abaqus stress histories; it does not claim critical-plane or non-proportional multiaxial fatigue criteria.

### 6. Release-aware compatibility

Abaqus Python environments are release-dependent. The external package targets modern Python, while generated Abaqus-side scripts intentionally avoid unnecessary modern Python-only syntax. Exact native API compatibility must be verified against the installed Abaqus release.

## Installation

The external package targets **Python 3.9+**.

```bash
git clone https://github.com/chenlei-gh/Abaqus-AI-Agent.git
cd Abaqus-AI-Agent
python -m pip install -e .
python -m pip install -e ".[test]"
python -m pytest -q
```

The normal test suite does not require a licensed Abaqus installation.

## Minimal usage

```python
from abaqus_ai_agent.actions import static_step
from abaqus_ai_agent.actions.runner import preview

action = static_step("Model-1", time_period=1.0, max_num_inc=100)
print(preview(action))
```

For a legitimate Abaqus API that is not yet represented by a typed builder:

```python
from abaqus_ai_agent.actions import python_action

action = python_action("Model-1", "print(list(mdb.models.keys()))")
```

The escape hatch is deliberate: the typed Action layer should not become a bottleneck for legitimate Abaqus APIs.

## Current capability status

| Area | Status |
|---|---|
| Core action contracts | Implemented |
| Materials / sections | Implemented |
| Static / Explicit / Implicit dynamics | Implemented |
| Heat transfer / Coupled temperature-displacement | Implemented |
| Amplitudes / loads / predefined fields / BCs | Implemented |
| Assembly instance operations | Implemented |
| INP / ODB CSV export | Implemented |
| Result extraction | Implemented |
| Mesh strategy and native mesh verification | Implemented for the supported action subset |
| Mesh convergence | Implemented with explicit QoI metadata |
| Geometry grounding | Implemented for calibrated viewport/projection paths |
| Fatigue | Implemented for deterministic scalar stress-history post-processing |
| Uncertainty / sensitivity / calibration / reliability | Implemented in bounded non-runtime workflows |
| Controlled one-shot correction | Implemented with explicit authorization |
| Arbitrary native Abaqus API access | Implemented through Python escape hatch |
| Full automatic arbitrary-photo geometry registration | Not claimed |
| Critical-plane / non-proportional multiaxial fatigue | Deferred |
| FORM/SORM | Deferred |
| Bayesian inference | Deferred |
| Adaptive remeshing | Deferred |
| CAD/Part/Sketch/Extrude generation | Intentionally deferred |
| Tosca / topology optimization automation | Intentionally deferred |

## Testing and CI

GitHub Actions runs the Python test suite on pushes to `main`, pushes to `feature/**`, and pull requests. CI uses Python 3.11 and runs:

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

Abaqus-dependent validation remains separate because Abaqus requires a licensed, release-specific runtime.

## Abaqus R2018 / B28 validation

For **Abaqus V5 R2018 / B28**, the intended validation sequence is:

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

- AI-assisted engineering-analysis workflows around Abaqus/CAE;
- model inspection and state grounding;
- native Abaqus actions;
- validation and preflight;
- job execution and diagnostics;
- ODB/result extraction;
- acceptance and evidence;
- controlled extension through native Abaqus Python.

### Deliberately out of scope for the current core

- replacing Abaqus's solver;
- pretending to support every Abaqus API through typed wrappers;
- unrestricted autonomous geometry mutation from images;
- claiming a full fatigue solver without implementing the underlying numerical methods;
- CAD authoring as the primary purpose of this repository;
- topology optimization as a substitute for engineering requirements.

## Roadmap

The near-term engineering path is to keep the action/validation/evidence chain stable, complete the B28 smoke-test harness, execute it on a real Abaqus R2018/B28 machine, classify/fix release-specific incompatibilities, and expand only capabilities justified by real engineering workflows.

Potential future areas include richer geometry grounding, more result extraction patterns, broader native Abaqus action coverage, stronger job diagnostics, more complete fatigue post-processing, and additional release-specific adapters.

New capabilities should preserve the existing action → validation → execution → evidence boundaries.

## Reference projects and ecosystem

The live-execution boundary is informed by public Abaqus automation/MCP projects, including:

- [Abaqus-Control-MCP](https://github.com/forxyo/abaqus-control-mcp)
- [CAE-Agent-Hub](https://github.com/chenlei-gh/CAE-Agent-Hub)

Those projects demonstrate useful patterns such as live Abaqus bridges, arbitrary Python execution, model inspection, job monitoring, ODB inspection, and viewport interaction. This repository emphasizes explicit geometry grounding, validation, result requirements, acceptance, and evidence.

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

Contributions are welcome when they preserve the project's engineering boundaries. Useful contributions should normally include a clear capability/defect description, explicit validation behavior, deterministic tests, release-specific assumptions where applicable, and evidence requirements for engineering claims.

## Engineering closure status

The current non-runtime closure covers bounded uncertainty execution, numerical refinement verification, explicitly authorized one-shot correction, engineering evidence checks, mesh strategy/verification, mesh convergence QoIs, calibration, reliability, and scalar fatigue post-processing.

Explicitly deferred areas include FORM/SORM, Bayesian inference, critical-plane/non-proportional multiaxial fatigue, adaptive remeshing, and future release-specific validation. These are not silently represented as implemented capabilities.

A licensed Abaqus V5 R2018/B28 installation is still required for final real-machine compatibility validation.
