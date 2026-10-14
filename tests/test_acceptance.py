from abaqus_ai_agent.acceptance import evaluate_criteria


def test_acceptance_passes():
    result = evaluate_criteria(
        {"max_stress": 180.0},
        [{"name": "stress", "value_key": "max_stress",
          "operator": "<", "limit": 250.0, "unit": "MPa"}],
    )
    assert result.passed
    assert not result.failures


def test_acceptance_fails():
    result = evaluate_criteria(
        {"max_stress": 280.0},
        [{"name": "stress", "value_key": "max_stress",
          "operator": "<", "limit": 250.0, "unit": "MPa"}],
    )
    assert not result.passed
    assert len(result.failures) == 1


def test_acceptance_relative_tolerance_and_warning():
    result = evaluate_criteria(
        {"stress": 101.0},
        [{"name": "stress", "value_key": "stress", "operator": "<", "limit": 100.0,
          "relative_tolerance": 0.02, "unit": "MPa"}],
    )
    assert result.passed
    assert result.criteria[0].relative_error == 0.01


def test_acceptance_warns_when_tolerance_has_no_order_semantics():
    result = evaluate_criteria(
        {"stress": 100.1},
        [{"value_key": "stress", "operator": "==", "limit": 100.0,
          "relative_tolerance": 0.01}],
    )
    assert not result.passed
    assert result.warnings == ("relative_tolerance_ignored_for_==",)


def test_result_acceptance_requires_completed_solver_status():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    result = evaluate_result_acceptance(
        "completed",
        values={"max_stress": 180.0},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
    )
    assert result.passed


def test_result_acceptance_does_not_treat_failed_solver_as_engineering_pass():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    result = evaluate_result_acceptance(
        "error",
        values={"max_stress": 180.0},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
    )
    assert not result.passed
    assert "solver_status:error" in result.failures


def test_result_acceptance_blocks_failed_engineering_checks():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    class Checks:
        passed = False
    result = evaluate_result_acceptance(
        "completed",
        engineering=Checks(),
        values={"max_stress": 180.0},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
    )
    assert not result.passed
    assert "engineering_checks_failed" in result.failures


# --- MS13L lessons: elastic-range validity + report/model reconciliation ---


def test_elastic_range_exceeded_is_result_invalid_and_not_deliverable():
    """MS13L Case2@85C: purely elastic deck, extracted stress 33.93 > yield 27.1.
    The linear-elastic result past yield must fail closed as RESULT_INVALID and
    must never be deliverable or narratable as plastic deformation."""
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    result = evaluate_result_acceptance(
        "completed",
        values={"max_stress": 33.93},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
        elastic_validity={
            "is_purely_elastic": True,
            "yield_strength": 27.1,
            "max_stress": 33.93,
        },
    )
    assert not result.passed
    assert result.acceptance_status == "RESULT_INVALID"
    assert str(result.result_validity) == "RESULT_INVALID"
    assert result.deliverable is False
    assert any("elastic_range_exceeded" in f for f in result.failures)


def test_elastic_range_within_yield_stays_deliverable_path():
    """A purely elastic model whose stress stays below yield is NOT blocked by
    the elastic-range rule (it may still pass on its own criteria)."""
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    result = evaluate_result_acceptance(
        "completed",
        values={"max_stress": 8.07},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
        elastic_validity={
            "is_purely_elastic": True,
            "yield_strength": 44.0,
            "max_stress": 8.07,
        },
    )
    assert not any("elastic_range_exceeded" in f for f in result.failures)
    assert result.deliverable is True


def test_elastic_range_rule_ignores_non_finite_and_bool_inputs():
    """Malformed elastic_validity inputs must not fabricate a failure."""
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    for bad in (
        {"is_purely_elastic": True, "yield_strength": float("nan"), "max_stress": 10.0},
        {"is_purely_elastic": True, "yield_strength": 27.1, "max_stress": True},
        {"is_purely_elastic": True, "yield_strength": float("inf"), "max_stress": 10.0},
        {"is_purely_elastic": False, "yield_strength": 1.0, "max_stress": 999.0},
        None,
    ):
        result = evaluate_result_acceptance(
            "completed",
            values={"max_stress": 8.07},
            criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
            elastic_validity=bad,
        )
        assert not any("elastic_range_exceeded" in f for f in result.failures)


def test_reconcile_model_claims_flags_ms13l_fabrication():
    """Report claims C3D10M + elasto-plastic; deck is C3D4 + purely elastic."""
    from abaqus_ai_agent.reporting.pipeline import _reconcile_model_claims
    inp = "*Element, type=C3D4\n*Material, name=PCABS\n*Elastic\n1900., 0.38\n"
    mm = _reconcile_model_claims(
        {"element_type": "C3D10M", "analysis_type": "非线性弹塑性校核"}, inp)
    assert mm is not None
    assert "element_type" in mm
    assert mm["element_type"]["actual_codes"] == ["C3D4"]
    assert mm["plasticity"]["actual"] == "purely_elastic"


def test_reconcile_model_claims_passes_honest_declaration():
    from abaqus_ai_agent.reporting.pipeline import _reconcile_model_claims
    inp = "*Element, type=C3D4\n*Material, name=PCABS\n*Elastic\n1900., 0.38\n"
    assert _reconcile_model_claims(
        {"element_type": "C3D4", "analysis_type": "linear elastic static"}, inp) is None
    # No inp text -> nothing to reconcile against, no fabrication
    assert _reconcile_model_claims({"element_type": "C3D10M"}, "") is None
