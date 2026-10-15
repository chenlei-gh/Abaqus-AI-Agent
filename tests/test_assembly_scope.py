"""Assembly scope screens by requirement, then grounds retained contact and fixture."""

import os
import tempfile

import pytest

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.geometry.assembly_scope import build_assembly_scope, screen_assembly_requirement
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
        CadSolid("S_HANDLE", shell_ids=("SH_base",), step_body_index=2, source_name="handle"),
        CadSolid("S_PIN", shell_ids=("SH_pin",), step_body_index=1, source_name="pin"),
    )
    bbox = CadBoundingBox(0.0, 0.0, 0.0, 40.0, 20.0, 50.0)
    return _model(solids, shells, faces, edges, vertices, bbox)


def test_related_parts_receive_contact_and_installation_fixture():
    scope = build_assembly_scope(
        _mated_handle_model(),
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )

    assert [part.solid_id for part in scope.parts] == ["S_PIN", "S_HANDLE"]
    assert [part.step_body_index for part in scope.parts] == [1, 2]
    assert scope.is_complete is True
    assert len(scope.contacts) == 1
    assert {scope.contacts[0].master_part, scope.contacts[0].slave_part} == {"S_HANDLE", "S_PIN"}
    assert scope.fixture is not None
    assert scope.fixture.set_name == "InstallationFixed"
    assert scope.fixture.part_id == "S_HANDLE"
    assert scope.fixture.face_id == "F_base_bot"
    assert scope.gaps == ()

    cap = classify_cad_model(_mated_handle_model())
    assert cap.status == CapabilityStatus.ASSISTED
    assert cap.action_type == "assembly_scope"
    assert "No analysis requirement" in cap.reason


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

    scope = build_assembly_scope(
        separated,
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    assert scope.part_count == 2
    assert scope.contacts == ()
    assert scope.is_complete is False
    assert any(gap.startswith("parts_without_mating_contact") for gap in scope.gaps)

    unmapped = GeometryModel(
        model_id=model.model_id,
        provenance=model.provenance,
        bounding_box=model.bounding_box,
        solids=tuple(
            CadSolid(solid.id, shell_ids=solid.shell_ids, step_body_index=None)
            for solid in model.solids
        ),
        shells=model.shells,
        faces=model.faces,
        edges=model.edges,
        vertices=model.vertices,
    )
    unmapped_scope = build_assembly_scope(
        unmapped,
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    assert unmapped_scope.is_complete is False
    assert any(gap.startswith("step_body_index_missing") for gap in unmapped_scope.gaps)

    cap = classify_cad_model(separated)
    assert cap.status == CapabilityStatus.ASSISTED
    assert "No analysis requirement" in cap.reason


def test_step_assembly_script_keeps_every_part_contact_and_fixture(tmp_path=None):
    model = _mated_handle_model()
    scope = build_assembly_scope(
        model,
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
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
    assert script.count("_step_file = mdb.openStep(") == 1
    assert "import auxImportGeom" in script
    assert "if not _step_source.isascii():" in script
    assert "shutil.copy2(_step_source, _step_staged)" in script
    assert "geometryFile=_step_file" in script
    assert "geometryFile=mdb.acis" not in script
    assert "from step import *" not in script
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
            description="Analyze the handle and pin",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
            metadata={"assembly_screen": screen_assembly_requirement(
                model, {"include_solid_ids": ["S_HANDLE", "S_PIN"]},
            )},
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
    with pytest.raises(ValueError, match="cannot be solved until the analysis requirement"):
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
        description="Analyze the handle and pin",
        metadata={"assembly_screen": screen_assembly_requirement(
            separated, {"include_solid_ids": ["S_HANDLE", "S_PIN"]},
        )},
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
    assert "cannot be solved until the analysis requirement" in result.errors[0]


def test_unverified_exterior_fixture_fails_closed_without_semantics():
    # Model without any semantic tags (no 'base', 'fix', etc.)
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
        CadEdge("E1", start_vertex_id="V1", end_vertex_id="V2"),
        CadEdge("E2", start_vertex_id="V3", end_vertex_id="V4"),
        CadEdge("E3", start_vertex_id="V5", end_vertex_id="V6"),
        CadEdge("E4", start_vertex_id="V7", end_vertex_id="V8"),
    )
    # Generic names with no semantic keyword
    faces = (
        CadFace("F_p1_1", surface_type="PLANE", edge_ids=("E1",), normal=(0.0, 0.0, -1.0), is_planar=True, area=800.0),
        CadFace("F_p1_2", surface_type="PLANE", edge_ids=("E2",), normal=(0.0, 0.0, 1.0), is_planar=True, area=800.0),
        CadFace("F_p2_1", surface_type="PLANE", edge_ids=("E3",), normal=(0.0, 0.0, -1.0), is_planar=True, area=280.0),
        CadFace("F_p2_2", surface_type="PLANE", edge_ids=("E4",), normal=(0.0, 0.0, 1.0), is_planar=True, area=280.0),
    )
    shells = (
        CadShell("SH1", face_ids=("F_p1_1", "F_p1_2"), is_closed=True),
        CadShell("SH2", face_ids=("F_p2_1", "F_p2_2"), is_closed=True),
    )
    solids = (
        CadSolid("SOLID_ALPHA", shell_ids=("SH1",), step_body_index=1),
        CadSolid("SOLID_BETA", shell_ids=("SH2",), step_body_index=2),
    )
    bbox = CadBoundingBox(0.0, 0.0, 0.0, 40.0, 20.0, 50.0)
    model = _model(solids, shells, faces, edges, vertices, bbox)

    # Without verified semantic tags or explicit fixture_face_id, must fail-closed:
    scope = build_assembly_scope(
        model,
        allow_unverified_exterior_fixture=False,
        requirement={"include_solid_ids": ["SOLID_ALPHA", "SOLID_BETA"]},
    )
    assert scope.fixture is None
    assert "installation_fixture_not_grounded" in scope.gaps
    assert scope.is_complete is False

    # When explicit fixture_face_id is provided, grounds successfully:
    scope_grounded = build_assembly_scope(
        model,
        fixture_face_id="F_p1_1",
        requirement={"include_solid_ids": ["SOLID_ALPHA", "SOLID_BETA"]},
    )
    assert scope_grounded.fixture is not None
    assert scope_grounded.fixture.face_id == "F_p1_1"
    assert scope_grounded.fixture.part_id == "SOLID_ALPHA"
    assert "installation_fixture_not_grounded" not in scope_grounded.gaps
    assert scope_grounded.is_complete is True


def _three_part_product():
    model = _mated_handle_model()
    screw_vertex = CadVertex("V9", (100.0, 100.0, 0.0))
    screw_edge = CadEdge("E_screw", start_vertex_id="V9", end_vertex_id="V9")
    screw_face = CadFace(
        "F_screw", surface_type="PLANE", edge_ids=("E_screw",),
        normal=(0.0, 0.0, 1.0), is_planar=True, area=20.0,
    )
    screw_shell = CadShell("SH_screw", face_ids=("F_screw",), is_closed=True)
    screw = CadSolid("S_SCREW", shell_ids=("SH_screw",), step_body_index=3, source_name="screw")
    return GeometryModel(
        model_id=model.model_id,
        provenance=model.provenance,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 50.0),
        solids=model.solids + (screw,),
        shells=model.shells + (screw_shell,),
        faces=model.faces + (screw_face,),
        edges=model.edges + (screw_edge,),
        vertices=model.vertices + (screw_vertex,),
    )


def test_natural_language_entry_uses_jev_screen_before_solving():
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.task import TaskStatus

    model = _three_part_product()
    agent = AbaqusAIAgent(executor=None)
    pending = agent.solve_requirement(
        "Check the strength of this product",
        geometry=IntentGeometrySpec(shape="step_file", assembly_scope=model),
        submit_job=False,
        context={
            "dimensions": {"length": 100.0, "unit": "mm"},
            "material": {"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
            "boundary_conditions": [{"type": "encastre", "region": "Base"}],
            "loads": [{"type": "concentrated_force", "magnitude": 100.0, "region": "Handle"}],
        },
    )
    assert pending.status == TaskStatus.NEEDS_CLARIFICATION
    assert pending.summary_card["status"] == "ASSEMBLY_SCREEN_PENDING"


def test_live_screening_error_becomes_pending_not_a_crash(monkeypatch):
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.typesafe_intent import JevApiError

    class _BrokenRouter:
        mode = "offline"

        def route(self, requirement, context=None):
            from abaqus_ai_agent.typesafe_intent import EngineeringIntentRouter
            return EngineeringIntentRouter(mode="offline").route(requirement, context=context)

        def screen_parts(self, requirement, solids):
            raise JevApiError("provider timed out")

    monkeypatch.setattr(
        "abaqus_ai_agent.typesafe_intent.JevIntentRouter",
        lambda *args, **kwargs: _BrokenRouter(),
    )
    model = _three_part_product()
    agent = AbaqusAIAgent(executor=None)
    result = agent.solve_requirement(
        "Analyze the handle and its pin",
        geometry=IntentGeometrySpec(shape="step_file", assembly_scope=model),
        submit_job=False,
        context={
            "dimensions": {"length": 100.0, "unit": "mm"},
            "material": {"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
            "boundary_conditions": [{"type": "encastre", "region": "Base"}],
            "loads": [{"type": "concentrated_force", "magnitude": 100.0, "region": "Handle"}],
        },
    )

    assert result.status == TaskStatus.NEEDS_CLARIFICATION
    assert result.summary_card["status"] == "ASSEMBLY_SCREEN_PENDING"
    assert result.summary_card["retained"] == []


def test_requirement_screen_keeps_named_parts_and_drops_fastener():
    model = _three_part_product()
    screen = screen_assembly_requirement(model, "Analyze the handle and its pin")

    assert screen.retained_ids == ("S_HANDLE", "S_PIN")
    assert screen.excluded_ids == ("S_SCREW",)
    assert screen.pending_ids == ()

    scope = build_assembly_scope(model, screen=screen)
    assert [part.solid_id for part in scope.parts] == ["S_PIN", "S_HANDLE"]
    assert "S_SCREW" not in [part.solid_id for part in scope.parts]
    assert scope.excluded_solid_ids == ("S_SCREW",)
    assert scope.is_complete is True


def test_missing_requirement_does_not_analyze_the_whole_product():
    model = _three_part_product()
    scope = build_assembly_scope(model)

    assert scope.parts == ()
    assert "analysis_requirement_missing" in scope.gaps
    assert scope.is_complete is False


def test_ambiguous_identity_stays_pending_instead_of_full_analysis():
    model = _three_part_product()
    screen = screen_assembly_requirement(model, "Check the strength of this product")

    assert screen.excluded_ids == ("S_SCREW",)
    assert set(screen.pending_ids) == {"S_HANDLE", "S_PIN"}
    scope = build_assembly_scope(model, screen=screen)
    assert scope.parts == ()
    assert any(gap.startswith("screening_pending") for gap in scope.gaps)
    assert scope.is_complete is False


def test_jev_probability_thresholds_do_not_force_a_middle_value():
    model = _three_part_product()
    scope = build_assembly_scope(
        model,
        requirement="Analyze the handle",
        judgments={
            "S_HANDLE": {"probability": 0.95, "role": "analysis_object"},
            "S_PIN": {"probability": 0.91, "role": "load_path"},
            "S_SCREW": {"probability": 0.05, "role": "fastener"},
        },
    )
    assert [part.solid_id for part in scope.parts] == ["S_PIN", "S_HANDLE"]
    assert scope.is_complete is True

    uncertain = build_assembly_scope(
        model,
        requirement="Analyze the handle",
        judgments={
            "S_HANDLE": {"probability": 0.95},
            "S_PIN": {"probability": 0.55},
            "S_SCREW": {"probability": 0.05},
        },
    )
    assert uncertain.parts == ()
    assert any("S_PIN" in gap for gap in uncertain.gaps)
    assert uncertain.is_complete is False


def test_explicit_ids_do_not_exclude_a_connected_part():
    model = _three_part_product()
    screen = screen_assembly_requirement(
        model,
        {"include_solid_ids": ["S_HANDLE"]},
    )

    assert screen.retained_ids == ("S_HANDLE",)
    assert "S_PIN" in screen.pending_ids
    assert screen.excluded_ids == ()
    assert screen.is_resolved is False
    scope = build_assembly_scope(model, screen=screen)
    assert scope.parts == ()
    assert scope.is_complete is False


def test_numbered_solids_stay_pending_without_a_source_name():
    model = _three_part_product()
    numbered = tuple(
        CadSolid(solid.id, shell_ids=solid.shell_ids, step_body_index=solid.step_body_index)
        for solid in model.solids
    )
    unlabeled = GeometryModel(
        model_id=model.model_id,
        provenance=model.provenance,
        bounding_box=model.bounding_box,
        solids=numbered,
        shells=model.shells,
        faces=model.faces,
        edges=model.edges,
        vertices=model.vertices,
    )
    screen = screen_assembly_requirement(unlabeled, "Analyze the handle and its pin")

    assert screen.retained_ids == ()
    assert screen.excluded_ids == ()
    assert set(screen.pending_ids) == {"S_HANDLE", "S_PIN", "S_SCREW"}
    assert all("identity_missing" in item.evidence for item in screen.decisions)
    scope = build_assembly_scope(unlabeled, screen=screen)
    assert scope.parts == ()
    assert scope.is_complete is False
