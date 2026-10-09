# Engineering Run / Evidence Closure Roadmap

**Status:** 
- **RC 1.0 Baseline (Historical)**: Initially frozen at 17 L4 + 3 L3; post-RC1 evolutionary tracks (GA-F4 Fatigue, GA-C4 Connectors, GA-M4 FMBD) have now formally promoted all remaining domains to **20 L4 / 0 L3 (100% Agent Full-Chain Qualified)** on live Abaqus 2025.
- **Current Operational Baseline**: **20 L4 / 0 L3 Full-Chain Qualified**; Strategic focus permanently transitioned from solver domain expansion to **Commercial Productization & Engineering Grounding (P1)**. 🚀
**Version:** 2026-10-04 (Full 20 L4 Physical Engineering Domains Qualified; Productization Transition)
**Scope:** Abaqus-AI-Agent engineering architecture, foundational contracts, evidence chain, real-machine physics benchmarks, and material intelligence grounding

---

## RC1 Frozen Product Qualification

RC1 freezes the existing engineering capability boundary rather than expanding the feature count.

### 20-domain qualification split

- **20 L4 Agent Full-Chain domains:** Linear Static; Nonlinear Static; Contact & Friction; Bolt Pretension; Thermal; Sequential Thermal-Structural; Modal/Frequency; Preloaded Modal; Explicit Dynamics; Implicit Dynamics; High-Cycle Fatigue; Multi-Step Procedure; Spatial Field Loading; Kinematic Connectors; Flexible Multibody (FMBD); Assembly & Tie Interaction; Mesh Quality & GCI; Material Constitutive; Boundary & Load Grounding; Result Acceptance & Engineering Report.
- **0 L3 Specialized Workflow domains remaining:** All 20 physical engineering domains fully qualified at L4 Agent Full-Chain.

L4 requires the canonical path:

`EngineeringIntent → compile_intent_to_actions → AnalysisRun → Preflight → Abaqus 2025 → ODB → Evidence V2 → Verification → Acceptance → Engineering Report`

L3 requires a bounded, real-Abaqus, evidence-backed specialized workflow, but does **not** claim generic main-entry Intent-to-Solver coverage.

### Three-tier validation hierarchy

| Tier | Purpose | RC1 gate |
|---|---|---|
| **Tier A — Real-Machine Physics** | Authentic Abaqus 2025 solver, real ODB, physics-specific metrics | Required for every physical-domain qualification |
| **Tier B — Engineering Trust** | Preflight, verification, Evidence V2, deterministic Acceptance, fail-closed negative paths | Required before an engineering conclusion can be accepted |
| **Tier C — Product Delivery** | Agent routing/compiler chain, AnalysisRun traceability, reporting and reproducibility | Required for L4; bounded for L3 |

### False-PASS closure

RC1 records **zero production False-PASS bypasses**. The production code audit confirms:

1. `ACCEPTED` requires passing Acceptance **and** `result_source == "odb"`.
2. `external_input` cannot become `ACCEPTED`.
3. Canonical ODB acceptance requires Evidence V2 integrity and expected run identity.
4. Preflight is mandatory before Job creation/submission.
5. Tampered, stale, incomplete, or run-ID-mismatched evidence fails closed.
6. No second production Acceptance state machine was identified.

### RC1 freeze rule

No new physical-domain claim may be promoted to L4 without a new real-machine Agent Full-Chain qualification and corresponding Evidence V2 artifact. Specialized workflows remain L3 until their main Agent entry path is independently qualified. RC1 documentation must preserve these boundaries and must not imply universal Abaqus keyword coverage.

## 1. Purpose

This document is the implementation/audit checklist for the next phase of Abaqus-AI-Agent.

Its purpose is to prevent capability drift and omissions. Any future change to the engineering core should be checked against this document before implementation.

The project should **not** return to feature-count expansion as its primary strategy. The next phase is to close and productize the existing engineering chain:

```
Engineering Intent
→ Solver Selection
→ Post-Processing Profile
→ Effective Result Criteria
→ Output Planning
→ Native Abaqus Output Requests
→ Job Execution
→ Artifacts / ODB
→ Result Extraction
→ Verification
→ Acceptance
→ Engineering Status
→ Evidence
→ Engineering Report
```

The current repository already contains the core of this chain. The goal is to strengthen and unify it rather than create parallel architectures.

---

## 2. Final Architectural Decision

### 2.1 Existing `AnalysisRun` is the canonical Engineering Run

**Do not create a separate Capsule / EngineeringRun subsystem.**

The existing:

- `execution/analysis_run.py`
- `contracts/metrics.py`
- `engineering_evidence.py`
- `acceptance.py`
- `provenance.py`
- `reporting/`
- `evidence/`

should converge around `AnalysisRun` as the canonical persisted engineering execution record.

Conceptual target:

```
AnalysisRun
├── intent
├── assumptions
├── solver_selection
├── postprocess_profile
├── action_plan
├── model_snapshot
├── runtime
├── solver
├── inputs
├── artifacts
├── outputs
├── metrics
├── verification
├── acceptance
├── diagnostics
├── provenance
└── report_reference
```

Do not introduce another object that duplicates these responsibilities.

---

## 3. External Design Ideas to Absorb

The following reference projects were reviewed at code level, not only by README:

- Tomsabay/abaqus_agent
- Cai-aa/CAE-Agent-Hub
- Whfkl/Abaqus-Control-MCP
- Cai-aa/abaqus-mcp
- jasonanewcoder/abaqus_skills

The following ideas are approved for absorption **only when mapped into the existing architecture**.

| Reference idea | Target in this project | Decision |
|---|---|---|
| Experiment Capsule / manifest | AnalysisRun + Evidence + Provenance | Absorb |
| ODB Lens / declarative KPI recipe | ResultRequirement + EngineeringMetric | Absorb |
| Physics Contracts / predicates | Acceptance + EngineeringChecks | Absorb |
| Simulation Diff | AnalysisRun Diff | Absorb |
| Solver Doctor | Diagnostics | Absorb |
| Case Memory | Run Index after AnalysisRun stabilizes | Later |
| MCP runtime bridge | Execution Adapter | Absorb selectively |
| Skill routing | Existing capability/action routing | Absorb selectively |
| Progressive disclosure | Docs / knowledge / skills | Absorb |
| Executable helpers | Tools / runtime helpers | Absorb |
| Multi-agent orchestration | Not required now | Do not copy |
| Giant skill library | Not required now | Do not copy |
| MCP as core architecture | Incorrect boundary | Do not copy |
| Arbitrary Python as formal semantic capability | Escape hatch only | Do not elevate |

**Principle:** borrow proven mechanisms, not parallel architectures.

---

## 4. Foundational Engineering Contract Closure

**Status: ✅ CLOSED and FROZEN at Commit `644cad7` (347/347 tests passed, 13/13 Golden Matrix verified).**

The current code-level audit confirms that the project already has sufficient Abaqus API coverage for the next real-machine phase. The foundational semantic chain is now unified and frozen:

```
Engineering Model
│
├── UnitSystem
├── Material Definition
├── Geometry / Region Reference
├── Analysis Step
├── Boundary Conditions / Loads
├── Mesh Specification / Quality
└── Result Requirement
        ↓
Workflow → Action → Abaqus → ODB → Metric → Verification → Acceptance
```

### 4.1 Region — P0 [CLOSED]

The repository contains:

- `GeometryCandidate`
- `GroundingResult`
- `GeometrySelection`
- `RegionBinding`
- `RegionReference`
- `resolve_region()`
- viewport/geometry grounding
- native Set/Surface materialization

Unified Region Resolver (`contracts/geometry.py`) is now integrated directly into all Action Builders (`actions/builders.py`). It accepts raw string expressions, `RegionBinding`, `GeometrySelection`, `RegionReference`, or dict specifications, failing closed on empty regions by default. Raw `region_expression` strings remain 100% backward-compatible.

### 4.2 BC / Load Preflight — P0 [CLOSED]

Preflight checking (`validation/preflight.py`) is deterministic and structural:

- Validates region existence and non-emptiness via `resolve_region()`.
- Validates step definition order and reference sequence.
- Checks DOFs and finite values (supporting Abaqus CAE `'UNSET'` constant).
- Integrated `validate_action_quantities()` for physical non-negativity and unit dimensional consistency.
- Enforces structural conflict detection: duplicate or mutually-exclusive BCs on the same `(region, step)` (such as `fixed_bc` conflicting with non-zero `displacement_bc`) are blocked.
- Bounded scope: Structural preflight is complete; full physical well-posedness is delegated to solver and ODB acceptance evidence.

### 4.3 Mesh Contract and Quality — P0 [CLOSED]

Contract and quality classification boundaries are established:

- Explicitly distinguishes `native`, `analysis`, `derived`, and `unsupported` check scopes.
- `MeshQualityResult` structured schema covers violations, element counts, and evidence.
- No further mesh API expansion; remaining closure is live Abaqus shape metrics verification.

### 4.4 Unit System — P1 [CLOSED]

UnitSystem propagation across the Action and Preflight chain is fully wired:

- `validate_action_quantities()` is actively invoked during `preflight_action()` for all quantity-bearing actions.
- Quantity-bearing actions store declared `unit_system` in parameters for provenance.
- Cleaned unreachable dead code in `units.py`.

### 4.5 Material Definition — P1 [CLOSED]

Consolidated in `MaterialDefinition` (`contracts/material.py`):

- `__post_init__()` validates declared `unit_system` via `UnitSystem.named()`, failing closed on invalid unit systems.
- `to_actions()` materializes elastic, density, plastic, and thermal properties while losslessly passing `unit_system` semantics to native material actions.

### 4.6 Analysis Step Contract — P1 [CLOSED]

Lossless mapping from semantic `AnalysisStep` (`contracts/step.py`) to native Action Builders:

- Supports `static`, `implicit_dynamic`, `explicit_dynamic`, `heat_transfer`, `frequency`, and `coupled_temp_displacement`.
- Explicit step propagates `max_inc` → `max_increment`.
- Heat transfer propagates `steady_state` and `amplitude`.
- Action parameters preserve `metadata` without semantic loss.

---

## 5. P0 — Complete the Engineering Run

### P0.1 AnalysisRun completeness

Strengthen the existing `AnalysisRun` so a completed run can answer:

- What engineering intent was requested?
- What assumptions were used?
- Which solver and post-processing profile were selected?
- Which actions were planned and executed?
- What model state was used?
- Which Abaqus/runtime environment was used?
- Which input/output artifacts were produced?
- Which metrics were extracted?
- Which verification checks were performed?
- Which acceptance criteria were applied?
- Which diagnostics occurred?
- What evidence supports every important conclusion?
- What report was generated?

### P0.2 Provenance completeness

Current provenance deliberately distinguishes metadata hashing from actual content hashing. Do not claim reproducibility that was not captured.

Target:

```
intent hash
model snapshot hash
INP/input hash
ODB/output hash
artifact content hashes
action-plan hash
runtime/environment
solver version
run ID
```

If a content hash cannot be captured, record it as unavailable rather than fabricating reproducibility.

### P0.3 Evidence Package

Do not create a second package architecture.

The run should be able to expose a coherent evidence view containing:

```
artifacts
metrics
solver status
ODB status
verification
acceptance
diagnostics
provenance
report
```

---

## 6. P0 — Declarative Result Requirements

The existing `ResultRequirement` / `EngineeringMetric` layer is correct and should be extended rather than replaced.

Target semantic chain:

```
ResultRequirement
    ↓
Abaqus output planning
    ↓
ODB extraction
    ↓
EngineeringMetric
    ↓
Verification / Acceptance
    ↓
Evidence / Report
```

A result requirement should be able to express, where applicable:

- name
- source
- field
- component
- invariant
- region
- step
- frame
- history variable
- reducer/aggregation
- unit
- required/optional status

Example:

```yaml
max_root_mises:
  field: S
  invariant: MISES
  region: ROOT
  reducer: max
```

The key objective is to make the system understand **what engineering result is required**, not merely which extraction function happens to exist.

---

## 7. P0 — Acceptance as an Evidence Gate

The existing deterministic acceptance layer should remain the single acceptance system.

Acceptance should combine, when applicable:

```
Execution Gate
+ ODB/Result Gate
+ Required-Metric Gate
+ Numerical Verification Gate
+ Engineering Check Gate
+ Mesh/Convergence Gate
+ Fatigue Gate
+ Contact Gate
+ Evidence Sufficiency Gate
```

Important rules:

1. Missing upstream evidence must not silently become PASS.
2. Missing required metrics must block acceptance.
3. Solver completion alone is not engineering acceptance.
4. ODB existence alone is not result validity.
5. A numerical criterion alone is not sufficient when higher-level verification was explicitly required.
6. Warnings must remain distinguishable from failures.
7. `Diagnosis ≠ Correction`.
8. Acceptance must remain deterministic and inspectable.

---

## 8. P1 — AnalysisRun Diff

Extend the existing `state_diff.py` direction into a run-level diff.

Target:

```
Baseline AnalysisRun
        ↕
Candidate AnalysisRun
        ↓
AnalysisRunDiff
```

Compare, where available:

- engineering intent
- assumptions
- solver selection
- action plan
- model snapshot
- mesh
- loads
- BCs
- interactions
- output requests
- solver settings
- artifacts
- metrics
- verification
- acceptance
- provenance

The diff should report deterministic before/after values and deltas. It should not invent engineering significance.

---

## 9. P1 — Solver Diagnostics

Build a deterministic diagnostic pattern library around real Abaqus artifacts:

- `.msg`
- `.sta`
- `.dat`
- `.log`
- job status
- ODB status

Target:

```
solver failure
→ diagnostic pattern
→ diagnosis ID
→ supporting evidence
→ likely cause
→ suggested remediation
```

Diagnostics must remain bounded and evidence-backed.

Do not turn this into an unrestricted autonomous repair system.

If correction is later automated, it must pass through the existing controlled-correction boundary and generate a new AnalysisRun.

---

## 10. P1 — Runtime Error Normalization

Strengthen the existing execution layer using lessons from Abaqus-Control-MCP and abaqus-mcp:

- execution ID
- request/result lifecycle
- timeout
- stdout/stderr
- structured traceback
- source location where available
- Abaqus context
- runtime capability
- job state
- artifact references

Architecture:

```
Engineering Action
→ Execution Adapter
→ Abaqus runtime
→ Structured Execution Result
```

MCP/TCP/file IPC may be adapters. They are not the engineering core.

---

## 11. P2 — Case Memory / Run Index

Only after AnalysisRun is stable.

Target:

```
AnalysisRun
→ Run Index
→ search / filter / compare / reuse
```

Potential indexing dimensions:

- engineering intent
- solver
- analysis type
- model metadata
- metrics
- acceptance
- diagnostics
- artifact names
- verification results

Do not create a separate Capsule/Case/Memory persistence model unless a concrete requirement proves it necessary.

---

## 12. Peripheral Capabilities Requiring Real-Machine Closure

These capabilities must be separated into deterministic tests and live Abaqus validation.

### 12.1 Engineering Report

L0 deterministic:

```
Evidence JSON
→ report renderer
→ HTML/PDF
```

Verify:

- values
- units
- charts
- acceptance status
- evidence references
- report completeness

L1 live:

```
Real Abaqus
→ Real ODB
→ Metrics
→ Verification
→ Acceptance
→ Engineering Report
```

The report must be traceable to actual solver artifacts.

### 12.2 Image → Engineering Intent / Region

Separate:

1. Image interpretation
2. Geometry/viewport grounding
3. Abaqus region binding
4. BC/load application
5. solver evidence

Only (1) is adequately testable without Abaqus.

Real-machine validation is required for:

```
viewport image
→ grounded Face/Edge/region
→ BC/load
→ solver
→ ODB
```

### 12.3 Mesh Quality

Real-machine validation required for:

```
mesh action
→ actual Abaqus mesh
→ quality extraction
→ evidence
→ acceptance
```

### 12.4 Geometry-to-Mesh Strategy

Real-machine validation required for:

```
geometry
→ mesh strategy
→ actual mesh
→ quality
→ convergence
```

---

## 13. Six-Dimensional Real-Machine Validation Architecture (ASME V&V 10 Aligned)

A single passing test case does not validate an entire physical domain. To prevent cosmetic test accumulation (e.g. duplicating simple cantilever beam tests), the real-machine validation framework is organized along six orthogonal engineering dimensions:

### 13.1 Dimension A: Physics Domain Coverage
- **Linear Solid Mechanics**: Tension, compression, pure shear, Saint-Venant torsion, bending.
- **Material Nonlinearity**: Metal plasticity (J2 plasticity, hardening, unloading, residual strain), cyclic plasticity, hyperelasticity (elastomers), viscoelasticity, steady/transient creep.
- **Geometric Nonlinearity**: Large deformation, large rotations, load-stiffening (`NLGEOM`).
- **Structural Stability & Bifurcation**: Eigenvalue buckling (Euler column), nonlinear post-buckling with imperfections.
- **Dynamic & Vibrational Mechanics**: Natural frequencies/mode extraction, preloaded modal analysis, implicit structural dynamics, explicit high-speed impact.
- **Multi-Physics Coupling**: Sequential thermal-stress, fully coupled temperature-displacement.
- **Contact & Tribology Mechanics**: Small sliding, finite/large sliding, contact opening/separation, stick-slip friction continuity.
- **Fracture, Damage & Degradation**: Continuum damage mechanics, cohesive zone interfaces, contour integral fracture ($J$-integral).
- **Composite Architectures**: Classical lamination theory, ply angles, directional stiffnesses, open-hole stress concentrations.
- **Multi-Body Dynamics & Mechanisms**: Rigid bodies, mass properties, gravity equilibrium, connector elements (revolute, translational, spring/dashpot).

### 13.2 Dimension B: Numerical & Discretization Coverage
- **Linear vs. Nonlinear Formulations**: Newton-Raphson iteration, line search, stabilization.
- **Time Integration**: Implicit HHT-alpha, explicit central difference, stable time increment limits.
- **Discretization & Quality**: 1D beam/truss, 2D continuum/shell, 3D brick/tetrahedral elements, mesh convergence, Richardson extrapolation / GCI index.
- **Conservation & Balance**: Force/moment equilibrium, reaction vs. applied balance, kinetic/internal energy conservation.

### 13.3 Dimension C: Engineering Object Coverage
- Unified verification across Part, Assembly, Rigid Body, Connector, Contact Pair, General Contact, Material, Section Assignment, Mesh, AnalysisStep, Load, Boundary Condition, Field Output Request, and History Output Request.

### 13.4 Dimension D: Engineering Workflow Lifecycle Coverage
- Intent Ingestion → Preflight Validation → Model Construction → Execution → Diagnostics (when failing) → Remediation → Rerun → Extraction → Verification → Acceptance → Evidence Archival → Report Generation.

### 13.5 Dimension E: Evidence Integrity & Traceability Coverage
- For every benchmark, the output must not be an isolated boolean `PASS`. It must produce:
  1. *Input Evidence*: Parameter set, geometry fingerprints, material cards.
  2. *Solver Evidence*: Exit codes, `.sta`, `.msg`, `.dat` diagnostics.
  3. *ODB Evidence*: Field/history outputs, reaction force integrals.
  4. *Physics Evidence*: Analytical/benchmark comparisons, energy checks.
  5. *Acceptance Evidence*: Deterministic evaluation against engineering limits.

### 13.6 Dimension F: Failure Detection & Controlled Recovery Coverage
- Intentional injection of engineering errors (erroneous boundary conditions, unconstrained rigid modes, incompatible units, unphysical material parameters, extreme contact penetrations, divergent increments) to verify that the Agent autonomously detects, diagnoses, explains, remediates, and re-verifies.

---

### Status of Real-Machine Coverage Against the Six Dimensions

#### Already substantially covered by the Golden Ladder & Phase H/I
- Abaqus launch/runtime, license probe, CAE/noGUI execution
- Model creation, basic mesh, input generation, solver submission, artifact collection
- ODB discovery/opening, ODB extraction
- Linear static, explicit dynamics, implicit dynamics, steady thermal
- General contact with friction, Tie contact
- MBD Revolute, flexible MBD, closed-loop mechanism
- High-cycle fatigue life postprocessing (Rainflow + Goodman + Miner)
- Reaction/load equilibrium balance, kinetic/internal energy checks
- Mesh convergence & Richardson/GCI uncertainty verification
- Parameter sensitivity & baseline/candidate AnalysisRun diff

#### Priority physical expansions specified for Phase J
- **P0 Physical Benchmarks**: Uniaxial tension/compression/shear/torsion isolation, elastoplasticity with unloading, large deflection NLGEOM, eigenvalue buckling, natural frequency modal analysis, sequential thermo-mechanical coupling, hyperelastic rubber, contact separation, translational/spring connectors, gravity/mass equilibrium.
- **P1 Extended Physics**: Nonlinear post-buckling, preloaded modal analysis, fully coupled temperature-displacement, viscoelasticity, creep, cohesive debonding, $J$-integral fracture, laminate composite stiffness, explicit plate impact.

---

## 14. Failure-Path Validation Is Mandatory

Do not validate only successful runs.

The real-machine matrix must include at least:

```
PASS
FAIL
BLOCKED
SUSPICIOUS
INCOMPLETE
TIMEOUT
ODB_MISSING
RESULT_INVALID
```

Representative tests:

1. Solver reports failure.
2. Solver exits but required ODB is missing.
3. ODB exists but required field output is missing.
4. ODB opens but required metric cannot be extracted.
5. Required engineering check fails.
6. Mesh quality fails.
7. Mesh convergence fails.
8. Contact evidence is insufficient.
9. Runtime times out.
10. Artifact collection is incomplete.
11. Required region is missing or empty.
12. BC/load preflight detects a deterministic conflict.
13. Required unit/dimension semantics are invalid or unavailable.

Every failure path must produce a structured status and supporting evidence.

---

## 15. Verification / Validation Boundary

The project provides computational verification and evidence management.

Do not claim automatic physical validation merely because a simulation converged or passed numerical checks.

Keep the distinction:

```
Verification:
"Did we solve/compute the intended numerical problem correctly enough?"
```

versus

```
Physical validation:
"Does the computational model represent physical reality adequately?"
```

Physical validation requires experiment/application-specific evidence and remains outside the automatic solver-only claim.

---

## 16. V&V / Scientific Credibility Principles

The implementation should remain consistent with established computational mechanics V&V principles:

- verification and validation are distinct
- numerical convergence is evidence, not universal proof
- uncertainty should be represented explicitly where available
- assumptions must be visible
- evidence must be traceable
- engineering conclusions must not exceed available evidence

Richardson extrapolation / GCI should remain a verification mechanism, not be presented as physical validation.

---

## 18. Real-Machine Validation Phase Execution Plan (The Lower-Half Gate)

The project separates the verification and validation boundary into two gates:

```
                        ┌─ Unit Tests: 347/347 PASSED
                        │
                        ├─ Golden Matrix: 13/13 VALID & PASS
Software Contract Gate ─┤
(CLOSED at 644cad7)     └─ Structural/Consistency Checks: PASS
                                 │
                                 ▼
                     Real-Machine Validation Gate
                     (Abaqus 2025 Live Execution)
                                 │
                 ┌───────────────┼───────────────┐
                 ▼               ▼               ▼
           Model/Region        Solver           ODB
                 │               │               │
                 └───────────────┼───────────────┘
                                 ▼
                         Engineering Evidence
                                 │
                                 ▼
                             Acceptance
                                 │
                                 ▼
                         Engineering Report
```

### 18.1 Target Real-Machine Validation Tiers

1. **Tier 1: Region & Geometry Grounding in Live Abaqus**
   - Verify `GeometrySelection → RegionResolver → Set/Surface → Native BC/Load → Solver → ODB`.
   - Test live presence and non-emptiness across Face, Edge, Node, Element, Set, Surface.
   - Negative live tests: Empty region, non-existent region, entity-type mismatch must fail closed with structured diagnostics.
   - Prove: `Resolver expression valid ≠ Abaqus region exists and non-empty`.

2. **Tier 2: BC / Load Engineering Equivalence**
   - Case A: Fixed end + Concentrated force (verify reaction force RF vs applied CF).
   - Case B: Fixed end + Pressure load (verify integral pressure vs RF).
   - Case C: Temperature BC (verify thermal gradient and flux).
   - Case D: Structural conflict (verify preflight blocks before solver submission).
   - Case E: Rigid-body under-constrained model (verify solver singularity/warning detection).

3. **Tier 3: UnitSystem Physical Invariance**
   - Build two identical physical problems:
     - Model 1: `MM_N_MPA` (E = 210000 MPa, L in mm, F in N).
     - Model 2: `SI` / `M_N_PA` (E = 2.1e11 Pa, L in m, F in N).
   - Verify: Non-dimensional results and converted physical quantities (stress, strain, displacement) are numerically equivalent within tolerance.
   - Prove: UnitSystem is a physical invariance contract, not a cosmetic tag.

4. **Tier 4: MaterialDefinition Full-Chain Verification**
   - Trace `MaterialDefinition` through `to_actions()` → CAE Material → Section → Part → Solver → ODB.
   - Verify that Young's modulus, Poisson's ratio, density, yield stress, and conductivity are accurately reflected in the input deck and ODB material records.

5. **Tier 5: AnalysisStep Procedure Verification**
   - Execute minimal live runs across Static, Explicit Dynamic, Implicit Dynamic, Heat Transfer, and Coupled Temp-Displacement.
   - Verify that `max_increment`, `steady_state`, `amplitude`, and `metadata` correctly control solver behavior and appear in the generated input deck and ODB.

### 18.2 Architectural Freezing Directive

- **No further API proliferation**: Do not add new material, step, or mesh API endpoints unless justified by an unresolvable real-machine blocker.
- **Focus strictly on evidence**: The remaining goal is closing the loop from Intent to Model to Solver to ODB to Verification to Acceptance to Evidence to Report under live Abaqus 2025.
- **Extend existing modules only**: Prefer extending existing modules and contracts rather than introducing parallel architectures.

### 18.3 Phase I: Product Hardening & Release Gate (JEV-Powered System)

1. **I.1: Comprehensive Engineering Case Matrix**
   - 9 Golden Engineering Workflows: Static, Thermal, Modal, Contact, Fatigue, FMBD, Mesh Convergence, Diagnostics/Remediation, Image Grounding.
   - Traceable end-to-end evidence chains: Intent -> Action -> Abaqus Solver -> ODB -> Metrics -> Verification -> Acceptance -> Report.
2. **I.2: Mandatory Failure-Path Matrix & State Preservation**
   - Full fail-closed lifecycle for all 8 states: `PASS`, `FAIL`, `BLOCKED`, `SUSPICIOUS`, `INCOMPLETE`, `TIMEOUT`, `ODB_MISSING`, `RESULT_INVALID`.
   - Guaranteed diagnostic capture and non-corruption of historical evidence.
3. **I.3: Engineering Reproducibility & Tolerance Invariance**
   - Cryptographic hash invariance across input, model structure, action sequence, and input deck.
   - Solver output floating-point tolerance boundaries (relative tolerance $\le 10^{-4}$).
4. **I.4: JEV-Powered Product UX & TypeSafe Intent Routing**
   - TypeSafe System One JEV paradigm (Choice, Score, Noul primitives) mapping natural language prompts to typed `EngineeringIntent` and declarative `ResultRequirement`.
   - Guaranteed deterministic fallback and complete headless/live Abaqus integration.
5. **I.5: Packaging, CLI Entrypoints & Runtime Capability Fallback**
   - CLI executable `abaqus-agent` with automatic environment detection, headless execution modes, and graceful degradation when solver license is unavailable.
	6. **I.6: Public Release Audit, Documentation & Security Sanitization**
	   - Sanitization of machine-specific paths, environment leakage audit, complete user guide, and clean release packaging.

### 18.4 Decoupling Physics Domains from Cross-Cutting Capabilities

The initial "9 Physics Categories" historically conflated physical mechanics domains with cross-cutting agent capabilities. To establish an unambiguous architecture aligned with computational mechanics standards, these are formally decoupled:

```
                          Abaqus-AI-Agent Architecture
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
[ Core Mechanics Domains ]                              [ Cross-Cutting Capabilities ]
- Solid Mechanics (Tension/Shear/Torsion)               - Cross-Physics Solver Doctor (Ex-CASE-08)
- Nonlinearities (Plasticity/NLGEOM)                    - Multi-modal Topology Grounding (Ex-CASE-09)
- Stability & Buckling (Euler/Nonlinear)                - Verification & Acceptance Engine
- Dynamics & Vibration (Modal/Impact)                   - Uncertainty & GCI Mesh Convergence
- Thermal & Thermo-Mechanical Coupling                  - High-Cycle Fatigue Postprocessing
- Contact Mechanics (Separation/Sliding)                - Case Memory & AnalysisRun Diffing
- Degradation (Damage/Fracture/Cohesive)                - Automated Engineering Report Renderer
- Advanced Materials (Hyperelastic/Composite)           - TypeSafe JEV Intent Router
```

1. **Solver Failure Diagnosis & Remediation (`CASE-08`)** is elevated to a **Cross-Cutting Solver Doctor System** applicable across all physics procedures, not an isolated physics category.
2. **2D Image / Viewport Grounding (`CASE-09`)** is elevated to the **Engineering Perception & Intent Extraction Layer**, resolving geometric topology from external visual artifacts prior to model construction.

### 18.5 The Three-Tier Real-Machine Validation Hierarchy

Validation is structured into three discrete operational tiers to prevent test suite bloat while ensuring exhaustive coverage:

```
                            Real-Machine Validation Suite
                                          │
       ┌──────────────────────────────────┼──────────────────────────────────┐
       ▼                                  ▼                                  ▼
[ Tier A: Core Golden ]       [ Tier B: Extended Matrix ]       [ Tier C: Product Capabilities ]
- ~20 Mandatory Benchmarks    - ~15-20 Deep Physics             - E2E Autonomous Agent
- Every Release & PR Gate     - Nightly / Staging Regressions   - Intent -> Solve -> Heal -> Report
```

#### 1. Tier A: Core Golden Physics Benchmarks (~20 Baseline Runs, Mandatory for Every Release)
- **S1: Uniaxial Tension**: Stress, strain, axial displacement, reaction force vs. analytical Young's modulus & Poisson contraction.
- **S2: Pure Compression**: Directional sign validation, compressive stiffness, boundary orientation sanity check.
- **S3: Pure Shear**: Shear stress ($\tau_{xy}$), shear strain ($\gamma_{xy}$), shear modulus $G$, stress component decoupling.
- **S4: Saint-Venant Torsion**: Circular shaft under pure torque, torsional angle $\theta$, surface shear stress, polar moment $J$. In 3D continuum FE models, end kinematic coupling and encastre constraints introduce local stress concentrations; the 99.5th percentile of Tresca/2 within the uniform gauge section is evaluated to filter boundary singularities and align transparently with analytical Saint-Venant outer surface shear stress.
- **M1: Elastoplastic Tension & Unloading**: $J_2$ plasticity, yield onset, plastic strain accumulation, elastic unloading, residual plastic deformation.
- **M2: Cyclic Plasticity**: Reversed loading, hysteresis loop capture, Bauschinger effect / cyclic strain tracking for fatigue input.
- **M3: Geometric Nonlinearity (Large Deflection)**: Slender cantilever beam under transverse tip load with `NLGEOM=ON`, load-displacement curvature, geometric stiffening.
- **B1: Eigenvalue Buckling**: Simply supported Euler column, critical bifurcation load $P_{\text{cr}} = \pi^2 E I / L^2$, primary buckling mode shape extraction.
- **B2: Nonlinear Imperfection Post-Buckling**: Initial geometric imperfection perturbation, nonlinear equilibrium path, limit load detection.
- **D1: Natural Frequency Extraction**: Undamped cantilever beam, first 3 to 5 flexural eigenfrequencies and mode shapes against analytical beam vibration theory.
- **D2: Preloaded Modal Analysis**: Static axial preload step followed by frequency extraction step, demonstrating step-to-step state and geometric stiffness transfer.
- **T1: Sequential Thermal-Stress**: Steady/transient thermal heat conduction step generating temperature field, transferred to mechanical step generating thermal expansion stresses.
- **T2: Fully Coupled Temperature-Displacement**: Simultaneous displacement and temperature degree-of-freedom solution, mechanical work dissipation into heat, energy balance.
- **MAT-1: Hyperelastic Elastomer**: Neo-Hookean / Mooney-Rivlin incompressible rubber block under compression, large stretch, nonlinear stress-strain curve.
- **F1: Continuum Damage Mechanics**: Ductile damage initiation, stiffness degradation variable SDEG, localized element degradation.
- **C1: Classical Composite Laminate**: $[0/90/45/-45]_s$ balanced symmetric laminate, orthotropic engineering constants, directional stiffness matrix, ply stress extraction.
- **CTC-1: Contact Separation & State Transition**: Flat block compressed then pulled, capturing closed-to-open contact state transition and zero tensile contact pressure.
- **CTC-2: Finite Sliding Friction Continuity**: Stick-slip transition, tangential frictional force continuity, normal contact pressure integral vs. normal force.
- **CONN: Mechanism Connectors**: Revolute, Translational, and Spring/Dashpot elements, validating kinematic degrees of freedom and relative motion extraction.
- **I1-I2: Inertia, Mass Properties & Gravity**: Rigid/deformable bodies under gravity, center of mass, rotational inertia tensor, reaction force balance vs. total mass $\times g$.
- **E2: Explicit Dynamic Impact**: Rigid cylindrical impactor striking a deformable plate, energy balance ($E_{\text{kinetic}} + E_{\text{internal}} = \text{const}$), stable time increment tracking.
- **NEG-01: Intentional Divergence & Closed-Loop Healing**: Deliberately unstable non-convergent model, autonomous extraction of `.msg` force residuals, diagnostic categorization, step/stabilization remediation, rerun, and final acceptance.

#### 2. Tier B: Extended Engineering Physics Matrix (~15-20 Specialized Benchmarks, Nightly/Milestone)
- **Viscoelasticity**: Stress relaxation under constant strain, time-dependent shear modulus Prony series.
- **Steady-State & Transient Creep**: Constant sustained stress, secondary creep strain rate power law (Norton law).
- **Interface Debonding & Delamination**: Cohesive Zone Model (CZM) with traction-separation law, mixed-mode crack opening.
- **Fracture Mechanics ($J$-Integral)**: Mode I compact tension CT specimen, crack tip singular elements, domain contour $J$-integral mesh insensitivity.
- **Open-Hole Composite Specimen**: Stress concentration factor around circular hole in multi-ply laminate.
- **Preloaded Bolt & Thread Contact**: Bolt pretension 3D modeling, tightening step followed by external service load.
- **Transient Fluid/Thermal Diffusion**: Fickian moisture/temperature transient penetration into solid matrix.

#### 3. Tier C: Product UX & Autonomous Agent Capability Matrix
- **Natural Language Intent Ingestion**: End-to-end prompt to typed `EngineeringIntent` and declarative `ResultRequirement` (TypeSafe JEV).
- **Ambiguity Detection & Rejection**: Fail-closed prompt rejection requesting technical clarification before model generation.
- **2D Drawing / Viewport Grounding**: Automatic identification of geometric faces/edges from external graphical viewport coordinates.
- **Automated Verification & Reporting**: Automatic production of traceable engineering report (Markdown/HTML) from real ODB outputs.
- **Model Perturbation & Sensitivity**: Autonomous verification of input parameter variations on primary response variables.

### 18.6 Benchmark Isolation & Reference Standard Principles

In accordance with ASME V&V 10:
1. **Single-Mechanism Isolation**: Benchmark cases must isolate an individual physical or numerical mechanism wherever possible, comparing against closed-form analytical solutions (e.g. Timoshenko beam, Euler column, Hertzian contact) or authoritative reference data.
2. **Numerical Tolerance Thresholds**:
   - Closed-form analytical comparisons: Relative deviation $\le 1\%$ (or documented discretization error).
   - A/B Dual-run reproducibility: Relative deviation $\le 10^{-4}$ ($0.01\%$).
   - Reaction vs. applied force balance: Relative equilibrium error $\le 10^{-3}$ ($0.1\%$).
3. **No Analytical Stubs in Real-Machine Tiers**: All Tier A and Tier B benchmarks must execute against authentic Abaqus 2025 solver binaries and extract metrics directly from physical ODB files. Hardcoded analytical stubs are prohibited.
4. **Official Benchmark & Local Documentation Example Primacy**:
   - Wherever an official benchmark exists in the *Abaqus Benchmarks Guide*, *Abaqus Verification Guide*, *Abaqus Example Problems Guide*, or local SIMULIA 2025 documentation samples (e.g. NAFEMS LE1/LE10/NL1 benchmarks, standard Euler column buckling, canonical cantilever modal extraction 1.1.1, Hertzian contact, patch test, Taylor bar impact), the system **must prioritize re-executing against the official Abaqus benchmark definitions**.
   - Model geometry, material definitions, step parameters, and boundary conditions must faithfully reproduce the official problem specification.
   - Acceptance criteria must directly compare live solver ODB results against the official reference solutions published in the Dassault Systèmes documentation.
   - Benchmark provenance must explicitly record the official reference ID (e.g. `Abaqus Verification Guide 1.1.1`, `NAFEMS LE10`).

---

## 19. Implementation Order

The default implementation order is:

### Phase A — Foundational contract closure

- [x] Unify Region resolution without breaking existing Action compatibility
- [x] Strengthen BC/Load deterministic preflight
- [x] Close native mesh-quality evidence boundaries
- [x] Preserve existing Geometry grounding and RegionBinding architecture
- [x] Avoid new parallel foundational subsystems

### Phase B — Engineering Run / Evidence closure

- [x] Complete AnalysisRun as canonical Engineering Run
- [x] Complete provenance/content-hash semantics
- [x] Unify evidence/artifacts/metrics/verification/acceptance/report references

### Phase C — Result semantics

- [x] Complete declarative ResultRequirement
- [x] Ensure output planning is driven by result requirements
- [x] Normalize EngineeringMetric
- [x] Ensure metrics are traceable to ODB evidence

### Phase D — Acceptance

- [x] Ensure missing evidence blocks acceptance
- [x] Ensure all verification gates are deterministic
- [x] Preserve PASS/WARNING/FAIL/BLOCKED distinctions

### Phase E — Engineering comparison/diagnosis

- [x] AnalysisRun Diff
- [x] Solver diagnostic pattern library
- [x] Runtime error normalization

### Phase F — Unit / Material / Step semantic strengthening

- [x] Propagate UnitSystem through foundational Actions
- [x] Strengthen MaterialDefinition without creating a second material architecture
- [x] Strengthen AnalysisStep without creating a second step architecture

### Phase G — Real-Machine Live Validation Matrix (Tier 1 ~ Tier 5) [CLOSED & FROZEN]

- [x] Tier 1: Region & Geometry Grounding in Live Abaqus (Face/Edge/Node/Set/Surface live presence & fail-closed)
- [x] Tier 2: BC / Load Engineering Equivalence (RF vs CF/Pressure balance, Thermal gradient, structural conflict/singularity)
- [x] Tier 3: UnitSystem Physical Invariance (MM_N_MPA vs SI M_N_PA live numerical equivalence)
- [x] Tier 4: MaterialDefinition Full-Chain Verification (elastic, plastic, thermal properties in INP and ODB)
- [x] Tier 5: AnalysisStep Procedure Verification (max_increment, steady_state, amplitude solver control)

> **Architectural Status**: Foundational Engineering Contract CLOSED ✅; Tier 1~5 Real-Machine Gate CLOSED ✅; Low-level Abaqus API expansion FROZEN 🔒.

### Phase H — Productization & End-to-End Engineering Workflow Validation

- [x] H.1: End-to-End Engineering Report Generator (Real ODB + Evidence Envelope -> Structured Engineering Report)
- [x] H.2: Real ODB Fatigue Postprocessing Workflow (Stress history -> Rainflow counting -> Goodman -> Miner damage -> Acceptance)
- [x] H.3: Mesh Convergence & GCI Uncertainty Workflow (Coarse/Medium/Fine -> Monotonicity -> Richardson extrapolation -> GCI evidence)
- [x] H.4: Contact & Interaction Mechanical Continuity Workflow (Tie & General contact -> Kinematic continuity -> ODB evidence)
- [x] H.5: Controlled Solver Failure Diagnostics & Remediation (Real solver error -> Diagnosis ID -> Root cause -> Remediation plan)
- [x] H.6: Image / Intent to Region Grounding Real Validation (Intent -> Viewport candidate -> Region binding -> CAE validation)
- [x] H.7: Sensitivity & Model Uncertainty Verification (Parameter perturbation -> Response variation -> Sensitivity index)
- [x] H.8: Case Memory & AnalysisRun Comparison (Run index -> Fast retrieval -> Baseline/Candidate structural diff)

### Phase I — Product Hardening & Release Gate (JEV-Powered Engineering System)

- [x] I.1: Comprehensive Engineering Case Matrix (E2E golden workflows across 9 core physics: Static, Thermal, Modal, Contact, Fatigue, FMBD, Mesh Convergence, Solver Diagnostics, Image Grounding)
- [x] I.2: Mandatory Failure-Path Matrix & State Preservation (Fail-closed execution across PASS, FAIL, BLOCKED, SUSPICIOUS, INCOMPLETE, TIMEOUT, ODB_MISSING, RESULT_INVALID)
- [x] I.3: Engineering Reproducibility & Tolerance Invariance (Double-run hash invariance and solver numerical tolerance verification)
- [x] I.4: JEV-Powered Product UX & TypeSafe Intent Routing (TypeSafe System One JEV model for natural language intent -> Typed EngineeringIntent -> Plan -> Execution -> Report)
- [x] I.5: Packaging, CLI Entrypoints & Runtime Capability Fallback (Abaqus environment detection, CLI launcher, license capability probes, graceful headless fallback)
- [x] I.6: Public Release Audit, Documentation & Security Sanitization (Hardcoded path sanitization, repository release hygiene, user guides, test suite validation)

### Phase I.R — Release Hardening & Strict Quality Gates (I.1R ~ I.6R + CI Gate)

- [x] I.1R: Fresh Execution & Evidence Freshness Gate (Validate live execution freshness hashes, input parameter fingerprints, and prevent static-only evidence spoofing)
- [x] I.2R: Runtime Solver Failure & Process Boundary Probes (Live runtime process error handling, non-zero return code normalization, artifact corruption fail-closed verification)
- [x] I.3R: True A/B Dual-Run Numerical Reproducibility & Perturbation Detection (Independent A/B execution comparison with tolerance <= 1e-4 and deliberate perturbation rejection)
- [x] I.4R: TypeSafe JEV Intent with Ambiguity Handling & Clarification Blocking (Fail-closed rejection for ambiguous/incomplete prompts -> NEEDS_CLARIFICATION / BLOCKED)
- [x] I.5R: Multi-tier Runtime Capability Inspector & Subprocess Packaging Smoke (Rigorous launcher/probe/license/solver capability decoupling and CLI subprocess smoke)
- [x] I.6R: Repository-Wide Security, Hygiene & Path Leakage Audit (Scan entire git tracked tree for private paths, API keys, credentials, and untracked binaries)
- [x] CI Gate: Automated CI Workflow Matrix & Verification (GitHub Actions workflow covering pytest, packaging smoke, and release hygiene audit)

### Phase I.R.1 — Evidence Authenticity & Live Abaqus Process Closure (The Real Machine Gate)

This phase establishes the strict dual-gate separation required for production release:
1. **CI Gate (Software Contracts & Headless Invariance)**:
   - Platform: Cross-platform (Ubuntu, Windows, macOS) in GitHub Actions.
   - Scope: Pure Python unit tests, Golden Evidence envelope structural parsing, TypeSafe JEV ambiguity rejection, CLI packaging smoke test, Git-tree hygiene & path sanitizer.
   - Rule: Deterministic, hermetic, zero external Abaqus solver license dependency. Fails closed on any contract violation.
2. **Real Machine Gate (Live Abaqus 2025 Process & Solver Closure)**:
   - Platform: Windows host with authentic Abaqus 2025 CAE / Standard / Explicit solver installation.
   - Scope: Live Abaqus noGUI/Batch execution, real OS subprocess lifecycle & failure injection, true dual-run A/B solver execution & physical ODB numerical invariance (tolerance <= 1e-4), live canonical physics solving.
   - Rule: Zero hardcoded analytical approximations (e.g. $FL^3/3EI$ or static constants). Every live run must produce an authentic ODB file, verified timestamp, authentic field output extraction, and complete provenance.

- [x] I.1-Live: True Abaqus Fresh Solver Execution (Reject hard-coded / analytical Python stubs. Drive real Abaqus solver to produce fresh live ODB, fresh solver artifacts, and fresh extracted metrics across representative canonical physics)
- [x] I.2-Live: Real OS Subprocess Boundary & Injected Failure Probes (Spawn real OS subprocesses via subprocess.Popen/run to generate non-zero exit codes, actual TimeoutExpired exceptions, and real workdir missing/corrupt ODB artifacts to verify process-level fail-closed integrity)
- [x] I.3-Live: True Live Abaqus A/B Dual-Run & Dual-ODB Verification (Eliminate single-run fallback loophole. Require true independent Run B; execute Run A and Run B through live Abaqus to compare physical ODB metrics within relative tolerance <= 1e-4, and verify rejection under physical perturbation)
- [x] Gate Distinction: Formalize boundary between CI Gate (cross-platform software contracts, headless deterministic tests) and Real Machine Gate (Windows Abaqus 2025 solver execution & ODB verification)

### Phase J — Comprehensive Engineering Physics & Extended Real-Machine Matrix (Tier A / B / C)

- [x] J.1: Architectural Decoupling of Cross-Cutting Capabilities from Physics
  - [x] Elevate Solver Failure Diagnosis/Remediation (ex-CASE-08) to global cross-physics Solver Doctor.
  - [x] Elevate 2D Viewport Image Grounding (ex-CASE-09) to pre-model Perception & Intent Grounding layer.
- [x] J.2: Tier A 22 Official Benchmarks Dual-Layer Architecture (ASME V&V 10 Aligned)
  - [x] **Phase J-Reference Gate** (`tools/j_comprehensive_physics_matrix.py`):
    - 13 Closed-Form Analytical Mechanics Solutions (S1-S4, M1-M2, B1, D1, T1, CTC1-CTC2, CONN, I1) calculated with zero artificial fudge factors.
    - 9 Theoretical Parameter & Specification Contracts (M3, B2, D2, T2, MAT1, F1, C1, E2, NEG01) with dimensional consistency & parameter integrity validation.
    - Strict prohibition of synthetic observation factors (e.g. `ref * 0.999x`).
  - [x] **Phase J-Live Real-Machine Gate** (`tools/j_live_abaqus_matrix.py`):
    - Full end-to-end live execution on authentic Abaqus 2025 solver (`abaqus cae noGUI`).
    - 22/22 live models built, meshed, solved, and evaluated directly from physical ODB field/history output databases.
    - Cryptographic SHA-256 artifacts captured for `.inp`, `.odb`, `.sta`, and `.msg`.
    - 22/22 cases validated against published Dassault Systèmes references within non-zero engineering tolerances.
  - [x] S1: Uniaxial tension sanity benchmark ($E, \nu, \sigma, \varepsilon, \Delta L$, reaction balance).
  - [x] S2: Pure compression benchmark (directional sign, stiffness, boundary sanity).
  - [x] S3: Pure shear benchmark ($\tau_{xy}, \gamma_{xy}, G$, component decoupling).
  - [x] S4: Saint-Venant circular shaft torsion ($T, \theta, \tau_{\max}, J$).
  - [x] M1: Elastoplastic uniaxial tension, yield onset, $J_2$ hardening, and elastic unloading residual strain.
  - [x] M2: Cyclic reversed plasticity, hysteresis loop, Bauschinger effect, and plastic strain accumulation.
  - [x] M3: Geometric nonlinearity (`NLGEOM=ON`), slender beam large deflection, geometric stiffening.
  - [x] B1: Eigenvalue buckling (Euler column critical bifurcation load $P_{\text{cr}}$ and mode shape).
  - [x] B2: Nonlinear post-buckling with initial geometric imperfection, equilibrium path tracking.
  - [x] D1: Natural frequency modal extraction (cantilever beam first 3-5 eigenfrequencies and mode shapes).
  - [x] D2: Preloaded modal analysis (static axial preload step -> frequency extraction step state transfer).
  - [x] T1: Sequential thermal-stress coupling (steady/transient thermal -> mechanical thermal expansion).
  - [x] T2: Fully coupled temperature-displacement (bidirectional thermomechanical coupling & energy balance).
  - [x] MAT-1: Hyperelastic elastomer (Neo-Hookean / Mooney-Rivlin large strain compression).
  - [x] F1: Continuum damage mechanics (ductile damage initiation and stiffness degradation SDEG).
  - [x] C1: Classical laminate composite ($[0/90/45/-45]_s$ orthotropic stiffness matrix & ply stresses).
  - [x] CTC-1: Contact separation & state transition (compression -> tensile opening -> zero pressure).
  - [x] CTC-2: Finite sliding friction continuity (stick-slip transition & normal pressure integral).
  - [x] CONN: Multi-body connector verification (Translational, Spring, Dashpot relative kinematics).
  - [x] I1-I2: Inertia, mass properties & gravity equilibrium (mass, center of mass, $RF = mg$).
  - [x] E2: Explicit dynamic impact (rigid impactor striking plate, kinetic/internal energy balance).
  - [x] NEG-01: Intentional divergence injection, `.msg` residual extraction, automated healing, rerun & accept.
- [x] J.3: Tier B Extended Engineering Physics Benchmarks (Nightly / Milestone Staging)
  - [x] Viscoelasticity (Prony series stress relaxation under sustained strain).
  - [x] Steady-state and transient creep (Norton power law strain rate under sustained stress).
  - [x] Cohesive Zone Interface debonding (traction-separation law delamination).
  - [x] Fracture mechanics $J$-integral (CT specimen contour integral mesh insensitivity).
  - [x] Open-hole multi-ply composite stress concentration verification.
  - [x] 3D bolt pretension tightening step followed by external service load.
  - [x] Transient fluid/thermal matrix diffusion.
- [x] J.4: Tier C Autonomous Product UX & Agent Capability Integration
  - [x] Natural language complex engineering prompt decomposition via TypeSafe JEV.
  - [x] Fail-closed prompt ambiguity detection and technical clarification requests.
  - [x] Viewport 2D drawing topological feature grounding to Abaqus native sets/surfaces.
  - [x] Fully automated engineering report generation directly from live ODB metrics.
  - [x] Multi-run parametric sensitivity and automated baseline/candidate diff analysis.
- [x] J.5: ASME V&V 10 & Official Abaqus Documentation Benchmark Alignment
  - [x] Inventory and map all applicable Tier A / Tier B physics benchmarks to official *Abaqus Benchmarks Guide*, *Abaqus Verification Guide*, and local SIMULIA 2025 documentation samples.
  - [x] Re-run all mapped benchmarks using official benchmark input specifications and geometry/mesh/step parameters.
  - [x] Standardize benchmark error tolerances against official reference solutions published in Dassault Systèmes documentation ($\le 1\%$ relative discrepancy).
  - [x] Maintain dual-run numerical reproducibility tolerances ($\le 10^{-4}$).
  - [x] Record official benchmark citation and documentation locator in `AnalysisRun.provenance` and `EvidenceBundle`.

### Phase K — Engineering Material Intelligence & External Knowledge Grounding (MaterialRecord & Resolver)

- [x] K.1: Core Material Contracts Specification
  - [x] Implement `MaterialIdentity` (`contracts/material_record.py`): polymer family, manufacturer, commercial grade, trade name, reinforcement type & content, filler, variant.
  - [x] Implement `MaterialSource` (`contracts/material_record.py`): provider (CAMPUS / Manufacturer / User), locator, retrieval timestamp, evidence level, license disclaimer.
  - [x] Implement `MaterialCondition` (`contracts/material_record.py`): test temperature, conditioning state (dry / conditioned / humid), test standards (ISO 10350 / ISO 11403 / ISO 527), strain rate.
  - [x] Implement `MaterialProperty` & `MaterialCurve` (`contracts/material_record.py`): scalar properties with raw/normalized units; multi-point isochronous, stress-strain, and temperature-dependent modulus curves.
  - [x] Implement consolidated `MaterialRecord`: unified entity encapsulating identity, source, conditions, scalar properties, and multi-point curves.
- [x] K.2: Constitutive MaterialResolver Engine
  - [x] Implement `MaterialResolver` (`contracts/material_resolver.py`): map condition-specific `MaterialRecord` to canonical Abaqus `MaterialDefinition`.
  - [x] Enforce constitutive sanity boundary: reject naive casting of raw polymer stress-strain curves to metal $J_2$ plasticity (`PlasticProperties`) without explicit constitutive verification.
  - [x] Support mapping paths to Abaqus `Elastic` (temperature-dependent), `Plastic` (rate-dependent hardening), `Viscoelastic` (Prony series), and `Creep`.
  - [x] Implement fail-closed fallback: emit `Unsupported` or `Assisted` status when required environmental or time-dependent data is missing for the active simulation step.
- [x] K.3: External Source Adapters & Open-Source IP Boundary
  - [x] Implement runtime `CampusAdapter` (`adapters/materials/campus.py`) for querying and structuring external CAMPUS ISO 10350/11403 datasheets on demand.
  - [x] Implement `ManufacturerAdapter` (`adapters/materials/manufacturer.py`) for parsing structured manufacturer technical data sheets.
  - [x] Enforce Apache-2.0 compliance redline: **No scraped proprietary material databases shall be bundled into the Git repository**. The repository shall only contain code adapters and data schema definitions.
- [x] K.4: Dual-Evidence Verification & Applicability Preflight
  - [x] Implement cross-source evidence comparison (e.g. CAMPUS vs. Manufacturer Technical Data Sheet) with discrepancy reporting.
  - [x] Implement environmental applicability preflight: verify that material test conditions (temperature, humidity, strain rate) cover the operating conditions specified in the `EngineeringIntent`.
  - [x] Link `MaterialRecord` and `MaterialSource` into `AnalysisRun.provenance` and `EvidenceBundle` for complete end-to-end auditability.

### Phase L — Autonomous Agent Engineering Workflow Validation (L1–L4 Gate) [CLOSED]

With Phase J establishing an unshakeable 22/22 live physical solver foundation, Phase L validates that the **Abaqus AI Agent functions as a fully autonomous, reliable, and fail-closed engineering system** across real-world workflows:

- [x] L1: End-to-End Autonomous Engineering Workflow (Prompt → JEV Intent → Plan → Solve → ODB → Acceptance → Report)
  - [x] Natural language complex engineering prompt ingestion via TypeSafe JEV System One.
  - [x] Strongly-typed `EngineeringIntent` compilation with fail-closed rejection for ambiguous/underspecified prompts.
  - [x] Autonomous Action planning, execution under Abaqus/CAE 2025, and ODB tensor extraction (`U`, `S_Mises`, `RF`).
  - [x] Deterministic acceptance gating against allowable limits and automatic publication-grade report compilation (Markdown & HTML).
- [x] L2: Real-World Material Intelligence Grounding (Datasheet / CAMPUS → MaterialRecord → Resolver → Abaqus Model → ODB)
  - [x] Ground commercial engineering polymers (e.g. PA66-GF30, POM) from structured CAMPUS/manufacturer datasheets into `MaterialRecord`.
  - [x] `MaterialResolver` environmental preflight: match operating temperatures/moisture and verify constitutive suitability.
  - [x] Fail-closed rejection (`BLOCKED` / `NEEDS_CLARIFICATION`) when test conditions are missing; prevent naive casting of polymers to metal $J_2$ plasticity.
  - [x] Native Abaqus material card synthesis (`*ELASTIC`, `*DENSITY`) and solver execution with ODB strain/stress validation.
- [x] L3: Closed-Loop Solver Diagnostics & Controlled Remediation (Injection → .msg Diagnostics → Doctor → Repair Plan → Rerun → Acceptance)
  - [x] Cross-physics deliberate injection of divergence-prone conditions (extreme contact penetrations, boundary singularities, severe non-convergence).
  - [x] Authentic extraction of solver diagnostics from `.msg`, `.sta`, and `.dat` (identifying force residuals, numerical singularities, cutbacks).
  - [x] Solver Doctor diagnosis classification and generation of a controlled, bounded remediation plan (stabilization damping, step controls, constraint repair).
  - [x] Automated remediation execution, solver re-submission, convergence verification, and final acceptance.
- [x] L4: Vision & Viewport Topology Grounding Live Verification (2D Viewport Annotations → 3D Spatial Raycast → findAt Binding → Sets/Surfaces → BC/Load → Solver Closure)
  - [x] Map 2D engineering drawing/viewport annotations into 3D raycast candidate spatial points.
  - [x] Automatically synthesize deterministic `findAt(...)` topological selection expressions in native Abaqus/CAE.
  - [x] Live verification of non-empty entity selection, native Set/Surface generation, boundary condition/load application, and reaction equilibrium closure.

### Phase M — Production Engineering Convergence & Task-Level Verification (R0–R5 Gate)

Following the live closure of the 22-case Tier A physics matrix (Phase J) and autonomous workflows (Phase L), Phase M seals remaining architectural deliverables to elevate Abaqus-AI-Agent from a solver automation suite to a true, commercial-grade autonomous engineering product:

- [x] **R0: CI Cross-Platform Hardening & Path Hygiene Closure**
  - [x] Eliminate ephemeral CI runner absolute path false positives in `i6_release_audit.py` (filter `/home/runner` and `/Users/runner`).
  - [x] Convert all tool-generated evidence outputs (e.g. `h1_engineering_report_evidence.json`, `h8_case_memory_comparison_evidence.json`) from OS-specific absolute paths to repository-relative paths (`machine_validation/...`).
  - [x] Enforce explicit `testpaths = ["tests"]` in `pyproject.toml` to prevent unintended directory discovery.
  - [x] Achieve 100% green status across all Python matrix environments (3.10, 3.11, 3.12) on Linux and Windows.
- [x] **R1: Agent-Native Action Chain End-to-End Grounding**
  - [x] Transform L1 from pre-packaged CAE script execution into a dynamic agent pipeline: `EngineeringIntent → ActionPlan → ActionBuilders → CAE Native Model → Solver → ODB → Acceptance → Report`.
  - [x] Prove that the model parameters and scripts are compiled directly from intent specifications rather than test-harness stubs.
- [x] **R2: Mesh Engineering Gate & Multi-Family Quality Verification**
  - [x] Real-machine verification across continuum, shell, and beam element families: C3D8/C3D8R, C3D10, S4R, B31.
  - [x] Extraction of native Abaqus element quality metrics: aspect ratio, minimum interior angles, face out-of-plane distortion, and negative Jacobian indicators.
  - [x] Fail-closed mesh acceptance gate: unresolvable element distortion or negative Jacobian triggers `BLOCKED` status before solver invocation.
- [x] **R3: Material Condition 2.0 Multi-Dimensional Fail-Closed Matching**
  - [x] Extend `MaterialCondition` matching beyond scalar temperature to multi-dimensional criteria: `strain_rate`, `test_time` (creep duration), `frequency` (DMA), and `humidity_state` (dry vs. conditioned).
  - [x] Enforce strict anti-extrapolation: out-of-range operating conditions must result in `BLOCKED` / `NEEDS_CLARIFICATION` rather than uncontrolled room-temperature fallback.
- [x] **R4: Clean-Room External Material Source Adapters**
  - [x] Deliver pluggable runtime adapters (`CampusAdapter`, `DatasheetAdapter`) with structured JSON/dict ingestion.
  - [x] Enforce Apache-2.0 legal boundary: zero proprietary database bulk dumps committed to repository; runtime translation into canonical `MaterialRecord` with full provenance tracking.
- [x] **R5: Engineering Task Acceptance Matrix (T1–T6 Real-World Scenarios)**
  - [x] Transition from isolated benchmark problems to multi-step engineering tasks:
    - **T1: Structural Static Strength & Factor of Safety (FoS)** task under deflection and stress limits.
    - **T2: Coupled Thermo-Mechanical Thermal Stress** task with temperature gradient and expansion constraints.
    - **T3: Contact & Tribological Interaction** task evaluating contact pressure, gap closure, and frictional dissipation.
    - **T4: Nonlinear Plastic Hardening & Residual Stress** task evaluating post-yield deformation.
	    - **T5: Transient Dynamic Vibration & Energy Balance** task with kinematic/internal energy checks.
	    - **T6: Autonomous Diagnosis & Self-Healing** task recovering from intentional non-convergence.

### Phase GA — General Availability Evolution Matrix (GA-1 ~ GA-3)

With the RC 1.0 foundation formally frozen and audited (`v1.0.0-rc1 — CONDITIONAL PASS`), the focus of the General Availability (GA) phase transitions from "proving solver/framework correctness" to "expanding autonomous engineering problem scope and establishing production-grade enterprise reliability".

#### 1. GA Unified Architectural Principles (The Iron Rules)
1. **Zero Duplicate Core Subsystems**: GA features shall **never** introduce a parallel `AnalysisRun`, `Evidence`, `Acceptance`, `Provenance`, or `MeshGate` subsystem. All capabilities compile into and feed directly through the established, audited canonical chain:
   ```
   EngineeringIntent
     ↓
   Canonical AnalysisRun (Single Source of Truth)
     ↓
   ActionPlan & Native Abaqus Actions
     ↓
   Abaqus 2025 Live Solver
     ↓
   ODB & Artifacts
     ↓
   EvidenceBundle
     ↓
   Numerical Verification & Engineering Acceptance
     ↓
   Traceable Engineering Report
   ```
2. **Standardized Capability Boundary (`CapabilityResult`)**:
   To prevent ambiguous capability drift across CAD, perception, and runtime, every evaluation stage outputs a unified four-state capability contract:
   ```python
   @dataclass(frozen=True)
   class CapabilityResult:
       capability: str
       status: Literal["SUPPORTED", "ASSISTED", "BLOCKED", "UNSUPPORTED"]
       reason: Optional[str] = None
       evidence: Dict[str, Any] = field(default_factory=dict)
       required_user_input: Optional[str] = None
       next_action: Optional[str] = None
   ```
3. **Strict Implementation Sequencing (Post-RC1 Strategic Pivot Completed)**:
   $$\text{GA-3 (Runtime - P0 [CLOSED])} \longrightarrow \text{GA-1 (CAD/Mesh - P1 [FROZEN])} \longrightarrow \text{GA-CL (Multi-Physics - P0 [FROZEN])} \longrightarrow \text{Engineering Grounding Layer (CLOSED)}$$
   Post-RC1 evolutionary progression (All Completed):
   $$\text{Track GA-2A (3D Viewport Grounding [CLOSED])} \longrightarrow \text{Track GA-F4 (Fatigue L4 [CLOSED])} \longrightarrow \text{Track GA-2B (Multimodal Perception [CLOSED])}$$
   $$\longrightarrow \text{Track GA-C4 (Connectors L4 [CLOSED])} \longrightarrow \text{Track GA-M4 (FMBD L4 [CLOSED])}$$
   *All 20 physical engineering domains (including Connectors and FMBD) are formally promoted and verified at L4 Agent Full-Chain Qualified.*

```
                   Abaqus-AI-Agent Post-RC1 Architecture
                                    │
    ┌───────────────────────────────┴───────────────────────────────┐
    ▼                                                               ▼
[ Engineering Grounding Layer (Input) ]                 [ Deep Physics Track (20 L4 / 0 L3) ]
- 3D Viewport Raycast & Picking (GA-2A) [CLOSED]         - Fatigue L4 (GA-F4) [CLOSED]
- Multimodal Blueprints/Photos (GA-2B)  [CLOSED]         - Kinematic Connectors (GA-C4) [L4 Closed]
- Canonical Natural Language Text                        - Flexible Multibody (GA-M4) [L4 Closed]
    │                                                               │
    └───────────────────────────────┬───────────────────────────────┘
                                    ▼
                          GroundingObservation
                                    ▼
                         HITL / Confidence Gate
                                    ▼
                         Typed EngineeringIntent
                                    ▼
               ┌─────────────────────────────────────────┐
               │    RC1 Frozen Canonical Backend Core    │
               │                                         │
               │  Compiler -> Preflight -> Abaqus 2025   │
               │  ODB -> Evidence V2 -> Acceptance       │
               │  Engineering Report (Single Exit Gate)  │
               └─────────────────────────────────────────┘
```

---

#### Track GA-3: Production Runtime Infrastructure & Enterprise Resilience [P0 HIGHEST PRIORITY]
*Enterprise Deployment Core: Ensuring multi-job orchestration, abstract license provider management, and non-blocking execution in real-world corporate environments.*

- [x] **GA-3.1: AnalysisRun Task Queue & Multi-Job Execution Engine**
  - [x] Implement persistent job task queue with asynchronous workers and explicit lifecycle state machine (`PENDING`, `ACQUIRING_LICENSE`, `RUNNING`, `RETRYING`, `COMPLETED`, `FAILED`, `CANCELLED`).
  - [x] Enforce job priority queues, concurrency limits, and host CPU/memory throttling.
- [x] **GA-3.2: Abstract License Provider Architecture (Vendor-Agnostic)**
  - [x] Define canonical, abstract `LicenseProvider` interface:
    ```python
    class LicenseProvider(ABC):
        def available_tokens(self, feature: str) -> int: ...
        def reserve(self, feature: str, tokens: int, timeout_s: float) -> LicenseHandle: ...
        def release(self, handle: LicenseHandle) -> None: ...
        def health(self) -> LicenseHealthStatus: ...
    ```
  - [x] Deliver pluggable driver adapters: `FlexNetAdapter` and `DSLSAdapter` as concrete driver implementations, avoiding hardcoded reliance on specific CLI commands (`lmutil`, `dslsstat`).
  - [x] Support dynamic token tracking across essential SIMULIA features (`abaqus`, `standard`, `explicit`, `cae`, `parallel`).
- [x] **GA-3.3: License Exhaustion Queue & Exponential Backoff Retry**
  - [x] Detect license checkout errors in solver preflight and live runtime logs (e.g. `License Manager error -1004` / `No license available`).
  - [x] Implement non-destructive task suspension with configurable exponential backoff and randomized jitter (`retry_after`, `max_wait_timeout`).
  - [x] Provide non-blocking queueing so multiple engineering agents wait cooperatively without aborting or losing state.
- [x] **GA-3.4: Multi-Job Workdir Sandbox & Artifact Isolation**
  - [x] Enforce strict per-run scratch directory sandboxing with UUID isolation to eliminate lock file collisions (`.lck`) and race conditions.
  - [x] Implement structured artifact promotion: only finalized `.odb`, `.sta`, `.msg`, and evidence bundles are promoted to long-term storage; ephemeral files are purged.
- [x] **GA-3.5: Run-Level Recovery & Resumption Checkpointing**
  - [x] Implement crash-resilient checkpoints across lifecycle states: `PLANNED`, `SUBMITTED`, `RUNNING`, `SOLVED`, `EXTRACTED`, `ACCEPTED`.
  - [x] Enable post-mortem run recovery: on process crash or restart, inspect workspace artifacts (`.lck`, `.odb`, `.sta`, `.msg`) to evaluate state:
    - `RECOVERABLE_RECONNECT`: Background Abaqus solver is still running or finished cleanly; reconnect and extract metrics without re-solving.
    - `NON_RECOVERABLE_RESUBMIT`: Abrupt solver termination or corrupted database; clean up workspace and requeue task cleanly.
    - `CLEANUP_FAILED`: Fatal unresolvable state; record diagnostic evidence and mark run failed closed.
- [x] **GA-3.6: Production Worker Runtime & Persistent Queue Closure**
  - [x] Implement atomic disk persistence (`persistence_path`) with atomic file swap to protect queue state against sudden process crashes.
  - [x] Implement `recover_orphaned_runs()` to self-heal jobs stranded in `RUNNING` or `ACQUIRING_LICENSE` after unexpected crashes into safe `RETRYING` states without deadlocks.
  - [x] Deliver `RunWorker` execution loop executing inside isolated `RunSandbox`, promoting verified artifacts (`.odb`, `.sta`, `.msg`, `.dat`), diagnosing failures via `inspect_run_state`, and updating canonical `AnalysisRun`.
  - [x] Deliver `RunWorkerPool` for concurrent multi-threaded execution with graceful drain and shutdown capabilities.
  - [x] **Audit Boundary Clarification**:
    - *Run-Level Recovery*: Strictly qualified as run-level recovery and resubmission via deterministic file system artifacts (`.lck`, `.odb`, `.sta`, `.msg`); not solver-internal transparent checkpoint resumption.
    - *License Provider*: Vendor-agnostic abstraction and offline parsing contract established; live communication against proprietary FlexNet/DSLS servers subject to deployment site physical access.

##### Track GA-3 Real-Machine Production Evidence Pack (G3-R1 ~ G3-R6 Gate)
*Separating Code Architecture Completion from Physical Hardware Execution: The 453 automated tests verify Python algorithms, queue state machines, and concurrency synchronization, but production clearance requires audited physical Abaqus solver evidence across the following 6 canonical production scenarios.*

- [x] **G3-R1: Dual-Job Real-Machine Concurrent Execution**
  - **Requirement**: Submit 2 authentic Abaqus 2025 jobs (Job A & Job B) concurrently into `RunWorkerPool` with 2 distinct `RunSandbox` instances.
  - **Validation**: Both jobs execute concurrently in separate OS worker processes/threads, generating uncorrupted, independent `.odb`, `.sta`, `.msg`, `.dat` artifacts. Verified via SHA-256 artifact hashes and independent ODB field extraction.
  - **Status & Evidence**: `DONE` — Live Abaqus 2025 executed concurrent Job A & Job B in 16.20s; concurrency overlap verified (`max_concurrent=2`), producing independent `.odb` (220KB/219KB) with distinct SHA-256 hashes (`machine_validation/ga3_real_machine_evidence.json`).
- [x] **G3-R2: Concurrency Cap & RLock Scheduling Rigor**
  - **Requirement**: Queue 8 tasks under worker count 4 with `max_concurrency=2`.
  - **Validation**: Enforce invariant $\text{RUNNING} \le 2$ across the full execution lifecycle. Zero double-dispatching, zero task dropping, zero execution duplication, zero license token leak.
  - **Status & Evidence**: `DONE` — All 8 tasks dispatched across 4 worker threads; 48 timeline samples confirm $\text{RUNNING} \le 2$ strictly maintained throughout execution.
- [x] **G3-R3: Authentic Abaqus Solver Failure & RunRecovery Resilience**
  - **Requirement**: Induce authentic numerical singularity or unconstrained rigid body motion in Abaqus/Standard (no artificial `raise RuntimeError`).
  - **Validation**: Solver terminates abnormally with authentic `.sta`/`.msg`/`.lck` diagnostic signatures. `RunWorker` invokes `RunRecovery.inspect_run_state()`, identifies `RECOVERABLE_RESUBMIT`, transitions run to `RETRYING`, allocates clean sandbox, and executes attempt #2 to successful ODB acceptance.
  - **Status & Evidence**: `DONE` — Authentic Abaqus rigid body singularity induced in Attempt 1 (`.msg` failure diagnosed); Worker automated Attempt 2 with Encastre BC, reaching `COMPLETED` and valid ODB (217KB).
- [x] **G3-R4: Worker Process Crash & Orphaned Run Recovery**
  - **Requirement**: Terminate a running Worker process abruptly (simulating host panic or SIGKILL) while tasks reside in `RUNNING`.
  - **Validation**: Upon process restart, new Worker initializes, reads durable queue from `persistence_path`, executes `recover_orphaned_runs()`, transitions stranded `RUNNING` tasks to `RETRYING`, and completes execution cleanly without deadlock.
  - **Status & Evidence**: `DONE` — Unexpected termination simulated with active `RUNNING` task; durable queue restored via atomic file swap, `recover_orphaned_runs()` recovered task to `RETRYING`, and subsequent worker executed to `COMPLETED`.
- [x] **G3-R5: License Token Exhaustion & Exponential Backoff**
  - **Requirement**: Configure constrained token limit ($N=1$). Submit 2 competing jobs. Job A reserves token and transitions to `RUNNING`. Job B is denied, enters `RETRYING` with exponential backoff and jitter, and successfully acquires token upon Job A release.
  - **Validation**: Cooperative task suspension without job abort or state corruption.
  - **Status & Evidence**: `QUALIFIED` — Offline token contention and backoff verified. Physical quota server connection honestly classified as `REAL_LICENSE_SERVER_NOT_AVAILABLE` (zero synthetic falsification).
- [x] **G3-R6: End-to-End Artifact Integrity & Provenance Promotion**
  - **Requirement**: Complete execution cycle verifying all primary artifacts (`.inp`, `.odb`, `.sta`, `.msg`, `.dat`) are non-empty, cryptographically hashed via SHA-256, verified readable via `openOdb`, and safely promoted to long-term storage while purging ephemeral scratch files.
  - **Validation**: Full provenance link between `AnalysisRun`, `RunSandbox`, and final promoted evidence manifests.
  - **Status & Evidence**: `DONE` — 15 promoted production artifacts audited with non-empty cryptographic SHA-256 digests; temporary sandbox directories purged without leakage.

---

#### Track GA-1: Arbitrary Complex CAD Topology & Adaptive Meshing [P1 ENGINEERING CORE]
*Structural Mechanics Expansion: Moving from parametric primitives to complex industrial CAD via a decoupled, multi-stage pipeline with fail-closed gating at every transition.*

##### Architectural Foundation & CAD Backend Boundary
1. **Zero Duplicate CAD Kernel Rule**: OpenCASCADE (pythonocc-core) serves strictly as an inspection, validation, and topological analysis backend helper. It shall **never** be used to construct a secondary internal CAD modeling kernel. All final geometric operations, cell partitioning, and meshing directives compile strictly to native Abaqus CAE/Python commands.
2. **Deterministic Capability Boundary**: Every stage in the GA-1 pipeline must evaluate its output against the project's canonical 4-state capability contract:
   - `SUPPORTED`: Feature/topology completely within autonomous resolution capability.
   - `ASSISTED`: Complex topology requiring parameter guidance or falling back to robust secondary strategies (e.g. tetrahedral fallback).
   - `BLOCKED`: Geometry contains un-meshable flaws (open shell, non-manifold edge) that strictly halt execution before solver dispatch.
   - `UNSUPPORTED`: Topology format or feature class outside engineering capability scope.

##### Stage 1 Core Pipeline (Phased Rollout: GA-1.1 ~ GA-1.4)
```
CAD Ingestion (GA-1.1) 
       │
       ▼
Geometry Health Inspection (GA-1.2)
       │
       ▼
Topology Normalization & Feature Recognition (GA-1.3)
       │
       ▼
Meshability Assessment (GA-1.4) ───[Direct Reuse]───► Existing Mesh Quality Gate (mesh/mesh_gate.py)
```

- [x] **GA-1.1: STEP / IGES Neutral CAD Ingestion & Canonical Geometry Model**
  - [x] Robust neutral CAD file ingestion (`.stp`, `.step`, `.igs`, `.iges`) compiling into a unified, lightweight internal `GeometryModel`.
  - [x] Extract standardized topological primitives: solids, open shells, boundary faces, edges, vertices, bounding box dimensions, and source units.
  - [x] Enforce source provenance tracking: SHA-256 hash of original CAD file, import timestamps, and CAD system vendor tags.
  - [x] Implemented canonical 4-state capability boundary evaluation (`SUPPORTED`, `ASSISTED`, `BLOCKED`, `UNSUPPORTED`).
  - [x] Zero duplicate CAD kernel: lightweight deterministic Python parser with 100% offline regression coverage (7 tests in `tests/test_cad_ingestion.py`).
- [x] **GA-1.2: Geometry Health Inspection & Defect Detection Gate**
  - [x] Multi-layer non-destructive geometry audit: topological consistency (non-manifold edge, dangling edge, shell closure), geometric consistency (degenerate zero-length edge, zero-area face), scale anomalies (micro-slivers, tiny edge features).
  - [x] Analysis-intent compatibility: explicitly differentiate intentional shell/surface models (`SUPPORTED` under shell intent) from invalid solid volume voids (`BLOCKED` under solid intent) without assuming open shell is an unconditional defect.
  - [x] Strict Fail-Closed Rule: Map health diagnostic results directly into the 4-state capability contract (`SUPPORTED`, `ASSISTED`, `BLOCKED`, `UNSUPPORTED`).
  - [x] Strict non-destructive contract: pure detection and auditing; zero auto-healing, zero auto-stitching, zero secondary CAD kernel invention (8 tests in `tests/test_geometry_health.py`).
- [x] **GA-1.3A: Canonical Topology Normalization**
  - [x] Canonical B-Rep hierarchy normalization: map `Solid -> Shell -> Face (outer/inner loops) -> Edge -> Vertex` into deterministic `NormalizedTopology`.
  - [x] Full boundary loop modeling: introduce `CadLoop` differentiating outer boundary loops from inner void/hole loops with oriented edge sequences.
  - [x] Complete bidirectional adjacency indices: resolve `edge_to_adjacent_faces`, `vertex_to_incident_edges`, `face_adjacency` via shared edges, boundary edges, and connected components.
  - [x] Idempotent identity rule: deterministic sorting across all entity mappings guarantees identical topological graph identity across repeated ingestions. Zero duplicate CAD kernel dependency (5 tests in `tests/test_topology_normalization.py`).
- [x] **GA-1.3B: Functional Feature Recognition (Staged Rollout)**
  - [x] Stage 1 Fastener Hole detection: unified `FeatureCandidate` / `FeatureEvidence` contract, cylindrical/conical faces + axis + closed loops + diameter/depth metrics, through/blind/counterbore/countersink classification, oversized cavity false-positive rejection, and non-manifold block gate (7 tests in `tests/test_feature_recognition.py`).
  - [x] Stage 2 Fillet recognition: constant-radius cylindrical faces bridging non-coplanar corner faces, scale-ratio filtering, honest continuity gating (`ASSISTED` + `INSUFFICIENT_SURFACE_CONTINUITY_EVIDENCE` strictly forbidding hallucinated G1 claims), radius extraction gated strictly by real circle/arc evidence (`radius=None` and `is_constant_radius=False` without arc evidence; zero `5.0` or area-heuristic fallbacks), and non-manifold block gate.
  - [x] Stage 3 Chamfer recognition: planar transitional surfaces bridging exactly two non-coplanar primary adjacent faces with transverse width thresholding, oversized sloped face rejection, strict non-fabrication of width without transverse edges (`width=None`), honest `ASSISTED` capability rating pending full 3D B-Rep spatial metric proof, and non-manifold block gate.
  - [x] GA-1.3B-4.1 Evidence Hardening & Deep Recursive Type Guard: `FeatureCandidate.geometry` deep recursive validation strictly forbidding runtime non-canonical objects, zero synthetic radius/width defaults, and consolidated feature specialization disambiguation (17 tests in `tests/test_feature_recognition.py`).
  - [x] Stage 4 Rib and Contact Plane classification (GA-1.3B-5): candidate semantic extraction with `ASSISTED` confidence flags, opposing wall topology, common base anchoring, protrusion vs. groove/pocket rejection guard, dimensional thickness/length extraction strictly degrading to `None` without transverse edge evidence, contact spotface/flange anchoring, strict normal vector unit verification (unverified normals strictly degrade to `normal=None` with zero synthetic normalization), zero contact-pair interaction actions, and consolidated 5-class feature disambiguation (28 tests in `tests/test_feature_recognition.py`).
  - [x] GA-1.3B-5.1 Evidence Hardening: Groove guard loophole closed (V-groove/bottom seam sharing edge without outward cap strictly rejected), honest docstring/code convergence to direct common-base attachment (zero unverified `attachment_depth <= 2` claims), normal validity unit guard on candidate rib walls, and conservative protrusion evidence enforcement (30 tests in `tests/test_feature_recognition.py`, 507 repository-wide regression tests).
- [x] **GA-1.4: Meshability Assessment & Direct Mesh Gate Reuse (Real-Machine Qualified)**
  - [x] Pre-meshing Geometry Meshability Gate: Multi-layer evaluation consuming `GeometryModel`, `GeometryHealthReport`, `NormalizedTopology`, and `FeatureCandidate`. Fail-closed blocking (`BLOCKED`, `is_meshable=False`) on topological or geometric defects (non-manifold edge, unclosed solid shell).
  - [x] Local Geometric Risk Screening: Detect sub-scale tiny edges ($L_e < 0.005 L_{\text{char}}$) and micro-sliver faces ($A < 10^{-4} L_{\text{char}}^2$) generating `TINY_FEATURE_DEFORMATION` and `SLIVER_FACE_DISTORTION` warning risks. Detect target mesh size conflicts ($h_{\text{target}} > 2 \times \min(L_e)$) as non-blocking `SCALE_CONFLICT_ELEMENT_SWALLOWING` warnings.
  - [x] Evidenced Feature Scale Hints: Heuristic refinement candidate derivation strictly bounded by proven feature parameters (holes $\sim 0.25D$ without Kt assumptions, fillets $\sim 0.5R$ strictly gated by proven radius, chamfers $\sim 0.5W$, ribs $\sim 0.5T$ with zero partition mandates, contact planes with zero synthetic interaction pairs). Unproven dimensions strictly degrade to `suggested_size=None` and review classification.
  - [x] Zero Duplicate Mesh Gate: Direct bridge to existing `GeometryMeshPlan` (`MeshRefinementRequest`) with explicit separation before post-meshing element shape gates in `src/abaqus_ai_agent/mesh_gate.py` (`evaluate_mesh_quality_gate`). Explicit `limitations` contract stating unverified hex sweep and partition feasibility (10 tests in `tests/test_meshability.py`).
  - [x] Real-Machine Mesh Qualification Suite (M1 ~ M4 + STEP-HOLE + STEP-FILLET) [FROZEN & REAL_ABAQUS QUALIFIED]:
    - Validated closed-loop pipeline from CAD geometry to GA-1.4 meshability, `GeometryMeshPlan`, live Abaqus 2025 mesh generation, actual element size back-measurement, and `mesh_gate.py` post-mesh evaluation.
    - M1 Plain Block: Global baseline mesh (320 hex elements, C3D8R, 525 nodes; dynamically computed mean size 5.0mm, max AR 1.0, `mesh_gate` PASS).
    - M2 Plate + Hole: GA-1.3B hole recognition $\to$ GA-1.4 suggested size ($0.25D = 5.0\text{ mm}$) $\to$ Abaqus local seeding $\to$ **dynamically back-measured actual hole perimeter element size ($4.450\text{ mm}$ vs global $9.878\text{ mm}$, refinement ratio $0.451 < 0.70$ verified)** $\to$ `mesh_gate` PASS.
    - M3 Plate + Fillet: Evidenced fillet radius ($R=6.0\text{ mm}$) $\to$ suggested size ($0.5R = 3.0\text{ mm}$) $\to$ Abaqus local seeding $\to$ **dynamically back-measured actual fillet span size ($3.106\text{ mm}$ vs far-field $8.171\text{ mm}$, refinement ratio $0.380 < 0.60$ verified)** $\to$ `mesh_gate` PASS.
    - M4 Defective Geometry: Non-manifold defect $\to$ GA-1.4 fail-closed gate (`BLOCKED`, `is_meshable=False`) $\to$ plan conversion blocked $\to$ zero Abaqus mesh dispatched.
    - STEP-HOLE Real CAD Pipeline: Real STEP file (`plate_with_hole.step`) $\to$ pure Python ingestion $\to$ health audit $\to$ topology normalization $\to$ fastener hole recognition ($D=20.0\text{ mm}$) $\to$ GA-1.4 suggested size ($5.0\text{ mm}$) $\to$ Abaqus 2025 mesh $\to$ **actual hole element back-measurement ($4.450\text{ mm}$ vs global $9.878\text{ mm}$, ratio $0.451$)** $\to$ `mesh_gate` PASS (zero artificial `FeatureCandidate` fixture).
    - STEP-FILLET Real CAD Pipeline: Real STEP file (`stepped_fillet_bar.step`) $\to$ pure Python ingestion $\to$ health audit $\to$ topology normalization $\to$ fillet recognition ($R=5.0\text{ mm}$) $\to$ GA-1.4 suggested size ($2.5\text{ mm}$) $\to$ Abaqus 2025 mesh $\to$ **actual fillet element back-measurement ($3.191\text{ mm}$ vs far-field $10.481\text{ mm}$, ratio $0.304$)** $\to$ `mesh_gate` PASS (provenance distinction: feature radius $5.0\text{ mm}$ vs. actual mesh edge $3.191\text{ mm}$ explicitly decoupled).
    - Harness 2.0 Hardening: Strict fail-fast enforcement (missing launcher or solver execution error raises immediate failure without silent fallback; explicit `--offline` required for emulated regressions; zero hardcoded mesh metrics).
    - Audited evidence manifest: `machine_validation/ga14_real_machine_evidence.json` (6/6 passed; 16 qualification tests in `tests/test_ga14_qualification.py`, 533 repository-wide regression tests).
    - **Frozen Baseline & Evidence Boundary (Commit `cb597d6`)**: Track GA-1.1 ~ GA-1.4 is formally CLOSED and FROZEN. Boundary disclosure: Qualification covers Minimal STEP B-Rep, Hole/Fillet feature recognition, and defined benchmark geometries; it does not claim universal automated meshing for arbitrary unconstrained industrial CAD.

##### Post-GA Future Expansion (GA-1.5 ~ GA-1.7) [DEFERRED - Does not block Track GA-2 Active Line]
*Note: GA-1.1 ~ GA-1.4 baseline is formally closed and frozen. The following capabilities are reserved for future architectural expansion and are strictly decoupled from the active GA-2 engineering track.*
- [ ] **GA-1.5: Autonomous Virtual Topology & Cell Partition Strategy**
  - [ ] Implement rule-based and AI-guided volume partitioning to decompose complex 3D bodies into sweepable cells.
  - [ ] Synthesize native Abaqus partition planes, datum sketches, and cell cut actions (`Part.PartitionCellByPlane`, `PartitionCellByExtrudeEdge`).
- [ ] **GA-1.6: Hybrid Mesh Generation & Curvature-Driven Refinement**
  - [ ] Multi-zone mesh synthesis: structured hexahedral (C3D8R) in sweepable sub-volumes with automated transition to quadratic tetrahedral (C3D10) in complex fillets.
  - [ ] Local seed refinement driven by curvature and proximity at stress concentrations.
- [ ] **GA-1.7: Complex Multi-Part Assembly & Contact Grounding**
  - [ ] Resolve assembly component hierarchy and instance transformations for multi-part CAD models.
  - [ ] Automate proximity-based contact pair discovery between mating surfaces; synthesize native Master-Slave surfaces and Tie constraints.

---

#### Track GA-2: Semantic Physical Grounding & Deterministic Compilation [P1 ENGINEERING CORE]
*The Deterministic Bridge: Connecting natural-language engineering intent to CAD topological features, deterministic Abaqus actions, live solver execution, and physical reaction equilibrium closure.*

##### Track GA-2.1 ~ GA-2.4 Core Pipeline (Feature Grounding & First Golden Case) [CLOSED & REAL_ABAQUS QUALIFIED]
```
Natural Language Prompt
       │
       ▼
EngineeringIntent (GA-2.1)
       │
       ▼
STEP Minimal B-Rep & Feature Candidates (GA-1.1 ~ GA-1.3B)
       │
       ▼
Feature & Physical Grounding (GA-2.2) ──► Pure GroundedRegion (Abaqus-neutral)
       │
       ▼
Deterministic Compiler (GA-2.3) ──► Native faces.findAt() & Equivalent Pressure (P = F / A)
       │
       ▼
Preflight Engine (33 checks / 0 blockers)
       │
       ▼
Abaqus 2025 Live Solver
       │
       ▼
ODB Tensor Extraction & Equilibrium Verification (RF vs Applied Error = 0.002%) (GA-2.4)
```

- [x] **GA-2.1: Semantic Engineering Intent Schema**
  - [x] Structured representation of engineering requests without premature solver coupling (`AnalysisIntent`, `GeometryIntent`, `BoundaryConditions`, `Loads`, `Outputs`).
  - [x] Explicit grounding requirements: marks target regions as requiring topological grounding before solver dispatch.
- [x] **GA-2.2: Feature & Physical Grounding Engine (`src/abaqus_ai_agent/grounding/feature_grounding.py`)**
  - [x] Deterministic mapping from high-level semantic targets (`INSTALLATION_HOLE`, `TOP_SURFACE`) to verified geometric entities in `GeometryModel` and `FeatureCandidate`.
  - [x] Output pure, Abaqus-neutral `GroundedRegion`: includes spatial anchor coordinates `(x, y, z)`, entity IDs, confidence, status, and supporting evidence; strictly forbids generating raw Abaqus API expressions (e.g. `findAt`) in the grounding layer.
  - [x] Topological disambiguation & selection heuristics:
    - `INSTALLATION_HOLE`: Matches `FASTENER_HOLE` candidates, filters cylindrical faces, computes axial anchor coordinates.
    - `TOP_SURFACE`: Evaluates face planarity, normal orientation ($n_z \approx 1$), local height $z_{\max}$, surface area, and non-hole topology.
  - [x] Fail-closed gating: zero-candidate, ambiguous multiple unranked candidates, or entity type mismatches immediately return `BLOCKED` / `NEEDS_CLARIFICATION` (6 tests in `tests/test_feature_grounding.py`).
- [x] **GA-2.3: Deterministic Intent Compiler Grounded Region Consumption (`src/abaqus_ai_agent/planning/compiler.py`)**
  - [x] Upgraded compiler to consume `GroundedRegion` and handle Abaqus-specific region syntax: synthesizes native `faces.findAt(((x, y, z),))` expressions directly.
  - [x] FEA Load Equivalence: detects concentrated force application on surface regions, automatically converts point force to equivalent distributed surface traction/pressure ($P = F / A$), preventing numerical stress singularities and avoiding Abaqus CAE invalid region errors for concentrated loads on faces.
  - [x] Complete backward compatibility: seamlessly supports string expressions, `RegionBinding`, and `GroundedRegion` across boundary conditions and mechanical loads (2 tests in `tests/test_agent_compiler.py`).
- [x] **GA-2.4: First End-to-End Real-Machine Golden Case (`tools/ga2_e2e_golden_case.py`)**
  - [x] Verified full autonomous chain on real STEP file (`plate_with_hole.step`): Prompt (*"将安装孔的圆柱面完全固定，在顶面施加 1000 N 向下集中载荷，计算最大应力和位移"*).
  - [x] Executed live under Abaqus 2025:
    - Preflight audit: 33 checks passed, 0 blockers.
    - Applied load: $-1000.0\text{ N}$.
    - Live reaction force sum: $\Sigma RF_z = 1000.02\text{ N}$.
    - **Equilibrium balance error: $0.002\%$** (far below $0.1\%$ physical tolerance threshold).
    - Extracted metrics: Max Mises stress $3.149\text{ MPa}$, Max displacement $0.000777\text{ mm}$, 2014 C3D10 elements, 3431 nodes.
  - [x] Full provenance & evidence envelope: `machine_validation/ga2_golden_evidence.json` marked as `QUALIFIED` with `REAL_ABAQUS` level (4 tests in `tests/test_ga2_e2e_golden.py`, 544 repository-wide regression tests).

##### Stage 2 Intent Expansion & Multimodal Grounding (GA-2.5 ~ GA-2.6 & GA-2A / GA-2B)
- [x] **GA-2.5: Extended Feature Semantics Grounding [CLOSED & QUALIFIED]**
  - [x] Implemented semantic resolvers for `BOTTOM_SURFACE`, `SYMMETRY_PLANE` (including `SYMMETRY_X/Y/Z`), `BEARING_SEAT`, `SIDE_WALL` (including `LEFT/RIGHT/FRONT/BACK_WALL`), and multi-feature groups (`ALL_HOLES`, `FASTENER_HOLES`, `BOLT_GROUP`).
  - [x] Upgraded `GroundedRegion` contract to support composite `anchor_points` and `feature_ids` while preserving complete backward compatibility with existing single-entity consumers.
  - [x] Upgraded `compiler.py` to synthesize native multi-object `findAt(((x1,y1,z1),), ((x2,y2,z2),), ...)` sets and surfaces, enabling simultaneous group constraint and load application.
  - [x] Enforced strict fail-closed gating: 0 candidates -> `NOT_FOUND`, competing candidates without dominant area or un-directed side/symmetry planes -> `AMBIGUOUS` with explicit user guidance.
  - [x] Added 9 targeted tests covering all extended semantics and boundary failure modes (14 tests in `tests/test_feature_grounding.py`, 3 tests in `tests/test_agent_compiler.py`, 553 repository-wide regression tests).
- [ ] **GA-2.6: Multi-Step & Complex Physical Load Procedure Compilation**
  - [x] **GA-2.6.0: Physical Procedure & Lifecycle Contracts [CLOSED & QUALIFIED]**
    - [x] Implemented multi-step procedure DAG contract (`MultiStepProcedureSpec`, `StepDependency`) with parent dependency validation and `nlgeom` cross-step conflict safety guards.
    - [x] Formulated two-stage bolt pretension lifecycle contract (`BoltPretensionLifecycleSpec`, `BoltPretensionMethod`: `APPLY_FORCE` -> `FIX_LENGTH`).
    - [x] Formulated load transfer strategy matrix for moment/torque on continuous media (`MomentLoadSpec`, `MomentTransferStrategy`: `RP_COUPLING`, `DISTRIBUTED_COUPLE`, `EXISTING_RP`, `DIRECT_DOF`).
    - [x] Implemented strict whitelist AST validator for analytical spatial fields (`validate_field_expression`, `SpatialLoadField`), eliminating string injection while permitting coordinate arithmetic ($X, Y, Z$).
    - [x] Upgraded `preflight.py` with fail-closed gates for step DAG order, `nlgeom` downgrade blocking, bolt lifecycle inversions, moment strategy checks, and field expression AST guards.
    - [x] Added 12 targeted procedure & preflight tests (`tests/test_procedure_contracts_preflight.py`, 565 repository-wide regression tests).
  - [x] **GA-2.6.1: Abaqus 2025 Physical API Probes & Solver Calibration [CLOSED & QUALIFIED]**
    - [x] Implemented fail-fast physical probe harness in `tools/ga261_physical_api_probes.py`.
    - [x] Probe 0 (P0 Multi-Step State Inheritance): Verified state inheritance across `Initial` $\to$ `Step-1` $\to$ `Step-2`. Step-1 load $1000.0\text{ N}$ propagated into Step-2 with $500.0\text{ N}$ increment; live $\Sigma RF_y = 1500.0\text{ N}$ (relative error $< 2 \times 10^{-6}\%$).
    - [x] Probe 1 (P1 Bolt Pretension Lifecycle): Verified two-stage lifecycle (`APPLY_FORCE` $\to$ `FIX_LENGTH`). Step-Preload achieved target bolt reaction $-5000.0\text{ N}$ ($0.0\%$ error); Step-Service locked length, released top support, and applied $2000.0\text{ N}$ external tension with exact bottom reaction equilibrium ($-2000.0\text{ N}$).
    - [x] Probe 2 (P2 Analytical Spatial Load Field): Verified native `ExpressionField` (`1.0 + 0.02 * Y`) with `Pressure(..., distributionType=FIELD)`. Numerical surface integration yielded $\Sigma RF_z = 14999.9999\text{ N}$ against exact analytical integral $15000.0\text{ N}$ (relative error $7.1 \times 10^{-7}\%$).
    - [x] Probe 3 (P3 Moment / Coupling Strategy): Verified Reference Point + Kinematic Coupling on 3D solid continuum with zero rotational DOFs. Applied $100000.0\text{ N}\cdot\text{mm}$ torque $M_z$; root reaction shear couple yielded $-99999.997\text{ N}\cdot\text{mm}$ (equilibrium error $2.9 \times 10^{-6}\%$, net shear force zero drift $2.6 \times 10^{-11}\text{ N}$).
    - [x] **API Calibration**: Calibrated native Abaqus CAE concentrated moment syntax (`m.Moment` instead of invalid `m.ConcentratedForce(..., cm3=...)` which triggered solver keyword rejection).
    - [x] Persisted certified live solver manifest: `machine_validation/ga261_probe_evidence.json` (4/4 Probes PASS on Abaqus 2025).
    - [x] Added 4 probe regression tests (`tests/test_ga261_probes.py`, 569 repository-wide regression tests).
  - [x] **GA-2.6.2: Multi-Step & Physical Procedure Compiler Integration [CLOSED & QUALIFIED]**
    - [x] Upgraded `src/abaqus_ai_agent/planning/compiler.py` to synthesize multi-step DAG analysis sequences (`MultiStepProcedureSpec` / `steps` / legacy `step`), guaranteeing 100% backward compatibility for single-step intents.
    - [x] Integrated two-stage bolt pretension lifecycle (`BoltPretensionLifecycleSpec`): automatically generates `DatumAxisByTwoPoints` direction reference, sets `BoltLoad(..., boltMethod=APPLY_FORCE)` in the preload step, and calls `loads[...].setValuesInStep(..., boltMethod=FIX_LENGTH)` in the service step.
    - [x] Implemented moment/torque transfer on continuous media (`MomentLoadSpec`, `MomentTransferStrategy.RP_COUPLING`): automatically creates Reference Point, Kinematic Coupling constraint, and applies native `m.Moment(name, createStepName, region, cm1, cm2, cm3)` directly on the RP set.
    - [x] Implemented spatial analytical field compilation (`SpatialLoadField`): performs fail-closed AST validation (`validate_field_expression`), synthesizes `ExpressionField(...)`, and connects pressure loads via `Pressure(..., distributionType=FIELD, field=...)`.
    - [x] Integrated symmetry boundary conditions (`XsymmBC`, `YsymmBC`, `ZsymmBC`) across explicit boundary specs and grounded semantics (`SYMMETRY_PLANE_X/Y/Z`).
    - [x] Added 6 comprehensive compiler integration tests in `tests/test_agent_compiler.py` (9/9 compiler tests passed; 575 repository-wide regression tests passed).
  - [x] **GA-2.6.3: Real Abaqus 2025 Multi-Step Golden Verification [CLOSED & QUALIFIED]**
    - [x] Executed autonomous end-to-end benchmark on live Abaqus 2025: Two-step procedure (`Step-Preload` APPLY_FORCE $5000\text{ N} \to$ `Step-Service` FIX_LENGTH with external tension $2000\text{ N}$ and torque $100000\text{ N}\cdot\text{mm}$ via RP Kinematic Coupling).
    - [x] Certified 5-layer engineering acceptance criteria:
      1. Procedure DAG: Initial $\to$ Step-Preload $\to$ Step-Service validated.
      2. Bolt Pretension: Preload measured $\Sigma RF_z = -4999.9999\text{ N}$ (target $5000\text{ N}$, relative error $1.5 \times 10^{-8}$).
      3. External Load Equilibrium: Service axial reaction $\Sigma RF_z = -1999.99999\text{ N}$ (target $2000\text{ N}$, error $3.8 \times 10^{-9}$); service reaction torque $\Sigma RM_z = -99999.999\text{ N}\cdot\text{mm}$ (target $100000\text{ N}\cdot\text{mm}$, error $9.2 \times 10^{-9}$); net shear drift $2.3 \times 10^{-13}\text{ N}$.
      4. Physical Validity: Evaluated via deterministic acceptance engine (`evaluate_result_acceptance`), max Mises $74.72\text{ MPa}$, max displacement $0.0804\text{ mm}$, elements $320$, status `PASS`.
      5. Evidence & Provenance: Persisted `.inp`, `.odb`, `.sta`, `.msg`, `.dat`, `.log` with SHA-256 cryptographic provenance in `machine_validation/ga263_golden_evidence.json` (Tier `REAL_ABAQUS`).
    - [x] Full regression test suite passing (579/579 tests, 0 failures). Formally declared Track GA-2.6 **CLOSED & QUALIFIED**.

---

#### Track GA-CL: Full-Chain Multi-Physics Closure & Failure Hardening [CLOSED & QUALIFIED]
*Core Strategic Pivot: Following the formal closure of Track GA-2.6 (multi-step procedural compiler & real Abaqus physical evidence), the repository shifted from foundational procedure enablement to broad multi-physics coverage, authentic solver failure-path verification, and end-to-end acceptance/reporting closure. With GA-CL.1 ~ GA-CL.8 fully verified, the baseline is formally frozen for RC1.*

- [x] **GA-CL.1: Agent Multi-Physics Golden Expansion (Intent -> Compiler -> Live Abaqus -> ODB) [CLOSED & QUALIFIED]**
  - [x] **GA-CL.1-R1 Full-Chain Architectural Refinement**:
    - MP-1 True Sequential Thermal-Stress Coupling (`MP1_SequentialThermalStructural`): two-phase analysis. Phase 1 executes steady-state thermal conduction with `DC3D8` heat transfer elements ($100^\circ\text{C} \to 20^\circ\text{C}$, `Job_MP1_Thermal.odb` with `NT11`). Phase 2 executes static stress with `C3D8R` elements importing the thermal ODB field via predefined field mapping; constrained axial expansion produces authentic thermal stress ($170.80\text{ MPa}$), reaction force ($15159.53\text{ N}$), and global reaction equilibrium sum $= 0.00\text{ N}$.
    - MP-2 Large-Sliding Frictional Contact (`MP2_FrictionContact`): compiled autonomously via `compile_intent_to_actions` using `two_blocks_contact` geometry and `IntentInteractionSpec`. Surface-to-surface standard contact with penalty friction ($\mu=0.25$), normal reaction balance ($1052.39\text{ N} \approx 1000\text{ N}$), peak contact pressure $CPRESS=2.337\text{ MPa}$, and peak tangential shear $CSHEAR1=0.5842\text{ MPa}$ precisely matching the Coulomb friction limit ($\tau / p = 0.2500$, error $< 0.01\%$).
    - MP-3 Preloaded Modal Dynamics (`MP3_PreloadedModal`): compiled autonomously via `compile_intent_to_actions`. Two-step procedure with axial tensile preload ($10000\text{ N}$, reaction $RF = -9998.50\text{ N}$, error $< 0.02\%$) followed by frequency extraction inheriting stress stiffening ($f_1 = 331.77\text{ Hz}$).
    - MP-4 Explicit Dynamic Transient Impulse (`MP4_ExplicitDynamic`): compiled autonomously via `compile_intent_to_actions`. Abaqus/Explicit dynamic wave response, central difference time integration, $ALLKE = 50.00\text{ mJ}$, $ALLIE = 86.65\text{ mJ}$, $ALLWK = 139.29\text{ mJ}$, energy balance error $1.93\% < 5\%$.
  - [x] All 4 Golden benchmarks compiled dynamically from `EngineeringIntent` via `compile_intent_to_actions` into native Abaqus actions and executable CAE scripts (zero hardcoded manual model creation).
  - [x] Implemented deterministic ODB field gating (`odb_fields` against `PhysicsResultProfile.required_fields`) across all domains in `evaluate_result_acceptance`.
  - [x] Executed negative probes for all 4 cases: missing key physical outputs (`NT`, `CSHEAR`, `RF`, `ALLKE`) deterministically triggered fail-closed rejection as `RESULT_INVALID` / `BLOCKED`.
  - [x] Validated unforgeable executive reporting audit summaries (`Solver: PASS | ODB: PASS | Required Result: PASS | Engineering Acceptance: PASS`) and persisted cryptographic SHA-256 provenance in `machine_validation/multi_physics_golden_manifest.json` (Tier `REAL_ABAQUS`). 600/600 regression tests passing.

- [x] **GA-CL.2: Real-Machine Failure-Path Matrix & State Preservation [CLOSED & QUALIFIED]**
  - [x] Upgrade `tools/i2_failure_matrix.py` and implement `tools/real_failure_matrix_e2e.py` with genuine Abaqus 2025 error injection & cryptographic tamper protection:
    - `UNCONSTRAINED_RIGID_BODY` (F1): omit boundary conditions, trigger Abaqus Standard Zero Pivot / Numerical Singularity abort -> verified status `FAILED`/`BLOCKED`, fail_closed=True.
    - `CONVERGENCE_CUTBACK_EXHAUSTED` (F2): plastic softening with minInc=0.08, initialInc=0.1, trigger cutback below minimum time increment -> verified status `FAILED`/`BLOCKED`, fail_closed=True.
    - `INP_SYNTAX_ABORT` (F3): inject invalid keyword syntax, trigger Abaqus pre-processor fatal error rejection -> verified status `FAILED`/`BLOCKED` with `.dat` preservation, fail_closed=True.
    - `MISSING_REQUIRED_FIELD_OUTPUT` (F4): job succeeds exit 0 and ODB exists, but required field output `U` (`max_displacement`) is omitted -> verified deterministic intercept as `RESULT_INVALID` / `BLOCKED`, fail_closed=True.
    - `EVIDENCE_TAMPER_PROTECTION` (F5): cryptographic SHA-256 mutation detection on ODB/INP -> verified fail-closed rejection.
  - [x] Persist certified live evidence package: `machine_validation/real_failure_matrix_evidence.json` (5/5 cases fail-closed).

- [x] **GA-CL.3: Mesh -> Solver -> ODB -> Acceptance Full Pipeline Closure [CLOSED & QUALIFIED]**
  - [x] Enhance `evaluate_result_acceptance` with physics-aware mandatory gate dispatch:
    - Analysis intents with contact MUST require `contact_diagnostics` (no silent `SKIPPED`).
    - Non-mandatory gates record explicit engineering justifications when SKIPPED.
    - Missing required physical metrics or mandatory gates deterministically set `result_validity="RESULT_INVALID"` and status `BLOCKED`.
  - [x] Proved across 5 domains (static, thermal, contact, modal, multi-step) that missing required outputs or gates fail closed.
  - [x] Proved on authentic Abaqus 2025 ODB (`Job_F4_MissingOutput.odb`) that solver exit 0 without displacement output fails closed as `RESULT_INVALID`.

- [x] **GA-CL.4: Evidence / Provenance Schema V2 & Cryptographic Contract [CLOSED & QUALIFIED]**
  - [x] Standardize all evidence manifests under unified `EvidenceManifestV2` contract (`contracts/evidence.py`):
    - Run Identity Binding: binds `run_id`, `case_id`, `created_at`, solver version (`Abaqus 2025`), intent hash, and required results into an immutable envelope.
    - Live Artifact Integrity: hashes `.inp`, `.odb`, `.sta`, `.msg`, `.dat`, `.log` via SHA-256; verifies file existence and non-empty byte count.
    - Anti-Stale Protection: detects run identity mismatches, case mismatches, or expired/stale artifact timestamps, failing closed as `EVIDENCE_STALE`.
    - Tamper Protection: bit-level mutation detection on disk artifacts or digital signatures fails closed as `EVIDENCE_TAMPERED`.
    - Incomplete Artifact Protection: missing required solver logs (.msg/.dat) fail closed as `EVIDENCE_INCOMPLETE`.
  - [x] Acceptance Integration: upgraded `evaluate_result_acceptance` with mandatory `evidence_sufficiency` gate. Manifest validation failures strictly override solver exit codes and set `result_validity="RESULT_INVALID"` / status `BLOCKED`.
  - [x] Executive Report Sync: synchronized `reporting/renderer.py` to display Evidence V2 Manifest ID, cryptographic integrity status, and provenance audit traces; prohibits unverified results from being rendered as valid engineering conclusions.
  - [x] Live Real-Machine Validation: verified 7 vectors in `tools/evidence_v2_qualification_e2e.py` and persisted `machine_validation/evidence_v2_manifest.json` (Tier `REAL_ABAQUS`). 608/608 regression tests passing.

- [x] **GA-CL.5: Engineering Report Cross-Physics Consistency & Unforgeable Audit [CLOSED & QUALIFIED]**
  - [x] Extend `src/abaqus_ai_agent/reporting/renderer.py` to render structured Verification Integrity & Audit Summary and Verification Gates Detailed Audit tables with engineering justifications.
  - [x] Deterministically format unforgeable audit summary line: `Solver: PASS | ODB: PASS | Required Result: FAIL | Engineering Acceptance: FAIL`.
  - [x] Explicitly reject engineering conclusion (`REJECTED (RESULT_INVALID)`) when required outputs or gates are missing, verified on real Abaqus 2025 ODB evidence.

- [x] **GA-CL.6: RC Evidence Freeze & Legacy Manifest Isolation [CLOSED & QUALIFIED]**
  - [x] Standardize all evidence manifests under unified cryptographic baseline freeze; isolated legacy Schema V1 (`golden_matrix_manifest.json`) marked as `DEPRECATED_V1` and archived in `machine_validation/legacy/`.
  - [x] Enforce read-only test suite execution mode ensuring `pytest` never generates dirty working tree diffs or unstaged timestamp noise in tracked evidence.
  - [x] Cryptographic verification (`verify_evidence_integrity`) strictly rejects legacy V1 manifests (`unsupported_legacy_manifest:schema_v1_deprecated_for_rc`).

- [x] **GA-CL.7: Full Agent-Chain Integrity & Zero-Bypass Audit [CLOSED & QUALIFIED]**
  - [x] End-to-end trace audit across all 14 pipeline stages:
    $\text{User Prompt} \to \text{EngineeringIntent} \to \text{PhysicsDomain} \to \text{Grounding} \to \text{Material} \to \text{Mesh} \to \text{Step DAG} \to \text{BC/Load} \to \text{ActionPlan} \to \text{Preflight} \to \text{Abaqus 2025} \to \text{ODB} \to \text{Required Results} \to \text{Verification} \to \text{Acceptance} \to \text{Report}$.
  - [x] Closed P0/P1 bypass vulnerabilities:
    - **P0-1**: Acceptance without valid EvidenceManifest fails closed as `BLOCKED` with `RESULT_INVALID`.
    - **P0-2**: Injected `external_input` results strictly cannot transition to `AnalysisRunState.ACCEPTED`; forced to `RESULTS_EXTRACTED` and `RESULT_SUSPICIOUS`.
    - **P1-1**: Preflight hard gate enforced in `AnalysisRunner` prior to job creation/submission; blocking failures halt execution without starting an Abaqus job.
    - **P1-2**: MP-1 ~ MP-4 Golden benchmarks formally bound to signed `EvidenceManifestV2`, verifying `evidence_sufficiency: PASS`.
    - **P1-3**: Legacy schema V1 manifests deprecated and isolated from RC evidence qualification.
  - [x] Validated across 8 mandatory fail-closed regression scenarios in `tests/test_rc_closure_bypasses.py`. Full test suite: 616/616 tests PASS.

- [x] **GA-CL.8: 20-Domain Physical Capability Audit & RC1 Baseline Freeze [CLOSED & QUALIFIED]**
  - [x] Comprehensive audit across 20 physical engineering domains:
    - Historical RC1 Status: 17 Domains initially qualified at **L4 (Agent Full-Chain Qualified)** and 3 Domains at **L3 (Specialized Workflow Qualified)** (Fatigue, Connectors, FMBD).
    - Post-RC1 Closure Update: All 3 remaining specialized domains have completed their full-chain compiler, runner, Evidence V2, and live Abaqus 2025 golden qualifications (Track GA-F4, GA-C4, GA-M4). **Current baseline is 100% closed at 20 L4 / 0 L3**.
  - [x] Confirmed single-exit acceptance gate architecture: zero bypass paths from `external_input` to `ACCEPTED`, mandatory `EvidenceManifestV2` verification, and fail-closed state transitions.
  - [x] Release Candidate 1.0 formally declared as **`RC1 BASELINE FROZEN` (`v1.0.0-rc1`)** at Commit `41f0c63` with 616/616 regression tests passing.

---

### Post-RC1 Strategic Track: The Unified Engineering Grounding Layer

With the RC1 backend execution, solver closure, Evidence V2, and single-exit acceptance engine formally frozen, the strategic bottleneck of the Abaqus AI Agent transitions from "solver capability expansion" to "engineering intent ingestion".

In practical engineering practice, user requests do not arrive as pre-grounded API regions. They arrive as 3D viewport selections, marked-up technical drawings, photographs with load arrows, and natural language descriptions.

#### Core Architectural Grounding Rules (The Three Laws of Grounding)
1. **Zero Invented Geometry**: The Agent shall **never** hallucinate or invent geometric region names (e.g. guessing `"Face-17"` or fabricated bounding boxes). Boundary conditions and loads are permitted to compile if and only if anchored to verified geometric entities via canonical `GroundedRegion`.
2. **Direct Reuse of Canonical Region Contracts**: No duplicate `VisualRegion`, `CADRegion`, or parallel spatial data structures shall be introduced. All grounding channels (3D viewport picking, 2D blueprints, external photos) compile into canonical `GroundedRegion` (`contracts/geometry.py`), resolved via `RegionResolver` (`grounding/resolver.py`), and consumed by `compile_intent_to_actions()` (`planning/compiler.py`).
3. **Mandatory Human-in-the-Loop (HITL) on Multimodal Vision**: Vision models (GA-2B) are strictly forbidden from directly outputting executable CAE Python scripts or bypassing preflight. They must output a structured `GroundingObservation`, pass confidence thresholds, receive explicit user/engineer confirmation (HITL), and synthesize typed `EngineeringIntent` before touching the solver backend.

```
                         Unified Engineering Grounding Layer
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         ▼                                ▼                                ▼
3D Viewport Picking (GA-2A)     Multimodal Vision (GA-2B)          Textual Intent
  - Perspective Raycasting         - Engineering Blueprints           - Canonical NLP
  - Depth Disambiguation           - Marked Photos & Annotations      - Feature Matching
  - Surface Normal Culling         - Spatial Callouts                 - JEV Router
         │                                │                                │
         └────────────────────────────────┼────────────────────────────────┘
                                          ▼
                                GroundingObservation
                       (Entity Candidates, Confidence, Anchor)
                                          │
                                          ▼
                              Confidence / HITL Gate
                       (User Confirmation if Ambiguous)
                                          │
                                          ▼
                              Canonical GroundedRegion
                             (x, y, z, findAt Syntax)
                                          │
                                          ▼
                                  EngineeringIntent
                                          │
                                          ▼
                       ┌─────────────────────────────────────┐
                       │  RC1 Frozen Canonical Backend Core  │
                       │                                     │
                       │  Compiler -> Preflight -> Abaqus    │
                       │  ODB -> Evidence V2 -> Acceptance   │
                       │  Engineering Report (Single Exit)   │
                       └─────────────────────────────────────┘
```

---

#### Track GA-2A: 3D Viewport Spatial Grounding & Topology Disambiguation [P1 - HIGHEST PRIORITY 🥇]
*Deterministic Viewport Projection: Connecting interactive user viewport clicks to authentic 3D CAD topology and native Abaqus constraints via calibrated perspective camera geometry and spatial raycasting.*

- [x] **GA-2A.1: Perspective Camera Model & Projection Matrix Calibration**
  - [x] Implement robust `PinholeCamera` model (`src/abaqus_ai_agent/grounding/projection.py`) supporting focal length, principal point, aspect ratio, near/far clipping planes, and $4\times 4$ camera extrinsic/intrinsic matrix ($[R|T]$).
  - [x] Calibrate against Abaqus CAE viewport camera parameters (`cameraPosition`, `cameraTarget`, `cameraUpVector`, `perspectiveAngle`).
  - [x] Backward compatibility: preserve existing parallel projection (`OrthographicCamera`) accuracy without breaking existing tests.
- [x] **GA-2A.2: Perspective Raycasting & Spatial Bounding Box Intersection**
  - [x] Implement 2D-to-3D back-projection: map screen normalized device coordinates $(u, v) \in [0, 1]$ to diverging 3D rays originating from the camera optical center $\vec{O}_{\text{cam}}$ along direction $\vec{d}$.
  - [x] Implement fast ray-AABB (Axis-Aligned Bounding Box) spatial screening against candidate geometry parts and topological cells.
- [x] **GA-2A.3: Depth Disambiguation, Z-Buffer & Surface Normal Backface Culling**
  - [x] Deterministic front-surface isolation: filter out back-facing surfaces via ray-normal dot product ($\vec{n} \cdot \vec{d} < 0$).
  - [x] Multi-surface ray penetration: implement $Z$-buffer parametric distance sorting ($t_{\min} = \arg\min t$) to resolve occluded geometry and select the nearest visible entity.
  - [x] Fallback to top-$K$ candidates with explicit confidence scores when intersection falls near geometric edges or sliver regions.
- [x] **GA-2A.4: Direct RegionResolver & Canonical GroundedRegion Bridge**
  - [x] Convert ray intersection 3D coordinates $(x, y, z)$ into canonical `GroundedRegion` (`contracts/geometry.py`).
  - [x] Pass directly into `RegionResolver` (`grounding/resolver.py` and `contracts/geometry.py`) to synthesize native Abaqus `findAt(((x, y, z),))` expressions without inventing duplicate region representations.
- [ ] **GA-2A.5: Real-Machine E2E Golden Verification on Abaqus 2025**
  - [ ] Execute complete autonomous loop: Viewport screen click $(u, v) \to$ Raycast $\to$ `GroundedRegion` $\to$ `compile_intent_to_actions` $\to$ Preflight $\to$ Abaqus 2025 $\to$ ODB $\to$ Evidence V2 $\to$ Acceptance $\to$ Report.
  - [ ] Validate reaction force equilibrium and stress results against analytical references; persist SHA-256 evidence manifest in `machine_validation/ga2a_viewport_golden_evidence.json`.

---

#### Track GA-F4: High-Cycle & Low-Cycle Fatigue L3 $\to$ L4 Full-Chain Upgrade [P1 - SECOND PRIORITY 🥈]
*Closing the Core Physics Gap: Upgrading the existing mature fatigue post-processing library (`src/abaqus_ai_agent/fatigue.py`) to an end-to-end declarative Agent capability driven by `EngineeringIntent`.*

- [x] **GA-F4.1: Declarative Fatigue Intent Contract (`IntentFatigueSpec`)**
  - [x] Implement `IntentFatigueSpec` (`contracts/fatigue.py` & `contracts/intent.py`): cyclic loading profile, target design life ($N_{\text{cycles}}$), allowable cumulative damage ($D_{\max}$), S-N curve parameters, and mean stress correction model (`GOODMAN`, `GERBER`, `SODERBERG`, `NONE`).
  - [x] Preflight validation: verify S-N curve applicability, positive life cycles, and stress tensor field output availability.
- [x] **GA-F4.2: Intent Compiler & Output Planning Integration**
  - [x] Integrate fatigue intent into `compile_intent_to_actions()`: automatically configure field output requests (`fieldOutputRequests`) to ensure stress tensor field output (`'S'`) is recorded.
  - [x] Fix `PhysicsResultProfile` for fatigue domain (`required_fields=("S",)`), preventing unphysical field gate failure.
- [x] **GA-F4.3: Automated ODB Stress History Extraction & Fatigue Engine Bridge**
  - [x] Implement `run_fatigue_postprocess` in `src/abaqus_ai_agent/fatigue.py`: scalar stress reduction (signed von Mises) $\to$ turning point extraction $\to$ rainflow cycle counting $\to$ Goodman mean stress correction $\to$ Palmgren-Miner linear damage summation.
  - [x] Bridge to standard `FatigueResult` dataclass and quantitative metrics (`fatigue_life`, `damage`, `hotspot_element`).
- [x] **GA-F4.4: Deterministic Fatigue Acceptance & Result Requirement Gate**
  - [x] Gate 8 fatigue verification and acceptance: mandatory gates for `fatigue_life` ($\ge N_{\text{target}}$) and `cumulative_damage` ($\le D_{\text{allowable}}$).
  - [x] Fail-closed gating: missing stress history, missing gate, or excessive damage deterministically yields `RESULT_INVALID` / `BLOCKED`.
- [x] **GA-F4.5: Full Agent-Chain Golden Benchmark & Negative Suite (`tools/fatigue_l4_golden_e2e.py` & `tests/test_fatigue_l4_real_machine.py`)**
  - [x] Full-chain live Abaqus 2025 execution: `EngineeringIntent` with `IntentFatigueSpec` $\to$ `compile_intent_to_actions` $\to$ multi-step cyclic solve on Abaqus 2025 $\to$ real ODB extraction $\to$ deterministic rainflow + Goodman + Miner $\to$ `EvidenceManifestV2` $\to$ `evaluate_result_acceptance` $\to$ `PASS`.
  - [x] 4 negative probes verified fail-closed on live artifacts: missing field output 'S' $\to$ `RESULT_INVALID`; omitted fatigue gate $\to$ `BLOCKED`; excessive damage $\to$ `FAIL`; tampered evidence $\to$ `EVIDENCE_TAMPERED`.
  - [x] Persisted authentic cryptographic evidence in `machine_validation/fatigue_l4_golden_manifest.json`.
  - [x] Promoted High-Cycle Fatigue from **L3 Specialized Workflow** to **L4 Agent Full-Chain Qualified** (Interim milestone: 18 L4 / 2 L3; finalized at 20 L4 / 0 L3 on live Abaqus 2025).

---

#### Track GA-2B: Multimodal Perception & Intent Ingestion (Drawings, Blueprints, Photos) [CLOSED & QUALIFIED - Grounding & HITL Protocol]
*Open-World Engineering Context: Associating real-world photos and standard 2D blueprints with 3D CAD models under mandatory Human-in-the-Loop review.*
*(Note: GA-2B closed the Grounding Observation schema, structured callout ingestion, GroundedRegion synthesis, HITL fail-closed protocol, and live Abaqus 2025 closure. True end-to-end computer vision/OCR model ingestion is formally tracked under Phase P1.1).*

- [x] **GA-2B.1: 2D Engineering Drawing Feature & Annotation Parsing**
  - [x] Ingest standard 2D mechanical engineering blueprints (orthographic multi-view projections, section views, datum lines).
  - [x] Parse text and dimension callouts (e.g. *"Fixed constraint at face A"*, *"Apply 5000N bearing load"*, *"Fillet weld R=5"*).
- [x] **GA-2B.2: Grounding Observation Schema & Candidate Correlation**
  - [x] Formulate `GroundingObservation` contract: maps detected visual callouts to candidate CAD topological faces/edges with geometric bounding box, feature type, and probability confidence.
  - [x] Correlate 2D drawing views with 3D CAD topological faces/edges via project-relative bounding box alignment and GA-2A perspective raycasting.
- [x] **GA-2B.3: Mandatory Human-in-the-Loop (HITL) & Confidence Gate**
  - [x] **Zero Direct Code Generation**: Vision models are strictly prohibited from generating executable Abaqus CAE/Python scripts.
  - [x] Visual interpretations synthesize candidate `EngineeringIntent` and present annotated viewports for explicit human confirmation.
  - [x] Execution halts in `NEEDS_CONFIRMATION` until the engineer accepts or refines the grounding candidate.
- [x] **GA-2B.4: Real-Machine Physical Verification**
  - [x] Verified full autonomous chain on live Abaqus 2025 (`Job_GA2B_Multimodal`): 2D Blueprint Callouts $\to$ VisualCallout $\to$ GroundedRegion $\to$ Mandatory HITL Confirmation $\to$ `compile_intent_to_actions` $\to$ Preflight (0 blockers) $\to$ Abaqus 2025 $\to$ Real ODB $\to$ Reaction Equilibrium ($1000.0\text{ N}$ applied vs $1000.0\text{ N}$ reaction, error $0.0000\%$).
  - [x] Verified 4 negative fail-closed probes: unconfirmed observation compilation blocked as `HITLBlockedError`, observation rejection cleanly handled, missing ODB results blocked as `RESULT_INVALID`, and evidence signature tampering blocked as `RESULT_INVALID`.
  - [x] Persisted certified cryptographic evidence manifest in `machine_validation/ga2b_multimodal_manifest.json` (Tier `REAL_ABAQUS`). 661/661 regression tests passing.

---

#### Track GA-C4: Kinematic Connectors & Mechanism Joints [CLOSED & QUALIFIED AT L4]
*Full Agent-Chain Qualification: Integrated into the canonical EngineeringIntent and compiler architecture with live Abaqus 2025 multi-body dynamics verification.*

- [x] **Connectors & Mechanism Joints**: Promoted to **L4 (Agent Full-Chain Qualified, stated connector scope)**.
  - Full canonical chain: `EngineeringIntent(connectors=(IntentConnectorSpec(...),))` $\to$ `compile_intent_to_actions` (automatic RP, DatumCsys, ConnectorSection, WireConnector, and CU/CTF extraction injection) $\to$ `preflight_plan` (0 blockers) $\to$ live Abaqus 2025 Standard solver $\to$ real ODB $\to$ `ConnectorKinematicsVerification` $\to$ Gate 13 (`connector_kinematics`) $\to$ `ACCEPTED` & `RESULT_VALID`.
  - Stated scope: CONN3D2, HINGE / standard connection types, DatumCsys orientation, elasticity/damping behavior, ODB CU/CTF extraction, double pendulum benchmark ($T_1$ error 0.54%, joint drift $9.78\times 10^{-6}$ mm $\le 10^{-3}$ mm, relative rotation $6.96^\circ \ge 2^\circ$, energy dissipation $2.13\% \le 3\%$).
  - Verified 9 negative fail-closed probes (missing endpoints, self-connection, undefined section, missing orientation, invalid types, missing required ODB fields, evidence tampering, semantic tampering, physical criteria violation).
  - Persisted certified cryptographic manifest in `machine_validation/connector_l4_manifest.json` (Tier `REAL_ABAQUS`).
- [x] **Track GA-M4: Flexible Multibody Dynamics (FMBD)** [CLOSED & QUALIFIED AT L4]:
  - Promoted Flexible Multibody Dynamics (FMBD) to **L4 (Agent Full-Chain Qualified, stated rigid-flexible coupling scope)**.
  - Implemented `IntentFMBDSpec`, `RigidBodySpec`, `FlexibleInterfaceSpec`, and `FMBDKinematicsVerification` in `contracts/fmbd.py` and wired into `EngineeringIntent.fmbd`.
  - Canonical compiler integration in `compile_intent_to_actions()`: automated Reference Point synthesis, native `rigid_body` constraints, native `coupling_constraint` (KINEMATIC/DISTRIBUTING), connector coupling, gravity loading, and automatic `S, U, UR, V, VR, CU, CTF, RF, RM` field output and `ALLIE, ALLKE, ALLWK, ALLSE, ETOTAL` history output injection.
  - Strict preflight lifecycle gate in `preflight_action()` and `preflight_plan()`: checks coupling control point and surface existence and distinctness, rigid body distinct regions, and connector sections with 0 blockers.
  - ODB result extraction and acceptance: Gate 14 `fmbd_dynamics` integrated into `evaluate_result_acceptance()` and `AnalysisRunner.run()`. Physics profile for `fmbd` enforcing required fields (`S, U, CU, CTF`), required metrics (`joint_drift, max_mises_stress, strain_energy_ratio, energy_dissipation_ratio`), and required gates.

---

### Phase P1 — Commercial Engineering Agent Productization (P1.0 ~ P1.5)

With the foundational 20 physical engineering domains (20 L4 / 0 L3) completely closed on live Abaqus 2025, Phase P1 shifts focus to building the true autonomous engineering product: transitioning from low-level execution scripts to a reliable, human-grade AI engineering partner.

#### P1.0: Agent Product Main Entry (`solve_requirement`) [CLOSED & QUALIFIED]
- **API**: `AbaqusAIAgent.solve_requirement(requirement, geometry, material, ...)` returning strongly-typed `EngineeringTaskResult`.
- **Lifecycle Gating**: Single-exit acceptance verification (`COMPLETED` iff `AnalysisRunState.ACCEPTED` and `acceptance_passed == True`).
- **20 L4 Automated Matrix**: Full compatibility routing across all 20 L4 domains with automated Bolt Pretension step inference.
- **Evidence**: `machine_validation/p1_product_solve_manifest.json` (Real Abaqus 2025).

#### P1.1: Multimodal Engineering Perception & Drawing Ingestion [CLOSED & QUALIFIED]
- **Document Ingestion**: Vector-first PDF parsing + multi-format raster image ingestion (PNG, JPEG, TIFF) with reversible coordinate mapping.
- **Clean Extraction Funnel**: `DimensionExtractor` and `BoundaryLoadExtractor` yielding normalized `VisualCallout`.
- **Engineering Grounding Bridge**: Canonical mapping to GA-2A CAD Grounding and GA-2B mandatory Human-in-the-Loop (HITL) review.
- **Evidence**: `machine_validation/p1_drawing_golden_manifest.json` (Perception F1 = 1.0000, Reaction Balance Error = 0.0000%).

#### P1.2: Engineering Intent Reasoning & Parameter Inference [CLOSED & QUALIFIED]
- **Material Alias Normalization**: Autonomous resolution of standard trade names (Q235, Q345, 45#, 6061) to complete constitutive models.
- **Mesh Heuristic Inference**: Aspect-ratio and geometry-aware mesh sizing with explicit evidence traceability.
- **Physical Plausibility Screening**: Fail-closed detection of unconstrained mechanisms, extreme loads, and parameter conflicts before solver dispatch.
- **Evidence**: `machine_validation/p1_intent_reasoning_manifest.json` (G1~G5 Golden Matrix Qualified).

#### P1.3: Result Intelligence & Engineering Deliverable Delivery (R1~R6) [CLOSED & QUALIFIED]
- **R1 General ODB Extraction**: Reliable tensor and vector field reading across continuum and structural elements (S, U, RF, CF).
- **R2 History & Parametric Curves**: Deterministic extraction of complete time-history sequences (ALLSE, ALLIE, ALLKE, ETOTAL, U2, RF2) into `XYCurveData`.
- **R3 Derived Physical Metrics**:
  - Global static equilibrium balance (`ReactionForceBalance`: Applied Load vs Reaction Force Resultant, error $\le 0.01\%$).
  - Numerical energy stability (`EnergyStability`: ETOTAL drift ratio and kinetic/internal energy checks).
  - Structural factor of safety (`FactorOfSafetyMetric`: Nominal FoS and Margin of Safety relative to material yield, strictly preserved as derived engineering facts without hijacking the Acceptance Engine).
- **R4 Spatial Hotspot Identification**: Top-$K$ localized stress/displacement peak concentration extraction with 3D spatial coordinates $(x,y,z)$, element labels, and node labels.
- **R5 High-Fidelity Vector SVG Visualization**: Pure Python vector SVG rendering engine for XY response curves and hotspot distribution cards with cryptographic SHA-256 provenance (zero mandatory matplotlib/reportlab dependencies).
- **R6 Unified Engineering Deliverable Generation**: Automated compilation of publication-grade Markdown and standalone HTML engineering reports embedded with Result Intelligence tables, executive summaries, and figure assets.
- **Evidence**: `machine_validation/p1_3_result_delivery_manifest.json` (Real Abaqus 2025, Max Mises = 505.03 MPa, Deflection = 2.1658 mm, Reaction Balance Error = 0.0000%, 5 Hotspots, 4 SVG Curves, 10/10 Probes PASS).
  - Live Abaqus 2025 Standard execution in `tools/fmbd_l4_golden_e2e.py`: coupled rigid crank and flexible link under gravity; 336 frames; joint drift $3.13\times 10^{-10}\text{ mm} \le 10^{-3}\text{ mm}$, flexible link max Mises $0.0435\text{ MPa}$ (passed $\ge 0.01\text{ MPa}$ non-trivial flexible-response probe), peak strain energy activation ratio $\max(\text{ALLSE})/\max(\text{ALLIE}) = 0.9993 \ge 0.01$, total energy balance drift ratio $|\max(\text{ETOTAL})-\min(\text{ETOTAL})|/E_{\text{ref}} = 0.0056 \le 0.05$.
  - Formal Metric Definitions & Clarifications:
    * `strain_energy_ratio`: Defined as $\max(\text{ALLSE}) / \max(\text{ALLIE})$, functioning as a peak flexible strain energy activation probe confirming genuine dynamic structural deformation (rather than instantaneous point-to-point energy conservation).
    * `energy_dissipation_ratio`: Defined as $|\max(\text{ETOTAL}) - \min(\text{ETOTAL})| / E_{\text{ref}}$, functioning as a numerical energy-balance drift ratio evaluating solver integration stability and global conservation, rather than pure physical dissipation (friction/damping).
    * `max_mises >= 0.01 MPa`: Configured as an activity probe (`non-trivial flexible-response probe`) to prevent false-PASS on trivial rigid-body modes without flexible deformation, rather than an arbitrary universal engineering stress limit.
  - 9 negative boundary probes verified fail-closed (missing coupling control point, missing surface, identical endpoints, undefined connector section, missing local orientation, missing mandatory gate, evidence tampering, rigid body self-tie, strict physical drift violation).
  - Persisted certified cryptographic manifest in `machine_validation/fmbd_l4_manifest.json` (Tier `REAL_ABAQUS`). Capability split: **20 L4 / 0 L3 (100% Agent Full-Chain Qualified across all 20 physical engineering domains)**.

---

## 20. Engineering Material Intelligence Architecture (CAMPUS, Real-World Polymers & Constitutive Mapping)

### 20.1 Core Boundary: MaterialRecord (Real World) vs. MaterialDefinition (Solver)

To accommodate real-world engineering polymers (such as commercial grades of PA66-GF30, POM, PBT) without architectural drift, the project establishes a strict separation between physical material identity and numerical constitutive modeling:

```
                            External Material Intelligence
                                           │
             ┌─────────────────────────────┼─────────────────────────────┐
             ▼                             ▼                             ▼
       CAMPUS Database           Manufacturer Datasheet            User Custom
       (ISO 10350/11403)         (Technical Bulletins)             (Experimental)
             │                             │                             │
             └─────────────────────────────┼─────────────────────────────┘
                                           ▼
                                    MaterialRecord
                       ┌───────────────────────────────────────┐
                       │ - MaterialIdentity (Family, Grade...) │
                       │ - MaterialSource (Provenance, URL...) │
                       │ - MaterialCondition (Temp, Humidity)  │
                       │ - MaterialProperty (Scalar values)    │
                       │ - MaterialCurve (Multipoint curves)   │
                       └───────────────────────────────────────┘
                                           │
                                           ▼
                                    MaterialResolver
                                           │
                      ┌────────────────────┴────────────────────┐
                      ▼                                         ▼
            Abaqus-Supported Model                      Unsupported / Assisted
            - Linear Elastic (T)                        - Missing Creep Data
            - J2 Hardening (Calibrated)                 - Extreme High Temperature
            - Viscoelastic (Prony)                      - Uncharacterized Moisture
                      │                                         │
                      ▼                                         ▼
              MaterialDefinition                        Fail-Closed Preflight
                      │                                 (Technical Clarification)
                      ▼
             Native Abaqus Action
                      │
                      ▼
             AnalysisRun / Evidence
```

1. **`MaterialRecord` represents the real-world material entity**: It captures manufacturer, commercial trade name, filler/fiber content, testing standards, environmental conditions (dry as molded vs. moisture conditioned), and experimental curves.
2. **`MaterialDefinition` represents the Abaqus solver input**: It defines concrete mathematical constitutive cards (`*ELASTIC`, `*PLASTIC`, `*DENSITY`, `*EXPANSION`) consumable by Abaqus CAE/Standard/Explicit.
3. **No Duplicate Architectures**: `MaterialRecord` does not introduce a second unit system or persistence framework. It leverages existing `UnitSystem` for unit conversions, existing `Evidence` for traceability, and registers directly into canonical `AnalysisRun.provenance`.

### 20.2 Generic Vendor-Agnostic Data Contracts

The architecture avoids vendor lock-in by using generic data classes:

```python
@dataclass(frozen=True)
class MaterialIdentity:
    polymer_family: str           # e.g. "PA66"
    manufacturer: str             # e.g. "BASF"
    grade: str                    # e.g. "Ultramid A3WG6"
    trade_name: Optional[str]     # e.g. "Ultramid"
    reinforcement_type: Optional[str] # e.g. "glass_fiber"
    reinforcement_content: Optional[float] # e.g. 30.0 (wt%)
    filler_type: Optional[str]    # e.g. "mineral"
    variant: Optional[str]        # e.g. "heat_stabilized"

@dataclass(frozen=True)
class MaterialSource:
    provider: str                 # e.g. "CAMPUS", "BASF_DATASHEET"
    source_type: str              # e.g. "iso_database", "technical_datasheet"
    locator: str                  # URL, DOI, or document identifier
    retrieved_at: str             # ISO-8601 timestamp
    source_version: Optional[str]
    evidence_level: str           # "certified_lab", "manufacturer_published", "user_estimate"
    license_note: Optional[str]

@dataclass(frozen=True)
class MaterialCondition:
    temperature: float            # in declared unit, e.g. 23.0
    temperature_unit: str         # "C" or "K"
    humidity_state: str           # "dry", "conditioned", "saturated", "ambient"
    relative_humidity: Optional[float] # e.g. 50.0 (%)
    test_standard: Optional[str]  # e.g. "ISO 527-1/-2", "ISO 178"
    strain_rate: Optional[float]  # e.g. 0.001 (1/s)

@dataclass(frozen=True)
class MaterialProperty:
    name: str                     # e.g. "youngs_modulus", "yield_stress"
    value: float
    unit: str                     # e.g. "MPa"
    quantity: str                 # "stress", "density", "thermal_conductivity"
    condition: Optional[MaterialCondition] = None

@dataclass(frozen=True)
class MaterialCurve:
    curve_type: str               # "stress_strain", "modulus_temperature", "creep_isochronous"
    x_name: str                   # e.g. "nominal_strain"
    x_unit: str                   # e.g. "mm/mm"
    y_name: str                   # e.g. "nominal_stress"
    y_unit: str                   # e.g. "MPa"
    points: Tuple[Tuple[float, float], ...]
    condition: MaterialCondition
```

### 20.3 The MaterialResolver Contract (Constitutive Mapping & Gatekeeping)

Engineering polymers exhibit strong temperature dependence, viscoelasticity, strain-rate sensitivity, and moisture plasticization. The `MaterialResolver` governs the transformation from experimental data to numerical constitutive cards:

1. **Anti-Hallucination Gate**: Eliminates LLM guessing of material properties. Parameters must trace back to authenticated `MaterialRecord` entries.
2. **Prohibition of Direct Polymer-to-$J_2$ Casting**: Raw polymer tensile stress-strain curves cannot be blindly dumped into Abaqus `*PLASTIC` (which assumes volume-preserving $J_2$ metal plasticity). The resolver determines whether:
   - Behavior is approximately linear within working stress $\rightarrow$ Materialize `ElasticProperties` with condition-specific modulus $E(T, \text{humidity})$.
   - Inelastic deformation is required $\rightarrow$ Check if material curve includes true stress-true strain conversion, yield criteria calibration, or rate dependency.
   - Long-term loading is specified $\rightarrow$ Require creep isochronous curve or Prony relaxation parameters.
3. **Fail-Closed Condition Preflight**: If a simulation step specifies an operating temperature of $120^\circ\text{C}$, but the material record only possesses room-temperature ($23^\circ\text{C}$) data, `MaterialResolver` rejects execution with status `BLOCKED` / `NEEDS_CLARIFICATION`, rather than executing with unvalidated room-temperature stiffness.

### 20.4 Open-Source Distribution & IP Boundary (Apache-2.0 Redline)

- **Strict Repository Cleanliness**: The GitHub repository is distributed under Apache-2.0. Proprietary material databases (such as raw CAMPUS database dumps, manufacturer proprietary bulk datasets, or commercial material libraries) **shall never be committed into the Git repository**.
- **Runtime Adapter Architecture**: All external material access is handled via runtime adapters (`CampusAdapter`, `DatasheetAdapter`). These adapters query remote services or read locally provided user files on demand, strictly recording provenance and source locator metadata in the generated `AnalysisRun` evidence envelope.

---

## 21. Phase L Autonomous Agent Engineering Workflow Architecture (L1–L4)

While Phase J validates the underlying finite-element solver fidelity across 22 Dassault Systèmes benchmarks, **Phase L validates the full autonomous engineering loop of the AI Agent itself**. It proves that the agent can accept unstructured human requests, make mathematically defensible decisions, apply verified real-world materials, heal from numerical divergence, and anchor visual features into native Abaqus topology without human intervention.

```text
                                Phase L Autonomous Agent System
                                                │
       ┌────────────────────────┬───────────────┴───────────────┬────────────────────────┐
       ▼                        ▼                               ▼                        ▼
[ L1: E2E Workflow ]    [ L2: Material Intel ]         [ L3: Solver Healing ]   [ L4: Viewport Grounding ]
Prompt -> JEV Intent     Datasheet / CAMPUS              Nonlinear Divergence    2D Camera Viewport Point
       ↓                        ↓                               ↓                        ↓
Typed Action Plan        MaterialRecord Schema           .msg Cutback Extraction 3D Spatial Raycast
       ↓                        ↓                               ↓                        ↓
Abaqus 2025 Solver       MaterialResolver Engine         Solver Doctor Diagnosis findAt(...) Topology
       ↓                        ↓                               ↓                        ↓
ODB Tensor Extraction    Abaqus Material Cards           Remediation Plan        Native Set/Surface
       ↓                        ↓                               ↓                        ↓
Engineering Acceptance   Live ODB Verification           Automated Rerun         BC / Load Application
       ↓                        ↓                               ↓                        ↓
Automated Report         Traceable Provenance            Final Acceptance        Equilibrium Solver Run
```

### 21.1 L1: End-to-End Autonomous Engineering Workflow
- **Input**: Natural language prompt (e.g. *"Perform a structural check on a 100mm cantilever beam under 1000N tip load; ensure deflection <= 2.5mm and Mises stress <= 600MPa"*).
- **Compilation**: TypeSafe JEV System One analyzes prompt completeness, units (`MM_N_MPA`), and physics domain (`linear_static`). Fails closed to `NEEDS_CLARIFICATION` if critical dimensions or constraints are omitted.
- **Execution & Acceptance**: Generates executable action plan, launches Abaqus 2025, extracts tip deflection and root Mises stress directly from the physical ODB, performs deterministic acceptance checking against allowable limits, and auto-renders Markdown and standalone HTML reports.

### 21.2 L2: Real-World Material Intelligence Grounding
- **Input**: Structured external engineering plastic datasheet (e.g. commercial PA66-GF30 from BASF Ultramid A3WG6, ISO 10350 / ISO 11403).
- **Contract & Preflight**: Constructs canonical `MaterialRecord` with explicit test conditions ($23^\circ\text{C}$, dry-as-molded, ISO 527). `MaterialResolver` verifies temperature compatibility with the operating environment and prevents uncalibrated $J_2$ plastic assignments.
- **Solver Verification**: Translates into native Abaqus `MaterialDefinition`, solves tensile bar under authentic Abaqus execution, and verifies that the ODB axial strain and reaction force match the datasheet modulus within 1% tolerance.

### 21.3 L3: Closed-Loop Solver Diagnostics & Remediation (Cross-Physics Solver Doctor)
- **Injection**: Evaluates unstable structural or contact models exhibiting severe force residuals or unconstrained rigid modes causing solver abort.
- **Diagnostic Capture**: Directly parses live `.msg` and `.sta` outputs, extracting exact numerical singularities, negative eigenvalues, and increment cutbacks.
- **Remediation & Convergence**: Maps issues to discrete remediation rules (e.g. activate automatic stabilization with damping factor, decrease initial time increment, add kinematic constraints), applies corrections in an updated `AnalysisRun`, re-solves, verifies zero divergence, and achieves engineering acceptance.

### 21.4 L4: Vision & Viewport Topology Grounding Live Closure
- **Perception**: Accepts 2D graphical coordinates representing annotated regions on a component (e.g. Fixed root face, tip load point).
- **Spatial Mapping**: Casts 3D projection rays through the geometry candidate database, ranking candidates by screen projection overlap, facing angle, and depth.
- **Native Materialization**: Produces verified `findAt(...)` strings, creates native Abaqus Sets and Surfaces, applies mechanical boundary conditions, and runs live Abaqus to verify complete reaction force balance.

---

## 22. Change-Control Checklist

Before modifying the engineering core, answer all of these:

- [x] Does the change extend an existing capability rather than duplicate it?
- [x] Which AnalysisRun field or lifecycle stage owns the new information?
- [x] Is the result represented as explicit evidence?
- [x] Is the result deterministic where it should be?
- [x] Does missing evidence fail closed?
- [x] Is the difference between solver success and engineering acceptance preserved?
- [x] Is provenance sufficient to reproduce or audit the claim?
- [x] Does the change require L0 tests?
- [x] Does the change require real Abaqus validation?
- [x] Does the failure path have a test?
- [x] Does the report expose the new evidence where appropriate?
- [x] Does the change introduce a duplicate architecture? (No duplicate architecture verified)
- [x] Does it expand scope without closing an existing engineering gap? (No, tightly closes engineering gap)

If the last two questions are problematic, stop and redesign before coding.

---

## 23. Definition of Done for the Current Phase

The current phase is complete when:

1. A real Abaqus run can be represented by one canonical AnalysisRun.
2. Intent, actions, runtime, model, artifacts, metrics, verification, acceptance, diagnostics and provenance are traceable.
3. Result requirements are declarative and drive output/extraction.
4. Acceptance is evidence-gated and deterministic.
5. Baseline/candidate runs can be compared deterministically.
6. Common solver failures produce bounded, evidence-backed diagnoses.
7. Real ODB results can generate a traceable engineering report.
8. Mesh quality and geometry-to-mesh strategy are verified on the real machine.
9. Image/viewport grounding can be traced to actual Abaqus regions in live validation.
10. Failure paths are tested, not only successful paths.
11. Region resolution is consistently usable across the foundational BC/Load/Section/Mesh/Contact workflows.
12. BC/Load preflight catches deterministic structural inconsistencies before execution.
13. Unit semantics are preserved across representative foundational Actions.
14. Material and AnalysisStep semantics are coherent without duplicate architectures.
15. No duplicate Capsule/Contract/Lens/Acceptance/Executor/Geometry/Unit architecture has been introduced.
16. The project can clearly distinguish computational verification from physical validation.

At that point, the project should shift from feature expansion to systematic real-machine regression, usability, documentation, and productization.

---

## 24. External Reference Basis

The architecture was cross-checked against:

- Tomsabay/abaqus_agent — capsule, KPI/ODB lens, contracts, diagnostics, simulation diff, case memory
- Cai-aa/CAE-Agent-Hub — skill routing, solver/runtime/viewer separation
- Whfkl/Abaqus-Control-MCP — live Abaqus bridge, execution lifecycle and structured runtime errors
- Cai-aa/abaqus-mcp — Abaqus-side command/result lifecycle and compatibility constraints
- jasonanewcoder/abaqus_skills — progressive disclosure, executable helpers, end-to-end playbooks
- recent LLM/Abaqus agent research on intent constraints, structured script generation, verification and review
- ASME V&V 10 computational solid mechanics verification/validation principles

These references are design inputs, not instructions to copy their architecture or code.

---

## 25. One-Line Architectural Rule

> **Do not add another subsystem when an existing AnalysisRun, ResultRequirement, Evidence, Verification, Acceptance, Provenance, Reporting, Geometry/Region, or Unit component can own the requirement.**

This rule should be used during future code reviews to prevent architectural drift.

---

## 26. Phase P1: Commercial Productization & Autonomous Engineering Agent (P1.0 ~ P1.5)

With all 20 physical engineering domains fully qualified at L4 on authentic Abaqus 2025, the strategic roadmap shifts permanently to **Commercial Productization and Usability**.

For full requirements backlog, input/output schemas, anti-hallucination constraints, and acceptance criteria, refer to the dedicated specification:
👉 [Phase P1 Commercial Productization Requirements Backlog (p1-product-requirements.md)](p1-product-requirements.md)

### Summary of P1 Tracks

- **P1.0 Agent Product Entry Point (`solve_requirement`) [CLOSED & QUALIFIED ✅]**:
  - Unified declarative entry point accepting natural language or intent dict.
  - Fail-closed clarification gate (`NEEDS_CLARIFICATION`) when required engineering parameters are omitted.
  - Decoupled capability resolver across all 20 L4 physics domains.
  - Unified `EngineeringTaskResult` container (intent, execution, acceptance, metrics, summary, report).
- **P1.1 Real Engineering Input Perception (Drawings & Photo OCR) [NEXT UP 🎯]**:
  - Ingestion of real PNG, JPEG, and PDF mechanical engineering blueprints.
  - OCR extraction of dimensions, tolerances, surface finishes, and load arrows into `VisualCallout`.
  - Mandatory Human-in-the-Loop (HITL) gate before synthesizing `EngineeringIntent`.
- **P1.2 Engineering Reasoning & Parameter Completion [PLANNED]**:
  - Intelligent material mapping backed by verified CAMPUS/TDS sources.
  - Bounded mesh recommendations with transparent engineering rationale (strictly zero black-box default guesses).
- **P1.3 Deliverable-Grade Multidimensional Result Visualization [PLANNED]**:
  - Automated headless ODB field contour rendering (Mises, Displacement, Contact Pressure).
  - Dynamic energy-balance history curves and interactive standalone HTML reports.
- **P1.4 Solver Doctor Diagnostics & Autonomous Remediation [PLANNED]**:
  - Deep parsing of `.msg`/`.sta` divergence and cutbacks.
  - Bounded remediation playbooks (stabilization damping, step sizing, boundary adjustments) with diff auditability.
- **P1.5 Commercial Engineering Workbench (Web / Desktop UI) [PLANNED]**:
  - Interactive 3D WebGL viewport picking and visual HITL confirmation cards.
  - Enterprise job queue, token license management, and case memory.

---

## 27. Phase P0: 验收安全内核与证据闭环实施路线 (P0 Implementation Roadmap)

*基线冻结时间：2026-10-09 | 状态：FROZEN & APPROVED AS P0 BASELINE*

针对全系统“求解真实性、物理可信度、报告忠实呈现”三层闭环的真实性治理，系统确立 P0 安全内核。严禁另起炉灶或重复建设子系统，坚决复用既有架构（`AnalysisRun`, `acceptance.py`, `EvidenceManifestV2`, `DeterministicReportPipeline`）。

### 27.1 核心工程原则与三大不可违反约束

1. **原则一：测试通过不等于工程通过**（算法单测环境与正式工程交付物理隔离）。
2. **原则二：哈希正确不等于来源真实**（SHA-256 仅防篡改脱节，不作为真实 Abaqus 物理机求解发生证明）。
3. **原则三：真实工件必须追溯到真实执行**（受控进程记录、输入哈希、原生二进制 ODB、步帧字段提取相互印证）。
4. **原则四：正式报告不能自行补造工程证据**（缺真实云图则阻断签发正式报告，严禁占位图冒充 CAE 计算结果）。

**三大实施期硬性技术约束**：
- **约束 1（摘要校验确定性）**：`audit_signature` 作为“规范化完整性自校验摘要 (Normalized Integrity Digest)”，必须具备无二义性的规范化 JSON 序列化规则、稳定排序、明确排除自身字段的递归哈希计算。空摘要、摘要不符与结构残缺必须明确区分。明确声明其不具备身份认证能力，不作为真实求解凭据。
- **约束 2（状态合成唯一内核计算）**：可信证据确认力学超标且伴随门禁缺失时，状态绝对优先保留为 `FAIL`，同时完整记录所有 `blocked` 项；数据源不可信时，严禁推导物理 `FAIL`。`deliverable` 仅由验收内核独立计算，任何调用方严禁擅自传参置 `True`。
- **约束 3（全仓零绕过可验证定义）**：全面封堵 `require_evidence=False`，同时报告渲染、交付卡签发、工件归档等所有出口全部前置 `deliverable is True` 校验。正式报告与诊断副本严格分离。

### 27.2 四维正交判定模型与状态合成决策表

验收输出解耦为独立正交字段：
- `acceptance_status`: `PASS` | `FAIL` | `BLOCKED` | `RESULT_INVALID`
- `result_validity`: `VALID` | `INCOMPLETE` | `EVIDENCE_STALE` | `EVIDENCE_TAMPERED` | `EVIDENCE_CORRUPT`
- `deliverable`: 仅当 `acceptance_status == "PASS"` 且 `result_validity == "VALID"` 时为 `True`
- `findings`: `AcceptanceFindings(failures, blocked, evidence_errors, warnings, missing_gates)` 永久保留全部独立事实明细

| 场景 | result_validity | criteria (力学判据) | gates (门禁执行) | acceptance_status | deliverable | 工程语义与裁决逻辑 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **S1** | `VALID` | 存在超标判据 | 必需门禁全部满足 | **`FAIL`** | **False** | 真实求解，数据有效，物理力学破坏 |
| **S2** | `VALID` | 存在超标判据 | 存在缺失/受阻门禁 | **`FAIL`** | **False** | **物理失败绝对优先**：保留 `FAIL` 事实，同时将缺失门禁记入 `blocked`，禁止被掩盖为 BLOCKED |
| **S3** | `VALID` | 全部数值合格 | 存在必需门禁受阻/缺失/跳过 | **`BLOCKED`** | **False** | 数据有效，但前置条件不全或必需门禁缺失（含必需项 `SKIPPED`），无法得出合格结论 |
| **S4** | `VALID` | 全部数值合格 | 必需门禁全部有效 PASS | **`PASS`** | **True** | **唯一合法正式交付状态**：真实物理全链路闭环通过 |
| **S5** | `INCOMPLETE` | 未评估 / 不全 | 缺少必需证据清单 | **`BLOCKED`** | **False** | 缺少必要证据输入 |
| **S6** | `EVIDENCE_STALE` | 无法作为依据 | Run ID 不匹配 / 跨任务混用 | **`RESULT_INVALID`** | **False** | 工件脱节或使用旧任务数据，拒绝推导任何力学结论 |
| **S7** | `EVIDENCE_TAMPERED`| 无法作为依据 | 单比特哈希不匹配 / 摘要不符 | **`RESULT_INVALID`** | **False** | 工件被篡改或损坏 |
| **S8** | `EVIDENCE_CORRUPT` | 无法作为依据 | 假 ODB (JSON) / 裸字典冒充 | **`RESULT_INVALID`** | **False** | 严重违背证据契约，直接定性为数据无效与破坏 |

### 27.3 四级渐进证据验证契约

- **Layer 1（初筛拦截）**：对 `role="odb"` 工件执行文本探测，若为 JSON 或明文脚本直接拦截为 `EVIDENCE_CORRUPT`（初筛通过 $\ne$ 合法 ODB）。
- **Layer 2（自校验摘要）**：生产模式下 `audit_signature` 必填且严格自校验；检测工件脱节与局部篡改。
- **Layer 3（运行因果绑定）**：验证 `AnalysisRun.run_id == EvidenceManifestV2.run_id == 提取上下文.run_id`，校验实际求解 INP 输入哈希，核验受控进程退出状态凭据。
- **Layer 4（物理场语义提取）**：通过受支持的解析工具实际打开 ODB，验证 Step / Frame / Field / Component 存在性，物理数值由提取器直传内核。

### 27.4 八项反例测试矩阵 (TDD 驱动基准)

| 用例 ID | 注入场景与行为 | 预期 status | 预期 validity | 预期 deliverable | 核心断言与错误标识 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`NEG-P0-01`** | **混合状态：应力超标 + 必需门禁缺失** | **`FAIL`** | **`VALID`** | **False** | `"criteria_exceeded" in res.findings.failures`<br>`"missing_mandatory_gate" in res.findings.blocked` |
| **`NEG-P0-02`** | **假工件：JSON 文本伪造 `.odb`** | **`RESULT_INVALID`** | **`EVIDENCE_CORRUPT`** | **False** | `"corrupt_artifact:odb_is_plaintext_json" in res.findings.evidence_errors` |
| **`NEG-P0-03`** | **空白摘要：`audit_signature=""`** | **`RESULT_INVALID`** | **`INCOMPLETE`** | **False** | `"evidence_unsigned:manifest_audit_signature_missing" in res.findings.evidence_errors` |
| **`NEG-P0-04`** | **裸字典冒充正式凭证** | **`RESULT_INVALID`** | **`EVIDENCE_CORRUPT`** | **False** | `"unsupported_evidence_format:bare_dict_not_permitted" in res.findings.evidence_errors`<br>禁止赋 PASS |
| **`NEG-P0-05`** | **单比特篡改：修改 `.sta` 1 个字节** | **`RESULT_INVALID`** | **`EVIDENCE_TAMPERED`** | **False** | `"evidence_tampered:sha256_mismatch" in res.findings.evidence_errors` |
| **`NEG-P0-06`** | **执行虚假：仅 `abaqus help` 无作业记录** | **`RESULT_INVALID`** | **`INCOMPLETE`** | **False** | `"solver_execution:job_not_submitted" in res.findings.evidence_errors` |
| **`NEG-P0-07`** | **跨任务混用：合法 ODB 但属跨运行工件** | **`RESULT_INVALID`** | **`EVIDENCE_STALE`** | **False** | `"evidence_stale:run_id_mismatch" in res.findings.evidence_errors` |
| **`NEG-P0-08`** | **静默跳过：必需门禁为 `SKIPPED`** | **`BLOCKED`** | **`VALID`** | **False** | `"mandatory_gate_skipped" in res.findings.blocked`<br>禁止将整体验收定为 PASS |

### 27.5 分阶段实施路线与退出门禁 (Exit Criteria)

- [x] **阶段 P0-A：状态语义、验收内核与反例驱动** `[CLOSED & QUALIFIED ✅]` (Commit `921ed09`)
  - 任务：编写 `NEG-P0-01` ~ `NEG-P0-08`（先红灯）；重构 `acceptance.py` 实现四维正交模型与 `AcceptanceFindings`；补充标准 PASS / 纯力学 FAIL / 纯证据无效 3 类基准单测。
  - 退出门禁：NEG-01/08 转绿，无既有单测回归失败，物理超标确定性输出 FAIL 且 deliverable=False。
- [x] **阶段 P0-B：工件初筛探针与自校验摘要契约** `[CLOSED & QUALIFIED ✅]`
  - 任务：升级 `contracts/evidence.py` 验签与摘要算法，将 `metadata` 纳入规范化 SHA-256 摘要；加入 Layer 1 ODB 空文件与明文/脚本初筛探针；删除裸字典宽松放行分支。
  - 退出门禁：NEG-02/03/04/05 全部转绿，伪造字典与 JSON/脚本假 ODB 被确定性拦截为 RESULT_INVALID / EVIDENCE_CORRUPT。
- [x] **阶段 P0-C：运行因果绑定与受控生产入口加固** `[CLOSED & QUALIFIED ✅]`
  - 任务：封装并加固 `evaluate_production_acceptance()`；强制要求有效 `analysis_run`（禁止为 None）；严禁在缺失作业状态时虚构默认 `completed`；强制校验 `AnalysisRun.provenance.input_hash` 与 Manifest 中 `role="inp"` 工件的哈希强一致性；调用方传入的 `expected_input_hash` 仅作为额外约束，严禁覆盖运行记录哈希，冲突时判定为 `EVIDENCE_TAMPERED`；拦截未提交作业、探测作业与 `external_input` 外部结果注入。
  - 退出门禁：覆盖缺失 AnalysisRun、缺失作业状态、缺失输入哈希、缺失 INP 工件、调用方参数覆盖攻击、跨运行旧工件 (EVIDENCE_STALE)、输入哈希篡改 (EVIDENCE_TAMPERED) 全反例，全部确定性 fail-closed。
- [x] **阶段 P0-D：交付出口封闭与报告门禁前移收口** `[CLOSED & QUALIFIED ✅]`
  - 任务：在报告管线 `DeterministicReportPipeline.build_and_render` 将交付授权检查前移至任何磁盘 I/O（动图、SVG、HTML 写入）之前，未授权交付彻底杜绝任何文件落盘泄露；`require_deliverable` 默认值收紧为 `True`；严格要求 `is_deliverable` 必须由受控验收内核显式签发 `deliverable=True`，严禁隐式回退或通过宽松默认放行；诊断与草稿副本强制标记 `[DIAGNOSTIC / NON-DELIVERABLE DRAFT]` 与 `delivery_mode="diagnostic_draft"`，彻底与正式交付物隔离。
  - 退出门禁：31 项 P0 专项负例与反例测试全绿，全套测试套件 920/920 PASS 零回归；任何未获授权交付被报告引擎在磁盘写入前拦截为 PermissionError 且零文件残留。
- [x] **阶段 P0-D 终态加固：CAE 图件真实性闭环与虚假图片工具彻底清除** `[CLOSED & QUALIFIED ✅]`
  - 任务：
    1. **删除所有虚假云图生成工具**：彻底删除 `src/abaqus_ai_agent/execution/case_01_contours.py` ~ `case_06_contours.py`，全仓清除 PIL 伪造物理量插值；
    2. **清除管线伪造占位生成**：彻底移除 `DeterministicReportPipeline` 内部无中生有注入 `transient_evolution.gif` 与兜底 SVG 占位图的逻辑；
    3. **P0-D-1 严格交付授权收口**：在 `pipeline.py` 中彻底移除针对缺少 `deliverable` 字段的兼容放行，正式交付必须严格校验 `acceptance_info.deliverable is True`，否则抛出 `PermissionError`；
    4. **P0-D-2 诊断草稿全域显式注入**：在 `renderer.py` 中检测到诊断模式时，在 HTML 正文顶部强制注入醒目的 `<div class="diagnostic-banner">` 警示横幅，确保无法被误认为是正式交付报告；
    5. **图件真实性阻断 (Fail-Closed)**：声明在 `visualization_specs` 中的 CAE 图件在磁盘上若不存在，正式交付模式下严禁生成虚假占位图，必须坚决抛出 `FileNotFoundError` 阻断正式报告签发，且保证零文件落盘；
    6. **案例工具解耦**：重构 `tools/p2_case_*_e2e.py`，移除对已删除 `contours.py` 的依赖，仅当真实归档或 headless Abaqus Viewer 导出的真实图件存在时才引用，严禁虚假伪造。
  - 退出门禁：全套测试套件 922/922 全部通过，43 项 P0 专项内核与管线反例测试全绿，全仓零合成假图工具。
- [x] **通用工程仿真执行架构攻坚与真实 CAE 交付闭环 (Universal CAE Execution & Extraction Backbone)** `[CLOSED & QUALIFIED ✅]`
  - 任务：
    1. **通用无头 ODB 真实提取器 (`odb_extractor.py`)**：基于真实 Abaqus Python 子进程调度与原生 `odbAccess` 脚本，杜绝任何外部注入/基准常量冒充；将 `run_id`、`input_hash`、`odb_path`、`odb_sha256` 深度注入至 `ResultExtraction.locator` 与 `Evidence.metadata`，实现物理结果与计算过程的绝对因果绑定；
    2. **真实云图渲染与报告管线打通 (`odb_rendering.py` & `pipeline.py`)**：实现 `render_authentic_visualizations`，由无头 Abaqus Viewer 原生渲染真实云图并验证文件存在且大于 0 字节；报告管线接收 `odb_path` 并自动调度真实渲染，缺少图件坚决 fail-closed 阻断，彻底消除任何合成占位图；
    3. **统一生产验收与 AnalysisRunner 贯穿 (`analysis_run.py`)**：在 `AnalysisRun` 增加 `extractions` 真实溯源列表；`AnalysisRunner.run` 支持 `require_production=True`，严格调用 `evaluate_production_acceptance`；当且仅当 `accepted.deliverable is True` 时方可签发 `ACCEPTED` 与 `acceptance_passed=True`，并自动回填 `.inp` 真实 SHA-256；
    4. **六层通用架构因果防绕过全贯穿测试 (`test_cae_pipeline_integration.py`)**：覆盖外部注入拒绝交付、作业未提交/失败阻断、真实 ODB 提取及 Manifest 授权全链路、伪造 ODB 渲染阻断及全失败路径零文件落盘。
  - 退出门禁：全套测试套件 946/946 全部通过，全仓零合成假图、零占位伪造，六层架构因果绑定全绿闭环。
