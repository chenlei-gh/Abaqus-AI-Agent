"""Live Abaqus runtime smoke-test harness helpers.

The generated script emits machine-readable markers and verifies API execution,
input generation, job completion, ODB opening, and a minimal field/history probe
independently.

Legacy B28 names remain available as aliases in this module. The former
``execution.b28_harness`` forwarding module was removed so there is one
canonical implementation.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RuntimeSmokeResult:
    script_completed: bool = False
    model_created: bool = False
    input_written: bool = False
    job_submitted: bool = False
    job_completed: bool = False
    odb_exists: bool = False
    odb_opened: bool = False
    required_outputs_present: bool = False
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    #: Strictness findings: duplicate/conflicting/contradictory/out-of-order
    #: markers, or markers that do not belong to the expected run. Any entry
    #: here makes the result fail closed regardless of the stage booleans.
    invalid_reasons: tuple = ()
    #: The run identity the accepted markers were bound to (None = unbound
    #: legacy parsing; callers that need cross-run safety must pass one).
    run_id: Optional[str] = None

    @property
    def passed(self):
        return all((
            self.script_completed,
            self.model_created,
            self.input_written,
            self.job_submitted,
            self.job_completed,
            self.odb_exists,
            self.odb_opened,
            self.required_outputs_present,
        )) and not self.invalid_reasons


# Backward compatibility alias
B28HarnessResult = RuntimeSmokeResult


def build_runtime_smoke_script(job_name="AIAgent_RuntimeSmoke", odb_path=None, run_id=None,
                               wait_timeout=3600):
    """Build a deterministic Abaqus runtime smoke script.

    The model is deliberately tiny: one 3D deformable brick, one static step,
    one encastre face, and one concentrated load. The harness is an execution
    compatibility probe, not a solver benchmark.

    ``run_id`` binds every marker to one specific invocation: parsers that are
    given the same id reject markers from any other run, so a stale artifact
    (e.g. an old abaqus.rpy) can never be mistaken for this run's evidence.

    ``wait_timeout`` bounds ``waitForCompletion``. Without a bound the generated
    script waits indefinitely, and the host-side transport timeout that kills the
    connection cannot stop the kernel job the way an in-kernel timeout does.
    """
    odb_path = odb_path or job_name + ".odb"
    return r'''# -*- coding: utf-8 -*-
from abaqus import *
from abaqusConstants import *
import os
import json
import regionToolset

JOB = %(job)r
ODB = %(odb)r
RUN_ID = %(run_id)r
WAIT_TIMEOUT = %(wait_timeout)d

def marker(name, **data):
    payload = {"marker": name}
    if RUN_ID:
        payload["run_id"] = RUN_ID
    payload.update(data)
    print("AIA_SMOKE_MARKER " + json.dumps(payload, sort_keys=True))

try:
    model = mdb.Model(name="AIA_RUNTIME_SMOKE")
    marker("model_created")
    
    part = model.Part(name="Block", dimensionality=THREE_D,
                      type=DEFORMABLE_BODY)
    sketch = model.ConstrainedSketch(name="__profile__", sheetSize=10.0)
    sketch.rectangle(point1=(0.0, 0.0), point2=(1.0, 1.0))
    part.BaseSolidExtrude(sketch=sketch, depth=1.0)
    del model.sketches["__profile__"]

    material = model.Material(name="Material-1")
    material.Elastic(table=((210000.0, 0.3),))
    model.HomogeneousSolidSection(name="Section-1", material="Material-1", thickness=None)
    section_region = regionToolset.Region(cells=part.cells)
    part.SectionAssignment(region=section_region, sectionName="Section-1")

    assembly = model.rootAssembly
    instance = assembly.Instance(name="Block-1", part=part, dependent=ON)

    model.StaticStep(name="Step-1", previous="Initial")

    region = regionToolset.Region(faces=instance.faces.findAt(((0.0, 0.5, 0.5),)))
    model.EncastreBC(name="BC-1", createStepName="Initial", region=region)

    load_region = regionToolset.Region(vertices=instance.vertices.findAt(((1.0, 1.0, 1.0),)))
    model.ConcentratedForce(name="Load-1", createStepName="Step-1",
                            region=load_region, cf3=-1.0)

    part.seedPart(size=0.5)
    part.generateMesh()
    model.rootAssembly.regenerate()

    job = mdb.Job(name=JOB, model=model, type=ANALYSIS)
    job.writeInput(consistencyChecking=OFF)
    marker("input_written", input_path=os.path.abspath(JOB + ".inp"))

    job.submit(consistencyChecking=OFF)
    marker("job_submitted")
    try:
        job.waitForCompletion(timeOut=WAIT_TIMEOUT)
        wait_error = None
    except Exception as exc:
        # The documented behaviour: a bound that expires raises AbaqusException
        # instead of the script hanging forever. Any other exception is a real
        # kernel failure and must not be relabelled as a wait expiry.
        if "timeOut" not in str(exc):
            raise
        wait_error = str(exc)
    if wait_error is not None:
        marker("job_wait_timed_out", error_message=wait_error)

    status = getattr(job, "status", None)
    completion_source = "job_status"
    if str(status) != "COMPLETED":
        sta_path = JOB + ".sta"
        log_path = JOB + ".log"
        sta_ok = False
        log_ok = False
        if os.path.exists(sta_path):
            with open(sta_path, "r", encoding="utf-8", errors="replace") as handle:
                sta_ok = "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in handle.read()
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                log_ok = ("Abaqus JOB " + JOB + " COMPLETED") in handle.read()
        if sta_ok and log_ok:
            status = "COMPLETED"
            completion_source = "solver_artifacts"
    marker("job_completed", status=str(status), completion_source=completion_source)
    if str(status) != "COMPLETED":
        marker("error", error_class="solver_job", error_message=str(status))
        raise RuntimeError("Abaqus job did not complete: " + str(status))

    if not os.path.exists(ODB):
        marker("error", error_class="odb_missing", error_message=ODB)
        raise RuntimeError("ODB not found: " + ODB)
    marker("odb_exists", path=os.path.abspath(ODB))

    from odbAccess import openOdb
    odb = openOdb(path=ODB, readOnly=True)
    marker("odb_opened", steps=list(odb.steps.keys()))

    if "Step-1" not in odb.steps:
        marker("error", error_class="odb_output", error_message="Step-1 missing")
        odb.close()
        raise RuntimeError("Step-1 missing from ODB")

    step = odb.steps["Step-1"]
    if not step.frames:
        marker("error", error_class="odb_output", error_message="no frames")
        odb.close()
        raise RuntimeError("No frames in ODB")

    frame = step.frames[-1]
    required = ("U", "RF")
    missing = [name for name in required if name not in frame.fieldOutputs]
    if missing:
        marker("error", error_class="odb_output",
               error_message="missing field outputs: " + ",".join(missing))
        odb.close()
        raise RuntimeError("Required field outputs missing")

    marker("required_outputs_present", outputs=list(required))
    odb.close()
    marker("script_completed", passed=True)
except Exception as exc:
    marker("error", error_class="script_api_or_model",
           error_message=str(exc))
    marker("script_completed", passed=False)
    raise
''' % {"job": job_name, "odb": odb_path, "run_id": run_id,
       "wait_timeout": int(wait_timeout)}


# Backward compatibility alias
build_b28_smoke_script = build_runtime_smoke_script


# Canonical stage order. Markers that appear out of order indicate replayed,
# merged, or corrupted output and must never read as a clean pass.
_STAGE_ORDER = (
    "model_created",
    "input_written",
    "job_submitted",
    "job_completed",
    "odb_exists",
    "odb_opened",
    "required_outputs_present",
    "script_completed",
)


def classify_smoke_markers(markers, expected_run_id=None):
    """Convert parsed marker dictionaries into a conservative, strict result.

    Strictness rules (fail closed on every ambiguity):

    - When ``expected_run_id`` is given, only markers carrying that exact
      ``run_id`` count. Anything else is foreign evidence (typically a stale
      abaqus.rpy from a previous run) and is rejected, never merged.
    - A marker name appearing twice is invalid, whether the payloads are
      identical duplicates or conflicting values.
    - An ``error`` marker alongside ``script_completed(passed=True)`` is a
      contradiction and is invalid.
    - Stage markers must appear in canonical order.
    """
    markers = list(markers or ())
    invalid = []

    bound = []
    foreign = 0
    unbound = 0
    for m in markers:
        if expected_run_id is None:
            bound.append(m)
            continue
        marker_run = m.get("run_id")
        if marker_run == expected_run_id:
            bound.append(m)
        elif marker_run:
            foreign += 1
        else:
            unbound += 1
    if expected_run_id is not None:
        if foreign:
            # Foreign markers are diagnostics only; they never enter `names`.
            pass
        if not bound and (foreign or unbound):
            invalid = ["no_markers_for_run:%s" % expected_run_id]
            if foreign:
                invalid.append("foreign_markers_rejected:%d" % foreign)
            if unbound:
                invalid.append("unbound_markers_rejected:%d" % unbound)
            return RuntimeSmokeResult(invalid_reasons=tuple(invalid), run_id=expected_run_id)

    names = {}
    order_positions = []
    for m in bound:
        name = m.get("marker")
        if name in names:
            if names[name] == m:
                invalid.append("duplicate_marker:%s" % name)
            else:
                invalid.append("conflicting_marker:%s" % name)
            continue
        names[name] = m
        if name in _STAGE_ORDER:
            order_positions.append(_STAGE_ORDER.index(name))
    if order_positions != sorted(order_positions):
        invalid.append("out_of_order_markers")

    error = names.get("error") or {}
    completed = names.get("script_completed", {})
    if "error" in names and completed.get("passed") is True:
        invalid.append("contradictory_markers:error_and_success")
    wait_timed_out = names.get("job_wait_timed_out")
    if wait_timed_out is not None and completed.get("passed") is True:
        # The wait bound expired yet the script reported a clean pass. That can
        # only mean the artifact fallback rescued it, and a bounded wait must not
        # silently become an unbounded one: surface the expiry either way.
        invalid.append("job_wait_timed_out_with_success")

    status = names.get("job_completed", {}).get("status")
    return RuntimeSmokeResult(
        script_completed=completed.get("passed") is True,
        model_created="model_created" in names,
        input_written="input_written" in names,
        job_submitted="job_submitted" in names,
        job_completed="job_completed" in names and status == "COMPLETED",
        odb_exists="odb_exists" in names,
        odb_opened="odb_opened" in names,
        required_outputs_present="required_outputs_present" in names,
        error_class=error.get("error_class"),
        error_message=(wait_timed_out or {}).get("error_message") or error.get("error_message"),
        invalid_reasons=tuple(invalid),
        run_id=expected_run_id,
    )


classify_b28_markers = classify_smoke_markers


def execute_runtime_smoke(executor, job_name="AIAgent_RuntimeSmoke", odb_path=None,
                           timeout=3600):
    """Execute the smoke script through an existing AbaqusExecutor."""
    script = build_runtime_smoke_script(job_name=job_name, odb_path=odb_path,
                                        wait_timeout=timeout)
    raw = executor.execute(script, timeout=timeout)
    if isinstance(raw, dict):
        output = raw.get("stdout") or raw.get("output") or raw.get("message") or ""
    else:
        output = raw or ""
    return parse_smoke_output(output)


execute_b28_smoke = execute_runtime_smoke


def parse_smoke_output(output, expected_run_id=None):
    """Parse output for AIA_SMOKE_MARKER or legacy AIA_B28_MARKER lines.

    ``expected_run_id`` binds the parse to one invocation: markers from other
    runs (or markers without any run identity) are rejected instead of being
    silently absorbed.
    """
    import json
    markers = []
    prefixes = ("AIA_SMOKE_MARKER ", "AIA_B28_MARKER ")
    for line in str(output or "").splitlines():
        line = line.strip()
        if line.startswith("#:"):
            line = line[2:].strip()
        for prefix in prefixes:
            if line.startswith(prefix):
                try:
                    markers.append(json.loads(line[len(prefix):]))
                except ValueError:
                    markers.append({"marker": "invalid_marker", "raw": line})
                break
    return classify_smoke_markers(markers, expected_run_id=expected_run_id)


parse_b28_output = parse_smoke_output
