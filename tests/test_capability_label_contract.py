"""Capability labels are workflow routes, not machine-validation certificates."""

from abaqus_ai_agent.contracts.capability import ALL_L4_CAPABILITIES, resolve_capability
from abaqus_ai_agent.contracts.intent import EngineeringIntent


def _intent(kind, **kwargs):
    return EngineeringIntent(
        id="cap-%s" % kind,
        kind=kind,
        description="Capability label contract probe",
        analysis_type=kind,
        **kwargs,
    )


def test_supported_workflows_are_not_current_job_certificates():
    samples = (
        _intent("linear_static"),
        _intent("contact_frictional", contacts=({"name": "c1"},)),
        _intent("high_cycle_fatigue"),
        _intent("explicit_dynamic"),
        _intent("thermal_structural"),
        _intent("flexible_multibody"),
        _intent("assembly_tie_interaction"),
    )
    for intent in samples:
        resolved = resolve_capability(intent)
        assert resolved.capability_id in ALL_L4_CAPABILITIES
        assert resolved.is_supported
        assert resolved.qualification_level == "WORKFLOW"
        assert resolved.qualification_level != "L4"
        assert "Qualified under" not in resolved.reason
        assert resolved.metadata.get("machine_validation_certificate") is False
        payload = resolved.to_dict()
        assert payload["qualification_level"] == "WORKFLOW"
        assert payload["metadata"]["machine_validation_certificate"] is False


def test_default_resolution_does_not_inherit_l4_certificate():
    resolved = resolve_capability(_intent("unspecified_static"))
    assert resolved.capability_id == "linear_static"
    assert resolved.qualification_level == "WORKFLOW"
    assert "not a machine-validation certificate" in resolved.reason
