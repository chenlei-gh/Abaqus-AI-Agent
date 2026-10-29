"""Historical M1FA Body-1 mesh probe. Not a production mesh entry.

This file keeps the 2026-10-28 DEFAULT_SIZE evidence path. It does not call
``tet_mesh_script`` and must not be rerun as the production mesher. A replay
requires ``ABAQUS_AI_HISTORICAL_MESH_PROBE=1``. No Job, no submit, no
waitForCompletion. A missing or invalid DEFAULT_SIZE stops before any seed
or mesh call. 2.5 mm is historical comparison only and is never a fallback.
"""

import os

PRODUCTION_MESH_ENTRY = False
HISTORICAL_REPLAY_ENV = "ABAQUS_AI_HISTORICAL_MESH_PROBE"


def refuse_production_mesh_replay():
    """Hard stop: this probe is evidence, not the production mesh chain."""
    if os.environ.get(HISTORICAL_REPLAY_ENV) != "1":
        raise RuntimeError(
            "m1fa_default_size_probe is not a production mesh entry and "
            "refuses to rerun without %s=1; use tet_mesh_script"
            % HISTORICAL_REPLAY_ENV
        )


refuse_production_mesh_replay()

from abaqus import mdb
from abaqusConstants import *
import auxImportGeom
import json
import math
import time

STEP = r"D:/AbaqusProjects/M1FA/M1FA_VENT_ASM_CTR_20261025.stp"
OUT = r"D:/AbaqusProjects/M1FA/working/REQ49_MESH/m1fa_default_size_probe.json"
LOG = r"D:/AbaqusProjects/M1FA/working/REQ49_MESH/default_size_probe.log"
FLAG = r"D:/AbaqusProjects/M1FA/working/REQ49_MESH/default_size_completed.flag"
FLOOR = 0.0001
FACE_ANGLE = 60.0

os.makedirs(os.path.dirname(OUT), exist_ok=True)
result = {
    "schema": "m1fa_default_size_probe_v1",
    "step": STEP,
    "body": 1,
    "bodies_meshed": 0,
    "seed_source": None,
    "seed_mm": None,
    "historical_seed_mm": 2.5,
    "historical_seed_used": False,
    "shape_factor_floor": FLOOR,
    "repair": False,
    "seed_retries": 0,
    "solver_submitted": False,
    "job_created": False,
    "local_edge_seeds_requested": False,
    "edge_coverage": "NOT_REQUESTED",
    "production_default": "NOT_SWITCHED",
    "production_mesh_entry": False,
    "not_mesh_convergence": True,
    "not_six_body_qualification": True,
}


def save(mark):
    result["mark"] = mark
    handle = open(LOG, "a")
    handle.write(mark + " " + json.dumps(result, default=str) + "\n")
    handle.close()
    print("MARK " + mark)


def positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def quality_counts(report, key):
    values = report.get(key, ()) or ()
    return len(values)


started = time.time()
try:
    model = mdb.Model(name="M1FA_DEFAULT_SIZE", modelType=STANDARD_EXPLICIT)
    import_started = time.time()
    # 2025 noGUI does not bind mdb.openStep until auxImportGeom is imported.
    imported = mdb.openStep(STEP, scaleFromFile=OFF)
    result["step_bodies"] = int(getattr(imported, "numberOfParts", 0) or 0)
    result["import_s"] = round(time.time() - import_started, 3)
    save("imported")
    model.PartFromGeometryFile(
        name="Body-1",
        geometryFile=imported,
        bodyNum=1,
        combine=False,
        dimensionality=THREE_D,
        type=DEFORMABLE_BODY,
    )
    part = model.parts["Body-1"]
    result["geometry_valid_before_check"] = bool(part.geometryValidity)
    part.checkGeometry(detailed=ON, level=20)
    result["geometry_valid"] = bool(part.geometryValidity)
    result["cells"] = len(part.cells)
    result["faces_before"] = len(part.faces)
    result["edges_before"] = len(part.edges)
    save("geometry")
    if not result["geometry_valid"]:
        result["status"] = "BLOCKED"
        result["reason"] = "invalid_geometry"
    else:
        assembly = model.rootAssembly
        instance = assembly.Instance(name="Body-1-1", part=part, dependent=ON)
        seed_error = None
        seed_value = None
        try:
            seed_value = assembly.getPartSeeds(region=instance, attribute=DEFAULT_SIZE)
            result["seed_api"] = "Assembly.getPartSeeds"
        except Exception as exc:
            seed_error = "%s: %s" % (type(exc).__name__, exc)
            try:
                seed_value = part.getPartSeeds(attribute=DEFAULT_SIZE)
                result["seed_api"] = "Part.getPartSeeds"
                seed_error = None
            except Exception as part_exc:
                result["part_seed_api_error"] = "%s: %s" % (type(part_exc).__name__, part_exc)
        result["seed_read_error"] = seed_error
        result["seed_raw"] = seed_value
        if not positive(seed_value):
            result["status"] = "BLOCKED"
            result["reason"] = "default_size_unreadable_or_invalid"
            result["seed_source"] = None
        else:
            seed = float(seed_value)
            threshold = 0.2 * seed
            face_area = threshold * threshold
            result["seed_mm"] = seed
            result["seed_source"] = "ABAQUS_DEFAULT_SIZE"
            result["short_edge_threshold_mm"] = threshold
            result["small_face_area_threshold"] = face_area
            save("default_size")
            vt_started = time.time()
            try:
                part.createVirtualTopology(
                    mergeShortEdges=True,
                    shortEdgeThreshold=threshold,
                    ignoreRedundantEntities=True,
                    cornerAngleTolerance=30.0,
                    mergeSmallFaces=False,
                    mergeSliverFaces=False,
                    mergeSmallAngleFaces=False,
                    mergeThinStairFaces=False,
                    applyBlendControls=False,
                )
                result["virtual_topology"] = "applied"
            except Exception as exc:
                result["virtual_topology"] = "no_entity_or_rejected"
                result["virtual_topology_error"] = "%s: %s" % (type(exc).__name__, exc)
            result["virtual_topology_s"] = round(time.time() - vt_started, 3)
            result["ignored_edges"] = len(part.ignoredEdges)
            result["ignored_vertices"] = len(part.ignoredVertices)
            save("virtual_topology")
            part.seedPart(size=seed, deviationFactor=0.1, minSizeFactor=0.1)
            assigned = None
            try:
                assigned = assembly.getPartSeeds(region=instance, attribute=SIZE)
            except Exception as exc:
                result["assigned_size_error"] = "%s: %s" % (type(exc).__name__, exc)
            result["assigned_size_mm"] = assigned
            part.setMeshControls(
                regions=part.cells, elemShape=TET, technique=FREE, sizeGrowth=MODERATE,
            )
            preview_started = time.time()
            part.generateMesh(boundaryPreview=ON)
            result["boundary_preview_s"] = round(time.time() - preview_started, 3)
            boundary = part.verifyMeshQuality(
                criterion=SHAPE_FACTOR, threshold=FLOOR, elemShape=TET,
            )
            result["boundary_failed_elements"] = quality_counts(boundary, "failedElements")
            save("boundary")
            if result["boundary_failed_elements"]:
                result["status"] = "BLOCKED"
                result["reason"] = "boundary_preview_below_shape_factor"
            else:
                interior_started = time.time()
                part.generateMesh()
                result["interior_mesh_s"] = round(time.time() - interior_started, 3)
                result["elements"] = len(part.elements)
                result["nodes"] = len(part.nodes)
                shape = part.verifyMeshQuality(
                    criterion=SHAPE_FACTOR, threshold=FLOOR, elemShape=TET,
                )
                analysis = part.verifyMeshQuality(criterion=ANALYSIS_CHECKS)
                result["shape_failed_elements"] = quality_counts(shape, "failedElements")
                result["shape_worst"] = shape.get("worst")
                result["analysis_failed_elements"] = quality_counts(analysis, "failedElements")
                result["analysis_warning_elements"] = quality_counts(analysis, "warningElements")
                result["secondary_face_merge"] = "not_needed"
                failed = (
                    result["shape_failed_elements"]
                    or result["analysis_failed_elements"]
                    or (
                        result["shape_worst"] is not None
                        and float(result["shape_worst"]) < FLOOR
                    )
                )
                if failed and result["shape_failed_elements"]:
                    labels = set(int(element.label) for element in shape.get("failedElements", ()) or ())
                    result["failed_element_labels"] = sorted(labels)
                    hosts = []
                    for face in part.faces:
                        hit = False
                        for face_element in face.getElements() or ():
                            if int(face_element.label) in labels:
                                hit = True
                                break
                        if not hit:
                            continue
                        area = float(face.getSize(printResults=False))
                        short_edge = False
                        for edge_index in face.getEdges():
                            if float(part.edges[edge_index].getSize(printResults=False)) <= threshold:
                                short_edge = True
                                break
                        if area <= face_area or short_edge:
                            hosts.append(face)
                    region = []
                    seen = set()
                    for host in hosts:
                        for candidate in host.getFacesByFaceAngle(FACE_ANGLE):
                            key = id(candidate)
                            if key in seen:
                                continue
                            area = float(candidate.getSize(printResults=False))
                            short_edge = False
                            for edge_index in candidate.getEdges():
                                if float(part.edges[edge_index].getSize(printResults=False)) <= threshold:
                                    short_edge = True
                                    break
                            if area > face_area and not short_edge:
                                continue
                            seen.add(key)
                            region.append(candidate)
                    result["secondary_host_faces"] = len(hosts)
                    result["secondary_region_faces"] = len(region)
                    if not region:
                        result["secondary_face_merge"] = "unavailable"
                        result["status"] = "BLOCKED"
                        result["reason"] = "quality_below_floor_no_small_host_face"
                    else:
                        part.createVirtualTopology(
                            regions=tuple(region),
                            mergeShortEdges=True,
                            shortEdgeThreshold=threshold,
                            mergeSmallFaces=True,
                            smallFaceAreaThreshold=face_area,
                            ignoreRedundantEntities=True,
                            cornerAngleTolerance=30.0,
                            mergeSliverFaces=False,
                            mergeSmallAngleFaces=False,
                            mergeThinStairFaces=False,
                            applyBlendControls=False,
                        )
                        result["secondary_face_merge"] = "applied"
                        part.deleteMesh()
                        part.generateMesh(boundaryPreview=ON)
                        boundary = part.verifyMeshQuality(
                            criterion=SHAPE_FACTOR, threshold=FLOOR, elemShape=TET,
                        )
                        result["secondary_boundary_failed_elements"] = quality_counts(
                            boundary, "failedElements",
                        )
                        if result["secondary_boundary_failed_elements"]:
                            result["status"] = "BLOCKED"
                            result["reason"] = "secondary_boundary_rejected"
                        else:
                            part.generateMesh()
                            result["elements"] = len(part.elements)
                            result["nodes"] = len(part.nodes)
                            shape = part.verifyMeshQuality(
                                criterion=SHAPE_FACTOR, threshold=FLOOR, elemShape=TET,
                            )
                            analysis = part.verifyMeshQuality(criterion=ANALYSIS_CHECKS)
                            result["shape_failed_elements"] = quality_counts(shape, "failedElements")
                            result["shape_worst"] = shape.get("worst")
                            result["analysis_failed_elements"] = quality_counts(
                                analysis, "failedElements",
                            )
                            result["analysis_warning_elements"] = quality_counts(
                                analysis, "warningElements",
                            )
                            failed = (
                                result["shape_failed_elements"]
                                or result["analysis_failed_elements"]
                                or (
                                    result["shape_worst"] is not None
                                    and float(result["shape_worst"]) < FLOOR
                                )
                            )
                            result["status"] = "BLOCKED" if failed else "CONTINUE"
                            result["reason"] = (
                                "quality_below_floor" if failed else "continuation_floor_met"
                            )
                else:
                    result["status"] = "BLOCKED" if failed else "CONTINUE"
                    result["reason"] = (
                        "quality_below_floor" if failed else "continuation_floor_met"
                    )
                if result.get("elements"):
                    result["bodies_meshed"] = 1
    result["elapsed_s"] = round(time.time() - started, 3)
    save("finished")
except Exception as exc:
    result["status"] = "BLOCKED"
    result["exception"] = "%s: %s" % (type(exc).__name__, exc)
    result["elapsed_s"] = round(time.time() - started, 3)
    save("exception")
finally:
    result["elapsed_s"] = round(time.time() - started, 3)
    result["solver_submitted"] = False
    handle = open(OUT, "w")
    json.dump(result, handle, indent=2, default=str)
    handle.close()
    done = open(FLAG, "w")
    done.write("completed")
    done.close()
