"""Multi-part assembly scope must keep every solid, contact, and fixture."""

import os
import tempfile

import pytest

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.geometry.assembly_scope import build_assembly_scope
from abaqus_ai_agent.geometry.cad_ingestion import classify_cad_model, ingest_cad_file
from abaqus_ai_agent.geometry.model import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
    CadProvenance,
    CadShell,
    CadSolid,
    CadVertex,
    GeometryModel,
)
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentMeshSpec,
    compile_intent_to_actions,
)


def _model(solids, shells, faces, edges, vertices, bbox):
    return GeometryModel(
        model_id="HANDLE_ASM",
        provenance=CadProvenance(
            file_path="handle.stp",
            file_name="handle.stp",
            file_sha256="a" * 64,
            file_size_bytes=10,
            ingested_at="2026-10-14T00:00:00Z",
            cad_format=CadFormat.STEP,
        ),
        bounding_box=bbox,
        solids=tuple(solids),
        shells=tuple(shells),
        faces=tuple(faces),
        edges=tuple(edges),
        vertices=tuple(vertices),
    )


def _mated_handle_model():
    vertices = (
        CadVertex("V1", (0.0, 0.0, 0.0)),
        CadVertex("V2", (40.0, 20.0, 0.0)),
        CadVertex("V3", (0.0, 0.0, 30.0)),
        CadVertex("V4", (40.0, 20.0, 30.0)),
        CadVertex("V5", (5.0, 2.0, 30.0)),
        CadVertex("V6", (25.0, 16.0, 30.0)),
        CadVertex("V7", (5.0, 2.0, 50.0)),
        CadVertex("V8", (25.0, 16.0, 50.0)),
    )
    edges = (
        CadEdge("E_base_bot", start_vertex_id="V1", end_vertex_id="V2"),
        CadEdge("E_base_top", start_vertex_id="V3", end_vertex_id="V4"),
        CadEdge("E_pin_bot", start_vertex_id="V5", end_vertex_id="V6"),
        CadEdge("E_pin_top", start_vertex_id="V7", end_vertex_id="V8"),
    )
    faces = (
        CadFace("F_base_bot", surface_type="PLANE", edge_ids=("E_base_bot",), normal=(0.0, 0.0, -1.0), is_planar=True, area=800.0),
        CadFace("F_base_top", surface_type="PLANE", edge_ids=("E_base_top",), normal=(0.0, 0.0, 1.0), is_planar=True, area=800.0),
        CadFace("F_pin_bot", surface_type="PLANE", edge_ids=("E_pin_bot",), normal=(0.0, 0.0, -1.0), is_planar=True, area=280.0),
        CadFace("F_pin_top", surface_type="PLANE", edge_ids=("E_pin_top",), normal=(0.0, 0.0, 1.0), is_planar=True, area=280.0),
    )
    shells = (
        CadShell("SH_base", face_ids=("F_base_bot", "F_base_top"), is_closed=True),
        CadShell("SH_pin", face_ids=("F_pin_bot", "F_pin_top"), is_closed=True),
    )
    solids = (
        CadSolid("S_HANDLE", shell_ids=("SH_base",), step_body_index=2),
        CadSolid("S_PIN", shell_ids=("SH_pin",), step_body_index=1),
    )
    bbox = CadBoundingBox(0.0, 0.0, 0.0, 40.0, 20.0, 50.0)
    return _model(solids, shells, faces, edges, vertices, bbox)


def test_related_parts_receive_contact_and_installation_fixture():
    scope = build_assembly_scope(_mated_handle_model())

    assert [part.solid_id for part in scope.parts] == ["S_PIN", "S_HANDLE"]
    assert [part.step_body_index for part in scope.parts] == [1, 2]
    assert scope.is_complete is True
    assert len(scope.contacts) == 1
    assert {scope.contacts[0].master_part, scope.contacts[0].slave_part} == {"S_HANDLE", "S_PIN"}
    assert scope.fixture is not None
    assert scope.fixture.set_name == "InstallationFixed"
    assert scope.fixture.part_id == "S_PIN"
    assert scope.fixture.face_id == "F_pin_top"
    assert scope.gaps == ()

    cap = classify_cad_model(_mated_handle_model())
    assert cap.status == CapabilityStatus.SUPPORTED
    assert cap.action_type == "assembly_scope"
    assert "2 mating" not in cap.reason
    assert "1 mating contact" in cap.reason


def test_separated_parts_are_not_declared_complete():
    model = _mated_handle_model()
    moved = []
    for face in model.faces:
        if face.id == "F_pin_bot":
            moved.append(CadFace(
                face.id, surface_type=face.surface_type, edge_ids=face.edge_ids,
                normal=face.normal, is_planar=True, area=face.area,
            ))
        else:
            moved.append(face)
    # Move the pin geometrically far from the handle by rewriting its vertices.
    far_vertices = tuple(
        CadVertex(vertex.id, (vertex.point[0], vertex.point[1], vertex.point[2] + 80.0))
        if vertex.id in {"V5", "V6", "V7", "V8"} else vertex
        for vertex in model.vertices
    )
    separated = GeometryModel(
        model_id=model.model_id,
        provenance=model.provenance,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 40.0, 20.0, 130.0),
        solids=model.solids,
        shells=model.shells,
        faces=tuple(moved),
        edges=model.edges,
        vertices=far_vertices,
    )

    scope = build_assembly_scope(separated)
    assert scope.part_count == 2
    assert scope.contacts == ()
    assert scope.is_complete is False
    assert any(gap.startswith("parts_without_mating_contact") for gap in scope.gaps)

    cap = classify_cad_model(separated)
    assert cap.status == CapabilityStatus.ASSISTED
    assert "cannot be reduced to one part" in cap.reason


def test_step_assembly_script_keeps_every_part_contact_and_fixture(tmp_path=None):
    model = _mated_handle_model()
    scope = build_assembly_scope(model)
    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "handle.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        plan = compile_intent_to_actions(
            model_name="HandleAsm",
            part_name="MustNotBeUsedAlone",
            job_name="Job-Handle",
            geometry=IntentGeometrySpec(
                shape="step_assembly",
                step_file_path=step_path,
                assembly_scope=scope,
            ),
            material=MaterialDefinition(
                name="PA66",
                unit_system="MM_N_MPA",
                elastic=ElasticProperties(youngs_modulus=3000.0, poisson_ratio=0.35),
            ),
            mesh=IntentMeshSpec(element_type="C3D10", global_size=1.5),
        )

    script = plan.cae_script
    assert "PartFromGeometryFile" in script
    assert "name='S_HANDLE'" in script
    assert "name='S_PIN'" in script
    pin_import = next(line for line in script.splitlines() if "name='S_PIN'" in line)
    handle_import = next(line for line in script.splitlines() if "name='S_HANDLE'" in line)
    assert "bodyNum=1" in pin_import
    assert "bodyNum=2" in handle_import
    assert "Instance(name='S_HANDLE-1'" in script
    assert "Instance(name='S_PIN-1'" in script
    assert "SurfaceToSurfaceContactStd" in script
    assert "EncastreBC" in script
    assert "InstallationFixed" in script
    assert "parts['MustNotBeUsedAlone']" not in script
    assert plan.intent_summary["geometry"]["assembly_scope"]["part_count"] == 2


def test_compiler_binds_multi_solid_step_and_refuses_incomplete_scope():
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    model = _mated_handle_model()
    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "handle.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        intent = EngineeringIntent(
            id="HANDLE_ASM",
            kind="linear_static",
            description="Handle assembly with related parts",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        )
        plan = compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(
                shape="step_file",
                step_file_path=step_path,
                assembly_scope=model,
            ),
        )

    script = plan.cae_script
    assert plan.intent_summary["geometry"]["shape"] == "step_assembly"
    assert script.count("PartFromGeometryFile") == 2
    assert "SurfaceToSurfaceContactStd" in script
    assert "InstallationFixed" in script
    assert "BaseSolidExtrude" not in script

    separated = _mated_handle_model()
    far_vertices = tuple(
        CadVertex(vertex.id, (vertex.point[0], vertex.point[1], vertex.point[2] + 80.0))
        if vertex.id in {"V5", "V6", "V7", "V8"} else vertex
        for vertex in separated.vertices
    )
    separated = GeometryModel(
        model_id=separated.model_id,
        provenance=separated.provenance,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 40.0, 20.0, 130.0),
        solids=separated.solids,
        shells=separated.shells,
        faces=separated.faces,
        edges=separated.edges,
        vertices=far_vertices,
    )
    with pytest.raises(ValueError, match="cannot be reduced to one part"):
        compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(
                shape="step_file",
                step_file_path=step_path,
                assembly_scope=separated,
            ),
        )


def test_product_entry_blocks_incomplete_multi_solid_scope():
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.task import TaskStatus

    separated = _mated_handle_model()
    far_vertices = tuple(
        CadVertex(vertex.id, (vertex.point[0], vertex.point[1], vertex.point[2] + 80.0))
        if vertex.id in {"V5", "V6", "V7", "V8"} else vertex
        for vertex in separated.vertices
    )
    separated = GeometryModel(
        model_id=separated.model_id,
        provenance=separated.provenance,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 40.0, 20.0, 130.0),
        solids=separated.solids,
        shells=separated.shells,
        faces=separated.faces,
        edges=separated.edges,
        vertices=far_vertices,
    )
    intent = EngineeringIntent(
        id="HANDLE_ENTRY",
        kind="linear_static",
        description="Do not solve the handle alone",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
    )
    result = AbaqusAIAgent(executor=None).solve_requirement(
        intent,
        geometry=IntentGeometrySpec(shape="step_file", assembly_scope=separated),
        submit_job=False,
    )
    assert result.status == TaskStatus.BLOCKED
    assert result.summary_card["status"] == "ASSEMBLY_SCOPE_BLOCKED"
    assert "cannot be reduced to one part" in result.errors[0]
