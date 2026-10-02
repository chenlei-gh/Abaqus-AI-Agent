#!/usr/bin/env python3
"""H.6: Image / Intent to Region Grounding Real Validation E2E.

Validates the full chain:
1. Engineering visual intent & viewport annotation (ImagePoint).
2. Projection probe matching with candidate faces/edges.
3. Scoring, ranking, and deterministic resolution policy.
4. Materialization to RegionBinding and native findAt expressions.
5. Live Abaqus/CAE verification: evaluates findAt on actual beam model,
   proving non-empty entity selection and Set creation.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.contracts.geometry import ImagePoint, GeometryCandidate
from abaqus_ai_agent.grounding.resolver import (
    resolve_image_point,
    selection_from_candidates,
    region_expression,
)
from abaqus_ai_agent.execution.batch import BatchExecutor


def run_h6_grounding_e2e():
    validation_dir = ROOT / "machine_validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    # 1. Viewport geometry probe for a cantilever beam
    # Left face (Fixed, x=0): 3D centroid (0.0, 5.0, 5.0), projected polygon near x=0.1
    # Right face (Tip, x=100): 3D centroid (100.0, 5.0, 5.0), projected polygon near x=0.9
    probe = {
        "faces": [
            {
                "instance": "Beam-1",
                "index": 0,
                "entity_type": "Face",
                "entity_key": "Face:0",
                "centroid": (0.0, 5.0, 5.0),
                "locator_point": (0.0, 5.0, 5.0),
                "normal": (-1.0, 0.0, 0.0),
                "screen": (0.1, 0.5),
                "screen_polygon": [(0.05, 0.3), (0.15, 0.3), (0.15, 0.7), (0.05, 0.7)],
                "facing_score": 1.0,
                "camera_depth": 50.0,
            },
            {
                "instance": "Beam-1",
                "index": 1,
                "entity_type": "Face",
                "entity_key": "Face:1",
                "centroid": (100.0, 5.0, 5.0),
                "locator_point": (100.0, 5.0, 5.0),
                "normal": (1.0, 0.0, 0.0),
                "screen": (0.9, 0.5),
                "screen_polygon": [(0.85, 0.3), (0.95, 0.3), (0.95, 0.7), (0.85, 0.7)],
                "facing_score": 1.0,
                "camera_depth": 50.0,
            },
        ],
        "edges": [],
        "vertices": [],
    }

    # 2. Intent 1: Click at fixed face (x=0.1, y=0.5)
    click_fixed = ImagePoint(0.1, 0.5)
    res_fixed = resolve_image_point("intent_fix_end", click_fixed, probe)
    assert res_fixed.selected is not None
    best_fixed = res_fixed.selected
    assert best_fixed.entity_type == "Face"
    assert best_fixed.centroid == (0.0, 5.0, 5.0)

    sel_fixed = selection_from_candidates([best_fixed], name="FixedGroundedFace")
    fixed_expr = region_expression(sel_fixed.targets[0], variable="inst")
    assert "findAt" in fixed_expr
    assert "0.0, 5.0, 5.0" in fixed_expr

    # 3. Intent 2: Click at tip face (x=0.9, y=0.5)
    click_tip = ImagePoint(0.9, 0.5)
    res_tip = resolve_image_point("intent_tip_load", click_tip, probe)
    assert res_tip.selected is not None
    best_tip = res_tip.selected
    assert best_tip.entity_type == "Face"
    assert best_tip.centroid == (100.0, 5.0, 5.0)

    sel_tip = selection_from_candidates([best_tip], name="TipGroundedFace")
    tip_expr = region_expression(sel_tip.targets[0], variable="inst")
    assert "100.0, 5.0, 5.0" in tip_expr

    # 4. Live Abaqus/CAE Grounding Verification
    # Run a lightweight verification script inside live Abaqus to test that
    # the resolved expressions accurately select entities and create valid sets
    res_json_file = validation_dir / "h6_grounding_live_result.json"
    res_json_str = str(res_json_file).replace("\\", "/")

    cae_script = r"""
import json
from abaqus import mdb
from abaqusConstants import THREE_D, DEFORMABLE_BODY, ON, CARTESIAN

model_name = 'GroundingVerificationModel'
if model_name in mdb.models:
    del mdb.models[model_name]
model = mdb.Model(name=model_name)

sketch = model.ConstrainedSketch(name='Profile', sheetSize=200.0)
sketch.rectangle(point1=(0.0, 0.0), point2=(100.0, 10.0))
part = model.Part(name='Beam', dimensionality=THREE_D, type=DEFORMABLE_BODY)
part.BaseSolidExtrude(sketch=sketch, depth=10.0)

a = model.rootAssembly
a.DatumCsysByDefault(CARTESIAN)
inst = a.Instance(name='Beam-1', part=part, dependent=ON)

# Execute grounded expressions
fixed_face = %s
tip_face = %s

set_fixed = a.Set(name='Grounded_Fixed', faces=fixed_face)
set_tip = a.Set(name='Grounded_Tip', faces=tip_face)

results = {
    'fixed_face_count': len(fixed_face),
    'tip_face_count': len(tip_face),
    'fixed_set_faces': len(set_fixed.faces),
    'tip_set_faces': len(set_tip.faces),
    'status': 'PASS' if len(fixed_face) == 1 and len(tip_face) == 1 else 'FAIL'
}

with open('%s', 'w') as f:
    json.dump(results, f, indent=2)
""" % (fixed_expr, tip_expr, res_json_str)

    cae_script_file = validation_dir / "h6_grounding_live_script.py"
    cae_script_file.write_text(cae_script, encoding="utf-8")

    executor = BatchExecutor(launcher="abaqus", workdir=str(validation_dir))
    proc = executor.run_nogui(str(cae_script_file), timeout=120)

    assert res_json_file.exists(), "Grounding results file was not created: %s" % res_json_file
    with open(res_json_file, "r", encoding="utf-8") as f:
        cae_results = json.load(f)

    assert cae_results["status"] == "PASS"
    assert cae_results["fixed_face_count"] == 1
    assert cae_results["tip_face_count"] == 1

    # 5. Output evidence payload
    evidence_payload = {
        "status": "PASS",
        "case": "H.6_image_intent_to_region_grounding",
        "intents": [
            {
                "intent_id": "intent_fix_end",
                "click_point": [click_fixed.x, click_fixed.y],
                "resolved_target": sel_fixed.targets[0],
                "expression": fixed_expr,
                "cae_matched_faces": cae_results["fixed_face_count"],
            },
            {
                "intent_id": "intent_tip_load",
                "click_point": [click_tip.x, click_tip.y],
                "resolved_target": sel_tip.targets[0],
                "expression": tip_expr,
                "cae_matched_faces": cae_results["tip_face_count"],
            },
        ],
        "cae_verification": cae_results,
    }

    evidence_file = validation_dir / "h6_image_intent_grounding_evidence.json"
    with open(evidence_file, "w", encoding="utf-8") as f:
        json.dump(evidence_payload, f, indent=2)

    print("H.6 Image/Intent to Region Grounding E2E: PASS")
    print("  Fixed face expression: %s -> %d face(s)" % (fixed_expr, cae_results["fixed_face_count"]))
    print("  Tip face expression:   %s -> %d face(s)" % (tip_expr, cae_results["tip_face_count"]))
    print("  Evidence:              %s" % evidence_file.name)
    return evidence_payload


if __name__ == "__main__":
    run_h6_grounding_e2e()
