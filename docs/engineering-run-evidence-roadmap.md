# Engineering Run / Evidence Closure Roadmap

**Status:** Foundational Contracts Closed & Frozen at Commit `644cad7`; Real-Machine Validation (Tier 1~5 Live Gate & Phase H Productization E2E) FULLY CLOSED & VALIDATED ✅  
**Version:** 2026-10-02 (Post-Contract-Closure Baseline)  
**Scope:** Abaqus-AI-Agent engineering architecture, foundational contracts, evidence chain, remaining implementation, and real-machine validation

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

## 13. Complete Real-Machine Validation Matrix

### Already substantially covered by the Golden Ladder

- Abaqus launch/runtime
- license/runtime path
- CAE/noGUI execution
- model creation
- mesh
- input generation
- solver submission
- solver completion
- artifact collection
- ODB discovery/opening
- ODB extraction
- static
- explicit dynamics
- implicit dynamics
- thermal
- contact/tie
- MBD
- flexible MBD
- fatigue
- analytical verification
- reaction/load balance
- energy evidence
- mesh convergence
- Richardson/GCI
- sensitivity/uncertainty evidence

### Still requiring explicit real-machine closure

#### P0

- native mesh-quality verification
- geometry-to-mesh strategy execution
- real ODB → Evidence → Engineering Report
- image/viewport → region → BC/load → solver → evidence
- complete AnalysisRun/Evidence persistence through a real run
- representative BC/Load preflight behavior against real Abaqus model state
- Region resolution/materialization across BC/Load/Section/Mesh/Contact workflows

#### P1

- controlled solver-failure diagnostics
- runtime error normalization under real Abaqus failures
- AnalysisRun baseline/candidate diff on real solver runs
- representative unit semantics through real Action → Abaqus → ODB workflows
- material/step semantic contracts across representative procedures

#### P2

- Case Memory / Run Index over real runs
- repeated-run retrieval and comparison

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

---

## 20. Change-Control Checklist

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

## 20. Definition of Done for the Current Phase

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

## 21. External Reference Basis

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

## 22. One-Line Architectural Rule

> **Do not add another subsystem when an existing AnalysisRun, ResultRequirement, Evidence, Verification, Acceptance, Provenance, Reporting, Geometry/Region, or Unit component can own the requirement.**

This rule should be used during future code reviews to prevent architectural drift.
