# Engineering Closure Audit — 2026-10-01

## Scope

Audit baseline: `main` at merge commit `a91c42b6e2438fc3c9a30833d272d081167aaabc` (PR #16, verification wired into acceptance).

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
| Contact / tie | typed actions + evidence extraction | Abaqus interaction/contact skills | 🟡 Evidence/diagnostic layer incomplete |
| Result output requests | field/history output actions + planner | Abaqus output skill | ✅ |
| INP / ODB CSV export | explicit actions | Abaqus export skill | ✅ Core subset |
| STEP/STL export | not typed | Abaqus export skill | ⏸️ Deferred |
| CAD Part/Sketch/Extrude creation | not implemented | Abaqus geometry skill | ⏸️ Deferred by scope |
| Tosca / topology optimization | not implemented | Abaqus optimization skills | ⏸️ Deferred by scope |
| Shape optimization | not implemented | Abaqus shape optimization skill | ⏸️ Deferred by scope |
| Full standalone fatigue solver | contract/workflow only | Abaqus fatigue skill | ⏸️ Explicitly not claimed |
| Geometry grounding | calibrated viewport/image grounding | hub skills + viewport tools | ✅ Differentiating capability |
| Deterministic result acceptance | acceptance gate | reference projects mostly expose execution/results | ✅ Stronger than reference execution boundary |
| Numerical verification | successive change + Richardson/GCI | reference workflows provide validation patterns | 🟡 Partial; time-step/element/singularity dimensions remain |
| Engineering sanity checks | load/reaction + energy | evidence-oriented hub workflows | 🟡 Standard catalog not yet closed |
| Provenance | contract + artifact manifest hash | not a first-class comparable feature in references | 🟡 Partial population |
| Sensitivity | contract + execution helper | reference workflow patterns | 🟡 Executable helper, not a full acceptance-bound experiment |
| Uncertainty | bounded scenario execution through AnalysisRunner + deterministic envelope aggregation | reference workflows vary | 🟡 Executable tolerance-bound propagation; probabilistic/full UQ deferred |
| Benchmarks | catalog + evaluator | reference examples/models | 🟡 Evaluation-only, no solver execution path |
| Controlled correction | policy/attempt evidence | reference error-recovery patterns | 🟡 Policy/evidence only; no concrete repair workflow |
| Unit/dimensional consistency | primitives only | engineering workflow requirement | 🔴 Main-chain integration missing |
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
| Planning | EngineeringPlan / output planning | Present; unit semantics not enforced |
| Action | AbaqusAction/builders | Present |
| Validation | validate_action/validate_plan | Present |
| Preflight | preflight_action | Present |
| Executor | AbaqusExecutor | Present |
| Job | JobController + artifacts | Present |
| ODB | inspect/summarize/extract | Present |
| Evidence | EvidenceBundle + result evidence | Present |
| Numerical verification | verification.py + numerical_verification.py | Present, partial dimensions |
| Engineering checks | load/reaction + energy + adapters | Present, standard catalog incomplete |
| Acceptance | evaluate_result_acceptance + AnalysisRunner | Present and wired by PR #16 |
| Provenance | AnalysisProvenance + manifest | Present but under-populated |
| Correction/retry | bounded policy and attempt record | Present as policy/evidence, not concrete workflow |

### No silent pass-through found in the reviewed P0 path

The PR #16 acceptance path now fails closed when supplied numerical verification or engineering checks fail. It also distinguishes ODB-backed values from externally injected values and marks the latter suspicious rather than valid.

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

Remaining improvement: sensitivity should expose solver/ODB validity separately from acceptance status rather than collapsing all non-failed run states into a generic `completed` label.

### 5. Unit / dimensional consistency
**Confirmed gap.** `contracts/units.py` contains primitives, but no production caller connects them to EngineeringIntent, action validation, result requirements, or acceptance.

This must be fixed without introducing automatic unit conversion. The first closure should be:
- validate declared intent magnitude + unit against the declared unit system;
- validate result criterion units against the requested result quantity;
- reject incompatible dimensions;
- preserve explicit units in evidence.

### 6. Provenance
**Confirmed partial gap.**
Currently populated reliably:
- run_id
- model_name
- job_name
- executor
- artifact manifest metadata hash

Currently optional/unpopulated in the normal runner path:
- model_hash
- input_hash
- output_hash
- Abaqus version
- Python version
- action plan
- environment

Therefore the provenance chain is not yet capable of answering every requested traceability question.

The correction should populate runtime metadata when the executor exposes it, record the generated output action plan, and explicitly distinguish content hashes from metadata hashes.

### 7. Engineering sanity checks
The existing checks are intentionally low-level and threshold-free. The missing piece is a small declared standard catalog, not dozens of hard-coded thresholds.

The catalog should identify required evidence/check families by analysis type:

- Static: global equilibrium, displacement sanity, stress/result sanity, energy when applicable.
- Dynamic: energy balance, kinetic/internal energy evidence, timestep evidence.
- Contact: contact state/opening/pressure evidence plus declared contact-consistency checks.
- Thermal/coupled: thermal result presence and declared balance/energy checks where applicable.

No universal engineering threshold should be invented here; limits remain problem-specific acceptance criteria.

## P1 after this audit

1. ContactDiagnostic engineering interpretation.
2. Benchmark execution through AnalysisRunner.
3. Uncertainty scenario execution through AnalysisRunner. **Completed in P1-3 as bounded tolerance propagation; probabilistic sampling/reliability remains deferred.**
4. Time-step and element-sensitivity numerical verification.
5. First narrow, explicitly authorized correction workflow.

## Deferred

- Real B28 runtime validation.
- CAD geometry authoring.
- STEP/STL.
- Tosca/topology/shape optimization.
- Full standalone fatigue solver.
- Calibration and experimental validation.
- Full UQ framework.

## Reference observations

Abaqus-Control-MCP is primarily a live execution/diagnostic bridge: its current tool set centers on Python execution, job monitoring, ODB inspection, viewport capture, and working-directory control.

CAE-Agent-Hub is broader: it packages MCP servers, Abaqus workflow Skills, subagents, solver workflows, optimization skills, and result viewers.

The current Abaqus-AI-Agent should not copy that breadth indiscriminately. Its differentiating engineering value is the evidence/verification/acceptance chain around a native Abaqus execution boundary.
