"""P0.3 Material Validity and Stress Acceptance Gate Test Suite.

Verifies the 5 specific stress & material engineering scenarios:
1. Stress check required, but no valid stress extracted -> blocks delivery.
2. Yield check required, but yield strength missing or unverified -> blocks delivery.
3. Purely elastic model stress exceeds verified yield strength -> RESULT_INVALID.
4. Non-stress check task without yield strength data -> does not block delivery alone.
5. Check required, but material mapping to critical regions incomplete -> blocks delivery.

Also tests anti-masking and propagation through evaluate_production_acceptance.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from abaqus_ai_agent.acceptance import (
    evaluate_result_acceptance,
    evaluate_production_acceptance,
    build_elastic_validity,
    AcceptanceResult,
)
from abaqus_ai_agent.execution.jobs import JobStatus, JobState
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2, compute_file_sha256
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance


def _create_mock_run_with_manifest(tmp_path: Path, run_id: str = "run_p03_mock"):
    roles = ("inp", "odb", "msg", "dat", "sta", "log")
    fnames = []
    for r in roles:
        fn = f"Job_{run_id}.{r}"
        p = tmp_path / fn
        if r == "odb":
            p.write_bytes(b"\x7fABAQUS_BINARY_ODB_HEADER\x00\x01\x02\x03\x04" * 64)
        else:
            p.write_text(f"Content for {fn}\n", encoding="utf-8")
        fnames.append(fn)

    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="case_p03",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
    )
    inp_hash = compute_file_sha256(tmp_path / f"Job_{run_id}.inp")
    prov = AnalysisProvenance(
        run_id=run_id,
        model_name="TestModel",
        job_name=f"Job_{run_id}",
        input_hash=inp_hash,
    )
    run = AnalysisRun(
        id=run_id,
        model_name="TestModel",
        job_name=f"Job_{run_id}",
        state=AnalysisRunState.COMPLETED,
        provenance=prov,
        job_status=JobStatus(name=f"Job_{run_id}", state=JobState.COMPLETED),
        odb_path=str(tmp_path / f"Job_{run_id}.odb"),
    )
    return run, manifest, inp_hash


def test_scenario_1_stress_check_missing_stress_blocks_delivery():
    """Scenario 1: Stress evaluation requested, but no valid stress extracted -> blocks delivery."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"displacement": 1.25},
        criteria=[{"name": "mises_limit", "value_key": "max_mises", "limit": 250.0, "operator": "<="}],
        required_metrics=["max_mises"],
        physics_domain="structural_static",
    )
    assert res.deliverable is False
    assert res.passed is False
    assert res.acceptance_status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert any("stress_check:no_valid_stress_extracted" in f for f in res.failures)
    assert res.gates.get("required_results") == "BLOCKED"


def test_scenario_2_yield_check_missing_yield_blocks_delivery():
    """Scenario 2: Yield verification requested, but yield strength missing or unverified -> blocks delivery."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": 180.0},
        criteria=[{"name": "yield_margin", "value_key": "yield_strength", "limit": 200.0, "operator": ">="}],
        explicit_requires_yield=True,
        elastic_validity={"yield_strength": None, "max_stress": 180.0, "is_purely_elastic": True},
    )
    assert res.deliverable is False
    assert res.passed is False
    assert res.acceptance_status == "BLOCKED"
    assert res.result_validity == "INCOMPLETE"
    assert any("yield_check:yield_strength_missing_or_unverified" in f for f in res.failures)
    assert res.gates.get("required_results") == "BLOCKED"


def test_scenario_3_purely_elastic_exceeds_yield_invalidates_result():
    """Scenario 3: Purely elastic model stress exceeds verified yield strength -> RESULT_INVALID."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": 320.0, "yield_strength": 250.0},
        criteria=[{"name": "stress_limit", "value_key": "max_mises", "limit": 400.0, "operator": "<="}],
        elastic_validity={
            "is_purely_elastic": True,
            "yield_strength": 250.0,
            "max_stress": 320.0,
        },
    )
    assert res.deliverable is False
    assert res.passed is False
    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "RESULT_INVALID"
    assert any("elastic_range_exceeded" in f for f in res.failures)


def test_scenario_4_non_stress_task_missing_yield_does_not_block_delivery():
    """Scenario 4: Non-stress check task without yield strength data -> does not block delivery alone."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_displacement": 1.5},
        criteria=[{"name": "disp_limit", "value_key": "max_displacement", "limit": 2.0, "operator": "<="}],
        required_metrics=["max_displacement"],
        physics_domain=None,
        explicit_requires_stress=False,
        explicit_requires_yield=False,
        elastic_validity=None,
    )
    assert res.deliverable is True
    assert res.passed is True
    assert res.acceptance_status == "PASS"
    assert res.result_validity == "VALID"
    assert len(res.failures) == 0


def test_scenario_5_incomplete_material_mapping_blocks_delivery():
    """Scenario 5: Check required, but material mapping to critical regions incomplete -> blocks delivery."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": 150.0, "yield_strength": 250.0},
        criteria=[{"name": "stress_limit", "value_key": "max_mises", "limit": 200.0, "operator": "<="}],
        explicit_material_mapping_complete=False,
        explicit_missing_regions=["Handle_Base", "Electroplate_Layer"],
    )
    assert res.deliverable is False
    assert res.passed is False
    assert res.acceptance_status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert any("material_mapping:incomplete_assignment_to_critical_regions" in f for f in res.failures)
    assert any("Handle_Base" in f for f in res.failures)
    assert res.gates.get("required_results") == "BLOCKED"


def test_p03_anti_masking_in_production_acceptance(tmp_path: Path):
    """Verify that failure state cannot be masked or bypassed in evaluate_production_acceptance."""
    run, manifest, inp_hash = _create_mock_run_with_manifest(tmp_path)
    mock_extraction = {
        "value_key": "max_mises",
        "value": 350.0,
        "unit": "MPa",
        "locator": {"source": "odb"},
    }

    # Case: purely elastic exceeds yield (Scenario 3) in production pipeline
    res = evaluate_production_acceptance(
        analysis_run=run,
        values={"max_mises": 350.0, "yield_strength": 250.0},
        criteria=[{"name": "stress_limit", "value_key": "max_mises", "limit": 400.0, "operator": "<=", "unit": "MPa"}],
        evidence_manifest=manifest,
        base_dir=tmp_path,
        result_extractions=[mock_extraction],
        elastic_validity={
            "is_purely_elastic": True,
            "yield_strength": 250.0,
            "max_stress": 350.0,
        },
    )
    assert res.deliverable is False
    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "RESULT_INVALID"


@pytest.mark.parametrize(
    "invalid_stress",
    ["not_a_number", "250.0 MPa", float("nan"), float("inf"), float("-inf"), True, False, None, [100.0]],
)
def test_non_numeric_stress_fails_closed_without_exceptions(invalid_stress):
    """Verify that non-numeric or non-finite stress inputs do not crash and fail-closed."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": invalid_stress},
        criteria=[{"name": "mises_limit", "value_key": "max_mises", "limit": 250.0, "operator": "<="}],
        required_metrics=["max_mises"],
        physics_domain="structural_static",
    )
    assert res.deliverable is False
    assert res.passed is False
    assert res.acceptance_status in ("BLOCKED", "RESULT_INVALID")
    assert any("stress_check:no_valid_stress_extracted" in f for f in res.failures)


@pytest.mark.parametrize(
    "invalid_yield",
    ["unknown_yield", float("nan"), float("inf"), None, True, {}],
)
def test_non_numeric_yield_strength_fails_closed_without_exceptions(invalid_yield):
    """Verify that non-numeric or non-finite yield strength inputs do not crash and fail-closed."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": 180.0},
        criteria=[{"name": "yield_margin", "value_key": "yield_strength", "limit": 200.0, "operator": ">="}],
        explicit_requires_yield=True,
        elastic_validity={"yield_strength": invalid_yield, "max_stress": 180.0, "is_purely_elastic": True},
    )
    assert res.deliverable is False
    assert res.passed is False
    assert res.acceptance_status == "BLOCKED"
    assert any("yield_check:yield_strength_missing_or_unverified" in f for f in res.failures)

