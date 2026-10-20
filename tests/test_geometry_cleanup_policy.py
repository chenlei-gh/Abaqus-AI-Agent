"""Geometry cleanup policy must be enforced at the single script choke point.

The contract declared ``allow_repair = False`` and ``allow_virtual_topology =
False`` but was never read by any caller, so those defaults blocked nothing.
These tests pin the enforcement, the fail-closed default, and the fact that the
policy cannot be discharged by an escape hatch.
"""

import pytest

from abaqus_ai_agent.actions import (
    ignore_entity,
    python_action,
    remove_redundant_entities,
    repair_geometry,
    restore_entity,
    seed_part,
    static_step,
)
from abaqus_ai_agent.actions.runner import preview
from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.contracts.geometry_cleanup import (
    DEFAULT_PART,
    GEOMETRY_GUARD_SENTINEL,
    GeometryCleanupPolicy,
    GeometryCleanupPolicySet,
    GeometryCleanupPolicyViolation,
    enforce_cleanup_policy,
    render_geometry_guard,
    verify_cleanup_transition,
)


# --- Fail-closed default ---------------------------------------------------


def test_default_policy_denies_repair_without_any_caller_configuration():
    with pytest.raises(GeometryCleanupPolicyViolation) as excinfo:
        action_to_script(repair_geometry("Model-1", "Part-1"))
    assert "repair" in str(excinfo.value)
    assert excinfo.value.policy.allow_repair is False


def test_default_policy_denies_redundant_entity_removal():
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(remove_redundant_entities("Model-1", "Part-1"))


def test_default_policy_denies_virtual_topology_mutation():
    for action in (
        ignore_entity("Model-1", "Part-1", "e[0]"),
        restore_entity("Model-1", "Part-1", "e[0]"),
    ):
        with pytest.raises(GeometryCleanupPolicyViolation):
            action_to_script(action)


def test_default_set_records_that_it_was_a_default():
    resolved = GeometryCleanupPolicySet.coerce(None)
    assert resolved.is_default is True
    assert resolved.policy_for("Part-1").allow_repair is False
    assert resolved.policy_for("Part-1").allow_virtual_topology is False


def test_unknown_part_still_denies_rather_than_falling_open():
    resolved = GeometryCleanupPolicySet(
        (GeometryCleanupPolicy(part="OtherPart", allow_repair=True),)
    )
    policy = resolved.policy_for("Part-1")
    assert policy.allow_repair is False


# --- Explicit opt-in -------------------------------------------------------


def test_explicit_policy_can_authorise_repair_for_its_own_part():
    policy = GeometryCleanupPolicy(part="Part-1", allow_repair=True)
    script = action_to_script(
        repair_geometry("Model-1", "Part-1"), cleanup_policies=policy
    )
    # ``repairGeometry`` does not exist in Abaqus 2025; ``repair`` does.
    assert ".repair()" in script


def test_authorising_one_part_does_not_authorise_another():
    policy = GeometryCleanupPolicy(part="Part-1", allow_repair=True)
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(
            repair_geometry("Model-1", "Part-2"), cleanup_policies=policy
        )


def test_explicit_policy_can_authorise_virtual_topology_separately():
    policy = GeometryCleanupPolicy(part="Part-1", allow_virtual_topology=True)
    script = action_to_script(
        ignore_entity("Model-1", "Part-1", "e[0]"), cleanup_policies=policy
    )
    assert "ignoreEntity" in script
    # Repair stays denied under the same policy.
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(
            repair_geometry("Model-1", "Part-1"), cleanup_policies=policy
        )


def test_wildcard_policy_applies_to_any_part():
    policy = GeometryCleanupPolicy(part=DEFAULT_PART, allow_repair=True)
    script = action_to_script(
        repair_geometry("Model-1", "AnyPart"), cleanup_policies=policy
    )
    assert ".repair()" in script


def test_multiple_matching_policies_take_the_most_restrictive():
    resolved = GeometryCleanupPolicySet((
        GeometryCleanupPolicy(part=DEFAULT_PART, allow_repair=True),
        GeometryCleanupPolicy(part="Part-1", allow_repair=False),
    ))
    assert resolved.policy_for("Part-1").allow_repair is False
    assert resolved.policy_for("Part-2").allow_repair is True


# --- The escape hatch cannot launder a denied repair ------------------------


@pytest.mark.parametrize("snippet", [
    "mdb.models['M'].parts['P'].repairGeometry()",
    "mdb.models['M'].parts['P'].removeRedundantEntities()",
    "mdb.models['M'].parts['P'].repair()",
    "mdb.models['M'].parts['P'].removeInvalidGeometry()",
])
def test_raw_python_repair_is_blocked_under_the_default_policy(snippet):
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(python_action("Model-1", snippet))


@pytest.mark.parametrize("snippet", [
    "mdb.models['M'].parts['P'].ignoreEntity(entities=e)",
    "mdb.models['M'].parts['P'].restoreIgnoredEntity(entities=e)",
    "mdb.models['M'].parts['P'].createVirtualTopology(regions=r)",
])
def test_raw_python_virtual_topology_is_blocked_under_the_default_policy(snippet):
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(python_action("Model-1", snippet))


def test_raw_python_repair_passes_only_under_an_explicit_allow_repair_policy():
    policy = GeometryCleanupPolicy(part=DEFAULT_PART, allow_repair=True)
    code = "mdb.models['M'].parts['P'].repair()"
    script = action_to_script(python_action("Model-1", code), cleanup_policies=policy)
    # The user's code is kept verbatim, but it now runs behind the runtime guard
    # that records (and, for other parts, still blocks) the call.
    assert script.endswith(code)
    assert GEOMETRY_GUARD_SENTINEL in script


def test_benign_python_keeps_its_code_but_runs_behind_the_guard():
    code = "print(list(mdb.models.keys()))"
    script = action_to_script(python_action("Model-1", code))
    assert script.endswith(code)
    assert GEOMETRY_GUARD_SENTINEL in script


def test_guard_can_be_suppressed_for_script_composition():
    """The compiler emits one guard for the whole deck, not one per action."""
    code = "print(1)"
    action = python_action("Model-1", code)
    assert action_to_script(action, include_guard=False) == code
    assert GEOMETRY_GUARD_SENTINEL in action_to_script(action)


def test_policy_does_not_interfere_with_unrelated_actions():
    assert "StaticStep" in action_to_script(static_step("Model-1"))
    assert "seedPart" in action_to_script(seed_part("Model-1", "Part-1", 5.0))


# --- The enforcement point is shared, not per-caller -----------------------


def test_every_script_path_shares_the_same_enforcement_point():
    """preview(), action_to_script() and the compiler all funnel through one guard."""
    action = repair_geometry("Model-1", "Part-1")
    with pytest.raises(GeometryCleanupPolicyViolation):
        preview(action)
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(action)
    with pytest.raises(GeometryCleanupPolicyViolation):
        enforce_cleanup_policy(action)


def test_violation_payload_is_auditable():
    with pytest.raises(GeometryCleanupPolicyViolation) as excinfo:
        action_to_script(repair_geometry("Model-1", "Part-1"))
    payload = excinfo.value.to_dict()
    assert payload["error"] == "geometry_cleanup_policy_violation"
    assert payload["action_type"] == "repair_geometry"
    assert payload["allow_repair"] is False
    assert payload["policy_is_default"] is True


# --- A no-op cleanup is not a success -------------------------------------


def test_no_observable_change_is_not_reported_as_verified():
    before = {"part": "Part-1", "issues": [], "entity_counts": {"Edge": 12}, "valid_geometry": True}
    after = {"part": "Part-1", "issues": [], "entity_counts": {"Edge": 12}, "valid_geometry": True}
    result = verify_cleanup_transition(before, after, "repair_geometry")
    assert result["verified"] is False
    assert result["reason"] == "no_observable_change"


def test_missing_post_inspection_blocks_verification():
    before = {"part": "Part-1", "issues": [], "entity_counts": {}}
    result = verify_cleanup_transition(before, {"part": "Part-1"}, "repair_geometry")
    assert result["verified"] is False
    assert result["reason"].startswith("missing_post_inspection:")


def test_inconclusive_validity_cannot_be_the_only_change():
    """``checkGeometry`` raises on failure, so a constant True is not evidence."""
    before = {"part": "P", "issues": [], "entity_counts": {"Edge": 4}, "valid_geometry": None}
    after = {"part": "P", "issues": [], "entity_counts": {"Edge": 4}, "valid_geometry": True}
    result = verify_cleanup_transition(before, after, "repair_geometry")
    assert result["verified"] is False
    assert result["validity_conclusive"] is False


def test_validity_flip_with_decided_endpoints_still_counts():
    before = {"part": "P", "issues": [], "entity_counts": {"Edge": 4}, "valid_geometry": False}
    after = {"part": "P", "issues": [], "entity_counts": {"Edge": 4}, "valid_geometry": True}
    result = verify_cleanup_transition(before, after, "repair_geometry")
    assert result["verified"] is True
    assert "validity_conclusive" not in result


# --- The runtime guard matches the real Abaqus 2025 API surface ------------


@pytest.mark.parametrize("mutator", [
    "repair",
    "removeInvalidGeometry",
    "CreateHealedPart",
    "ignoreEntity",
    "restoreIgnoredEntity",
    "createVirtualTopology",
])
def test_guard_registers_every_real_part_mutator(mutator):
    guard = render_geometry_guard()
    assert mutator in guard


def test_guard_compiles_as_python_and_is_idempotent_by_construction():
    guard = render_geometry_guard()
    compile(guard, "<guard>", "exec")
    # The sentinel is stored on ``sys`` so a second script in the same CAE
    # session reuses the live callback instead of stacking a second one.
    assert 'setattr(_abqai_sys, "__ABQAI_GEOMETRY_GUARD__", _state)' in guard
    assert "callbackExists" in guard


def test_guard_denies_by_default_in_the_generated_policy_payload():
    guard = render_geometry_guard()
    assert "{'*': {'repair': False, 'virtual_topology': False}}" in guard


def test_guard_payload_carries_per_part_permissions():
    guard = render_geometry_guard((
        GeometryCleanupPolicy(part="Part-1", allow_repair=True),
        GeometryCleanupPolicy(part="Part-2", allow_virtual_topology=True),
    ))
    assert "'Part-1': {'repair': True, 'virtual_topology': False}" in guard
    assert "'Part-2': {'repair': False, 'virtual_topology': True}" in guard


def test_guard_refuses_to_claim_enforcement_when_registration_fails():
    """If any methodCallback mutator cannot be registered the guard must fail, not downgrade."""
    guard = render_geometry_guard()
    assert "cannot enforce the geometry cleanup policy" in guard
    assert "one or more required mutator callbacks failed to register" in guard
    assert "raise RuntimeError" in guard


def test_guard_partial_registration_failure_raises_runtime_error():
    """Simulate a partial registration failure where some callbacks fail to register."""
    import sys
    import types
    from abaqus_ai_agent.contracts.geometry_cleanup import render_geometry_guard

    class MockMethodCallback:
        ALL_TYPES = "ALL_TYPES"
        def __init__(self):
            self.calls = []
        def callbackExists(self, cb_type, name, cb):
            return False
        def addCallback(self, cb_type, name, cb):
            # Simulate failure specifically for 'removeInvalidGeometry'
            if name == "removeInvalidGeometry":
                raise ValueError("Abaqus kernel failed to hook removeInvalidGeometry")
            self.calls.append(name)

    mock_inst = MockMethodCallback()
    mock_mod = types.ModuleType("methodCallback")
    mock_mod.ALL_TYPES = mock_inst.ALL_TYPES
    mock_mod.callbackExists = mock_inst.callbackExists
    mock_mod.addCallback = mock_inst.addCallback

    orig_mc = sys.modules.get("methodCallback")
    sys.modules["methodCallback"] = mock_mod

    guard = render_geometry_guard()
    env = {}
    orig_guard = getattr(sys, "__ABQAI_GEOMETRY_GUARD__", None)
    if hasattr(sys, "__ABQAI_GEOMETRY_GUARD__"):
        delattr(sys, "__ABQAI_GEOMETRY_GUARD__")

    try:
        with pytest.raises(RuntimeError) as excinfo:
            exec(guard, env)

        err_msg = str(excinfo.value)
        assert "one or more required mutator callbacks failed to register" in err_msg
        assert "removeInvalidGeometry" in err_msg
        # Assert that other mutators registered successfully into methodCallback!
        assert len(mock_inst.calls) > 0
        assert "repairGeometry" in mock_inst.calls
        assert "ignoreEntity" in mock_inst.calls
        assert "removeInvalidGeometry" not in mock_inst.calls
    finally:
        if orig_mc is not None:
            sys.modules["methodCallback"] = orig_mc
        else:
            sys.modules.pop("methodCallback", None)
        if orig_guard is not None:
            setattr(sys, "__ABQAI_GEOMETRY_GUARD__", orig_guard)
        elif hasattr(sys, "__ABQAI_GEOMETRY_GUARD__"):
            delattr(sys, "__ABQAI_GEOMETRY_GUARD__")


def test_guard_records_tolerance_changes_without_blocking_them():
    guard = render_geometry_guard(None, "p.setValues(geometryRefinement=FINE)")
    assert "for _abqai_record in ('geometryRefinement',):" in guard
    # Recorded, not denied: the tolerance is not an entity mutation.
    assert "geometryRefinement" not in render_geometry_guard().split("_repair_names =")[1]


# --- Typed actions must emit APIs that exist in Abaqus 2025 ---------------


def test_repair_action_emits_the_real_2025_api():
    policy = GeometryCleanupPolicy(part="Part-1", allow_repair=True)
    script = action_to_script(
        repair_geometry("Model-1", "Part-1"), cleanup_policies=policy
    )
    assert ".repair()" in script
    assert "repairGeometry" not in script


def test_remove_redundant_entities_maps_to_the_documented_api():
    policy = GeometryCleanupPolicy(part="Part-1", allow_repair=True)
    script = action_to_script(
        remove_redundant_entities("Model-1", "Part-1"), cleanup_policies=policy
    )
    assert "removeInvalidGeometry()" in script
    assert "removeRedundantEntities" not in script


def test_entity_actions_pass_a_tuple_not_a_bare_entity():
    policy = GeometryCleanupPolicy(part="Part-1", allow_virtual_topology=True)
    script = action_to_script(
        ignore_entity("Model-1", "Part-1", "e[0]"), cleanup_policies=policy
    )
    assert "isinstance(_abqai_entities, tuple)" in script
    assert "entities=_abqai_entities" in script


def test_geometry_inspection_does_not_report_a_constant_validity():
    """``checkGeometry`` returns None on success, so the old check was always True."""
    from abaqus_ai_agent.actions.script import _geometry_inspection_script

    script = _geometry_inspection_script("Model-1", {"part": "Part-1"})
    assert "if check is False" not in script
    assert "geometryValidity" in script
    assert "check_geometry_error" in script
    assert "'validity_source'" in script


# --- Virtual topology stays a candidate, never an action -------------------


def test_small_feature_virtual_topology_remains_review_only():
    from abaqus_ai_agent.planning.mesh_strategy import (
        local_seeds_from_geometry_plan,
        plan_geometry_mesh,
    )

    plan = plan_geometry_mesh(
        {"edges": [{"index": 3, "size": 0.2}]}, global_size=5.0
    )
    assert [r.method for r in plan.feature_reviews] == ["virtual_topology_review"]
    assert "small_geometry_requires_feature_classification_before_mutation" in plan.warnings
    # Review candidates must never become an executed ignore_entity action.
    assert local_seeds_from_geometry_plan(plan) == ()


# --- Intent evaluation fail-closed contract --------------------------------


def test_evaluate_geometry_cleanup_intent_clean():
    from abaqus_ai_agent.contracts.geometry_cleanup import (
        GeometryInspection,
        GeometryIssue,
        STATUS_CLEAN,
        evaluate_geometry_cleanup_intent,
    )
    insp = GeometryInspection(part="Part-1", issues=(), valid_geometry=True)
    res = evaluate_geometry_cleanup_intent(insp)
    assert res["status"] == STATUS_CLEAN
    assert res["action_permitted"] is False
    assert res["error_count"] == 0
    assert res["warning_count"] == 0


def test_evaluate_geometry_cleanup_intent_warning_only():
    from abaqus_ai_agent.contracts.geometry_cleanup import (
        GeometryInspection,
        GeometryIssue,
        STATUS_WARNING,
        evaluate_geometry_cleanup_intent,
    )
    issue = GeometryIssue(
        entity_type="Edge",
        index=5,
        issue_type="short_edge",
        severity="warning",
        metric=0.05,
        threshold=0.1,
        locator=(10.0, 20.0, 30.0),
        recommendation="Consider virtual topology or local seed refinement.",
    )
    insp = GeometryInspection(part="Part-1", issues=(issue,), valid_geometry=True)
    res = evaluate_geometry_cleanup_intent(insp)
    assert res["status"] == STATUS_WARNING
    assert res["action_permitted"] is False
    assert res["warning_count"] == 1
    assert len(res["diagnostics"]) == 1
    assert res["diagnostics"][0]["locator"] == (10.0, 20.0, 30.0)


def test_evaluate_geometry_cleanup_intent_error_denied_default_policy():
    from abaqus_ai_agent.contracts.geometry_cleanup import (
        GeometryInspection,
        GeometryIssue,
        STATUS_REPAIR_FORBIDDEN_FAIL_CLOSED,
        evaluate_geometry_cleanup_intent,
    )
    issue = GeometryIssue(
        entity_type="Face",
        index=2,
        issue_type="self_intersecting_face",
        severity="error",
        locator=(1.0, 2.0, 3.0),
        recommendation="Fix upstream CAD surface topology.",
    )
    insp = GeometryInspection(part="Part-1", issues=(issue,), valid_geometry=False)
    res = evaluate_geometry_cleanup_intent(insp)
    assert res["status"] == STATUS_REPAIR_FORBIDDEN_FAIL_CLOSED
    assert res["action_permitted"] is False
    assert res["allow_repair"] is False
    assert res["error_count"] >= 1
    assert len(res["diagnostics"]) >= 1
    assert res["diagnostics"][0]["locator"] == (1.0, 2.0, 3.0)
    assert "Fix upstream CAD" in res["recommendations"][0]


def test_evaluate_geometry_cleanup_intent_error_authorized():
    from abaqus_ai_agent.contracts.geometry_cleanup import (
        GeometryCleanupPolicy,
        GeometryInspection,
        GeometryIssue,
        STATUS_REPAIR_AUTHORIZED,
        evaluate_geometry_cleanup_intent,
    )
    issue = GeometryIssue(
        entity_type="Face",
        index=2,
        issue_type="invalid_face",
        severity="error",
        locator=(1.0, 2.0, 3.0),
        recommendation="Repair geometry with valid CAD tolerances.",
    )
    insp = GeometryInspection(part="Part-1", issues=(issue,), valid_geometry=False)
    policy = GeometryCleanupPolicy(part="Part-1", allow_repair=True)
    res = evaluate_geometry_cleanup_intent(insp, policy)
    assert res["status"] == STATUS_REPAIR_AUTHORIZED
    assert res["action_permitted"] is True
    assert res["allow_repair"] is True


def test_evaluate_geometry_cleanup_intent_invalid_geometry_flag():
    from abaqus_ai_agent.contracts.geometry_cleanup import (
        GeometryInspection,
        STATUS_REPAIR_FORBIDDEN_FAIL_CLOSED,
        evaluate_geometry_cleanup_intent,
    )
    insp = GeometryInspection(part="Part-1", issues=(), valid_geometry=False)
    res = evaluate_geometry_cleanup_intent(insp)
    assert res["status"] == STATUS_REPAIR_FORBIDDEN_FAIL_CLOSED
    assert res["action_permitted"] is False
    assert res["error_count"] == 1
    assert res["diagnostics"][0]["issue_type"] == "invalid_geometry"
