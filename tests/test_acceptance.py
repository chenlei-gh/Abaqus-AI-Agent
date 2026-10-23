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


def test_material_card_round_trip_blocks_the_five_m1fa_failures():
    """The solved deck, not the planned material, decides the report table."""
    from abaqus_ai_agent.contracts.deck_material import compare_material_claims, deck_material_table
    from abaqus_ai_agent.reporting.pipeline import reconcile_material_cards

    deck = (
        "*MATERIAL, NAME=PCABS\n"
        "*ELASTIC\n"
        "1900., 0.38\n"
        "*PLASTIC\n"
        "215., 0.\n"
    )
    claimed = [{
        "name": "PCABS",
        "unit_system": "MM_N_MPA",
        "elastic": {"youngs_modulus": 1900.0, "poisson_ratio": 0.38},
        "plastic": {
            "yield_stress": 190.0,
            "plastic_strain": 0.0,
            "hardening_table": [(200.0, 0.01), (210.0, 0.02), (220.0, 0.03), (230.0, 0.04)],
        },
    }]
    mismatch = reconcile_material_cards(claimed, deck)
    assert mismatch["code"] == "material_card_mismatch"
    codes = {item["code"] for item in mismatch["mismatches"]}
    assert "plastic_curve_mismatch" in codes

    table = deck_material_table(deck, input_sha256="deck-v1")
    assert table[0]["plastic"]["yield_stress"] == 215.0
    assert table[0]["input_sha256"] == "deck-v1"
    assert len(table[0]["plastic"]["hardening_table"]) == 0

    missing_point = reconcile_material_cards(
        [{"name": "PCABS", "plastic": {"yield_stress": 215.0, "hardening_table": []}}],
        deck + "220., 0.01\n",
    )
    assert "plastic_curve_mismatch" in {item["code"] for item in missing_point["mismatches"]}

    extra_point = reconcile_material_cards(
        [{"name": "PCABS", "plastic": {"yield_stress": 215.0, "hardening_table": [(230.0, 0.02)]}}],
        deck,
    )
    assert "plastic_curve_mismatch" in {item["code"] for item in extra_point["mismatches"]}

    deck_row = deck_material_table(
        "*MATERIAL, NAME=PCABS\n*ELASTIC\n1900., 0.38\n*PLASTIC\n215., 0.\n"
    )[0]
    deck_row = dict(deck_row)
    deck_row["unit_system"] = "MM_N_MPA"
    wrong_unit = compare_material_claims(
        [{
            "name": "PCABS",
            "unit_system": "SI",
            "elastic": {"youngs_modulus": 1900.0, "poisson_ratio": 0.38},
            "plastic": {"yield_stress": 215.0, "hardening_table": []},
        }],
        [deck_row],
    )
    assert "material_unit_mismatch" in {item["code"] for item in wrong_unit["mismatches"]}
    changed_value = reconcile_material_cards(
        [{"name": "PCABS", "elastic": {"youngs_modulus": 1800.0, "poisson_ratio": 0.38}}],
        "*MATERIAL, NAME=PCABS\n*ELASTIC\n1900., 0.38\n",
    )
    assert "material_value_mismatch" in {item["code"] for item in changed_value["mismatches"]}

    same_name_other_curve = reconcile_material_cards(
        [{"name": "PCABS", "plastic": {"yield_stress": 190.0, "hardening_table": [(200.0, 0.1)]}}],
        deck,
    )
    assert "plastic_curve_mismatch" in {item["code"] for item in same_name_other_curve["mismatches"]}

    stale = reconcile_material_cards(
        [{"name": "PCABS", "input_sha256": "old-deck", "plastic": {"yield_stress": 215.0}}],
        deck,
        input_hash="new-deck",
    )
    assert "stale_material_evidence" in {item["code"] for item in stale["mismatches"]}


def test_reconcile_model_claims_passes_honest_declaration():
    from abaqus_ai_agent.reporting.pipeline import _reconcile_model_claims
    inp = "*Element, type=C3D4\n*Material, name=PCABS\n*Elastic\n1900., 0.38\n"
    assert _reconcile_model_claims(
        {"element_type": "C3D4", "analysis_type": "linear elastic static"}, inp) is None
    # No inp text -> nothing to reconcile against, no fabrication
    assert _reconcile_model_claims({"element_type": "C3D10M"}, "") is None
