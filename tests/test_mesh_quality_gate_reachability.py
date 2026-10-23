"""D17: a required mesh gate must be able to reject an unusable mesh.

Measured on Abaqus 2025 with C3D10M free tets, `ANALYSIS_CHECKS` reported
`failedElements=0` on the same mesh that failed `ASPECT_RATIO` on 124 of 166
elements. A domain that makes `mesh_quality` mandatory while configuring only
analysis checks therefore owns a gate that can never say no.

These tests pin the three rules that make the gate real:

1. A domain policy always submits at least one shape threshold.
2. A required gate backed only by analysis checks is rejected at build time and
   at acceptance time.
3. The compiler fills thresholds from the domain policy instead of emitting a
   quality action that cannot fail.

The measured values quoted here come from `_probe_d10_c3d10m_bad.json` and
`_probe_d17_e2e*.json` (real kernel output, not estimates).
"""

import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.mesh_quality import (
    DEFAULT_DOMAIN_MESH_QUALITY_POLICY,
    SHAPE_THRESHOLD_FIELDS,
    DomainMeshQualityPolicy,
    mesh_quality_gate_configuration_errors,
    resolve_domain_mesh_quality_policy,
)
from abaqus_ai_agent.contracts.results import get_physics_result_profile


# Real Abaqus 2025 measurements, kept next to the assertions that depend on them.
GOOD_MESH_METRICS = {  # 20x10x10 mm block, seed 4.0 -> 413 C3D10M elements
    "max_aspect_ratio": 2.279,
    "min_angle": 26.971,
    "max_angle": 114.747,
}
BAD_MESH_METRICS = {  # 0.35 mm slab, seed 3.0 -> 166 C3D10M elements
    "max_aspect_ratio": 12.583,
    "min_angle": 2.609,
    "max_angle": 173.705,
}


def test_default_policy_submits_shape_thresholds():
    """A policy with no shape threshold could never fail; the default must not be that."""
    policy = DEFAULT_DOMAIN_MESH_QUALITY_POLICY
    assert policy.is_answerable()
    for name in SHAPE_THRESHOLD_FIELDS:
        assert getattr(policy, name) is not None


def test_default_thresholds_separate_the_measured_good_and_bad_meshes():
    """The defaults are grounded in one measured pair, so pin that they still split it."""
    policy = DEFAULT_DOMAIN_MESH_QUALITY_POLICY
    assert GOOD_MESH_METRICS["max_aspect_ratio"] <= policy.max_aspect_ratio
    assert GOOD_MESH_METRICS["min_angle"] >= policy.min_angle
    assert GOOD_MESH_METRICS["max_angle"] <= policy.max_angle

    assert BAD_MESH_METRICS["max_aspect_ratio"] > policy.max_aspect_ratio
    assert BAD_MESH_METRICS["min_angle"] < policy.min_angle
    assert BAD_MESH_METRICS["max_angle"] > policy.max_angle


def test_domain_policy_resolution_falls_back_conservatively():
    """An unknown domain must still get shape thresholds, not an empty policy."""
    for domain in ("static", "contact", "explicit_dynamic", "unheard_of_domain", None):
        assert resolve_domain_mesh_quality_policy(domain).is_answerable()


def test_policy_rejects_non_positive_thresholds():
    with pytest.raises(ValueError):
        DomainMeshQualityPolicy(max_aspect_ratio=0.0)
    with pytest.raises(ValueError):
        DomainMeshQualityPolicy(min_angle=-1.0)


# --- Build-time configuration check -----------------------------------------


def test_required_gate_without_shape_threshold_is_a_configuration_error():
    errors = mesh_quality_gate_configuration_errors(
        "static",
        ("execution", "odb", "mesh_quality"),
        policy=DomainMeshQualityPolicy(max_aspect_ratio=None, min_angle=None, max_angle=None),
    )
    assert errors
    assert "mesh_quality_gate_required_without_shape_threshold" in errors[0]


def test_optional_gate_without_shape_threshold_is_not_a_configuration_error():
    """The rule only binds domains that make the gate mandatory."""
    errors = mesh_quality_gate_configuration_errors(
        "static",
        ("execution", "odb"),
        policy=DomainMeshQualityPolicy(max_aspect_ratio=None, min_angle=None, max_angle=None),
    )
    assert errors == ()


def test_profile_builder_refuses_a_required_gate_backed_only_by_analysis_checks(monkeypatch):
    """A profile that could never reject a bad mesh must not be constructible."""
    import abaqus_ai_agent.contracts.mesh_quality as mq_module
    import abaqus_ai_agent.contracts.results as results_module

    empty = DomainMeshQualityPolicy(max_aspect_ratio=None, min_angle=None, max_angle=None)
    monkeypatch.setattr(mq_module, "DEFAULT_DOMAIN_MESH_QUALITY_POLICY", empty)
    monkeypatch.setattr(mq_module, "_DOMAIN_MESH_QUALITY_OVERRIDES", {})
    monkeypatch.setitem(results_module.__dict__, "mesh_quality_gate_configuration_errors",
                        mq_module.mesh_quality_gate_configuration_errors)

    with pytest.raises(ValueError, match="shape threshold"):
        get_physics_result_profile(
            "static",
            required_gates=("execution", "odb", "mesh_quality", "criteria"),
        )


def test_current_static_profile_is_constructible():
    """Guard against the check above being satisfied by a blanket failure."""
    profile = get_physics_result_profile("static")
    assert "mesh_quality" in profile.required_gates


# --- Acceptance semantics ---------------------------------------------------


def _accept_static(mesh_quality, required_gates=("execution", "odb", "mesh_quality", "criteria")):
    return evaluate_result_acceptance(
        result_status="completed",
        mesh_quality=mesh_quality,
        values={"max_displacement": 0.4, "max_mises": 120.0, "reaction_force": 1000.0},
        criteria=(),
        required_gates=required_gates,
    )


def test_measured_bad_mesh_blocks_a_required_domain():
    result = _accept_static(
        {"status": "fail", "metrics": dict(BAD_MESH_METRICS), "violations": ["max_aspect_ratio"]}
    )
    assert result.gates["mesh_quality"] == "FAIL"
    assert result.passed is False
    assert "mesh_quality_failed" in result.failures


def test_measured_good_mesh_passes_a_required_domain():
    result = _accept_static({"status": "pass", "metrics": dict(GOOD_MESH_METRICS)})
    assert result.gates["mesh_quality"] == "PASS"
    assert result.passed is True


def test_analysis_checks_only_cannot_satisfy_a_required_gate():
    """This is the D17 defect itself: warning-only evidence must not count as a pass."""
    result = _accept_static(
        {
            "status": "warning",
            "metrics": {},
            "warnings": ["analysis_check_warnings"],
            "warning_element_count": 152,
        }
    )
    assert result.passed is False
    assert "mesh_quality_no_shape_criterion" in result.blocked


def test_missing_mesh_evidence_blocks_a_required_domain():
    result = _accept_static(None)
    assert result.gates["mesh_quality"] == "BLOCKED"
    assert "missing_mandatory_gate:mesh_quality" in result.failures


def test_same_warning_is_advisory_when_the_gate_is_not_required():
    """The rule must not turn every advisory mesh note into a delivery blocker."""
    result = evaluate_result_acceptance(
        result_status="completed",
        mesh_quality={"status": "warning", "warnings": ["analysis_check_warnings"]},
        values={"disp": 1.0},
        criteria=(),
    )
    assert result.gates["mesh_quality"] == "WARNING"
    assert result.passed is True


# --- Compiler wires the thresholds ------------------------------------------


def test_compiled_quality_action_carries_shape_thresholds():
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_intent_to_actions

    actions = compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box", length=10.0, width=5.0, height=5.0),
        material=MaterialDefinition(
            name="Steel",
            unit_system="MM_N_MPA",
            elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        ),
    ).actions
    params = next(a for a in actions if a.action_type == "mesh_quality").parameters
    configured = [name for name in SHAPE_THRESHOLD_FIELDS if params.get(name) is not None]
    assert configured, "compiled quality action must submit at least one shape threshold"
    assert params["analysis_checks"] is True


def test_explicit_mesh_thresholds_win_over_the_domain_default():
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.planning.compiler import (
        IntentGeometrySpec,
        IntentMeshSpec,
        compile_intent_to_actions,
    )

    actions = compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box", length=10.0, width=5.0, height=5.0),
        material=MaterialDefinition(
            name="Steel",
            unit_system="MM_N_MPA",
            elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        ),
        mesh=IntentMeshSpec(max_aspect_ratio=3.0, min_angle=25.0, max_angle=150.0),
    ).actions
    params = next(a for a in actions if a.action_type == "mesh_quality").parameters
    assert params["max_aspect_ratio"] == 3.0
    assert params["min_angle"] == 25.0
    assert params["max_angle"] == 150.0
