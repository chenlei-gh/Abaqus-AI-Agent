"""Tests for evidence-driven adaptive solver resource configuration (P3.2)."""

import pytest

from abaqus_ai_agent.execution.solver_config import (
    SolverParameterDecision,
    calculate_adaptive_cpus,
    calculate_adaptive_memory,
    max_cpus_for_tokens,
    resolve_explicit_job_kwargs,
    resolve_job_kwargs,
    tokens_required_for_cpus,
)


def test_token_formula_adheres_to_dassault_standards():
    """Verify standard formula tokens = floor(5 * num_cpus^0.422)."""
    assert tokens_required_for_cpus(1) == 5
    assert tokens_required_for_cpus(2) == 6
    assert tokens_required_for_cpus(3) == 7
    assert tokens_required_for_cpus(4) == 8
    assert tokens_required_for_cpus(6) == 10
    assert tokens_required_for_cpus(8) == 12
    assert tokens_required_for_cpus(12) == 14
    assert tokens_required_for_cpus(16) == 16
    assert tokens_required_for_cpus(24) == 19
    assert tokens_required_for_cpus(32) == 21
    assert tokens_required_for_cpus(64) == 28


def test_token_formula_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="positive int"):
        tokens_required_for_cpus(True)
    with pytest.raises(ValueError, match="positive int"):
        tokens_required_for_cpus(0)
    with pytest.raises(ValueError, match="positive int"):
        tokens_required_for_cpus(-4)
    with pytest.raises(ValueError, match="positive int"):
        tokens_required_for_cpus(4.5)  # type: ignore


def test_max_cpus_for_tokens_inversion():
    assert max_cpus_for_tokens(0) == 0
    assert max_cpus_for_tokens(4) == 0
    assert max_cpus_for_tokens(5) == 1
    assert max_cpus_for_tokens(6) == 2
    assert max_cpus_for_tokens(7) == 3
    assert max_cpus_for_tokens(8) == 4
    # For any available tokens from 5 to 30, verify exact mathematical inversion
    for t in range(5, 30):
        c = max_cpus_for_tokens(t)
        assert tokens_required_for_cpus(c) <= t
        assert tokens_required_for_cpus(c + 1) > t


def test_adaptive_cpu_sizing_by_mesh_scale():
    # Small model (< 5,000 elements): single core to minimize IPC
    hw = {"logical_cpu_count": 16, "physical_cpu_count": 8}
    cpus, ev, reason = calculate_adaptive_cpus(host_hardware=hw, element_count=2000)
    assert cpus == 1
    assert "single-core" in reason

    # Medium model (5k ~ 50k elements): multi-core 2-4
    cpus, ev, reason = calculate_adaptive_cpus(host_hardware=hw, element_count=20000)
    assert cpus == 4
    assert "medium model" in reason

    # Large model (> 50k elements): up to 8 cores
    cpus, ev, reason = calculate_adaptive_cpus(host_hardware=hw, element_count=120000)
    assert cpus == 8
    assert "large model" in reason


def test_adaptive_cpu_constrained_by_license_tokens():
    hw = {"logical_cpu_count": 24, "physical_cpu_count": 12}
    # With 6 tokens, can only afford 2 cores despite large host and model
    cpus, ev, reason = calculate_adaptive_cpus(
        host_hardware=hw, element_count=200000, available_tokens=6
    )
    assert cpus == 2
    assert "available_tokens=6" in ev

    # With 8 tokens, can afford 4 cores
    cpus, ev, reason = calculate_adaptive_cpus(
        host_hardware=hw, element_count=200000, available_tokens=8
    )
    assert cpus == 4


def test_adaptive_cpu_preserves_host_headroom():
    # If host only has 4 logical cores, leave headroom and don't saturate
    hw = {"logical_cpu_count": 4, "physical_cpu_count": 2}
    cpus, ev, reason = calculate_adaptive_cpus(host_hardware=hw, element_count=100000)
    assert cpus <= 2


def test_adaptive_memory_allocation():
    hw = {"total_memory_bytes": 64 * 1024 * 1024 * 1024}  # 64 GB
    val, units, ev, reason = calculate_adaptive_memory(host_hardware=hw, target_percentage=75)
    assert val == 75
    assert units == "PERCENTAGE"
    assert "64.0GB" in ev
    assert "minimize disk I/O" in reason


def test_resolve_job_kwargs_adaptive_mode():
    context = {
        "host_hardware": {"logical_cpu_count": 16, "physical_cpu_count": 8, "total_memory_bytes": 32 * 1024**3},
        "solver_type": "EXPLICIT",
        "element_count": 45000,
        "available_tokens": 8,
        "large_deformation": True,
    }

    # With adaptive=True, unsupplied parameters are filled with evidence_adjusted decisions
    kwargs, decisions = resolve_job_kwargs({"adaptive": True}, context=context)
    by_name = {d.name: d for d in decisions}

    assert kwargs["numCpus"] == 4
    assert by_name["numCpus"].source == "evidence_adjusted"
    assert by_name["numCpus"].sent_to_solver is True

    # In Explicit dynamics, numDomains matches numCpus
    assert kwargs["numDomains"] == 4
    assert by_name["numDomains"].source == "evidence_adjusted"

    assert kwargs["memory"] == 75
    assert kwargs["memoryUnits"] == "PERCENTAGE"
    assert by_name["memory"].source == "evidence_adjusted"

    assert kwargs["explicitPrecision"] == "DOUBLE_PLUS_PACK"
    assert by_name["explicitPrecision"].source == "evidence_adjusted"


def test_caller_explicit_overrides_adaptive():
    context = {
        "host_hardware": {"logical_cpu_count": 16, "physical_cpu_count": 8},
        "element_count": 50000,
    }

    # Caller explicitly forces numCpus=2 and memory=50
    kwargs, decisions = resolve_job_kwargs(
        {"adaptive": True, "numCpus": 2, "memory": 50, "memoryUnits": "PERCENTAGE"},
        context=context,
    )
    by_name = {d.name: d for d in decisions}

    assert kwargs["numCpus"] == 2
    assert by_name["numCpus"].source == "explicit"
    assert by_name["numCpus"].sent_to_solver is True

    assert kwargs["memory"] == 50
    assert kwargs["memoryUnits"] == "PERCENTAGE"
    assert by_name["memory"].source == "explicit"


def test_decision_validation_contracts():
    # Valid evidence-adjusted
    d = SolverParameterDecision(
        name="numCpus",
        value=4,
        source="evidence_adjusted",
        evidence="host_cpus(physical=8)",
        reason="adaptive selection",
        sent_to_solver=True,
    )
    assert d.sent_to_solver is True

    # Empty evidence for evidence_adjusted raises
    with pytest.raises(ValueError, match="non-empty evidence"):
        SolverParameterDecision(
            name="numCpus",
            value=4,
            source="evidence_adjusted",
            evidence="none",
            reason="invalid",
            sent_to_solver=True,
        )

class _Jobs:
    def __init__(self):
        self.jobs = {}


class _RecordingExecutor:
    def __init__(self):
        self.commands = []
        self.workdir = None

    def execute(self, code, timeout=120):
        self.commands.append(code)
        if "waitForCompletion" in code or ".status" in code:
            return "COMPLETED"
        return ""

    def snapshot(self):
        return _Jobs()


def test_runner_executes_with_adaptive_job_options(tmp_path):
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    workdir = str(tmp_path / "adaptive_run")
    executor = _RecordingExecutor()
    executor.workdir = workdir

    runner = AnalysisRunner(executor)
    run = runner.run(
        model_name="AdaptiveModel",
        job_name="AdaptiveJob",
        workdir=workdir,
        require_production=False,
        job_options={"adaptive": True},
    )

    created = [c for c in executor.commands if c.startswith("mdb.Job(")]
    assert len(created) == 1
    job_cmd = created[0]
    # Check that adaptive parameters were forwarded to mdb.Job
    assert "numCpus=" in job_cmd
    assert "memory=75" in job_cmd
    assert "memoryUnits='PERCENTAGE'" in job_cmd

    # Check that metadata recorded the evidence-adjusted decisions
    decisions = {d.name: d for d in run.metadata["solver_parameter_decisions"]}
    assert decisions["numCpus"].source == "evidence_adjusted"
    assert decisions["numCpus"].sent_to_solver is True
    assert decisions["memory"].source == "evidence_adjusted"
    assert decisions["memory"].sent_to_solver is True
