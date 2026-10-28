"""One qualified partition, then stop.

A bad tetrahedron mesh must not reach solver submission, and the same
datacheck signature must not buy a second submission. Passing the continuation
floor is not a convergence claim.
"""

import pytest

from abaqus_ai_agent.actions.builders import contact
from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.contracts.action import AbaqusAction
from abaqus_ai_agent.contracts.mesh_quality import (
    MeshQualityResult,
    TET_SHAPE_FACTOR_FLOOR,
    mesh_submission_blockers,
    tet_mesh_script,
)
from abaqus_ai_agent.diagnostics.orchestrator import _datacheck_signature
from abaqus_ai_agent.diagnostics.solver_patterns import DiagnosticIssue


def test_tet_script_uses_default_mesher_and_stops_on_boundary_preview():
    script = tet_mesh_script("p", 2.5)
    assert "sizeGrowth=MODERATE" in script
    assert "algorithm=" not in script
    assert "NON_DEFAULT" not in script
    assert "createVirtualTopology(" in script
    assert "mergeShortEdges=True" in script
    assert "shortEdgeThreshold=0.5" in script
    assert "ignoreRedundantEntities=True" in script
    assert "mergeSmallFaces=False" in script
    assert "mergeSmallFaces=True" in script
    assert "_abqai_vt2 = " in script
    assert "smallFaceAreaThreshold=0.25" in script
    assert "getElementFaces()" in script
    assert "getFacesByFaceAngle(60.0)" in script
    assert "getAdjacentElements()" in script
    assert "findAt(" not in script
    assert "getCurvature(" not in script
    assert "evalAngle" not in script
    assert "applyBlendControls=False" in script
    assert "mergeSliverFaces=False" in script
    assert ".repair(" not in script
    assert "ignoreEntity(" not in script
    assert script.index("createVirtualTopology(") < script.index("generateMesh(boundaryPreview=ON)")
    assert script.index("generateMesh()") < script.index("_abqai_vt2 = ")
    assert "generateMesh(boundaryPreview=ON)" in script
    assert "SHAPE_FACTOR" in script
    assert str(TET_SHAPE_FACTOR_FLOOR) in script
    assert script.index("boundaryPreview=ON") < script.index("generateMesh()")
    assert "tet_boundary_preview_rejected" in script
    assert "tet_secondary_face_merge_unavailable" in script
    assert "no documented small host face" in script
    assert "tet_secondary_face_merge_failed" in script
    assert "worst=" in script
    assert "no_entity_or_rejected" in script
    assert script.count("createVirtualTopology(") == 2


def test_analysis_checks_pass_without_shape_evidence_is_not_a_stop_by_itself():
    # ANALYSIS_CHECKS failed=0 is not enough to call a mesh good, but a
    # warning-only result is not the hard stop. The hard stop is a failed
    # status, a failed element, or a shape factor below the documented floor.
    result = MeshQualityResult(
        status="pass",
        metrics={},
        evidence=("native_verify:ANALYSIS_CHECKS",),
    )
    assert mesh_submission_blockers(result) == ()


def test_failed_shape_factor_blocks_submission():
    result = MeshQualityResult(
        status="fail",
        metrics={"shape_factor": 0.0},
        violations=("shape_factor",),
        failed_element_count=12,
        evidence=("native_verify:SHAPE_FACTOR", "native_verify:ANALYSIS_CHECKS"),
    )
    blockers = mesh_submission_blockers(result)
    assert "mesh_quality_fail" in blockers
    assert "failed_elements:12" in blockers
    assert "shape_factor_below_floor:0.0" in blockers


def test_missing_mesh_result_does_not_block_legacy_callers_without_a_result():
    assert mesh_submission_blockers(None) == ("mesh_quality_missing",)


def test_contact_adjustment_is_rejected_before_script_exists():
    with pytest.raises(ValueError, match="mask solid overlap"):
        contact(
            "Model-1", "CP-1", "main", "secondary", "Prop",
            adjustMethod="OVERCLOSURE", adjustTolerance=0.08,
        )
    action = AbaqusAction(
        action_type="contact",
        model_name="Model-1",
        target="CP-1",
        parameters={
            "name": "CP-1",
            "master_expression": "main",
            "slave_expression": "secondary",
            "property": "Prop",
            "adjustTolerance": 0.08,
        },
    )
    with pytest.raises(ValueError, match="mask solid overlap"):
        action_to_script(action)


def test_hex_quality_script_does_not_apply_tetrahedron_shape_factor():
    action = AbaqusAction(
        action_type="mesh_quality",
        model_name="Model-1",
        target="Part-1",
        parameters={"part": "Part-1", "element_type": "C3D8R", "analysis_checks": True},
    )
    script = action_to_script(action)
    assert "SHAPE_FACTOR" not in script
    assert "ANALYSIS_CHECKS" in script


def test_triangle_quality_script_uses_documented_triangle_floor():
    action = AbaqusAction(
        action_type="mesh_quality",
        model_name="Model-1",
        target="Part-1",
        parameters={"part": "Part-1", "element_type": "S3", "analysis_checks": True},
    )
    script = action_to_script(action)
    assert "('SHAPE_FACTOR', 0.01, 'shape_factor')" in script


def test_geometry_diagnosis_rereads_validity_after_check():
    from abaqus_ai_agent.planning.compiler import (
        IntentBoundarySpec,
        IntentGeometrySpec,
        IntentLoadSpec,
        IntentMeshSpec,
        IntentStepSpec,
        compile_intent_to_actions,
    )
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition

    plan = compile_intent_to_actions(
        model_name="CompiledModel",
        part_name="BeamPart",
        job_name="CompiledJob",
        geometry=IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0),
        material=MaterialDefinition(
            name="Aluminum_6061",
            unit_system="MM_N_MPA",
            elastic=ElasticProperties(youngs_modulus=70000.0, poisson_ratio=0.33),
            density=2.7e-9,
        ),
        step=IntentStepSpec(name="LoadingStep", step_type="static_general", nlgeom=False),
        bcs=[IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace")],
        loads=[IntentLoadSpec(name="VerticalTipLoad", load_type="concentrated_force", region="TipPoint", magnitude=-500.0, direction="CF2")],
        mesh=IntentMeshSpec(element_type="C3D8R", global_size=3.0),
    )
    script = plan.cae_script
    assert script.count("seedPart(") == 1
    assert "checkGeometry(detailed=ON, level=20)" in script
    assert script.index("checkGeometry(detailed=ON, level=20)") < script.index("seedPart(")
    assert "geometryValidity is false after checkGeometry" in script
    assert "algorithm=" not in script
    assert "NON_DEFAULT" not in script
    assert "createVirtualTopology(" not in script
    assert "SHAPE_FACTOR" not in script


def test_same_datacheck_signature_is_stable_and_distinct_from_convergence():
    issue = DiagnosticIssue(
        diagnosis_id="ZERO_PIVOT",
        severity="ERROR",
        supporting_evidence=("zero pivot",),
        likely_cause="singularity",
        suggested_remediation="inspect constraints",
    )
    texts = {"dat": "ZERO PIVOT", "msg": "", "sta": "", "log": ""}
    assert _datacheck_signature((issue,), texts) == _datacheck_signature((issue,), texts)
    assert _datacheck_signature((), {"dat": "", "msg": "too many attempts", "sta": "", "log": ""}) is None
