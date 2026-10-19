"""An Initial-step contact must not require the caller to restate the only step.

``resolve_contact_stabilization`` already refuses to guess when several implicit
steps exist and already binds the single supported step when there is exactly
one. The script-emission block used to discard that resolved decision and raise
instead, so a remediation produced by the product could not be compiled without
the caller hand-supplying ``target_step``.

These tests lock the boundary: unambiguous resolution is carried through, every
ambiguous shape still fails closed.
"""

import pytest

from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.actions import builders
from abaqus_ai_agent.contracts.contact_stabilization import (
    ContactStabilizationError,
    resolve_contact_stabilization,
)
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.contracts.procedure import MultiStepProcedureSpec, StepDependency
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentInteractionSpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_intent_to_actions,
)

MATERIAL = MaterialDefinition(
    name="Steel",
    unit_system="MM_N_MPA",
    elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
)

STABILIZATION = {"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4}


def _compile(*, interactions, step=None, steps=None, procedure=None,
             contract=None):
    return compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box"),
        material=MATERIAL,
        step=step,
        steps=steps,
        procedure=procedure,
        mesh=IntentMeshSpec(),
        interactions=interactions,
        contact_stabilization=STABILIZATION if contract is None else contract,
    )


def _initial_contact():
    return IntentInteractionSpec(
        name="CP",
        master_region="BaseSurf",
        slave_region="SliderSurf",
        friction_coefficient=0.3,
        step="Initial",
        stabilization=dict(STABILIZATION),
    )


def test_single_implicit_step_binds_initial_step_contact_without_caller_target():
    plan = _compile(
        interactions=(_initial_contact(),),
        step=IntentStepSpec(name="Step-1", step_type="static_general"),
    )
    script = plan.cae_script
    # The control must be attached in the step, not at interaction creation.
    assert "StdContactControl(" in script
    assert "setValuesInStep(stepName='Step-1', contactControls='CC-Stabilization')" in script
    assert "createStepName='Initial', main=m_surf, secondary=s_surf" in script


def test_two_implicit_steps_still_require_an_explicit_target():
    """Two candidate steps is genuinely ambiguous, so it must fail closed."""
    with pytest.raises(ContactStabilizationError) as excinfo:
        _compile(
            interactions=(_initial_contact(),),
            steps=(
                IntentStepSpec(name="Step-1", step_type="static_general"),
                IntentStepSpec(name="Step-2", step_type="static_general",
                               previous="Step-1"),
            ),
        )
    assert "explicit target_step" in str(excinfo.value)


def test_explicit_top_level_target_step_wins_over_the_single_default():
    """An explicit target is honoured rather than replaced by the only step."""
    plan = _compile(
        interactions=(_initial_contact(),),
        steps=(
            IntentStepSpec(name="Step-1", step_type="static_general"),
            IntentStepSpec(name="Step-2", step_type="static_general",
                           previous="Step-1"),
        ),
        contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4,
                  "target_step": "Step-2"},
    )
    assert "setValuesInStep(stepName='Step-2', contactControls='CC-Stabilization')" in plan.cae_script


def test_contact_created_in_later_step_needs_no_override():
    contact = IntentInteractionSpec(
        name="CP",
        master_region="BaseSurf",
        slave_region="SliderSurf",
        friction_coefficient=0.3,
        step="Step-1",
        stabilization=dict(STABILIZATION),
    )
    plan = _compile(
        interactions=(contact,),
        step=IntentStepSpec(name="Step-1", step_type="static_general"),
    )
    script = plan.cae_script
    assert "contactControls='CC-Stabilization'" in script
    assert "setValuesInStep" not in script


def test_resolution_is_unique_or_refused():
    """The contract itself never invents a step from an ambiguous list."""
    from abaqus_ai_agent.contracts.contact_stabilization import (
        ContactStabilizationSpec,
    )

    _, bindings = resolve_contact_stabilization(
        [_initial_contact()],
        ContactStabilizationSpec(damp_factor=1e-4),
        step_order=("Step-1",),
    )
    assert bindings[0].target_step == "Step-1"
    assert bindings[0].requires_step_override is True

    with pytest.raises(ContactStabilizationError):
        resolve_contact_stabilization(
            [_initial_contact()],
            ContactStabilizationSpec(damp_factor=1e-4),
            step_order=("Step-1", "Step-2"),
        )
