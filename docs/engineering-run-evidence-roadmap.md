# Engineering Run / Evidence Closure Roadmap

**Status:** Baseline for implementation and audit  
**Version:** 2026-10-02  
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

The current code-level audit confirms that the project already has sufficient Abaqus API coverage for the next real-machine phase. The remaining foundational work is **contract strengthening, not broad feature expansion**.

The foundational semantic chain should be:

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

### 4.1 Region — P0

The repository already contains:

- `GeometryCandidate`
- `GroundingResult`
- `GeometrySelection`
- `RegionBinding`
- viewport/geometry grounding
- native Set/Surface materialization

**Do not create a second geometry subsystem.**

The remaining problem is that many foundational Actions still accept raw `region_expression` strings. The target is:

```
GeometrySelection / RegionBinding
        ↓
Unified Region Resolver
        ↓
native Abaqus region expression
        ↓
BC / Load / Section / Mesh / Contact / Output
```

Requirements:

- region identity must be stable and inspectable
- entity type must be explicit
- named Set/Surface and temporary geometry selections must remain distinguishable
- grounding source/evidence should be retained where applicable
- empty/nonexistent regions must fail closed
- existing `region_expression` remains a compatibility/internal representation during migration

**Do not break existing valid Action APIs merely to rename fields.**

### 4.2 BC / Load Preflight — P0

The current preflight layer already validates basic model/action prerequisites. Strengthen it to cover engineering consistency before execution.

BC checks should include where applicable:

- region exists and is non-empty
- entity/region type is compatible with the requested BC
- DOFs are valid for the selected procedure/entity
- duplicate or obviously conflicting constraints
- obvious rigid-body-motion risk
- step exists and is applicable
- amplitude reference is valid
- unit/dimension consistency

Load checks should include where applicable:

- region exists and is non-empty
- load type is compatible with the target entity
- magnitude/direction is structurally valid
- unit/dimension consistency
- step validity
- amplitude validity
- obvious BC/load conflict
- required geometric grounding evidence

The validator should remain deterministic and evidence-oriented. It must not pretend to perform full physical correctness proof.

### 4.3 Mesh Contract and Quality — P0

The code already has mesh actions, mesh inspection, mesh-quality contracts, and mesh convergence. **Do not expand mesh API coverage merely for feature count.**

Strengthen the existing contract so mesh intent can express, where applicable:

- global seed
- local refinement
- element family/formulation/order/integration
- mesh controls
- local transition intent
- quality thresholds
- convergence target

Quality must distinguish:

- native-supported checks
- element/procedure-specific checks
- analysis-only or derived checks
- unsupported/unverified checks

Real-machine evidence must establish which quality metrics are actually available for the selected Abaqus version and element type.

Target:

```
mesh action
→ actual Abaqus mesh
→ quality extraction
→ quality status
→ Evidence
→ Acceptance
```

### 4.4 Unit System — P1

The existing UnitSystem implementation is retained; do not create another unit framework.

The remaining task is to propagate quantity/unit semantics consistently through foundational Actions:

```
Intent
→ Material
→ Geometry/Region where dimensional
→ BC
→ Load
→ Step/time
→ Mesh
→ ResultRequirement
→ Metric
→ Acceptance
→ Report
```

Avoid silent loss of unit semantics through bare numeric values where engineering meaning depends on units.

Where full Quantity objects would cause excessive compatibility churn, retain numeric Action fields but validate them against an explicit model/run UnitSystem and record the unit semantics in the run/evidence layer.

### 4.5 Material Definition — P1

The current code already covers the principal material Actions needed by the existing workflows, including elastic, density, plastic and thermal properties.

Do not add a large material database or broad material API family now.

Instead, progressively unify the semantic representation into a material definition containing, where applicable:

- material identity
- provenance/source
- UnitSystem
- elastic properties
- density
- plasticity
- thermal properties
- temperature dependence
- validity/assumptions

Existing low-level Actions may remain the Abaqus materialization mechanism.

### 4.6 Analysis Step Contract — P1

The repository already supports Static, Explicit Dynamic, Implicit Dynamic, Frequency, Heat Transfer and Coupled Temperature-Displacement procedures.

Do not add Step types merely to increase coverage.

Unify the engineering semantics around:

```
AnalysisStep
├── procedure
├── previous
├── time
├── nonlinear settings
├── increment/control settings
├── stabilization
├── amplitude
├── output profile
└── solver-specific settings
```

Existing procedure-specific Actions remain the implementation adapters.

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

## 17. What Must NOT Be Added

Unless a concrete requirement proves otherwise, do not add:

- a second Capsule architecture
- a second EngineeringRun architecture
- a second Physics Contract architecture
- a second ODB Lens architecture
- a second Acceptance layer
- a second Executor
- a second Agent orchestrator
- a second Geometry/Region subsystem
- a second Unit framework
- a parallel Material/Step semantic architecture
- MCP as the core architecture
- unrestricted automatic model repair
- a giant copied skill library
- broad multi-solver expansion before the existing engineering loop is closed
- large new Abaqus feature families merely to increase feature count

Prefer extending existing modules and contracts.

---

## 18. Implementation Order

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

### Phase G — Real-machine peripheral closure

- [x] Mesh quality
- [x] Geometry-to-mesh strategy
- [x] Real ODB-to-report
- [x] Image-to-region-to-BC/load
- [x] Failure-path matrix
- [x] representative Region/BC/Load real-machine validation

### Phase H — Productization

- [x] Case Memory / Run Index
- [x] polished engineering report
- [x] run comparison UX
- [x] evidence browsing / traceability

---

## 19. Change-Control Checklist

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
