import os
import shutil
import tempfile
import pytest

from abaqus_ai_agent.actions import (
    connector_section,
    wire_connector,
    reference_point,
    action_to_script,
)
from abaqus_ai_agent.validation import validate_action


def test_connector_section_builder_and_validation():
    # Valid assembledType HINGE
    act1 = connector_section("Model-1", "ConnHinge", assembled_type="HINGE")
    assert validate_action(act1)
    script1 = action_to_script(act1)
    assert "ConnectorSection" in script1
    assert "assembledType=HINGE" in script1
    assert "name='ConnHinge'" in script1

    # Valid translational + rotational type JOIN + REVOLUTE
    act2 = connector_section(
        "Model-1",
        "ConnJoinRev",
        translational_type="JOIN",
        rotational_type="REVOLUTE",
    )
    assert validate_action(act2)
    script2 = action_to_script(act2)
    assert "translationalType=JOIN" in script2
    assert "rotationalType=REVOLUTE" in script2

    # Case-insensitive normalization
    act3 = connector_section("Model-1", "ConnBeam", assembled_type="beam")
    assert validate_action(act3)
    assert "assembledType=BEAM" in action_to_script(act3)


def test_connector_section_validation_failures():
    # Missing name
    with pytest.raises(ValueError, match="name is required"):
        validate_action(connector_section("Model-1", "", assembled_type="HINGE"))

    # Missing all types
    with pytest.raises(ValueError, match="requires assembled_type, translational_type, or rotational_type"):
        validate_action(connector_section("Model-1", "NoType"))

    # Invalid assembled_type
    with pytest.raises(ValueError, match="unsupported assembled_type"):
        validate_action(connector_section("Model-1", "BadAsmb", assembled_type="INVALID_TYPE"))

    # Invalid translational_type
    with pytest.raises(ValueError, match="unsupported translational_type"):
        validate_action(connector_section("Model-1", "BadTrans", translational_type="INVALID_TRANS"))

    # Invalid rotational_type
    with pytest.raises(ValueError, match="unsupported rotational_type"):
        validate_action(connector_section("Model-1", "BadRot", rotational_type="INVALID_ROT"))


def test_wire_connector_builder_and_validation():
    # Valid wire connector with reference point names
    act = wire_connector(
        "Model-1",
        "ElbowJoint",
        section_name="ConnHinge",
        point1_name="RP_Arm1",
        point2_name="RP_Arm2",
    )
    assert validate_action(act)
    script = action_to_script(act)

    assert "WirePolyLine" in script
    assert "ConnWire-ElbowJoint" in script
    assert "ConnWireSet-ElbowJoint" in script
    assert "edges.findAt" in script
    assert "SectionAssignment" in script
    assert "ConnHinge" in script


def test_wire_connector_shorthand_and_custom_names():
    # Shorthand point1 / point2
    act = wire_connector(
        "Model-1",
        "KneeJoint",
        section_name="ConnHinge",
        point1="RP-1",
        point2="RP-2",
        wire_feature_name="CustomWireFeat",
        wire_set_name="CustomWireSet",
    )
    assert validate_action(act)
    script = action_to_script(act)
    assert "CustomWireFeat" in script
    assert "CustomWireSet" in script


def test_wire_connector_validation_failures():
    # Missing name
    with pytest.raises(ValueError, match="name is required"):
        validate_action(wire_connector("Model-1", "", "ConnHinge", point1="RP-1", point2="RP-2"))

    # Missing section_name
    with pytest.raises(ValueError, match="section_name is required"):
        validate_action(wire_connector("Model-1", "J1", "", point1="RP-1", point2="RP-2"))

    # Missing point1
    with pytest.raises(ValueError, match="point1_name or point1_expression is required"):
        validate_action(wire_connector("Model-1", "J1", "ConnHinge", point2="RP-2"))

    # Missing point2
    with pytest.raises(ValueError, match="point2_name or point2_expression is required"):
        validate_action(wire_connector("Model-1", "J1", "ConnHinge", point1="RP-1"))


def test_connector_inp_generation_static_check():
    """Static check verifying writeInput() outputs CONN3D2 and Connector Section keywords."""
    abaqus_cmd = os.environ.get("ABAQUS_BAT", "C:/SIMULIA/Commands/abaqus.bat")
    if not os.path.exists(abaqus_cmd):
        pytest.skip("Abaqus executable not available on this machine")

    from abaqus_ai_agent.execution.batch import BatchExecutor

    actions = [
        reference_point("ConnModel", "RP_A", (0.0, 0.0, 0.0)),
        reference_point("ConnModel", "RP_B", (0.0, -100.0, 0.0)),
        connector_section("ConnModel", "HingeSec", assembled_type="HINGE"),
        wire_connector("ConnModel", "JointAB", "HingeSec", point1_name="RP_A", point2_name="RP_B"),
    ]

    temp_dir = tempfile.mkdtemp(prefix="abaqus_conn_check_")
    try:
        executor = BatchExecutor(launcher=abaqus_cmd, workdir=temp_dir)
        py_lines = [
            "from abaqus import mdb",
            "from abaqusConstants import *",
            "m = mdb.Model(name='ConnModel')",
            "a = m.rootAssembly",
            "a.DatumCsysByDefault(CARTESIAN)",
        ]
        for act in actions:
            py_lines.append(action_to_script(act))
        py_lines.append("job = mdb.Job(name='ConnCheckJob', model='ConnModel', type=ANALYSIS)")
        py_lines.append("job.writeInput(consistencyChecking=OFF)")
        py_lines.append("print('CONN_CHECK_INP_WRITTEN')")

        script_file = os.path.join(temp_dir, "run_check.py")
        with open(script_file, "w") as f:
            f.write("\n".join(py_lines) + "\n")

        res = executor.run_nogui(script_file)
        assert res.return_code == 0, f"Execution failed (rc={res.return_code}): {res.stderr}\n{res.stdout}"

        inp_path = os.path.join(temp_dir, "ConnCheckJob.inp")
        assert os.path.exists(inp_path), f"INP file not found at {inp_path}"

        with open(inp_path, "r") as f:
            inp_text = f.read()

        # Check essential keywords generated by Abaqus
        assert "*Element, type=CONN3D2" in inp_text
        assert "*Connector Section, elset=ConnWireSet-JointAB" in inp_text
        assert "Hinge" in inp_text
        assert "*Elset, elset=ConnWireSet-JointAB" in inp_text

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
