import pytest

from abaqus_ai_agent.contracts.fatigue import FatigueAnalysisIntent, FatigueWorkflow


def test_fatigue_contract_and_workflow():
    intent = FatigueAnalysisIntent(
        name="Bracket fatigue",
        method="S_N",
        cycles=1.0e6,
        stress_variable="S",
        material_curve=((1.0e6, 100.0), (1.0e5, 150.0)),
    )
    workflow = FatigueWorkflow.for_intent(intent)
    assert workflow.solver_scope == "postprocess_existing_abaqus_results"
    assert "cycle_counting" in workflow.steps
    assert "damage_accumulation" in workflow.steps


def test_fatigue_history_postprocessing_uses_explicit_sn_curve():
    from abaqus_ai_agent.fatigue import evaluate_fatigue_history
    intent = FatigueAnalysisIntent(
        name="Bracket fatigue",
        method="S_N",
        material_curve=((1.0e5, 150.0), (1.0e6, 100.0)),
    )
    result = evaluate_fatigue_history(intent, (0.0, 100.0, 0.0), source="ODB:S")
    assert result.status == "completed"
    assert result.cycles_evaluated == 2.0
    assert result.damage > 0.0
    assert result.source == "ODB:S"


def test_fatigue_fails_closed_for_unsupported_mean_stress_correction():
    from abaqus_ai_agent.fatigue import evaluate_fatigue_history
    intent = FatigueAnalysisIntent(
        name="Bracket fatigue",
        mean_stress_correction="GOODMAN",
        material_curve=((1.0e5, 150.0), (1.0e6, 100.0)),
    )
    with pytest.raises(ValueError):
        evaluate_fatigue_history(intent, (0.0, 100.0, 0.0))
