"""Unit tests for Phase 3.2 parallel execution specification and experiment contracts."""

from pathlib import Path
import pytest

from abaqus_ai_agent.execution.parallel_experiment import (
    ParallelExperimentError,
    ParallelExperimentResult,
    ParallelRunSpec,
    collect_host_hardware_metadata,
)
from tools.case_07_jounce_bumper_e2e import (
    build_compress_script,
    build_seat_script,
)


# --- ParallelRunSpec tests ----------------------------------------------------


def test_spec_valid_configurations():
    """Valid CPU counts (1, 2, 4, 8) and solvers construct and preserve attributes."""
    for cpus in (1, 2, 4, 8):
        spec_std = ParallelRunSpec(
            job_name="JobStd",
            model_name="ModelStd",
            solver_type="STANDARD",
            num_cpus=cpus,
        )
        assert spec_std.num_cpus == cpus
        assert spec_std.num_domains is None
        assert spec_std.effective_domains == cpus
        assert spec_std.solver_type == "STANDARD"
        assert spec_std.precision == "SINGLE"

    # Explicit domain count
    spec_exp = ParallelRunSpec(
        job_name="JobExp",
        model_name="ModelExp",
        solver_type="explicit",
        num_cpus=4,
        num_domains=2,
        precision="DOUBLE_PLUS_PACK",
    )
    assert spec_exp.num_cpus == 4
    assert spec_exp.num_domains == 2
    assert spec_exp.effective_domains == 2
    assert spec_exp.solver_type == "EXPLICIT"
    assert spec_exp.precision == "DOUBLE_PLUS_PACK"

    # Serialization roundtrip
    d = spec_exp.to_dict()
    restored = ParallelRunSpec.from_dict(d)
    assert restored == spec_exp


@pytest.mark.parametrize("bad_cpus", [0, 3, 5, 6, 7, 16, -1, 4.0, "4", True, False])
def test_spec_rejects_invalid_num_cpus(bad_cpus):
    """num_cpus must strictly be an int in {1, 2, 4, 8}, rejecting bools and floats."""
    with pytest.raises(ParallelExperimentError):
        ParallelRunSpec(
            job_name="Job",
            model_name="Model",
            solver_type="STANDARD",
            num_cpus=bad_cpus,
        )


@pytest.mark.parametrize("bad_domains", [0, -1, -4, 2.0, "2", True, False])
def test_spec_rejects_invalid_num_domains(bad_domains):
    """num_domains must strictly be None or int >= 1."""
    with pytest.raises(ParallelExperimentError):
        ParallelRunSpec(
            job_name="Job",
            model_name="Model",
            solver_type="STANDARD",
            num_cpus=4,
            num_domains=bad_domains,
        )


@pytest.mark.parametrize("bad_solver", ["CFD", "STATIC", "", "standard_dynamic"])
def test_spec_rejects_invalid_solver_type(bad_solver):
    """solver_type must be STANDARD or EXPLICIT."""
    with pytest.raises(ParallelExperimentError):
        ParallelRunSpec(
            job_name="Job",
            model_name="Model",
            solver_type=bad_solver,
            num_cpus=4,
        )


@pytest.mark.parametrize("bad_str", ["", "   ", None])
def test_spec_rejects_empty_identifiers(bad_str):
    """job_name and model_name must be non-empty strings."""
    with pytest.raises((ParallelExperimentError, TypeError)):
        ParallelRunSpec(
            job_name=bad_str,  # type: ignore
            model_name="Model",
            solver_type="STANDARD",
            num_cpus=4,
        )
    with pytest.raises((ParallelExperimentError, TypeError)):
        ParallelRunSpec(
            job_name="Job",
            model_name=bad_str,  # type: ignore
            solver_type="STANDARD",
            num_cpus=4,
        )


def test_spec_from_dict_validation():
    """from_dict requires a dictionary and all mandatory fields."""
    with pytest.raises(ParallelExperimentError):
        ParallelRunSpec.from_dict(["not", "a", "dict"])  # type: ignore

    with pytest.raises(ParallelExperimentError, match="Missing required field"):
        ParallelRunSpec.from_dict({
            "job_name": "Job",
            "model_name": "Model",
            "solver_type": "STANDARD",
            # missing num_cpus
        })


# --- collect_host_hardware_metadata tests -------------------------------------


def test_collect_host_hardware_metadata():
    """Hardware metadata collection captures system specs without crashing."""
    meta = collect_host_hardware_metadata()
    assert isinstance(meta, dict)
    assert "system" in meta
    assert "machine" in meta
    assert "logical_cpu_count" in meta
    assert meta["logical_cpu_count"] is None or (
        isinstance(meta["logical_cpu_count"], int) and meta["logical_cpu_count"] > 0
    )


# --- ParallelExperimentResult tests -------------------------------------------


def test_result_valid_and_roundtrip():
    """Experiment result records validate and roundtrip through dict and JSON."""
    spec = ParallelRunSpec(
        job_name="C07SeatJob",
        model_name="C07Seat",
        solver_type="STANDARD",
        num_cpus=4,
    )
    result = ParallelExperimentResult(
        spec=spec,
        run_id="run_exp_001",
        repeat_index=0,
        status="completed",
        t4a_duration_s=14.85,
        t4b_solver_s=7.20,
        model_hash="sha256:abc123model",
        inp_hash="sha256:def456inp",
        evidence_paths={"log": "C07SeatJob.log", "sta": "C07SeatJob.sta"},
        notes="controlled baseline",
    )
    assert result.status == "COMPLETED"
    assert result.t4a_duration_s == 14.85
    assert result.t4b_solver_s == 7.20
    assert result.timestamp_utc != ""
    assert isinstance(result.host_hardware, dict)

    # Roundtrip via dict
    d = result.to_dict()
    restored_d = ParallelExperimentResult.from_dict(d)
    assert restored_d.run_id == result.run_id
    assert restored_d.spec == spec
    assert restored_d.t4a_duration_s == 14.85
    assert restored_d.t4b_solver_s == 7.20

    # Roundtrip via JSON
    json_str = result.to_json()
    restored_j = ParallelExperimentResult.from_json(json_str)
    assert restored_j.run_id == result.run_id
    assert restored_j.spec == spec
    assert restored_j.evidence_paths == result.evidence_paths


@pytest.mark.parametrize("bad_repeat", [-1, True, False, 1.5, "0"])
def test_result_rejects_invalid_repeat_index(bad_repeat):
    """repeat_index must strictly be a non-negative int."""
    spec = ParallelRunSpec(
        job_name="Job", model_name="M", solver_type="STANDARD", num_cpus=2
    )
    with pytest.raises(ParallelExperimentError):
        ParallelExperimentResult(
            spec=spec,
            run_id="run1",
            repeat_index=bad_repeat,
            status="COMPLETED",
        )


@pytest.mark.parametrize(
    "bad_duration",
    [-1.0, -0.001, float("nan"), float("inf"), float("-inf"), True, False, "12.0"],
)
def test_result_rejects_invalid_timing_metrics(bad_duration):
    """Timings must strictly be finite non-negative numbers or None."""
    spec = ParallelRunSpec(
        job_name="Job", model_name="M", solver_type="STANDARD", num_cpus=2
    )
    with pytest.raises(ParallelExperimentError):
        ParallelExperimentResult(
            spec=spec,
            run_id="run1",
            repeat_index=0,
            status="COMPLETED",
            t4a_duration_s=bad_duration,
        )
    with pytest.raises(ParallelExperimentError):
        ParallelExperimentResult(
            spec=spec,
            run_id="run1",
            repeat_index=0,
            status="COMPLETED",
            t4b_solver_s=bad_duration,
        )


def test_result_from_json_invalid():
    """from_json rejects unparseable text or corrupted structures."""
    with pytest.raises(ParallelExperimentError, match="Invalid JSON"):
        ParallelExperimentResult.from_json("not valid json {")

    with pytest.raises(ParallelExperimentError):
        ParallelExperimentResult.from_dict({"spec": "invalid_spec", "run_id": "r1"})


# --- Case 07 script generator integration tests -------------------------------


def test_case_07_script_generators_num_cpus_injection():
    """build_seat_script and build_compress_script generate accurate parallel calls."""
    src = Path("src")

    # 1. Default parameters: backward-compatible numCpus=4, numDomains=4
    seat_def = build_seat_script(src)
    assert "numCpus=4, numDomains=4" in seat_def

    comp_def = build_compress_script(src)
    assert "numCpus=4, numDomains=4" in comp_def

    # 2. Single-core (1 CPU, 1 Domain)
    seat_1 = build_seat_script(src, num_cpus=1)
    assert "numCpus=1, numDomains=1" in seat_1

    comp_1 = build_compress_script(src, num_cpus=1)
    assert "numCpus=1, numDomains=1" in comp_1

    # 3. 8-core (8 CPU, 8 Domains)
    seat_8 = build_seat_script(src, num_cpus=8, num_domains=8)
    assert "numCpus=8, numDomains=8" in seat_8

    comp_8 = build_compress_script(src, num_cpus=8, num_domains=8)
    assert "numCpus=8, numDomains=8" in comp_8

    # 4. Decoupled domain count (e.g. 4 CPUs, 2 Domains)
    seat_custom = build_seat_script(src, num_cpus=4, num_domains=2)
    assert "numCpus=4, numDomains=2" in seat_custom

    comp_custom = build_compress_script(src, num_cpus=4, num_domains=2)
    assert "numCpus=4, numDomains=2" in comp_custom

    # 5. Invalid parameters raise ParallelExperimentError
    with pytest.raises(ParallelExperimentError):
        build_seat_script(src, num_cpus=3)

    with pytest.raises(ParallelExperimentError):
        build_compress_script(src, num_cpus=True)  # type: ignore
