# Abaqus AI Agent

An engineering agent between a stated analysis requirement and Abaqus. It compiles the requirement into a model a person can review, submits that model only after review, and writes a formal report only when solver evidence supports the stated criteria.

[中文](README_CN.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/CI-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

A script that ran, a job that finished, and an answer that was accepted are three separate claims. The package does not install Abaqus, does not ship a license, and is not on PyPI. A generated report is not an analyst's sign-off.

It is for engineers who already have a licensed Abaqus installation and want that path kept separate. It is not a general chatbot, and it does not decide that the load path, the support, or the criterion was the right question.

## Install

Two interpreters stay separate. Install this package into a normal CPython virtual environment. Abaqus keeps its own Python and is called through the SIMULIA launcher. Do not install this package into the Python that ships with Abaqus/CAE.

The package is not on PyPI. Install it from this source tree. Use a virtual environment and `python -m pip`, so the install lands in the interpreter you just checked. Do not use `python setup.py install`.

Windows, from the repository root:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install .
python -m abaqus_ai_agent --help
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python -m abaqus_ai_agent --help
```

That installs `abaqus-ai-agent` 0.2.2. `pyproject.toml` declares Python `>=3.9`. Continuous integration tests 3.10, 3.11, and 3.12 on Ubuntu and Windows. The runtime dependency is `Pillow>=9`. The console scripts are `abaqus-ai-agent` and `abaqus-agent`.

To work on this repository, install the test extra in editable mode and run the offline suite:

```bat
python -m pip install -e ".[test]"
python -m pytest tests -q -m unit
```

In `cmd`, the quotes around `".[test]"` are required. Square brackets are wildcards. An editable install follows Python edits under `src/`. A change to dependencies or entry points in `pyproject.toml` needs the same install command again.

### Abaqus, which this package does not install

A live solve needs an already installed, licensed Abaqus. This repository does not configure the license server, `custom_v6.env`, or token availability.

The Abaqus installer creates the command directory: `C:\SIMULIA\Commands` on Windows, `/var/DassaultSystemes/SIMULIA/Commands` on Linux. The 2025 shortcut is `abq2025`. `abaqus` is the unversioned entry.

This package resolves the launcher in that order: an explicit path, `abaqus` on `PATH`, then `C:\SIMULIA\Commands\abaqus.BAT` on Windows.

```bat
where abaqus
abaqus information=release
abaqus-ai-agent inspect --json
```

A release string means the launcher runs. It does not mean a license token is free. `inspect` with no launcher means an offline host, not a failed package install.

## Try it

This does not start Abaqus. It routes the requirement and stops. The same command is what continuous integration runs.

```bat
abaqus-ai-agent ask "Apply 1000N vertical load to the free end of a 100mm cantilever beam, material steel, fixed root, check deflection <= 2.5mm." --dry-run
```

A successful dry run exits 0. The command prints an intent-routing header, then:

```text
[DRY-RUN] Intent and plan contracts verified successfully. No solver invoked.
Solver invoked:     NO
Report authorized:  NO
```

The lines between those name the inferred physics, unit system, solver, and the counts of boundaries, loads, and criteria. They do not start a job and they do not authorize a report.

The same sentence without a place for the load exits 2 and names `missing_load_application_region`. That stop is intended. It is not a solver failure.

Building the model and submitting a job is `AbaqusAIAgent.solve_requirement`. The default does not submit. Before submission, the candidate is written to `pre_solve_review.html` and opened in the default browser. That file is the review. There is no separate interactive UI. Approval is recorded against that candidate:

```bat
abaqus-ai-agent approve --workdir ./run_workdir --by "analyst name"
```

Editing the candidate invalidates the approval.

## How it is built

A requirement is compiled into a typed intent and an ordered action list. Abaqus Python is rendered from that list. The script is not the source of the model. Geometry is not invented. A boundary or a load is executable only after its region comes from geometry grounding or an explicit selection.

The three claims stay separate through the run. A script that ran is not a job that finished. A finished job is not an accepted answer. The formal file is `report.html`, and only when solver-authored evidence supports the declared criteria. Otherwise the file is `report.diagnostic.html`. Renaming it does not make it the formal report.

The agent can refuse a launch that will obviously fail. It cannot decide that the question itself was the right one.

The gate sequence, completion markers, and solver-selection rules are in the [requirements and plan](docs/PROJECT_REQUIREMENTS_AND_PLAN.md). That file is the only planning document.

## One qualified case

On a licensed Abaqus 2025 host, the cantilever in [`machine_validation/`](machine_validation/) was run with C3D20R and tip shear. Deflection was 6.3330 mm against 6.4000 mm beam theory (1.05%). Integration-point stress was 138.89 MPa against 138.56 MPa analytical (0.23%). That qualifies that case. It does not qualify every procedure, element, or contact formulation.

Record: [`official_cantilever_benchmark_evidence.json`](machine_validation/official_cantilever_benchmark_evidence.json).

## Help

Questions and defects: [GitHub issues](https://github.com/chenlei-gh/Abaqus-AI-Agent/issues).

## License

[Apache License 2.0](LICENSE).
