# Abaqus AI Agent

An engineering agent that compiles a stated analysis requirement into an Abaqus model, runs that model only after review, and releases a report only when the solver artifacts support the stated criteria.

[中文](README_CN.md) | [Requirements and plan](docs/PROJECT_REQUIREMENTS_AND_PLAN.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Abaqus](https://img.shields.io/badge/Abaqus-2025-blue.svg)](https://www.3ds.com/products-services/simulia/products/abaqus/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

This package does not install Abaqus, does not ship a license, and is not published on PyPI. A generated report is not an analyst's sign-off.

## Installation

Two runtimes stay separate. The agent installs into a normal CPython environment. Abaqus keeps its own interpreter and is invoked through the SIMULIA launcher. Do not `pip install` this package into the Python that ships with Abaqus/CAE.

The package is not on PyPI. Install it from this source tree. PyPA's install guide is to use a virtual environment and invoke pip as `python -m pip`, so the install lands in the interpreter you just checked.

Windows, from the repository root:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m abaqus_ai_agent --help
```

The quotes around `".[test]"` are required. In `cmd`, square brackets are wildcards.

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m abaqus_ai_agent --help
```

What that command does:

| Item | Value |
|---|---|
| Distribution | `abaqus-ai-agent` 0.2.2, setuptools `src` layout |
| Declared Python | `>=3.9` in `pyproject.toml` |
| Interpreter tested by CI | 3.10, 3.11, 3.12, on Ubuntu and Windows |
| Runtime dependency | `Pillow>=9` |
| Test extra | `pytest>=7` |
| Console scripts | `abaqus-ai-agent`, `abaqus-agent` |
| Install mode | editable (`-e`), so source edits are imported without reinstall |

`-e ".[test]"` is the development install used by CI. For an environment that only runs the agent, omit the extra:

```bash
python -m pip install -e .
```

Editable install tracks Python changes in `src/`. A change to `pyproject.toml` dependencies or entry points still requires the same install command again. Do not use `python setup.py install`; that path is deprecated.

Offline checks do not need a solver:

```bash
python -m pytest tests -q -m unit
abaqus-ai-agent inspect --json
```

`inspect` reports whether a launcher was found. A missing launcher is an offline host, not a failed package install.

### Abaqus, which this package does not install

A live solve needs an already installed, licensed Abaqus 2025. The installer creates the command directory and, on Windows, prepends it to `PATH`. The defaults are `C:\SIMULIA\Commands` and `/var/DassaultSystemes/SIMULIA/Commands`. The 2025 shortcut is `abq2025`; `abaqus` is the unversioned entry.

This package resolves the launcher in that order: an explicit path, `abaqus` on `PATH`, then `C:\SIMULIA\Commands\abaqus.BAT` on Windows. License server, `custom_v6.env`, and token availability belong to the Abaqus installation. This repository does not configure them.

Confirm the external product before expecting a solve:

```bat
where abaqus
abaqus information=release
```

`abaqus information=release` returning a release string means the launcher is usable. It does not mean a token is free.

## The engineering model

A script that runs is not an analysis that finished, and a finished job is not an acceptable answer. The agent keeps those as separate states.

```text
requirement
  -> typed intent
  -> ordered actions
  -> generated Abaqus Python
  -> CAE kernel
  -> solver job
  -> ODB and solver logs
  -> acceptance against declared criteria
  -> report.html, or report.diagnostic.html
```

The agent does not invent geometry. A boundary or load is executable only after its region comes from geometry grounding or an explicit selection. A vision model is not allowed to pick a face by index.

### Compilation

`EngineeringIntent` is the closed statement of the analysis: geometry, material, boundaries, loads, mesh, procedure, and criteria. The compiler lowers that statement into an ordered list of `AbaqusAction` values. Each action names its target, parameters, preconditions, and expected state. The script is rendered from that list. It is not the source of the model.

An action the compiler can render is `SUPPORTED`. Native Python that bypasses a typed action is `EXECUTABLE`: it may run, and that run is not evidence that the engineering operation was verified. An operation with no execution path is not described as complete.

Solver family is a recorded decision, not a silent rewrite. The selection is `STANDARD` or `EXPLICIT`. A declared kinematic requirement that conflicts with the requested solver blocks submission. Frequency and thermal procedures have no Explicit alternative, so a preference there is not treated as that conflict.

### Execution

Generated fragments run in an isolated kernel namespace, not in the caller's globals. Solver waits emitted by the compiler are bounded: `waitForCompletion(timeOut=...)`. A bare wait is rejected.

On Windows, `abaqus cae noGUI` does not give the host a process it can wait on. The launcher returns after starting `ABQcaeK.exe`. Completion is a marker written by the kernel script itself: `completed`, `blocked`, or `failed`. A quiet work directory is `quiescence_only`. That means the directory stopped changing. It does not mean the script finished.

A solver job is submitted in the foreground with `interactive`, because the default batch mode returns as soon as the launcher hands the job off. Exit code 0 does not prove the job completed. An ODB existing on disk does not prove it either. The positive evidence is the solver's own completion record.

### Evidence and acceptance

Every extracted result is bound to the run that produced it: `run_id`, input hash, ODB path, and ODB SHA256. A file with the same name and size is not the same result. Corrupt, empty, or non-binary ODB inputs are rejected. Missing fields raise; they are not replaced with benchmark constants.

Acceptance is a fixed gate sequence, not a single pass flag:

| Gate | What must be true |
|---|---|
| execution | the job actually terminated in a solver-authored completed state |
| odb | the ODB opens as the ODB from this run |
| evidence | the requested fields and history exist |
| numerical | the solution is not a completed job full of non-finite values |
| engineering | declared checks have evidence |
| mesh | shape metrics, not merely `ANALYSIS_CHECKS`, when mesh quality is required |
| convergence | mesh-convergence evidence, when requested |
| fatigue | fatigue evidence, when requested |
| contact | contact state matches the requested contact problem |
| procedure | the requested procedure actually ran |
| thermal / energy | thermal balance, static stabilization, or transient energy, when that physics is in scope |
| criteria | declared numeric criteria pass |
| connectors / FMBD | kinematic or flexible-multibody evidence, when that model is in scope |

A failed gate writes `report.diagnostic.html`. Renaming that file does not make it the formal report.

### What a person still decides

Before submission, the candidate is written to `pre_solve_review.html` and opened in the default browser. That file is the review. There is no separate interactive UI. Approval binds to that candidate; editing the deck invalidates it.

The agent can stop a launch that will obviously fail. It cannot decide that the load path, the support, or the criterion was the right engineering question. Those remain the reviewer's decision.

## Reference result

On a licensed Abaqus 2025 host, the official cantilever benchmark in `machine_validation/` was run with C3D20R and tip shear. Deflection was 6.3330 mm against 6.4000 mm beam theory (1.05%). Integration-point stress was 138.89 MPa against 138.56 MPa analytical (0.23%). That qualifies that case. It does not qualify every procedure, element, or contact formulation in the compiler.

## Use

```python
from abaqus_ai_agent import AbaqusAIAgent

agent = AbaqusAIAgent(executor=None)
result = agent.solve_requirement(
    "200 x 20 x 5 mm steel cantilever, encastre at the root, 100 N shear at the free end",
    submit_job=False,
)
```

The default does not submit a job. It builds and checks the candidate. After that candidate is approved, the same work directory can be solved. Task completion and criterion acceptance are separate fields on the result.

```bash
abaqus-ai-agent ask "..." --dry-run
abaqus-ai-agent approve --workdir ./run_workdir --by "analyst name"
```

## Layout

```text
src/abaqus_ai_agent/
  contracts/     intent, actions, evidence, acceptance
  planning/      intent compiler, mesh and procedure planning
  actions/       action builders and script rendering
  execution/     kernel, batch jobs, approval, ODB extraction
  validation/    structural checks before launch
  grounding/     region binding from geometry, not from a guessed index
  reporting/     formal report and diagnostic report
```

`docs/PROJECT_REQUIREMENTS_AND_PLAN.md` is the only planning document.

## License

[Apache License 2.0](LICENSE).
