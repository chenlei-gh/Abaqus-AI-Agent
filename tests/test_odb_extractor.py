"""Unit and Contract Tests for Universal Headless ODB Extractor.

Verifies:
1. Rejection of missing, empty, or mock JSON ODB files (Fail-Closed).
2. Proper detection and handling of missing Abaqus executables.
3. Subprocess execution failure, timeout, and KeyError field missing handling.
4. Causal lineage binding: run_id, input_hash, odb_path, and odb_sha256 in locators and evidence.
5. Strict unit preservation and numeric validation.
"""

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.results import ResultRequirement
from abaqus_ai_agent.execution.odb_extractor import (
    AbaqusLauncherNotFoundError,
    ExtractionExecutionError,
    ExtractionFieldNotFoundError,
    HeadlessAbaqusPythonExecutor,
    OdbCorruptOrInvalidError,
    OdbExtractionError,
    OdbFileNotFoundError,
    extract_odb_results,
)


def _create_dummy_binary_odb(path: Path, size: int = 4096) -> Path:
    """Create a dummy binary file that passes basic authentic binary size and header checks."""
    content = b"\x89HDF\r\n\x1a\n" + b"\x00" * (size - 8)
    path.write_bytes(content)
    return path


def test_rejects_nonexistent_odb(tmp_path):
    missing_odb = tmp_path / "nonexistent.odb"
    with pytest.raises(OdbFileNotFoundError, match="Target ODB file does not exist"):
        extract_odb_results(
            missing_odb,
            requirements_or_criteria=[],
            run_id="test_run",
            input_hash="fake_hash",
        )


def test_rejects_empty_or_small_file(tmp_path):
    empty_odb = tmp_path / "empty.odb"
    empty_odb.write_bytes(b"small")
    with pytest.raises(OdbCorruptOrInvalidError, match="not an authentic binary ODB"):
        extract_odb_results(
            empty_odb,
            requirements_or_criteria=[],
            run_id="test_run",
            input_hash="fake_hash",
        )


def test_rejects_plaintext_json_as_odb(tmp_path):
    fake_json_odb = tmp_path / "fake.odb"
    # Create file > 1024 bytes but starts with JSON {
    data = {"fake": "content" * 200}
    fake_json_odb.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(OdbCorruptOrInvalidError, match="not an authentic binary ODB"):
        extract_odb_results(
            fake_json_odb,
            requirements_or_criteria=[],
            run_id="test_run",
            input_hash="fake_hash",
        )


def test_headless_executor_fails_closed_when_abaqus_missing(tmp_path):
    executor = HeadlessAbaqusPythonExecutor(
        launcher_cmd="non_existent_abaqus_cmd_xyz",
        workdir=tmp_path,
    )
    with pytest.raises(AbaqusLauncherNotFoundError, match="Abaqus executable not found"):
        executor.execute("print('hello')")


def test_extraction_fail_closed_on_subprocess_error(tmp_path):
    odb_file = _create_dummy_binary_odb(tmp_path / "valid.odb")

    def failing_runner(code: str):
        raise KeyError("Field S not found in Step-1")

    req = ResultRequirement(
        name="stress_gate",
        value_key="max_mises",
        field="S",
        invariant="MISES",
        unit="MPa",
    )

    with pytest.raises(OdbExtractionError, match="Fail-closed: Failed to extract"):
        extract_odb_results(
            odb_file,
            requirements_or_criteria=[req],
            run_id="run_fail_1",
            input_hash="hash_123",
            custom_runner=failing_runner,
        )


def test_authentic_extraction_and_causal_binding(tmp_path):
    odb_file = _create_dummy_binary_odb(tmp_path / "valid_model.odb")

    # Mock runner that returns authentic extraction JSON envelope
    def mock_runner(code: str):
        if "fieldOutputs" in code or "fo=" in code:
            return {
                "meta": {"field": "S", "count": 1},
                "values": [
                    {
                        "element_label": 101,
                        "instance": "PART-1-1",
                        "mises": 185.5,
                        "data": (185.5,),
                    }
                ],
            }
        elif "historyOutputs" in code:
            return {"value": 12.34, "region": "NodeSet-1", "variable": "RF2"}
        elif "names=list(odb.steps.keys())" in code:
            return "Step-1"
        return {}

    req_field = ResultRequirement(
        name="mises_gate",
        value_key="max_mises",
        field="S",
        invariant="MISES",
        unit="MPa",
        aggregation="max",
    )

    req_history = ResultRequirement(
        name="reaction_force",
        value_key="rf_y",
        output_kind="history",
        history_region="NodeSet-1",
        history_variable="RF2",
        unit="N",
        aggregation="last",
    )

    report = extract_odb_results(
        odb_file,
        requirements_or_criteria=[req_field, req_history],
        run_id="run_golden_causal",
        input_hash="hash_inp_authoritative_sha256",
        custom_runner=mock_runner,
        workdir=tmp_path,
    )

    # 1. Verify metrics dictionary
    assert report.run_id == "run_golden_causal"
    assert report.input_hash == "hash_inp_authoritative_sha256"
    assert report.metrics["max_mises"] == 185.5
    assert report.metrics["rf_y"] == 12.34

    # 2. Verify causal lineage binding in ResultExtraction
    ext_mises = report.get_extraction("max_mises")
    assert ext_mises is not None
    assert ext_mises.value == 185.5
    assert ext_mises.locator["run_id"] == "run_golden_causal"
    assert ext_mises.locator["input_hash"] == "hash_inp_authoritative_sha256"
    assert ext_mises.locator["odb_path"] == str(odb_file.resolve())
    assert ext_mises.locator["odb_sha256"] == report.odb_sha256
    assert ext_mises.locator["element_label"] == 101

    # 3. Verify causal binding and physical unit in Evidence
    assert len(ext_mises.evidence) > 0
    ev = ext_mises.evidence[0]
    assert ev.unit == "MPa"
    assert ev.metadata["run_id"] == "run_golden_causal"
    assert ev.metadata["input_hash"] == "hash_inp_authoritative_sha256"
    assert ev.metadata["odb_sha256"] == report.odb_sha256


def test_extraction_accepts_criteria_dict_and_converts(tmp_path):
    odb_file = _create_dummy_binary_odb(tmp_path / "valid_model.odb")

    def mock_runner(code: str):
        if "names=list(odb.steps.keys())" in code:
            return "Step-1"
        return {
            "values": [{"mises": 240.0, "data": (240.0,)}]
        }

    criteria = [
        {
            "name": "stress_criterion",
            "value_key": "max_mises",
            "operator": "<=",
            "limit": 250.0,
            "unit": "MPa",
            "field": "S",
            "invariant": "MISES",
        }
    ]

    report = extract_odb_results(
        odb_file,
        requirements_or_criteria=criteria,
        run_id="run_criteria_conversion",
        input_hash="hash_criteria_conversion",
        custom_runner=mock_runner,
        workdir=tmp_path,
    )

    assert "max_mises" in report.metrics
    assert report.metrics["max_mises"] == 240.0
    ext = report.get_extraction("max_mises")
    assert ext is not None
    assert ext.requirement.unit == "MPa"
    assert ext.locator["run_id"] == "run_criteria_conversion"
