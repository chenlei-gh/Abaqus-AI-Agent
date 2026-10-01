# Engineering Closure Audit — 2026-10-01

## Scope

Audit baseline: current P1-5 head `3fa4538cf5cd432cc0f74d170d8283bfffc538f4`, compared with the P1-2 base and the repository's current execution chain.

Reference set:
- Whfkl/Abaqus-Control-MCP
- Cai-aa/CAE-Agent-Hub
- the repository's own declared scope and native-Python escape hatch

This audit distinguishes capability presence from execution-chain integration. A contract or helper is not classified as executed merely because it exists.

## Final capability matrix

| Capability | Abaqus-AI-Agent | Reference evidence | Classification |
|---|---|---|---|
| Live Abaqus execution boundary | AbaqusExecutor / BridgeExecutor / InProcessExecutor | Abaqus-Control-MCP live socket bridge | ✅ Equivalent architectural capability |
| Arbitrary native Abaqus Python | `python_action` | `run_python` | ✅ Equivalent escape hatch |
| Model inspection | inspection + snapshot | MCP model/session inspection | ✅ |
| Job creation/submission/status | JobController + artifacts | MCP job monitor | ✅ |
| ODB inspection/extraction | ODB inspection + field/history extraction | MCP inspect_odb | ✅ |
| Viewport evidence | viewport helpers + grounding | MCP capture_viewport | ✅ |
| Materials / sections | typed builders | Abaqus skills | ✅ Core subset |
| Static / explicit / implicit dynamic | typed steps | Abaqus skills | ✅ |
| Frequency/modal step | typed step + frequency result requirement | Abaqus skills | ✅ Core |
| Thermal / coupled | typed steps/actions | Abaqus skills | ✅ Core |
| Amplitudes | 4 basic types | Abaqus amplitude skill | ✅ |
| Loads / BCs / predefined fields | typed actions | Abaqus skills | ✅ Core |
| Assembly instance operations | inspect/translate/rotate/pattern | live Python / skills | ✅ Core subset |
| Mesh generation / element intent | seed/controls/generate/element type | Abaqus mesh skill | ✅ Core |
| Contact / tie | typed actions + evidence extraction + bounded contact diagnostics | Abaqus interaction/contact skills | 🟢 Core contact evidence/diagnostic path closed; deeper interaction semantics remain scope-limited |
| Result output requests | field/history output actions + planner | Abaqus output skill | ✅ |
| INP / ODB CSV export | explicit actions | Abaqus export skill | ✅ Core subset |
| STEP/STL export | not typed | Abaqus export skill | ⏸️ Deferred |
| CAD Part/Sketch/Extrude creation | not implemented | Abaqus geometry skill | ⏸️ Deferred by scope |
| Tosca / topology optimization | not implemented | Abaqus optimization skills | ⏸️ Deferred by scope |
| Shape optimization | not implemented | Abaqus shape optimization skill | ⏸️ Deferred by scope |
| Fatigue | deterministic scalar stress-history post-processing (Rainflow + half/full cycles + range/amplitude/mean + Goodman + S-N + Miner); critical-plane/non-proportional multiaxial criteria remain out of scope | Abaqus fatigue skill / fe-safe S-N workflow | 🟢 Bounded scalar post-processing closed; advanced multiaxial criteria remain out of scope |
| Geometry grounding | calibrated viewport/image grounding | hub skills + viewport tools | ✅ Differentiating capability |
| Deterministic result acceptance | acceptance gate | reference projects mostly expose execution/results | ✅ Stronger than reference execution boundary |
| Numerical verification | successive change + Richardson/GCI + executable mesh/time-step refinement studies + explicit singularity interpretation | reference workflows provide validation patterns | 🟢 Execution and interpretation boundary closed; physical adequacy remains problem-specific |
| Engineering sanity checks | load/reaction + energy + declared static/dynamic/contact/thermal/coupled families | evidence-oriented hub workflows | 🟢 Catalog boundary closed; thresholds remain problem-specific |
| Provenance | runtime population + action-plan records + model-snapshot/artifact metadata hashes; content hashes explicitly optional | not a first-class comparable feature in references | 🟢 Honest bounded provenance; content capture remains optional |
| Sensitivity | contract + AnalysisRunner execution helper + explicit result extraction; execution/result/acceptance states are distinct | reference workflow patterns | 🟢 Bounded experiment runner; acceptance remains intentionally separate |
| Uncertainty | bounded scenario execution + reproducible uniform sampling/statistics through AnalysisRunner | reference workflows vary | 🟢 First bounded probabilistic-UQ path closed; reliability/inference remain deferred |
| Benchmarks | catalog + result-requirement output planning + AnalysisRunner execution + evaluator | reference examples/models | 🟢 Execution/evaluation path closed; external reference values remain explicit inputs |
| Controlled correction | policy + explicit confirmation + existing Action Runner + AnalysisRunner rerun + Acceptance gate | reference error-recovery patterns | 🟢 One-shot authorized workflow; autonomous repair loops intentionally excluded |
| Unit/dimensional consistency | intent planning + ResultRequirement validation + dimensional checks | Declared intent/result units are validated without automatic conversion | 🟢 Main-chain validation closed for declared units |
| MCP server packaging | not the repository's core role | both references provide MCP servers | ⏸️ Not required for current architecture |

### Interpretation

The reference comparison does **not** justify adding typed wrappers for every Abaqus API. The existing native-Python escape hatch means many reference capabilities are already reachable without a new typed Capability.

The genuine gaps are therefore concentrated in engineering credibility and chain closure, not raw Abaqus API breadth.

## Full architecture closure

### Chain under audit

```
Intent
  -> Planning
  -> Action
  -> Validation
  -> Preflight
  -> Executor
  -> Job
  -> ODB
  -> Evidence
  -> Numerical Verification
  -> Engineering Checks
  -> Acceptance
  -> Provenance
  -> Correction / Retry
```

| Node | Current state | Closure finding |
|---|---|---|
| Intent | EngineeringIntent | Present |
| Planning | EngineeringPlan / output planning | Present; declared unit/dimensional semantics validated where represented by the contract |
| Action | AbaqusAction/builders | Present |
| Validation | validate_action/validate_plan | Present |
| Preflight | preflight_action | Present |
| Executor | AbaqusExecutor | Present |
| Job | JobController + artifacts | Present |
| ODB | inspect/summarize/extract | Present |
| Evidence | EvidenceBundle + result evidence | Present |
| Numerical verification | verification.py + numerical_verification.py | Present; executable element/time-step refinement with successive-change and Richardson/GCI methods |
| Engineering checks | deterministic load/reaction + energy adapters plus declared check-family catalog | Executable evidence adapters are present for the currently implemented checks; family names without adapters remain declarations, not automatic checks |
| Acceptance | evaluate_result_acceptance + AnalysisRunner | Present and wired by PR #16 |
| Provenance | runtime metadata + effective action plan + model-snapshot/artifact metadata hashes + deterministic manifest | Bounded traceability populated by AnalysisRunner; model/input/output content hashes remain optional/not captured |
| Correction/retry | bounded policy + explicitly confirmed Action execution + AnalysisRunner rerun + Acceptance gate | Present as one-shot controlled workflow; autonomous repair loops remain out of scope |

### No silent pass-through found in the reviewed verification path

The current acceptance path fails closed when supplied numerical verification, engineering checks, contact diagnostics, or benchmark evaluation fails. It also distinguishes ODB-backed values from externally injected values and marks the latter suspicious rather than valid.

## P0 findings

### 1. Reference matrix
Completed by this document.

### 2. Architecture closure
The main result path is structurally connected, but several credibility contracts remain optional inputs rather than automatically derived evidence.

### 3. Acceptance / verification regression
No semantic regression found in PR #16:
- solver status is normalized to `completed`;
- failed numerical verification blocks acceptance;
- failed engineering checks block acceptance;
- verification can still operate without explicit acceptance criteria.

The latter is intentional: verification is itself a gate. Absence of criteria produces a warning rather than an automatic failure.

### 4. Sensitivity regression
The PR #16 acceptance changes do not break `execute_sensitivity`. Sensitivity deliberately calls the existing runner without explicit acceptance criteria and extracts declared result values afterward. This is an experiment runner, not an acceptance result.

Resolved in the current audit tranche: sensitivity now records execution status, result availability/error, and acceptance status separately. `status=completed` requires completed execution plus available declared results; acceptance remains `not_evaluated` unless supplied by the runner.

### 5. Unit / dimensional consistency
**Closed for the declared contract boundary.** Engineering intent/result requirements validate declared units and dimensions without introducing automatic conversion. Live solver validation remains release/model dependent.

### 6. Provenance
**Bounded closure confirmed.** `AnalysisRunner` now populates runtime metadata when the executor exposes it, records the effective action plan, preserves caller environment metadata, and records model-snapshot/artifact metadata hashes. The contract deliberately leaves model/input/output content hashes optional because the runner does not claim to capture those bytes. This is a traceability boundary, not a claim of byte-level reproducibility.

### 7. Engineering sanity checks
The existing checks are intentionally low-level and threshold-free. The catalog is a declaration of supported engineering-check families; it is not evidence that every named family is automatically extracted from every ODB. The currently executable evidence adapters cover explicit reaction-balance and history-energy checks, while contact checks are handled by the dedicated contact diagnostic chain:

- Static: global equilibrium, displacement sanity, stress/result sanity, energy when applicable.
- Dynamic: energy balance, kinetic/internal energy evidence, timestep evidence.
- Contact: contact state/opening/pressure evidence plus declared contact-consistency checks.
- Thermal/coupled: thermal result presence and declared balance/energy checks where applicable.

No universal engineering threshold should be invented here; limits remain problem-specific acceptance criteria.

## P1 closure status

1. Contact diagnostic chain — **closed**.
2. Benchmark execution through AnalysisRunner — **closed**.
3. Uncertainty scenario execution through AnalysisRunner — **closed for bounded deterministic and first reproducible probabilistic sampling/statistics**; reliability/inference remain deferred.
4. Time-step and element refinement verification — **closed for executable successive-change and Richardson/GCI paths**; singularity interpretation is explicit-evidence-only.
5. First narrow authorized correction workflow — **closed as one-shot confirmed Action → AnalysisRunner → Acceptance**.

Remaining engineering credibility work is now outside the P1 execution tranche: broader physical check coverage, calibration/parameter identification, and reliability/inference methods. The legacy convergence contract is retained as a deterministic evaluation-only compatibility helper; executable mesh/time-step refinement belongs to numerical_verification.py, so there is no second refinement execution path.

## Deferred

- Real B28 runtime validation.
- CAD geometry authoring.
- STEP/STL.
- Tosca/topology/shape optimization.
- Full standalone fatigue solver.
- Model calibration / parameter identification remains deferred.
- Full probabilistic UQ framework remains deferred.

## Reference observations

Abaqus-Control-MCP is primarily a live execution/diagnostic bridge: its current tool set centers on Python execution, job monitoring, ODB inspection, viewport capture, and working-directory control.

CAE-Agent-Hub is broader: it packages MCP servers, Abaqus workflow Skills, subagents, solver workflows, optimization skills, and result viewers.

The current Abaqus-AI-Agent should not copy that breadth indiscriminately. Its differentiating engineering value is the evidence/verification/acceptance chain around a native Abaqus execution boundary.


## P1 capability-audit conclusions

### Sensitivity
Sensitivity is an experiment runner, not an acceptance workflow. Its result contract now distinguishes:
- execution_status: whether the AnalysisRunner completed;
- result_status: whether the declared result extractor produced usable values;
- acceptance_status: whether the underlying run's Acceptance result was passed, failed, or not evaluated;
- legacy status: completed only when execution completed and declared results are available.

This prevents an ODB/result extraction state from being represented as engineering acceptance.

### Convergence compatibility
The legacy mesh-convergence contract evaluates already-collected mesh/result pairs only. It does not create or modify Abaqus models and does not execute jobs. The executable refinement workflow is numerical_verification.py, which owns element-size/time-step study execution and successive-change/Richardson/GCI verification. The legacy helper therefore remains a compatibility/evaluation surface rather than a competing execution framework.

### Engineering-check execution boundary
The repository now distinguishes three levels:
1. family declaration — STANDARD_ENGINEERING_CHECKS;
2. deterministic evaluator — EngineeringCheck helpers;
3. ODB evidence adapter — engineering_evidence.py where evidence-to-check conversion is implemented.

A family name alone is not treated as automatic ODB verification. Problem-specific limits and assumptions remain caller-declared.

### Provenance population boundary
AnalysisRunner populates runtime version/Python metadata when available, preserves caller environment metadata, records the effective action plan, and records model-snapshot/artifact metadata hashes. content_hash_scope="not_captured" remains explicit when model/input/ODB bytes are not captured. The resulting claim is bounded traceability, not byte-identical reproducibility.


## P2 engineering-credibility tranche

The first P2 step extends deterministic engineering evidence without introducing universal physics thresholds. The new bounded field-sanity adapter can evaluate scalar/vector field evidence (including temperature, stress, or displacement-derived magnitudes) only when the caller declares explicit minimum/maximum limits. Non-finite values fail closed. This expands executable coverage of the existing static/thermal/coupled check families while keeping problem-specific engineering assumptions outside the library.

This remains deliberately below calibration/experimental validation and probabilistic UQ: it is an evidence-to-check primitive, not a new solver, unit-conversion engine, or autonomous engineering-judgment layer.


### P2-2 deterministic experimental validation

A bounded experimental-validation contract/evaluator is now present for measured-vs-simulated scalar quantities. It records measured value, simulated value, absolute/relative error, declared tolerance, measurement uncertainty, unit, and source provenance. Validation is intentionally **not calibration**: it never adjusts model parameters and measurement uncertainty never silently relaxes the declared acceptance tolerance. Zero-valued measurements use absolute tolerance because relative error is undefined.


## P2-2 integration closure

Experimental validation is now connected to the existing result path rather than remaining a standalone post-processing helper:

- `AnalysisRunner` accepts explicit measured-observation mappings keyed to extracted result values.
- Simulated values come only from the ODB/result extraction path (or are explicitly marked external when caller-injected results are used).
- The existing experimental-validation evaluator computes absolute/relative error against caller-declared tolerances.
- Measurement uncertainty remains evidence metadata and never silently relaxes tolerance.
- A failed experimental-validation report blocks the existing Acceptance gate and is recorded as `experimental_validation` evidence.
- No parameter calibration, optimization, model identification, or second extraction/execution subsystem was introduced.

This closes the deterministic validation chain while preserving the boundary that validation is not calibration.


## P2-1 / P2-3 closure update

The declared engineering-check catalog now has deterministic executable helpers for the remaining bounded gaps:

- Dynamic time-step evidence can be evaluated from an explicit history variable against caller-declared minimum/maximum limits.
- Coupled thermal-mechanical consistency can be evaluated only when the caller supplies the paired result fields, expected ratio, and tolerance.
- Existing reaction balance, energy ratio, contact diagnostics, and generic numeric field sanity remain unchanged.
- No universal material/physics thresholds are inferred.

Probabilistic uncertainty is now available as a bounded extension of the existing uncertainty execution path:

- Uniform sampling is explicit and reproducible through a caller-provided seed.
- Parameter bounds come from the existing `UncertaintyParameter` contract.
- Sampled parameter values are not silently applied; an explicit `action_plan_factory` must map each sample to existing Abaqus actions.
- Every sample still executes through `AnalysisRunner`.
- Statistics are deterministic sample statistics (count, mean, population standard deviation, min/max, interpolated quantiles).
- No distribution fitting, reliability index, confidence interval, Bayesian inference, or optimizer was added.
- The reported quantiles are empirical sample summaries, not claims of a fitted probability distribution.

This is sufficient for a first probabilistic-UQ execution capability without introducing a second execution or verification architecture.


## Reference-gap decision update

A current reference check confirms that the reference projects emphasize live execution, model/ODB inspection, reusable workflow skills, optimization workflows, and viewers. Abaqus-Control-MCP exposes arbitrary kernel Python plus job/ODB/viewport controls, while CAE-Agent-Hub routes complete analysis intents to specialized skills including fatigue and optimization.

The audit does **not** justify copying their full typed API surface because this repository already has a native Python escape hatch. Fatigue: deterministic scalar stress-history post-processing (Rainflow + half/full cycles + range/amplitude/mean + Goodman + S-N + Miner); critical-plane/non-proportional multiaxial criteria remain out of scope

The following remain intentionally deferred because implementing them now would expand scope rather than close a demonstrated core-chain gap:

- Tosca/topology/shape optimization.
- CAD authoring.
- STEP/STL typed export.
- Reliability methods / FORM/SORM.
- Bayesian inference / distribution fitting.
- Broader mean-stress correction matrix (Walker/Gerber/etc.) and critical-plane/non-proportional multiaxial fatigue.


## Post-P1/P2 audit correction — 2026-10-01

The previous CI result exposed four fatigue test defects rather than four production defects: the ASTM-style open-history case was asserting a fabricated full cycle, the published nine-reversal example's cycle-weight total was arithmetically incorrect (4.0, not 3.5), the compressive Goodman expectation used the wrong formula, and the Goodman integration fixture placed corrected amplitudes below its declared S-N domain. The production rainflow implementation already matched the published reversal-by-reversal cycle list.

The Goodman implementation is now explicit about the fe-safe measured-signal S-N convention: the ordinary Goodman line is used for nonnegative mean stress, while the compressive extension uses half the original slope. This is distinct from other fe-safe contexts that may deliberately make no allowance for compressive mean-stress benefit; the project therefore does not generalize this convention beyond the declared S-N workflow. fe-safe documents the measured-signal equation and the half-slope compressive extension.

The remaining P1/P2 gaps are scope boundaries rather than missing core-chain functions: real B28 execution validation, model calibration/parameter identification, reliability/inference methods, broader fatigue methodologies, CAD authoring, STEP/STL typed export, and Tosca/topology/shape optimization. No additional typed API breadth is justified merely to match the reference projects because native Python remains the controlled escape hatch.
