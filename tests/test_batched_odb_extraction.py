"""Unit and regression tests for single-invocation headless ODB extraction pipeline (REQ-P1-057)."""

import json
from pathlib import Path

import pytest

from abaqus_ai_agent.contracts.results import ResultRequirement
from abaqus_ai_agent.execution.odb_extractor import (
    OdbExtractionReport,
    build_batched_extraction_script,
    extract_odb_results,
    ExtractionFieldNotFoundError,
)


def _create_mock_binary_odb(path: Path) -> Path:
    """Create a dummy file with sufficient size and non-JSON header to pass authentic binary check."""
    path.write_bytes(b"\x00\x01\x02\x03" + b"X" * 2048)
    return path


def test_build_batched_extraction_script_syntax():
    """Verify generated batch script contains required inspection, requirement, and energy logic."""
    reqs = [
        ResultRequirement(
            name="MaxMises",
            value_key="max_mises",
            output_kind="field",
            field="S",
            invariant="MISES",
            aggregation="max",
            unit="MPa",
        ),
        ResultRequirement(
            name="TipDisp",
            value_key="tip_disp",
            output_kind="history",
            history_region="Node ASSEMBLY.1",
            history_variable="U2",
            aggregation="last",
            unit="mm",
        ),
    ]
    energy_spec = {
        "step": "Step-1",
        "region": "Assembly ASSEMBLY",
        "variables": ["ALLIE", "ALLKE", "ALLWK", "ETOTAL"],
    }
    script = build_batched_extraction_script(
        odb_path="dummy.odb",
        requirements=reqs,
        extract_metadata=True,
        energy_spec=energy_spec,
    )

    assert "openOdb" in script
    assert "__BATCH_ODB_PAYLOAD__" in script
    assert "payload[\"metadata\"]" in script
    assert "max_mises" in script
    assert "tip_disp" in script
    assert "ALLIE" in script


def test_batched_extraction_single_invocation(tmp_path):
    """Verify extract_odb_results executes only a single invocation when batch payload is returned."""
    odb_file = _create_mock_binary_odb(tmp_path / "test.odb")

    req = ResultRequirement(
        name="MaxStress",
        value_key="max_s",
        output_kind="field",
        field="S",
        aggregation="max",
    )

    call_count = [0]

    def mock_custom_runner(code: str):
        call_count[0] += 1
        # Return a simulated batch payload
        payload = {
            "status": "success",
            "metadata": {
                "status": "available",
                "steps": ["Step-1"],
                "instances": ["Beam-1"],
                "step_frames": {"Step-1": 1},
            },
            "requirements": {
                "max_s": {
                    "success": True,
                    "value": 150.5,
                    "locator": {"step": "Step-1", "frame": -1, "element_label": 10},
                }
            },
            "energy": {
                "status": "available",
                "step": "Step-1",
                "region": "Assembly ASSEMBLY",
                "variables": {
                    "ALLIE": [[0.0, 0.0], [1.0, 100.0]],
                    "ALLKE": [[0.0, 0.0], [1.0, 0.0]],
                    "ALLWK": [[0.0, 0.0], [1.0, 100.0]],
                    "ETOTAL": [[0.0, 0.0], [1.0, 0.0]],
                },
            },
        }
        return payload

    report = extract_odb_results(
        odb_path=odb_file,
        requirements_or_criteria=[req],
        run_id="run-batch-001",
        input_hash="hash-1234",
        workdir=tmp_path,
        custom_runner=mock_custom_runner,
        energy_spec={"step": "Step-1"},
    )

    # Key Assertion: Exactly 1 invocation!
    assert call_count[0] == 1
    assert isinstance(report, OdbExtractionReport)
    assert report.metrics["max_s"] == 150.5
    assert report.metadata["steps"] == ["Step-1"]
    assert report.energy_evidence["status"] == "available"
    assert "ALLIE" in report.energy_evidence["variables"]


def test_batched_extraction_field_missing_fails_closed(tmp_path):
    """When a required field fails extraction inside the batch payload, typed exception is raised."""
    odb_file = _create_mock_binary_odb(tmp_path / "test.odb")

    req = ResultRequirement(
        name="MissingField",
        value_key="missing_fld",
        output_kind="field",
        field="NONEXISTENT",
        aggregation="max",
    )

    def mock_custom_runner(code: str):
        return {
            "status": "success",
            "metadata": {"status": "available", "steps": ["Step-1"]},
            "requirements": {
                "missing_fld": {
                    "success": False,
                    "error": "FieldOutput not found: NONEXISTENT",
                }
            },
            "energy": None,
        }

    with pytest.raises(ExtractionFieldNotFoundError) as exc_info:
        extract_odb_results(
            odb_path=odb_file,
            requirements_or_criteria=[req],
            run_id="run-batch-002",
            input_hash="hash-1234",
            workdir=tmp_path,
            custom_runner=mock_custom_runner,
        )

    assert "NONEXISTENT" in str(exc_info.value)


def test_batched_extraction_multi_step_without_step_spec_fails_closed(tmp_path):
    """When an ODB has multiple non-initial steps and energy_spec omits 'step', extraction must fail closed with energy_step_ambiguous."""
    odb_file = _create_mock_binary_odb(tmp_path / "multi_step.odb")

    req = ResultRequirement(
        name="TipDisp",
        value_key="tip_disp",
        output_kind="frame_value",
        step="Step-1",
        frame=-1,
    )

    def mock_custom_runner(code: str):
        # Verify generated script contains the ambiguity guard
        assert "energy_step_ambiguous" in code
        return {
            "status": "success",
            "metadata": {"status": "available", "steps": ["Initial", "Step-1", "Step-2"]},
            "requirements": {
                "tip_disp": {
                    "success": True,
                    "value": 1.25,
                    "locator": {"step": "Step-1", "frame": -1},
                }
            },
            "energy": {
                "status": "unavailable",
                "reason": "energy_step_ambiguous",
                "available_steps": ["Step-1", "Step-2"],
            },
        }

    report = extract_odb_results(
        odb_path=odb_file,
        requirements_or_criteria=[req],
        run_id="run-batch-multi-ambig",
        input_hash="hash-1234",
        workdir=tmp_path,
        custom_runner=mock_custom_runner,
        energy_spec={},  # omitted step on multi-step ODB
    )

    assert report.energy_evidence is not None
    assert report.energy_evidence["status"] == "unavailable"
    assert report.energy_evidence["reason"] == "energy_step_ambiguous"
    assert report.energy_evidence["available_steps"] == ["Step-1", "Step-2"]


def test_batched_extraction_multi_step_with_declared_step_extracts_correct_step(tmp_path):
    """When an ODB has multiple steps and 'step' is explicitly declared, that exact step's energy is extracted."""
    odb_file = _create_mock_binary_odb(tmp_path / "multi_step_declared.odb")

    req = ResultRequirement(
        name="TipDisp",
        value_key="tip_disp",
        output_kind="frame_value",
        step="Step-1",
        frame=-1,
    )

    def mock_custom_runner(code: str):
        return {
            "status": "success",
            "metadata": {"status": "available", "steps": ["Initial", "Step-1", "Step-2"]},
            "requirements": {
                "tip_disp": {
                    "success": True,
                    "value": 1.25,
                    "locator": {"step": "Step-1", "frame": -1},
                }
            },
            "energy": {
                "status": "available",
                "step": "Step-2",
                "region": "Assembly ASSEMBLY",
                "variables": {
                    "ALLIE": [[0.0, 0.0], [1.0, 50.0]],
                    "ALLKE": [[0.0, 0.0], [1.0, 2.0]],
                    "ALLWK": [[0.0, 0.0], [1.0, 52.0]],
                    "ETOTAL": [[0.0, 0.0], [1.0, 0.0]],
                },
            },
        }

    report = extract_odb_results(
        odb_path=odb_file,
        requirements_or_criteria=[req],
        run_id="run-batch-multi-declared",
        input_hash="hash-1234",
        workdir=tmp_path,
        custom_runner=mock_custom_runner,
        energy_spec={"step": "Step-2"},
    )

    assert report.energy_evidence is not None
    assert report.energy_evidence["status"] == "available"
    assert report.energy_evidence["step"] == "Step-2"


def test_requirement_without_step_on_multi_step_fails_closed(tmp_path):
    """When a requirement omits 'step' and ODB has multiple steps, extraction fails closed."""
    odb_file = _create_mock_binary_odb(tmp_path / "multi_step_req.odb")

    req = ResultRequirement(
        name="AmbiguousDisp",
        value_key="ambig_disp",
        output_kind="field",
        field="U",
        aggregation="max",
        # step is omitted!
    )

    def mock_custom_runner(code: str):
        # The generated script must include the multiple non-Initial steps check
        assert "multiple non-Initial steps" in code
        return {
            "status": "success",
            "metadata": {"status": "available", "steps": ["Initial", "Step-1", "Step-2"]},
            "requirements": {
                "ambig_disp": {
                    "success": False,
                    "error": "Requirement 'AmbiguousDisp' specifies no step, but ODB contains multiple non-Initial steps: ['Step-1', 'Step-2']. Explicit step required.",
                }
            },
            "energy": None,
        }

    with pytest.raises(ExtractionFieldNotFoundError) as exc_info:
        extract_odb_results(
            odb_path=odb_file,
            requirements_or_criteria=[req],
            run_id="run-batch-req-ambig",
            input_hash="hash-1234",
            workdir=tmp_path,
            custom_runner=mock_custom_runner,
        )

    assert "AmbiguousDisp" in str(exc_info.value)
    assert "multiple non-Initial steps" in str(exc_info.value)


def test_in_process_requirement_step_binding_contract():
    """Verify _extract_single_requirement_in_process enforces explicit step binding on multi-step ODB."""
    from abaqus_ai_agent.execution.odb_extractor import _extract_single_requirement_in_process

    class MockOdb:
        def __init__(self, step_names):
            self.steps = {name: type("Step", (), {"frames": []})() for name in step_names}

    # 1. Multi-step without declared step must fail closed
    multi_odb = MockOdb(["Initial", "Step-Preload", "Step-Load"])
    req_no_step = ResultRequirement(
        name="StressReq",
        value_key="stress",
        output_kind="field",
        field="S",
    )
    with pytest.raises(ExtractionFieldNotFoundError) as exc_info:
        _extract_single_requirement_in_process(multi_odb, req_no_step)
    assert "multiple non-Initial steps" in str(exc_info.value)

    # 2. Single non-initial step without declared step safely defaults
    single_odb = MockOdb(["Initial", "Step-1"])
    # It will proceed past step resolution to frame check
    try:
        _extract_single_requirement_in_process(single_odb, req_no_step)
    except ExtractionFieldNotFoundError as exc:
        # Fails at frame count, proving it successfully bound to Step-1!
        assert "Step-1" in str(exc)
        assert "0 frames available" in str(exc)
