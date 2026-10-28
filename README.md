# Abaqus AI Agent

An engineering agent that turns a stated analysis requirement into an Abaqus model, a solver run, and a report that can be defended from evidence.

[中文](README_CN.md) | [Requirements and plan](docs/PROJECT_REQUIREMENTS_AND_PLAN.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Abaqus](https://img.shields.io/badge/Abaqus-2025-blue.svg)](https://www.3ds.com/products-services/simulia/products/abaqus/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Abaqus remains the solver. This repository does not ship a license, and a generated report is not an analyst's sign-off.

## The problem

Most of the time in an automated CAE loop is not spent in the solver. It is spent discovering that the script does not parse, the region was guessed, the units do not close, the job did not actually finish, or the report states a result the ODB does not support.

A language model can draft Abaqus Python. It cannot, by itself, tell a successful script from a finished analysis, or a finished analysis from an acceptable engineering answer. This project exists to keep those three claims separate.

## What it is

The agent sits between a requirement and Abaqus/CAE. It does not replace the preprocessor, and it does not reinterpret the solver.

```text
requirement
    -> typed intent
    -> action plan
    -> Abaqus Python
    -> CAE kernel
    -> solver
    -> ODB and logs
    -> acceptance against the stated criteria
    -> one report, or a diagnostic
```

A human reviews the model, mesh, boundary conditions, and loads before submission. The review is a static HTML file opened in the default browser, not an application UI. Approval is bound to that candidate. Changing the deck invalidates it.

## Design

Five rules determine the architecture.

**Language is not authority.** A model may interpret a requirement, propose a modeling choice, or draft native Python. It may not mutate the analysis by slipping past the typed action path. An operation the model can write is not therefore a supported capability.

**An action is the unit of modeling.** Geometry, material, mesh, step, boundary, load, and contact are compiled from typed actions. The generated script is a consequence of the plan, not the plan itself. Free-form Python remains an explicit escape hatch, and its result is execution evidence only.

**Evidence is layered.** Calling an API is not model state. Model state is not a finished job. A finished job is not an ODB. An ODB is not acceptance. Each layer has to be present before the next claim is allowed.

**Failure stays failure.** Missing input stops as clarification. An illegal plan stops before launch. An unapproved candidate stops before the solver. A failed acceptance check produces a diagnostic report. None of these is rewritten into a completed analysis.

**The solver is not trusted blindly, and neither is the agent.** Abaqus computes the response. The agent checks that the requested question was actually run, that the artifacts belong to that run, and that the declared criteria were met. It does not invent a better physics answer than the solver returned.

## Scope

The intended analysis surface is structural and thermal work that can be expressed as a closed requirement: linear and nonlinear statics, contact, connectors, implicit and explicit dynamics, flexible multibody, heat transfer, and the mesh and material choices those analyses depend on.

That list is the direction of the system, not a certificate that every procedure, element, contact formulation, or material model has been qualified. A capability is supported only when it has a typed action, a validation path, result semantics, and tests. Live Abaqus evidence qualifies a stated case; it does not promote the neighboring case.

The reference live case is the official cantilever benchmark under `machine_validation/`: C3D20R, tip shear, deflection within 1.05% of beam theory and integration-point stress within 0.23% of the analytical value. Contact, approval, and corrupted-ODB rejection have also been exercised on that host. Broader claims stay in the requirements document until they have the same kind of evidence.

## Where the time actually goes

The expensive failures are not mysterious.

| Failure | Where it is stopped | What still requires a person |
|---|---|---|
| Incomplete requirement | Before a plan exists | Supply the missing geometry, material, support, load, or criterion |
| Illegal model structure | Before script launch | Change the analysis definition |
| Python that cannot be parsed | Before CAE starts | Fix the generated source; this does not prove the Abaqus API is valid |
| Unreviewed model | Before solver submission | Read the pre-solve review and approve that candidate |
| Job that did not really finish | Before a result is read | Inspect the kernel and solver artifacts |
| Result that misses its criterion | Before formal delivery | Accept the diagnostic, or change the model and rerun |

Syntax rejection removes one class of wasted launch. It does not remove bad regions, wrong units, or a misunderstood load path. Those are modeling errors, and the acceptance path is where they become visible. There is no measured before/after study showing that total correction time has fallen.

## Using it

Python 3.10 or newer. A licensed Abaqus 2025 installation is required only when a job is actually solved.

```bash
git clone https://github.com/chenlei-gh/Abaqus-AI-Agent.git
cd Abaqus-AI-Agent
python -m pip install -e ".[test]"
python -m pytest tests -q -m unit
```

```python
from abaqus_ai_agent import AbaqusAIAgent

agent = AbaqusAIAgent(executor=None)
result = agent.solve_requirement(
    "200 x 20 x 5 mm steel cantilever, encastre at the root, 100 N shear at the free end",
    submit_job=False,
)
```

`submit_job=False` is the default. The call builds and checks the analysis candidate; it does not submit it. After the review file has been approved, the same work directory can be run. A completed status means the task finished its path. Acceptance is a separate judgment against the declared criteria.

```bash
abaqus-ai-agent ask "..." --dry-run
abaqus-ai-agent approve --workdir ./run_workdir --by "analyst name"
```

## Layout

```text
src/abaqus_ai_agent/
  contracts/     typed intent, actions, evidence, acceptance
  planning/      mesh and analysis planning
  actions/       action construction and script generation
  execution/     CAE kernel, batch jobs, approval
  validation/    structural checks before launch
  evidence/      artifact and ODB evidence
  reporting/     formal report and diagnostic report
  materials/     material records used by the model
  telemetry/     correction and timing records
```

`docs/PROJECT_REQUIREMENTS_AND_PLAN.md` is the only planning document. New requirements are added there.

## License

[Apache License 2.0](LICENSE).
