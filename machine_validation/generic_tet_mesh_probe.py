"""Execute the production tetrahedron mesher on an ordinary native part.

Run with Abaqus/CAE noGUI. No project geometry, solver job, seed retry, or
model-specific branch is used. Completion is indicated by the kernel flag.
"""

from abaqus import mdb
from abaqusConstants import *
import hashlib
import json
import mesh
import os
import sys
import time

REPO = os.environ["ABQAI_REPO"]
TAG = os.environ.get("ABQAI_TAG", "native_box")
STEP = os.environ.get("ABQAI_STEP", "")
BODY = int(os.environ.get("ABQAI_BODY", "1"))
OUT = REPO + "/runs/generic_tet_mesh/" + TAG + "_result.json"
FLAG = REPO + "/runs/generic_tet_mesh/" + TAG + "_completed.flag"
sys.path.insert(0, REPO + "/src")
from abaqus_ai_agent.contracts.mesh_quality import tet_mesh_script

result = {
    "schema": "generic_tet_mesh_probe_v1",
    "geometry": STEP or "native_20x10x5_box",
    "body": BODY if STEP else None,
    "production_entry": "tet_mesh_script",
    "solver_submitted": False,
    "job_created": False,
    "model_specific_branches": False,
}
started = time.time()


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


result["kernel_pid"] = os.getpid()
result["working_directory"] = os.getcwd()
result["started_epoch_s"] = started
result["production_source_sha256"] = file_sha256(
    REPO + "/src/abaqus_ai_agent/contracts/mesh_quality.py"
)
result["local_remesh_source_sha256"] = file_sha256(
    REPO + "/src/abaqus_ai_agent/contracts/local_remesh.py"
)
result["probe_source_sha256"] = file_sha256(
    REPO + "/machine_validation/generic_tet_mesh_probe.py"
)
if STEP:
    result["input_sha256"] = file_sha256(STEP)
try:
    model = mdb.Model(name="GenericTetQualification", modelType=STANDARD_EXPLICIT)
    if STEP:
        import auxImportGeom
        imported = mdb.openStep(STEP, scaleFromFile=OFF)
        model.PartFromGeometryFile(
            name="InputBody", geometryFile=imported, bodyNum=BODY,
            combine=False, dimensionality=THREE_D, type=DEFORMABLE_BODY,
        )
        part = model.parts["InputBody"]
    else:
        sketch = model.ConstrainedSketch(name="profile", sheetSize=50.0)
        sketch.rectangle(point1=(0.0, 0.0), point2=(20.0, 10.0))
        part = model.Part(name="InputBody", dimensionality=THREE_D, type=DEFORMABLE_BODY)
        part.BaseSolidExtrude(sketch=sketch, depth=5.0)
        del model.sketches["profile"]
    instance = model.rootAssembly.Instance(name="InputBody-1", part=part, dependent=ON)
    seed = float(model.rootAssembly.getPartSeeds(region=instance, attribute=DEFAULT_SIZE))
    result["seed_mm"] = seed
    result["seed_source"] = "ABAQUS_DEFAULT_SIZE"
    part.seedPart(size=seed, deviationFactor=0.1, minSizeFactor=0.1)
    part.setElementType(
        regions=(part.cells,),
        elemTypes=(mesh.ElemType(elemCode=C3D10, elemLibrary=STANDARD),),
    )
    scope = {"p": part, "mdb": mdb, "mesh": mesh, "TET": TET, "TRI": TRI, "FREE": FREE,
             "MODERATE": MODERATE, "ON": ON, "SHAPE_FACTOR": SHAPE_FACTOR,
             "ANALYSIS_CHECKS": ANALYSIS_CHECKS, "SIZE": SIZE,
             "DEFAULT_SIZE": DEFAULT_SIZE, "FINER": FINER,
             "EDGE_SEEDING_METHOD": EDGE_SEEDING_METHOD}
    try:
        exec(compile(tet_mesh_script("p", seed), "<production_tet_mesh_script>", "exec"), scope)
    finally:
        result["virtual_topology"] = scope.get("_abqai_vt_status")
        result["combined_cleanup_faces"] = scope.get("_abqai_vt_faces")
        result["mesh_rounds"] = scope.get("_abqai_rounds")
        result["second_shape_failed_elements"] = scope.get("_abqai_retry2_failed")
        result["second_shape_worst"] = scope.get("_abqai_retry2_worst")
        result["local_attempt"] = scope.get("_abqai_local_attempt")
        result["local_status"] = scope.get("_abqai_local_status")
        result["local_region_indices"] = scope.get("_abqai_local_region_indices")
        result["local_current_hosts"] = scope.get("_abqai_local_current_hosts")
        result["boundary_gate"] = scope.get("_abqai_boundary_gate")
        result["boundary_recovery"] = scope.get("_abqai_recovery")
    shape = part.verifyMeshQuality(criterion=SHAPE_FACTOR, threshold=0.0001, elemShape=TET)
    analysis = part.verifyMeshQuality(criterion=ANALYSIS_CHECKS)
    result.update({
        "elements": len(part.elements),
        "nodes": len(part.nodes),
        "shape_failed_elements": len(shape.get("failedElements", ()) or ()),
        "shape_worst": shape.get("worst"),
        "analysis_failed_elements": len(analysis.get("failedElements", ()) or ()),
        "analysis_warning_elements": len(analysis.get("warningElements", ()) or ()),
        "status": "PASS" if not shape.get("failedElements", ()) and not analysis.get("failedElements", ()) else "BLOCKED",
    })
except Exception as exc:
    result["status"] = "BLOCKED"
    result["exception"] = "%s: %s" % (type(exc).__name__, exc)
    try:
        shape = part.verifyMeshQuality(criterion=SHAPE_FACTOR, threshold=0.0001, elemShape=TET)
        analysis = part.verifyMeshQuality(criterion=ANALYSIS_CHECKS)
        result.update({
            "elements": len(part.elements),
            "nodes": len(part.nodes),
            "shape_failed_elements": len(shape.get("failedElements", ()) or ()),
            "shape_worst": shape.get("worst"),
            "analysis_failed_elements": len(analysis.get("failedElements", ()) or ()),
            "analysis_warning_elements": len(analysis.get("warningElements", ()) or ()),
        })
    except Exception as quality_exc:
        result["quality_readback_error"] = "%s: %s" % (type(quality_exc).__name__, quality_exc)
finally:
    result["elapsed_s"] = round(time.time() - started, 3)
    result["finished_epoch_s"] = time.time()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as handle:
        json.dump(result, handle, indent=2)
    with open(FLAG, "w") as handle:
        handle.write("completed")
