"""Runner-level binding for the dynamic energy balance gate.

The gate is opt-in. These tests pin that behaviour and the step binding, because
reading the wrong step or enforcing an undeclared threshold would both produce a
confident but wrong acceptance verdict.
"""

import pytest

from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

_REAL_IMPLICIT = {
    "ALLIE": [
        (0.0, 0.0), (0.00788281206041574, 1034.71032714844),
        (0.0178828127682209, 996.005187988281), (0.0199999995529652, 1013.96575927734),
    ],
    "ALLKE": [
        (0.0, 0.0), (0.00788281206041574, 1.23314929008484),
        (0.0178828127682209, 0.00682488782331347), (0.0199999995529652, 0.148330762982368),
    ],
    "ALLWK": [
        (0.0, 0.0), (0.00788281206041574, 1037.33020019531),
        (0.0178828127682209, 998.300476074219), (0.0199999995529652, 1016.50921630859),
    ],
    "ETOTAL": [
        (0.0, 0.0), (0.00788281206041574, -1.38669860363007),
        (0.0178828127682209, -2.28848218917847), (0.0199999995529652, -2.39511466026306),
    ],
}


class _Executor:
    def execute(self, code, timeout=120):
        return code


class _Intent:
    def __init__(self, metadata):
        self.metadata = metadata


class _Selection:
    def __init__(self, strategy):
        self.strategy = strategy


def _gate(monkeypatch, odb_steps, metadata, strategy="DYNAMIC_IMPLICIT",
          energy=None, extracted=None):
    import abaqus_ai_agent.execution.odb as odb_module

    def _fake_extract(_executor, _path, step, _region):
        if extracted is not None:
            extracted.append(step)
        if energy is not None:
            return energy
        return {
            "step": step,
            "region": "Assembly ASSEMBLY",
            "variables": {
                name: {"status": "available", "data": data}
                for name, data in _REAL_IMPLICIT.items()
            },
        }

    monkeypatch.setattr(odb_module, "extract_energy_evidence", _fake_extract)
    runner = AnalysisRunner(_Executor())
    return runner._evaluate_dynamic_energy_gate(
        "",
        {"steps": list(odb_steps)},
        {"history_regions": ["Assembly ASSEMBLY"]},
        "job.odb",
        _Intent(metadata),
        selection=_Selection(strategy),
    )


def test_gate_is_not_evaluated_when_the_caller_does_not_request_it(monkeypatch):
    extracted = []
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1"],
        {"dynamic_energy_threshold": 0.01}, extracted=extracted,
    )
    assert enabled is False
    assert verdict is None
    assert extracted == []


def test_opt_in_gate_passes_on_a_clean_history(monkeypatch):
    extracted = []
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1"],
        {"dynamic_energy_threshold": 0.01, "dynamic_energy_gate": True},
        extracted=extracted,
    )
    assert enabled is True
    assert extracted == ["Step-1"]
    assert verdict.status == "PASS"
    assert verdict.solver_product == "standard"
    assert verdict.threshold == 0.01


def test_opt_in_without_threshold_blocks_rather_than_defaulting(monkeypatch):
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1"], {"dynamic_energy_gate": True}
    )
    assert enabled is True
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_energy_threshold_not_configured"
    assert verdict.ratio is None


def test_multi_step_without_a_declared_step_blocks(monkeypatch):
    """The last step is not assumed to be the dynamic event of interest."""
    extracted = []
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1", "Step-2"],
        {"dynamic_energy_threshold": 0.01, "dynamic_energy_gate": True},
        extracted=extracted,
    )
    assert enabled is True
    assert extracted == []
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_step_ambiguous"


def test_declared_step_selects_that_step_not_the_last(monkeypatch):
    extracted = []
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1", "Step-2"],
        {
            "dynamic_energy_threshold": 0.01,
            "dynamic_energy_gate": True,
            "dynamic_energy_step": "Step-1",
        },
        extracted=extracted,
    )
    assert enabled is True
    assert extracted == ["Step-1"]
    assert verdict.status == "PASS"


def test_declared_step_missing_from_the_odb_blocks(monkeypatch):
    extracted = []
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1"],
        {
            "dynamic_energy_threshold": 0.01,
            "dynamic_energy_gate": True,
            "dynamic_energy_step": "Step-Event",
        },
        extracted=extracted,
    )
    assert enabled is True
    assert extracted == []
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_step_missing_in_odb"


def test_explicit_strategy_declares_the_explicit_product(monkeypatch):
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1"],
        {"dynamic_energy_threshold": 0.001, "dynamic_energy_gate": True},
        strategy="DYNAMIC_EXPLICIT",
    )
    assert enabled is True
    assert verdict.solver_product == "explicit"
    # The same history is held to the explicit caller's stricter policy.
    assert verdict.status == "FAIL"


def test_missing_etotal_evidence_blocks_even_when_other_energies_exist(monkeypatch):
    energy = {
        "step": "Step-1",
        "region": "Assembly ASSEMBLY",
        "variables": {
            "ALLIE": {"status": "available", "data": _REAL_IMPLICIT["ALLIE"]},
            "ALLKE": {"status": "available", "data": _REAL_IMPLICIT["ALLKE"]},
            "ALLWK": {"status": "available", "data": _REAL_IMPLICIT["ALLWK"]},
        },
    }
    enabled, verdict = _gate(
        monkeypatch, ["Initial", "Step-1"],
        {"dynamic_energy_threshold": 0.01, "dynamic_energy_gate": True},
        energy=energy,
    )
    assert enabled is True
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "missing_total_energy_history"


def test_extraction_failure_blocks_instead_of_skipping(monkeypatch):
    import abaqus_ai_agent.execution.odb as odb_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("odb step missing")

    monkeypatch.setattr(odb_module, "extract_energy_evidence", _boom)
    runner = AnalysisRunner(_Executor())
    enabled, verdict = runner._evaluate_dynamic_energy_gate(
        "",
        {"steps": ["Initial", "Step-1"]},
        {"history_regions": ["Assembly ASSEMBLY"]},
        "job.odb",
        _Intent({"dynamic_energy_threshold": 0.01, "dynamic_energy_gate": True}),
        selection=_Selection("DYNAMIC_IMPLICIT"),
    )
    assert enabled is True
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_energy_extraction_failed"


def test_cached_energy_pre_injection_eliminates_secondary_extraction(monkeypatch):
    """When energy evidence is pre-injected in the batch run, secondary extraction is completely eliminated."""
    import abaqus_ai_agent.execution.odb as odb_module

    extracted = []
    def _fail_if_called(*_args, **_kwargs):
        extracted.append(True)
        raise AssertionError("Secondary extraction should not be called when cached_energy matches target step")

    monkeypatch.setattr(odb_module, "extract_energy_evidence", _fail_if_called)

    cached_energy = {
        "status": "available",
        "step": "Step-1",
        "region": "Assembly ASSEMBLY",
        "variables": {
            name: {"status": "available", "data": data}
            for name, data in _REAL_IMPLICIT.items()
        },
    }

    runner = AnalysisRunner(_Executor())
    enabled, verdict = runner._evaluate_dynamic_energy_gate(
        "",
        {"steps": ["Initial", "Step-1"]},
        {"history_regions": ["Assembly ASSEMBLY"]},
        "job.odb",
        _Intent({"dynamic_energy_threshold": 0.01, "dynamic_energy_gate": True}),
        selection=_Selection("DYNAMIC_IMPLICIT"),
        cached_energy=cached_energy,
    )

    assert enabled is True
    assert extracted == []  # Not called!
    assert verdict.status == "PASS"


@pytest.mark.parametrize("strategy,expected", [
    ("DYNAMIC_IMPLICIT", "standard"),
    ("DYNAMIC_EXPLICIT", "explicit"),
    ("QUASI_STATIC_EXPLICIT", "explicit"),
    (None, "standard"),
])
def test_solver_product_mapping(strategy, expected):
    assert AnalysisRunner._solver_product_for_strategy(strategy) == expected
