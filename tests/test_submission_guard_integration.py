from unittest.mock import MagicMock
import pytest
from pathlib import Path

from abaqus_ai_agent.validation.assembly_guard import AssemblyContractViolation
from abaqus_ai_agent.execution.input_modes import solve_user_inp


MISSING_PART_INP = """
*HEADING
Degraded single part handle
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=HANDLE_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""


def test_solve_user_inp_blocks_submission_on_assembly_violation(tmp_path: Path):
    inp_file = tmp_path / "test_degraded.inp"
    inp_file.write_text(MISSING_PART_INP, encoding="utf-8")

    executor = MagicMock()
    executor.workdir = str(tmp_path)
    executor.run_input = MagicMock()
    executor.execute = MagicMock()

    multipart_scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }

    # Solver execution MUST be blocked, throwing AssemblyContractViolation
    with pytest.raises(AssemblyContractViolation) as exc_info:
        solve_user_inp(
            executor=executor,
            inp_path=inp_file,
            assembly_scope=multipart_scope,
        )

    assert "Direct INP solve blocked prior to solver invocation" in str(exc_info.value)
    assert "BASE_1" in str(exc_info.value)

    # CRITICAL: Verify that the solver was NEVER invoked!
    assert executor.run_input.call_count == 0
    assert executor.execute.call_count == 0
