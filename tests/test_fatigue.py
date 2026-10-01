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
