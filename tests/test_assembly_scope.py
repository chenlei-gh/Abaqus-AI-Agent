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
    IntentLoadSpec,
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
            mesh=IntentMeshSpec(element_type="C3D10", global_size=1.5, primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED'),
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
            mesh=IntentMeshSpec(
                global_size=1.5,
                primary_wall_thickness=1000.0,
                primary_wall_thickness_source="MEASURED",
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
            mesh=IntentMeshSpec(
                global_size=1.5,
                primary_wall_thickness=1000.0,
                primary_wall_thickness_source="MEASURED",
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
        mesh_requirements={
            "global_size": 1.5,
            "primary_wall_thickness": 1000.0,
            "primary_wall_thickness_source": "MEASURED",
        },
    )
    result = AbaqusAIAgent(executor=None).solve_requirement(
        intent,
        geometry=IntentGeometrySpec(shape="step_file", assembly_scope=separated),
        mesh=IntentMeshSpec(
            global_size=1.5,
            primary_wall_thickness=1000.0,
            primary_wall_thickness_source="MEASURED",
        ),
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


def test_explicit_fixture_face_reaches_the_product_entry_through_intent_metadata():
    """A named fixture face must survive the intent-to-scope path, not only the direct call.

    build_assembly_scope has accepted fixture_face_id for a while, but neither
    compile_engineering_intent nor solve_requirement ever passed one, so any
    model without a semantic face name could only fail closed.
    """
    from dataclasses import replace as _dc_replace

    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    model = _symmetrical_unlabelled_model()

    intent = EngineeringIntent(
        id="FIXTURE_ENTRY",
        kind="linear_static",
        description="Analyze both blocks",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        metadata={
            "assembly_screen": screen_assembly_requirement(
                model, {"include_solid_ids": ["SOLID_ALPHA", "SOLID_BETA"]},
            ),
            "assembly_fixture_face_id": "F_p1_1",
        },
    )

    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "blocks.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        plan = compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(shape="step_file", step_file_path=step_path, assembly_scope=model),
            mesh=IntentMeshSpec(
                global_size=1.5,
                primary_wall_thickness=1000.0,
                primary_wall_thickness_source="MEASURED",
            ),
        )

    script = plan.cae_script
    assert "EncastreBC" in script
    assert plan.intent_summary["geometry"]["assembly_scope"]["fixture_record"]["face_id"] == "F_p1_1"


def test_explicit_body_index_maps_imported_body_numbers_and_refuses_bad_mappings():
    """bodyNum is user-supplied; an unusable mapping must fail instead of guessing."""
    from abaqus_ai_agent.planning.compiler import _apply_explicit_body_index

    model = _mated_handle_model()
    stripped = GeometryModel(
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

    bound = _apply_explicit_body_index(stripped, {"S_HANDLE": 2, "S_PIN": 1})
    assert {solid.id: solid.step_body_index for solid in bound.solids} == {"S_HANDLE": 2, "S_PIN": 1}
    scope = build_assembly_scope(
        bound,
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    assert not any(gap.startswith("step_body_index_missing") for gap in scope.gaps)

    with pytest.raises(ValueError, match="does not contain"):
        _apply_explicit_body_index(stripped, {"S_MISSING": 1})

    with pytest.raises(ValueError, match="both"):
        _apply_explicit_body_index(stripped, {"S_HANDLE": 1, "S_PIN": 1})

    with pytest.raises(ValueError, match="1-based"):
        _apply_explicit_body_index(stripped, {"S_HANDLE": 0})

    with pytest.raises(ValueError, match="must map solid id"):
        _apply_explicit_body_index(stripped, [1, 2])


def test_unmapped_body_index_still_refuses_to_compile_a_step_assembly():
    """Without an explicit mapping the compiler must keep refusing, not infer order."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    model = _mated_handle_model()
    stripped = GeometryModel(
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
    intent = EngineeringIntent(
        id="NO_BODY_INDEX",
        kind="linear_static",
        description="Analyze the handle and pin",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        metadata={
            "assembly_screen": screen_assembly_requirement(
                stripped, {"include_solid_ids": ["S_HANDLE", "S_PIN"]},
            ),
        },
    )
    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "handle.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        with pytest.raises(ValueError, match="cannot be solved until the analysis requirement"):
            compile_engineering_intent(
                intent,
                geometry=IntentGeometrySpec(shape="step_file", step_file_path=step_path, assembly_scope=stripped),
                mesh=IntentMeshSpec(
                    global_size=1.5,
                    primary_wall_thickness=1000.0,
                    primary_wall_thickness_source="MEASURED",
                ),
            )


def _assembly_plan_with_load(scope, model, load_region, grounded, *, mesh_wall=1000.0):
    """Compile a mated two-part assembly whose load names one face."""
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "handle.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        return compile_intent_to_actions(
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
            loads=(
                IntentLoadSpec(
                    name="PressTop",
                    load_type="pressure",
                    region=load_region,
                    magnitude=2.5,
                ),
            ),
            grounded_regions=grounded,
            mesh=IntentMeshSpec(
                element_type="C3D10",
                global_size=1.5,
                primary_wall_thickness=mesh_wall,
                primary_wall_thickness_source="MEASURED",
            ),
        )


def test_load_binds_to_the_instance_that_owns_its_face():
    """A load must land on the part that owns the face, not on part one.

    Both parts become their own instance, so reusing the first part's instance
    name silently applies the pressure to the wrong body.
    """
    model = _mated_handle_model()
    scope = build_assembly_scope(
        model,
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    # Parts are ordered by bodyNum: S_PIN is part one, S_HANDLE is part two.
    assert [part.solid_id for part in scope.parts] == ["S_PIN", "S_HANDLE"]

    grounded = {
        "F_base_top": {
            "anchor_points": [(20.0, 10.0, 30.0)],
            "anchor_point": (20.0, 10.0, 30.0),
            "entity_type": "face",
            "entity_ids": ["F_base_top"],
            "status": "RESOLVED",
            "confidence": 1.0,
        },
    }
    plan = _assembly_plan_with_load(scope, model, "F_base_top", grounded)
    script = plan.cae_script

    assert "a.instances['S_HANDLE-1'].faces" in script
    load_action = next(
        block for block in script.split("# Action:") if "PressTop" in block and "findAt" in block
    )
    assert "S_HANDLE-1" in load_action
    assert "S_PIN-1" not in load_action


def test_load_without_entity_ids_is_refused_in_a_multi_part_assembly():
    """A bare point cannot identify its owner, so it must not fall back to part one."""
    model = _mated_handle_model()
    scope = build_assembly_scope(
        model,
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    grounded = {
        "F_base_top": {
            "anchor_points": [(20.0, 10.0, 30.0)],
            "anchor_point": (20.0, 10.0, 30.0),
            "entity_type": "face",
            "status": "RESOLVED",
            "confidence": 1.0,
        },
    }
    with pytest.raises(ValueError, match="does not name a CAD entity"):
        _assembly_plan_with_load(scope, model, "F_base_top", grounded)


def _symmetrical_unlabelled_model():
    """Two mated blocks with no semantic face or part names."""
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
        CadFace("F_p1_1", surface_type="PLANE", edge_ids=("E_base_bot",), normal=(0.0, 0.0, -1.0), is_planar=True, area=800.0),
        CadFace("F_p1_2", surface_type="PLANE", edge_ids=("E_base_top",), normal=(0.0, 0.0, 1.0), is_planar=True, area=800.0),
        CadFace("F_p2_1", surface_type="PLANE", edge_ids=("E_pin_bot",), normal=(0.0, 0.0, -1.0), is_planar=True, area=280.0),
        CadFace("F_p2_2", surface_type="PLANE", edge_ids=("E_pin_top",), normal=(0.0, 0.0, 1.0), is_planar=True, area=280.0),
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
    return _model(solids, shells, faces, edges, vertices, bbox)


def test_opposed_faces_without_projected_overlap_are_not_a_contact_pair():
    """Parallel opposed faces are not touching just because they are close.

    Two faces that only share a rim project to zero overlap. Pairing them would
    invent a contact and a friction law where the parts merely pass each other.
    """
    vertices = (
        CadVertex("V1", (0.0, 0.0, 30.0)),
        CadVertex("V2", (40.0, 20.0, 30.0)),
        CadVertex("V3", (0.0, 0.0, 30.4)),
        CadVertex("V4", (40.0, 20.0, 30.4)),
        CadVertex("V5", (80.0, 0.0, 30.2)),
        CadVertex("V6", (120.0, 20.0, 30.2)),
    )
    edges = (
        CadEdge("E_base_top", start_vertex_id="V1", end_vertex_id="V2"),
        CadEdge("E_pin_bot", start_vertex_id="V3", end_vertex_id="V4"),
        CadEdge("E_far_bot", start_vertex_id="V5", end_vertex_id="V6"),
    )
    faces = (
        CadFace("F_base_top", surface_type="PLANE", edge_ids=("E_base_top",), normal=(0.0, 0.0, 1.0), is_planar=True, area=800.0),
        CadFace("F_pin_bot", surface_type="PLANE", edge_ids=("E_pin_bot",), normal=(0.0, 0.0, -1.0), is_planar=True, area=800.0),
        CadFace("F_far_bot", surface_type="PLANE", edge_ids=("E_far_bot",), normal=(0.0, 0.0, -1.0), is_planar=True, area=800.0),
    )
    shells = (
        CadShell("SH_base", face_ids=("F_base_top",), is_closed=True),
        CadShell("SH_pin", face_ids=("F_pin_bot",), is_closed=True),
        CadShell("SH_far", face_ids=("F_far_bot",), is_closed=True),
    )
    solids = (
        CadSolid("S_BASE", shell_ids=("SH_base",), step_body_index=1),
        CadSolid("S_PIN", shell_ids=("SH_pin",), step_body_index=2),
        CadSolid("S_FAR", shell_ids=("SH_far",), step_body_index=3),
    )
    model = _model(
        solids, shells, faces, edges, vertices,
        CadBoundingBox(0.0, 0.0, 30.0, 120.0, 20.0, 30.4),
    )

    scope = build_assembly_scope(
        model,
        requirement={"include_solid_ids": ["S_BASE", "S_PIN", "S_FAR"]},
    )

    paired = {frozenset((c.master_part, c.slave_part)) for c in scope.contacts}
    # 0.4 mm apart, overlapping in-plane: a real mating pair.
    assert frozenset(("S_BASE", "S_PIN")) in paired
    # 0.2 mm apart with the same opposed normals, but the faces never face
    # each other. Proximity alone must not invent this contact.
    assert frozenset(("S_BASE", "S_FAR")) not in paired


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
    assert pending.summary_card["passed"] is False
    assert pending.summary_card["screen_source"] == "requirement"
    assert "unclassified" in pending.summary_card["pending_roles"]
    assert "identity_missing" not in pending.summary_card["pending_roles"]
    assert pending.status != TaskStatus.COMPLETED


def test_live_routing_failure_stays_unresolved_and_does_not_solve(monkeypatch):
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.typesafe_intent import JevApiError

    class _DeadRouter:
        mode = "live"

        def route(self, requirement, context=None):
            raise JevApiError("provider timed out")

        def screen_parts(self, requirement, solids):
            raise AssertionError("screening must not run after routing failed")

    monkeypatch.setattr(
        "abaqus_ai_agent.typesafe_intent.JevIntentRouter",
        lambda *args, **kwargs: _DeadRouter(),
    )
    agent = AbaqusAIAgent(executor=None)
    result = agent.solve_requirement(
        "Analyze the handle",
        jev_mode="live",
        submit_job=False,
    )

    assert result.status == TaskStatus.NEEDS_CLARIFICATION
    assert result.is_completed is False
    assert result.summary_card["status"] == "INTENT_ROUTING_UNRESOLVED"
    assert result.summary_card["passed"] is False
    assert result.summary_card["jev_required"] is False
    assert "provider timed out" in result.summary_card["routing_error"]
    assert "provider timed out" in result.errors[0]


def test_validated_intent_does_not_call_jev(monkeypatch):
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.intent import EngineeringIntent

    def _forbidden(*args, **kwargs):
        raise AssertionError("a validated EngineeringIntent must not call JEV")

    monkeypatch.setattr("abaqus_ai_agent.typesafe_intent.JevIntentRouter", _forbidden)
    intent = EngineeringIntent(
        id="already-validated",
        kind="linear_static",
        description="validated cantilever",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        boundary_conditions=(),
        loads=(),
    )
    result = AbaqusAIAgent(executor=None).solve_requirement(intent, submit_job=False)

    assert result.summary_card.get("status") != "INTENT_ROUTING_UNRESOLVED"


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
    assert result.summary_card["passed"] is False
    assert result.summary_card["screen_source"] == "screening_error"
    assert result.summary_card["pending_roles"] == ["screening_failed"]
    assert result.summary_card["screening_errors"] == ["ExternalIntentApiError: provider timed out"]
    assert result.errors == ("ExternalIntentApiError: provider timed out",)
    assert "provider timed out" in result.clarification_prompt
    assert result.metadata["assembly_screen"]["source"] == "screening_error"
    assert result.status != TaskStatus.COMPLETED


def test_numbered_solids_in_solve_requirement_produce_identity_missing_contract():
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.task import TaskStatus

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
    agent = AbaqusAIAgent(executor=None)
    result = agent.solve_requirement(
        "Analyze the handle and its pin",
        geometry=IntentGeometrySpec(shape="step_file", assembly_scope=unlabeled),
        submit_job=False,
        context={
            "dimensions": {"length": 100.0, "unit": "mm"},
            "material": {"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
            "boundary_conditions": [{"type": "encastre", "region": "Base"}],
            "loads": [{"type": "concentrated_force", "magnitude": 100.0, "region": "Handle"}],
        },
    )

    # Contract verification: identity_missing is never COMPLETED or pass
    assert result.status == TaskStatus.NEEDS_CLARIFICATION
    assert result.is_completed is False
    assert result.summary_card["status"] == "ASSEMBLY_SCREEN_PENDING"
    assert result.summary_card["passed"] is False
    assert result.summary_card["screen_source"] == "requirement"
    assert "identity_missing" in result.summary_card["pending_roles"]
    assert result.summary_card["retained"] == []
    assert set(result.summary_card["pending"]) == {"S_HANDLE", "S_PIN", "S_SCREW"}
    assert result.run is None
    assert result.acceptance is None


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


def test_compiler_part_materials_pass_through():
    """Different materials assigned per solid in assembly must pass through to CAE script."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    model = _symmetrical_unlabelled_model()
    part_materials = {
        "SOLID_ALPHA": {"name": "POM", "elastic_modulus": 2800.0, "poisson_ratio": 0.35},
        "SOLID_BETA": {"name": "PC_ABS", "elastic_modulus": 2400.0, "poisson_ratio": 0.38},
    }

    intent = EngineeringIntent(
        id="MULTI_MAT",
        kind="linear_static",
        description="Multi-material assembly",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "FallbackMat", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        metadata={
            "assembly_screen": screen_assembly_requirement(
                model, {"include_solid_ids": ["SOLID_ALPHA", "SOLID_BETA"]},
            ),
            "assembly_fixture_face_id": "F_p1_1",
            "part_materials": part_materials,
        },
    )

    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "blocks.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        plan = compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(shape="step_file", step_file_path=step_path, assembly_scope=model),
            mesh=IntentMeshSpec(
                global_size=1.5,
                primary_wall_thickness=1000.0,
                primary_wall_thickness_source="MEASURED",
            ),
        )

    script = plan.cae_script
    assert "POM_Section" in script
    assert "PC_ABS_Section" in script
    assert "p_SOLID_ALPHA.SectionAssignment(region=reg_SOLID_ALPHA, sectionName='POM_Section')" in script
    assert "p_SOLID_BETA.SectionAssignment(region=reg_SOLID_BETA, sectionName='PC_ABS_Section')" in script

    assignments = {a["part"]: a["material"] for a in plan.material_assignments}
    assert assignments["SOLID_ALPHA"] == "POM"
    assert assignments["SOLID_BETA"] == "PC_ABS"


def test_compiler_assembly_friction_coefficient_pass_through():
    """Friction coefficient configured via assembly metadata must reach contact property."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    model = _symmetrical_unlabelled_model()
    intent = EngineeringIntent(
        id="FRICTION_ENTRY",
        kind="linear_static",
        description="Assembly with custom friction",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        metadata={
            "assembly_screen": screen_assembly_requirement(
                model, {"include_solid_ids": ["SOLID_ALPHA", "SOLID_BETA"]},
            ),
            "assembly_fixture_face_id": "F_p1_1",
            "assembly_friction_coefficient": 0.35,
        },
    )

    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "blocks.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        plan = compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(shape="step_file", step_file_path=step_path, assembly_scope=model),
            mesh=IntentMeshSpec(
                global_size=1.5,
                primary_wall_thickness=1000.0,
                primary_wall_thickness_source="MEASURED",
            ),
        )

    script = plan.cae_script
    assert "TangentialBehavior" in script
    assert "table=((0.35, ),)" in script


def test_compiler_whole_part_fixture():
    """Whole-part fixture must set EncastreBC over the entire instance cells/faces."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    model = _symmetrical_unlabelled_model()
    intent = EngineeringIntent(
        id="WHOLE_PART_FIX",
        kind="linear_static",
        description="Assembly with whole-part fixture",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        metadata={
            "assembly_screen": screen_assembly_requirement(
                model, {"include_solid_ids": ["SOLID_ALPHA", "SOLID_BETA"]},
            ),
            "assembly_fixture_part_id": "SOLID_ALPHA",
        },
    )

    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "blocks.stp")
        with open(step_path, "w", encoding="utf-8") as handle:
            handle.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
        plan = compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(shape="step_file", step_file_path=step_path, assembly_scope=model),
            mesh=IntentMeshSpec(
                global_size=1.5,
                primary_wall_thickness=1000.0,
                primary_wall_thickness_source="MEASURED",
            ),
        )

    script = plan.cae_script
    assert "_cells_fix = _inst_fix.cells" in script
    assert "EncastreBC" in script
    fixture_rec = plan.intent_summary["geometry"]["assembly_scope"]["fixture_record"]
    assert fixture_rec["target_scope"] == "part"
    assert fixture_rec["part_id"] == "SOLID_ALPHA"


def test_scope_dict_keeps_part_identity_and_boundary_points():
    """Serialized scope must still tell the report which instance is fixed and where."""
    scope = build_assembly_scope(
        _mated_handle_model(),
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    payload = scope.to_dict()

    assert payload["parts"] == ["S_PIN", "S_HANDLE"]
    assert [item["instance_name"] for item in payload["part_records"]] == ["S_PIN-1", "S_HANDLE-1"]
    assert payload["fixture"] == "InstallationFixed"
    assert payload["fixture_record"]["instance_name"] == "S_HANDLE-1"
    assert len(payload["fixture_record"]["point"]) == 3
    assert len(payload["fixture_record"]["normal"]) == 3
    assert len(payload["contact_records"][0]["master_point"]) == 3
    assert len(payload["contact_records"][0]["slave_point"]) == 3


def test_report_tables_show_installation_fixture_and_force_direction():
    from types import SimpleNamespace

    from abaqus_ai_agent.agent import _boundary_evidence_for_figures, _report_bcs, _report_loads
    from abaqus_ai_agent.contracts.intent import EngineeringIntent

    scope = build_assembly_scope(
        _mated_handle_model(),
        requirement={"include_solid_ids": ["S_HANDLE", "S_PIN"]},
    )
    plan = SimpleNamespace(intent_summary={
        "geometry": {"assembly_scope": scope.to_dict()},
    })
    intent = EngineeringIntent(
        id="INT-LOAD",
        kind="static",
        description="Handle load",
        loads=(
            SimpleNamespace(
                name="HandleForce",
                region="TipFace",
                load_type="concentrated_force",
                magnitude=100.0,
                direction="CF2",
                point=(10.0, 20.0, 30.0),
            ),
        ),
    )

    boundary = _boundary_evidence_for_figures(plan, intent)
    loads = _report_loads(boundary)
    bcs = _report_bcs(boundary)

    assert loads[0]["direction"] == "CF2"
    assert loads[0]["point"] == (10.0, 20.0, 30.0)
    assert "CF2" in loads[0]["description"]
    assert bcs[0]["bc_type"] == "ENCASTRE"
    assert bcs[0]["instance_name"] == "S_HANDLE-1"
    assert bcs[0]["point"] == list(scope.fixture.point)
