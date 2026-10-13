# ===========================================================================
# Unit and Contract Tests for Controlled INP Editing (Phase P1.4 / P1.5)
# ===========================================================================
import hashlib
from pathlib import Path
import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.editing.inp_editor import (
    ControlledInpEditor,
    InpEditAuditRecord,
    InpEditOperation,
    edit_inp_file,
)
from abaqus_ai_agent.execution.input_modes import edit_and_solve_user_inp
from abaqus_ai_agent.paths import create_external_project_context


SAMPLE_INP_DECK = """*HEADING
Model: Test Cantilever Beam
** ----------------------------------------------------
** MATERIALS
** ----------------------------------------------------
*MATERIAL, NAME=STEEL
*ELASTIC
 210000.0, 0.3
*DENSITY
 7.85e-9
** ----------------------------------------------------
** STEP DEFINITION
** ----------------------------------------------------
*STEP, NAME=Step-1, NLGEOM=YES
*STATIC
 0.1, 1.0, 1e-05, 1.0
*CLOAD
 LoadNodeSet, 2, -500.0
*OUTPUT, FIELD
*ELEMENT OUTPUT
 S, E
*NODE OUTPUT
 U, RF
*END STEP
"""


class DummyInpExecutor:
    """Mock executor tracking solver invocations."""

    def __init__(self, exit_code: int = 0, produce_odb: bool = True):
        self.invocations = []
        self.workdir = None
        self.exit_code = exit_code
        self.produce_odb = produce_odb

    def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
        self.invocations.append({
            "input_path": input_path,
            "job_name": job_name,
            "timeout": timeout,
            "workdir": workdir,
        })
        target_dir = Path(workdir) if workdir else Path(input_path).parent
        name = job_name or Path(input_path).stem
        if self.produce_odb:
            odb_file = target_dir / f"{name}.odb"
            odb_file.write_bytes(b"AUTHENTIC_EDITED_SIMULATION_ODB_CONTENT")
        return {
            "returncode": self.exit_code,
            "stdout": "Solver completed",
            "stderr": "Error encountered" if self.exit_code != 0 else "",
        }


def test_inp_editor_material_modification(tmp_path):
    """Verify surgical modification of material properties without altering comments or unrelated lines."""
    src = tmp_path / "beam.inp"
    src.write_text(SAMPLE_INP_DECK, encoding="utf-8")
    orig_sha = hashlib.sha256(src.read_bytes()).hexdigest()

    dest = tmp_path / "beam_modified.inp"
    editor = ControlledInpEditor(src)
    editor.edit_material(
        material_name="STEEL",
        property_keyword="*ELASTIC",
        new_data_lines=[[205000.0, 0.28]],
    )
    audit = editor.save(dest)

    assert isinstance(audit, InpEditAuditRecord)
    assert audit.source_sha256 == orig_sha
    assert audit.target_sha256 != orig_sha
    assert audit.lines_changed > 0
    assert "- 210000.0, 0.3" in audit.diff_summary
    assert "+ 205000.0, 0.28" in audit.diff_summary

    # Ensure source file remained completely unmodified
    assert src.read_text(encoding="utf-8") == SAMPLE_INP_DECK

    # Verify destination content integrity
    dest_content = dest.read_text(encoding="utf-8")
    assert "205000.0, 0.28" in dest_content
    assert "*DENSITY\n 7.85e-9" in dest_content  # Adjacent keyword intact
    assert "** MATERIALS" in dest_content  # Comments preserved


def test_inp_editor_step_parameters_modification(tmp_path):
    """Verify modification of step incrementation parameters and strict validation."""
    src = tmp_path / "beam.inp"
    src.write_text(SAMPLE_INP_DECK, encoding="utf-8")
    dest = tmp_path / "beam_step.inp"

    editor = ControlledInpEditor(src)
    editor.edit_step_parameters(
        procedure_type="*STATIC",
        time_incrementation={
            "initial_inc": 0.05,
            "total_time": 2.0,
            "min_inc": 1e-6,
            "max_inc": 0.2,
        },
        step_name="Step-1",
    )
    audit = editor.save(dest)

    dest_content = dest.read_text(encoding="utf-8")
    assert "0.05, 2.0, 1e-06, 0.2" in dest_content

    # Negative step increment must fail closed
    with pytest.raises(ValueError, match="Invalid incrementation parameters"):
        editor.edit_step_parameters(
            procedure_type="*STATIC",
            time_incrementation={"initial_inc": -0.1, "total_time": 1.0},
        )


def test_inp_editor_load_modification(tmp_path):
    """Verify surgical modification of concentrated load magnitudes."""
    src = tmp_path / "beam.inp"
    src.write_text(SAMPLE_INP_DECK, encoding="utf-8")
    dest = tmp_path / "beam_load.inp"

    editor = ControlledInpEditor(src)
    editor.edit_load(
        set_name="LoadNodeSet",
        new_magnitude=-1250.0,
        dof=2,
        load_keyword="*CLOAD",
        step_name="Step-1",
    )
    audit = editor.save(dest)

    dest_content = dest.read_text(encoding="utf-8")
    assert "LoadNodeSet, 2, -1250.0" in dest_content

    # Target set missing must raise KeyError
    with pytest.raises(KeyError, match="Load entry for set 'NonExistentSet'"):
        editor.edit_load(
            set_name="NonExistentSet",
            new_magnitude=-100.0,
        )


def test_inp_editor_output_request_modification(tmp_path):
    """Verify augmenting element field output requests."""
    src = tmp_path / "beam.inp"
    src.write_text(SAMPLE_INP_DECK, encoding="utf-8")
    dest = tmp_path / "beam_output.inp"

    editor = ControlledInpEditor(src)
    editor.edit_output_request(
        output_keyword="*ELEMENT OUTPUT",
        requested_variables=["S", "E", "LE", "PEEQ"],
        step_name="Step-1",
    )
    audit = editor.save(dest)

    dest_content = dest.read_text(encoding="utf-8")
    assert "S, E, LE, PEEQ" in dest_content


def test_inp_editor_zero_in_place_mutation_prevented(tmp_path):
    """Strict Contract: Zero In-Place Mutation violation raises PermissionError."""
    src = tmp_path / "beam.inp"
    src.write_text(SAMPLE_INP_DECK, encoding="utf-8")

    editor = ControlledInpEditor(src)
    editor.edit_material(
        material_name="STEEL",
        property_keyword="*ELASTIC",
        new_data_lines=[[100000.0, 0.3]],
    )

    # Attempting to save directly to the source file is strictly prohibited
    with pytest.raises(PermissionError, match="Zero In-Place Mutation violation"):
        editor.save(src)


def test_inp_editor_ambiguous_target_rejected(tmp_path):
    """Fail-Closed: Ambiguous duplicate material names must be rejected."""
    corrupted_deck = SAMPLE_INP_DECK + "\n*MATERIAL, NAME=STEEL\n*ELASTIC\n 100.0, 0.1\n"
    src = tmp_path / "duplicate_mat.inp"
    src.write_text(corrupted_deck, encoding="utf-8")

    editor = ControlledInpEditor(src)
    with pytest.raises(ValueError, match="Ambiguous target"):
        editor.edit_material(
            material_name="STEEL",
            property_keyword="*ELASTIC",
            new_data_lines=[[200000.0, 0.3]],
        )


def test_inp_editor_convenience_edit_inp_file(tmp_path):
    """Verify batch specification using edit_inp_file helper."""
    src = tmp_path / "model.inp"
    src.write_text(SAMPLE_INP_DECK, encoding="utf-8")
    dest = tmp_path / "model_batch.inp"

    ops = [
        InpEditOperation(
            category="material",
            target_identifier="STEEL",
            property_keyword="*ELASTIC",
            new_values=[[190000.0, 0.29]],
        ),
        InpEditOperation(
            category="load",
            target_identifier="LoadNodeSet",
            property_keyword="*CLOAD",
            new_values={"magnitude": -750.0, "dof": 2},
            metadata={"step_name": "Step-1"},
        ),
    ]

    record = edit_inp_file(src, dest, ops)
    assert record.lines_changed >= 2
    content = dest.read_text(encoding="utf-8")
    assert "190000.0, 0.29" in content
    assert "-750.0" in content


def test_edit_and_solve_user_inp_with_project_context(tmp_path):
    """End-to-End Contract: Edit in working_dir, solve in solver_dir, verify audit record."""
    ctx = create_external_project_context(tmp_path / "ExternalAuditProject")
    src_inp = ctx.input_dir / "cantilever.inp"
    src_inp.write_text(SAMPLE_INP_DECK, encoding="utf-8")
    src_sha = hashlib.sha256(src_inp.read_bytes()).hexdigest()

    executor = DummyInpExecutor()
    agent = AbaqusAIAgent(executor=executor)

    ops = [
        {
            "category": "material",
            "target": "STEEL",
            "keyword": "*ELASTIC",
            "values": [[215000.0, 0.31]],
        }
    ]

    res = agent.edit_and_solve_user_inp(
        inp_path=src_inp,
        operations=ops,
        project_context=ctx,
        run_id="run_edit_001",
    )

    assert res["status"] == "COMPLETED"
    assert res["is_edited"] is True
    assert res["source_inp_sha256"] == src_sha
    assert res["source_inp_path"] == str(src_inp.resolve())

    # Edited file must reside within working_dir
    edited_file = Path(res["edited_inp_path"])
    assert edited_file.is_file()
    assert edited_file.parent == ctx.working_dir.resolve()

    # Solver workspace must be within solver_dir/run_edit_001
    assert Path(res["workdir"]) == (ctx.solver_dir / "run_edit_001").resolve()
    assert Path(res["odb_path"]).is_file()

    # Original input deck remains untampered
    assert src_inp.read_text(encoding="utf-8") == SAMPLE_INP_DECK


def test_edit_and_solve_user_inp_failure_handling(tmp_path):
    """P0 Contract: Solver exit code != 0 or missing ODB must report status='FAILED'."""
    src_inp = tmp_path / "fail_model.inp"
    src_inp.write_text(SAMPLE_INP_DECK, encoding="utf-8")

    # 1. Non-zero exit code
    executor_fail = DummyInpExecutor(exit_code=1)
    agent_fail = AbaqusAIAgent(executor=executor_fail)

    res_fail = agent_fail.edit_and_solve_user_inp(
        inp_path=src_inp,
        operations=[{"category": "material", "target": "STEEL", "keyword": "*ELASTIC", "values": [[200000.0, 0.3]]}],
    )
    assert res_fail["status"] == "FAILED"
    assert "exit code 1" in res_fail["error"]

    # 2. Missing ODB despite exit code 0
    executor_no_odb = DummyInpExecutor(exit_code=0, produce_odb=False)
    agent_no_odb = AbaqusAIAgent(executor=executor_no_odb)

    res_no_odb = agent_no_odb.edit_and_solve_user_inp(
        inp_path=src_inp,
        operations=[{"category": "material", "target": "STEEL", "keyword": "*ELASTIC", "values": [[200000.0, 0.3]]}],
    )
    assert res_no_odb["status"] == "FAILED"
    assert "expected ODB output was not found" in res_no_odb["error"]
