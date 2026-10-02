"""B28-compatible smoke-test harness helpers.

The generated script intentionally uses Python 2.7-compatible syntax and emits
machine-readable markers. It verifies API execution, input generation, job
completion, ODB opening, and a minimal field/history probe independently.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class B28HarnessResult:
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
        ))


def build_b28_smoke_script(job_name="AIAgent_B28Smoke", odb_path=None):
    """Build a deterministic Abaqus Python 2.7-compatible smoke script.

    The model is deliberately tiny: one 3D deformable brick, one static step,
    one encastre face, and one concentrated load. The harness is an execution
    compatibility probe, not a solver benchmark.
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

def marker(name, **data):
    payload = {"marker": name}
    payload.update(data)
    print("AIA_B28_MARKER " + json.dumps(payload, sort_keys=True))

try:
    model = mdb.Model(name="AIA_B28_SMOKE")
    marker("model_created")
    
    part = model.Part(name="Block", dimensionality=THREE_D,
                      type=DEFORMABLE_BODY)
    sketch = model.ConstrainedSketch(name="__profile__", sheetSize=10.0)
    sketch.rectangle(point1=(0.0, 0.0), point2=(1.0, 1.0))
    part.BaseSolidExtrude(sketch=sketch, depth=1.0)
    del model.sketches["__profile__"]

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
    job.waitForCompletion()

    status = getattr(job, "status", None)
    marker("job_completed", status=str(status))
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
''' % {"job": job_name, "odb": odb_path}


def classify_b28_markers(markers):
    """Convert parsed marker dictionaries into a conservative result."""
    names = {x.get("marker"): x for x in markers}
    error = names.get("error") or {}
    status = names.get("job_completed", {}).get("status")
    return B28HarnessResult(
        script_completed=names.get("script_completed", {}).get("passed") is True,
        model_created="model_created" in names,
        input_written="input_written" in names,
        job_submitted="job_submitted" in names,
        job_completed="job_completed" in names and status == "COMPLETED",
        odb_exists="odb_exists" in names,
        odb_opened="odb_opened" in names,
        required_outputs_present="required_outputs_present" in names,
        error_class=error.get("error_class"),
        error_message=error.get("error_message"),
    )


def execute_b28_smoke(executor, job_name="AIAgent_B28Smoke", odb_path=None,
                      timeout=3600):
    """Execute the smoke script through an existing AbaqusExecutor.

    The executor remains responsible for transport/runtime invocation. This
    helper only builds the probe, normalizes the executor response, and parses
    its explicit markers. A zero process exit code without markers is not
    considered success.
    """
    script = build_b28_smoke_script(job_name=job_name, odb_path=odb_path)
    raw = executor.execute(script, timeout=timeout)
    if isinstance(raw, dict):
        output = raw.get("stdout") or raw.get("output") or raw.get("message") or ""
    else:
        output = raw or ""
    return parse_b28_output(output)


def parse_b28_output(output):
    import json
    markers = []
    for line in str(output or "").splitlines():
        prefix = "AIA_B28_MARKER "
        if line.startswith(prefix):
            try:
                markers.append(json.loads(line[len(prefix):]))
            except ValueError:
                markers.append({"marker": "invalid_marker", "raw": line})
    return classify_b28_markers(markers)
