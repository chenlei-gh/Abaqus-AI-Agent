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
  - global/local seeding
  - biased seeding by size or number
  - mesh controls
  - explicit sweep-path assignment
  - semantic element-strategy mapping for the supported continuum subset
  - legacy native element-type assignment
  - mesh generation
  - native Abaqus mesh-quality verification
- interaction intent:
  - tie
  - contact
- job creation and submission
- INP export
- ODB field CSV export
- mesh-convergence evaluation with explicit engineering QoI metadata
- deterministic fatigue post-processing for existing Abaqus scalar stress histories:
  - Rainflow cycle counting
  - half/full-cycle weighting
  - explicit range/amplitude/mean semantics
  - Goodman, Gerber, Soderberg and Walker mean-stress correction
  - log-log S-N interpolation
  - Palmgren-Miner damage
- bounded probabilistic uncertainty execution with reproducible sampling/statistics
- deterministic experimental validation against explicit measured observations

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
- engineering QoI-aware mesh convergence;
- a declarative benchmark catalog;
- sensitivity and uncertainty contracts;
- provenance and artifact-manifest hashing;
- bounded correction policies with explicit repair authorization;
- native mesh-verification evidence preserving raw failed/warning element labels.

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

## Engineering closure status

The project has closed the non-runtime foundations for bounded uncertainty execution, numerical refinement verification, explicitly authorized one-shot correction, engineering evidence checks, mesh strategy/verification, mesh convergence QoIs, calibration, reliability, and scalar fatigue post-processing.

The remaining explicitly deferred areas are broader problem-specific methods such as FORM/SORM, Bayesian inference, critical-plane/non-proportional multiaxial fatigue, adaptive remeshing, and future release-specific validation. These are not silently represented as implemented capabilities.

A licensed Abaqus V5 R2018/B28 installation is still required for final real-machine compatibility validation.
