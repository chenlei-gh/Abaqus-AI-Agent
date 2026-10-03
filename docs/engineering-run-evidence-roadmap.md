# Engineering Run / Evidence Closure Roadmap

**Status:** Foundational Contracts Closed & Frozen at Commit `644cad7`; Real-Machine Validation (Tier 1~5 Live Gate & Phase H Productization E2E) FULLY CLOSED & VALIDATED ✅; Phase J (Comprehensive Engineering Physics) & Phase K (Material Intelligence & CAMPUS Integration) SPECIFIED & ACTIVE 🚀  
**Version:** 2026-10-03 (Comprehensive Physics & Material Intelligence Baseline)  
**Scope:** Abaqus-AI-Agent engineering architecture, foundational contracts, evidence chain, real-machine physics benchmarks, and material intelligence grounding

---

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
- [ ] J.3: Tier B Extended Engineering Physics Benchmarks (Nightly / Milestone Staging)
  - [ ] Viscoelasticity (Prony series stress relaxation under sustained strain).
  - [ ] Steady-state and transient creep (Norton power law strain rate under sustained stress).
  - [ ] Cohesive Zone Interface debonding (traction-separation law delamination).
  - [ ] Fracture mechanics $J$-integral (CT specimen contour integral mesh insensitivity).
  - [ ] Open-hole multi-ply composite stress concentration verification.
  - [ ] 3D bolt pretension tightening step followed by external service load.
  - [ ] Transient fluid/thermal matrix diffusion.
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
- [ ] **R1: Agent-Native Action Chain End-to-End Grounding**
  - [ ] Transform L1 from pre-packaged CAE script execution into a dynamic agent pipeline: `EngineeringIntent → ActionPlan → ActionBuilders → CAE Native Model → Solver → ODB → Acceptance → Report`.
  - [ ] Prove that the model parameters and scripts are compiled directly from intent specifications rather than test-harness stubs.
- [ ] **R2: Mesh Engineering Gate & Multi-Family Quality Verification**
  - [ ] Real-machine verification across continuum, shell, and beam element families: C3D8/C3D8R, C3D10, S4R, B31.
  - [ ] Extraction of native Abaqus element quality metrics: aspect ratio, minimum interior angles, face out-of-plane distortion, and negative Jacobian indicators.
  - [ ] Fail-closed mesh acceptance gate: unresolvable element distortion or negative Jacobian triggers `BLOCKED` status before solver invocation.
- [ ] **R3: Material Condition 2.0 Multi-Dimensional Fail-Closed Matching**
  - [ ] Extend `MaterialCondition` matching beyond scalar temperature to multi-dimensional criteria: `strain_rate`, `test_time` (creep duration), `frequency` (DMA), and `humidity_state` (dry vs. conditioned).
  - [ ] Enforce strict anti-extrapolation: out-of-range operating conditions must result in `BLOCKED` / `NEEDS_CLARIFICATION` rather than uncontrolled room-temperature fallback.
- [ ] **R4: Clean-Room External Material Source Adapters**
  - [ ] Deliver pluggable runtime adapters (`CampusAdapter`, `DatasheetAdapter`) with structured JSON/dict ingestion.
  - [ ] Enforce Apache-2.0 legal boundary: zero proprietary database bulk dumps committed to repository; runtime translation into canonical `MaterialRecord` with full provenance tracking.
- [ ] **R5: Engineering Task Acceptance Matrix (T1–T6 Real-World Scenarios)**
  - [ ] Transition from isolated benchmark problems to multi-step engineering tasks:
    - **T1: Structural Static Strength & Factor of Safety (FoS)** task under deflection and stress limits.
    - **T2: Coupled Thermo-Mechanical Thermal Stress** task with temperature gradient and expansion constraints.
    - **T3: Contact & Tribological Interaction** task evaluating contact pressure, gap closure, and frictional dissipation.
    - **T4: Nonlinear Plastic Hardening & Residual Stress** task evaluating post-yield deformation.
    - **T5: Transient Dynamic Vibration & Energy Balance** task with kinematic/internal energy checks.
    - **T6: Autonomous Diagnosis & Self-Healing** task recovering from intentional non-convergence.

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
