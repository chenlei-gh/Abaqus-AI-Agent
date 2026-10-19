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
    GeometryCleanupPolicy,
    GeometryCleanupPolicySet,
    GeometryCleanupPolicyViolation,
    enforce_cleanup_policy,
    verify_cleanup_transition,
)


# --- Fail-closed default ---------------------------------------------------


def test_default_policy_denies_repair_without_any_caller_configuration():
    with pytest.raises(GeometryCleanupPolicyViolation) as excinfo:
        action_to_script(repair_geometry("Model-1", "Part-1"))
    assert "repairGeometry" in str(excinfo.value) or "repair_geometry" in str(excinfo.value)
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
    assert "repairGeometry" in script


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
    assert "repairGeometry" in script


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
])
def test_raw_python_repair_is_blocked_under_the_default_policy(snippet):
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(python_action("Model-1", snippet))


@pytest.mark.parametrize("snippet", [
    "mdb.models['M'].parts['P'].ignoreEntity(entities=e)",
    "mdb.models['M'].parts['P'].restoreIgnoredEntity(entities=e)",
])
def test_raw_python_virtual_topology_is_blocked_under_the_default_policy(snippet):
    with pytest.raises(GeometryCleanupPolicyViolation):
        action_to_script(python_action("Model-1", snippet))


def test_raw_python_repair_passes_only_under_an_explicit_allow_repair_policy():
    policy = GeometryCleanupPolicy(part=DEFAULT_PART, allow_repair=True)
    code = "mdb.models['M'].parts['P'].repairGeometry()"
    assert action_to_script(python_action("Model-1", code), cleanup_policies=policy) == code


def test_benign_python_is_unaffected_by_the_cleanup_policy():
    code = "print(list(mdb.models.keys()))"
    assert action_to_script(python_action("Model-1", code)) == code


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
