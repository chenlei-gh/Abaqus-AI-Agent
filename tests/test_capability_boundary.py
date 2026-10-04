from abaqus_ai_agent.actions import python_action, static_step
from abaqus_ai_agent.capability_boundary import CapabilityStatus, classify_action


def test_typed_action_is_formally_supported():
    boundary = classify_action(static_step("Model-1"))
    assert boundary.status == CapabilityStatus.SUPPORTED
    assert boundary.formally_supported
    assert boundary.executable
    assert not boundary.engineering_verified


def test_native_python_is_executable_but_not_formally_supported():
    boundary = classify_action(
        python_action("Model-1", "print(list(mdb.models.keys()))")
    )
    assert boundary.status == CapabilityStatus.EXECUTABLE
    assert boundary.executable
    assert not boundary.formally_supported
    assert not boundary.engineering_verified
    assert "escape hatch" in boundary.reason


def test_capability_boundary_does_not_promote_engineering_correctness():
    boundary = classify_action(static_step("Model-1"))
    assert boundary.status == CapabilityStatus.SUPPORTED
    assert boundary.engineering_verified is False


def test_unknown_action_is_not_promoted_to_supported():
    from abaqus_ai_agent.contracts.action import AbaqusAction

    action = AbaqusAction("not_a_real_action", "Model-1", None, {})
    boundary = classify_action(action)
    assert boundary.status == CapabilityStatus.UNSUPPORTED
    assert not boundary.executable


def test_resolve_capability_for_20_domains():
    from abaqus_ai_agent.contracts.capability import (
        resolve_capability,
        CapabilityStatus as ContractCapabilityStatus,
        ALL_L4_CAPABILITIES,
    )
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.fatigue import IntentFatigueSpec

    assert len(ALL_L4_CAPABILITIES) == 20

    # 1. Linear static
    intent_static = EngineeringIntent(id="1", kind="linear_static", description="Static test")
    res_static = resolve_capability(intent_static)
    assert res_static.capability_id == "linear_static"
    assert res_static.physics_domain == "static"
    assert res_static.is_supported is True
    assert "U" in res_static.profile.required_fields

    # 2. Fatigue
    fatigue_spec = IntentFatigueSpec(material_curve=((300.0, 1e4), (200.0, 1e6)))
    intent_fatigue = EngineeringIntent(id="2", kind="fatigue", description="Fatigue test", fatigue=fatigue_spec)
    res_fatigue = resolve_capability(intent_fatigue)
    assert res_fatigue.capability_id == "high_cycle_fatigue"
    assert res_fatigue.physics_domain == "fatigue"
    assert res_fatigue.is_supported is True
    assert "fatigue_life" in res_fatigue.profile.required_metrics

    # 3. Connectors
    intent_conn = EngineeringIntent(id="3", kind="kinematic_connectors", description="Connector test")
    res_conn = resolve_capability(intent_conn)
    assert res_conn.capability_id == "kinematic_connectors"
    assert res_conn.physics_domain == "connector"
    assert "CU" in res_conn.profile.required_fields

    # 4. FMBD
    intent_fmbd = EngineeringIntent(id="4", kind="fmbd", description="FMBD test")
    res_fmbd = resolve_capability(intent_fmbd)
    assert res_fmbd.capability_id == "flexible_multibody"
    assert res_fmbd.physics_domain == "fmbd"
    assert "joint_drift" in res_fmbd.profile.required_metrics

    # 5. Unsupported (CFD / Aerodynamics)
    intent_cfd = EngineeringIntent(id="5", kind="cfd_aerodynamics", description="CFD airflow")
    res_cfd = resolve_capability(intent_cfd)
    assert res_cfd.status == ContractCapabilityStatus.UNSUPPORTED
    assert res_cfd.is_supported is False
    assert "outside the 20 L4 verified" in res_cfd.reason
