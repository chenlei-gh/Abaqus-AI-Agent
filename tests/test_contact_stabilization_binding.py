"""P0-b: contact stabilization must reach the Abaqus contact object.

The defect being locked down: a diagnosis produced ``contact_damping=True`` and
``stabilization_magnitude``, ``apply_remediations`` merged both into
``metadata["step_controls"]``, and the compiler only ever read step controls.
Nothing reached a contact control object, so the "repair" was a no-op while the
audit trail claimed success.

Expected Abaqus 2025 behaviour encoded below was verified on the installed
release by writing the input deck:

* ``StdContactControl(name=..., stabilizeChoice=AUTOMATIC, dampFactor=1e-4)``
  plus ``SurfaceToSurfaceContactStd(..., contactControls=<name>)`` emits
  ``*Contact Controls, main=..., secondary=..., stabilize=0.0001``.
* ``Contact control cannot be specified in initial step`` -- an Initial-step
  contact must be bound with ``setValuesInStep``, which emits
  ``*Contact Controls, reset`` followed by the new setting.
* ``ExplicitDynamicsStep`` refuses the stabilized interaction.
"""

import pytest

from abaqus_ai_agent.actions import builders
from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.contracts.contact_stabilization import (
    ContactStabilizationError,
    ContactStabilizationSpec,
    coerce_contact_stabilization,
    contact_control_script,
    resolve_contact_stabilization,
)
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.diagnostics.remediator import SolverRemediator
from abaqus_ai_agent.diagnostics.solver_patterns import DiagnosticIssue
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentInteractionSpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)

MATERIAL = MaterialDefinition(
    name="PA66",
    unit_system="MM_N_MPA",
    elastic=ElasticProperties(youngs_modulus=3000.0, poisson_ratio=0.35),
)


def _interaction(name="C1", step="Initial", **kwargs):
    return IntentInteractionSpec(
        name=name,
        master_region="S1",
        slave_region="S2",
        step=step,
        **kwargs,
    )


def _compile(interactions, *, step=None, steps=None, procedure=None, contract=None):
    return compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box"),
        material=MATERIAL,
        step=step,
        steps=steps,
        procedure=procedure,
        mesh=IntentMeshSpec(global_size=2.5, size_source="USER_SPECIFIED"),
        interactions=interactions,
        contact_stabilization=contract,
    )


# --- contract level -------------------------------------------------------

def test_spec_requires_explicit_damp_factor_for_automatic():
    with pytest.raises(ContactStabilizationError):
        ContactStabilizationSpec(stabilize_choice="AUTOMATIC", damp_factor=None)


def test_spec_rejects_symbols_abaqus_does_not_accept():
    # FRICTIONAL is not a constant in Abaqus 2025, and DAMPING_FACTOR is a
    # StaticStep symbol, not a contact stabilizeChoice.
    for value in ("FRICTIONAL", "DAMPING_FACTOR", "STABILIZE"):
        with pytest.raises(ContactStabilizationError):
            ContactStabilizationSpec(stabilize_choice=value, damp_factor=1e-4)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_spec_rejects_unusable_damp_factor(bad):
    with pytest.raises(ContactStabilizationError):
        ContactStabilizationSpec(damp_factor=bad)


def test_coerce_refuses_step_level_symbol_in_contact_context():
    with pytest.raises(ContactStabilizationError):
        coerce_contact_stabilization(
            {"stabilization_method": "DAMPING_FACTOR", "stabilization_magnitude": 1e-4}
        )


def test_coerce_accepts_remediator_style_payload():
    spec = coerce_contact_stabilization(
        {"contact_damping": True, "stabilization_magnitude": 1e-4, "stabilize_choice": "AUTOMATIC"}
    )
    assert spec.stabilize_choice == "AUTOMATIC"
    assert spec.damp_factor == 1e-4


def test_resolve_rejects_ambiguous_multiple_contacts():
    with pytest.raises(ContactStabilizationError) as excinfo:
        resolve_contact_stabilization(
            [_interaction("C1"), _interaction("C2")],
            ContactStabilizationSpec(damp_factor=1e-4),
            step_order=("Step-1",),
        )
    assert "ambiguous" in str(excinfo.value)


def test_resolve_rejects_unsupported_interaction_type():
    inter = IntentInteractionSpec(
        name="Tie-1", interaction_type="tie", master_region="S1", slave_region="S2"
    )
    with pytest.raises(ContactStabilizationError) as excinfo:
        resolve_contact_stabilization(
            [inter], ContactStabilizationSpec(damp_factor=1e-4), step_order=("Step-1",)
        )
    assert "not implemented" in str(excinfo.value)


def test_resolve_requires_explicit_target_for_multi_step():
    with pytest.raises(ContactStabilizationError) as excinfo:
        resolve_contact_stabilization(
            [_interaction("C1", step="Step-1")],
            ContactStabilizationSpec(damp_factor=1e-4),
            step_order=("Step-1", "Step-2"),
        )
    assert "explicit target_step" in str(excinfo.value)


def test_resolve_rejects_retroactive_binding():
    with pytest.raises(ContactStabilizationError):
        resolve_contact_stabilization(
            [_interaction("C1", step="Step-2")],
            ContactStabilizationSpec(damp_factor=1e-4, target_step="Step-1"),
            step_order=("Step-1", "Step-2"),
        )


def test_resolve_initial_step_contact_uses_step_override():
    _, bindings = resolve_contact_stabilization(
        [_interaction("C1", step="Initial")],
        ContactStabilizationSpec(damp_factor=1e-4, target_step="Step-1"),
        step_order=("Step-1",),
    )
    assert bindings[0].requires_step_override is True


def test_contact_control_script_targets_the_contact_object():
    _, bindings = resolve_contact_stabilization(
        [_interaction("C1", step="Step-1")],
        ContactStabilizationSpec(damp_factor=1e-4),
        step_order=("Step-1",),
    )
    code = contact_control_script(bindings[0], "M")
    assert "StdContactControl(" in code
    assert "stabilizeChoice=AUTOMATIC" in code
    assert "dampFactor=0.0001" in code
    assert "setValuesInStep" not in code


# --- script level ---------------------------------------------------------

def test_contact_action_with_stabilization_binds_controls():
    action = builders.contact(
        "M",
        name="C1",
        master_expression="a.surfaces['S1']",
        slave_expression="a.surfaces['S2']",
        property="Prop-1",
        step="Step-1",
        stabilization={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
    )
    code = action_to_script(action)
    assert "contactControls='CC-Stabilization'" in code
    assert "StdContactControl(name='CC-Stabilization'" in code
    assert "setValuesInStep" not in code


def test_contact_action_from_initial_step_overrides_in_step():
    action = builders.contact(
        "M",
        name="C1",
        master_expression="a.surfaces['S1']",
        slave_expression="a.surfaces['S2']",
        property="Prop-1",
        step="Initial",
        stabilization={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4, "target_step": "Step-1"},
    )
    code = action_to_script(action)
    assert "contactControls=" not in code.split("StdContactControl")[0]
    assert "setValuesInStep(stepName='Step-1', contactControls='CC-Stabilization')" in code


def test_initial_step_contact_without_target_is_refused():
    action = builders.contact(
        "M",
        name="C1",
        master_expression="a.surfaces['S1']",
        slave_expression="a.surfaces['S2']",
        property="Prop-1",
        step="Initial",
        stabilization={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
    )
    with pytest.raises(ValueError) as excinfo:
        action_to_script(action)
    assert "target_step" in str(excinfo.value)


# --- compiler level -------------------------------------------------------

def test_compiler_emits_contact_controls_for_single_static_step():
    plan = _compile(
        [_interaction("C1", step="Step-1")],
        step=IntentStepSpec(name="Step-1", step_type="static_general"),
        contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
    )
    assert "StdContactControl(" in plan.cae_script
    assert "contactControls='CC-Stabilization'" in plan.cae_script


def test_compiler_requests_allsd_only_for_stabilized_steps():
    """The ALLSD/ALLSE gate needs dissipation history that Abaqus does not preselect."""
    plan = _compile(
        [_interaction("C1", step="Step-1")],
        step=IntentStepSpec(name="Step-1", step_type="static_general"),
        contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
    )
    script = plan.cae_script
    assert "H-Energy-Stabilization" in script
    assert "ALLSD" in script
    assert "createStepName='Step-1'" in script


def test_compiler_does_not_request_allsd_without_stabilization():
    plan = _compile(
        [_interaction("C1", step="Step-1")],
        step=IntentStepSpec(name="Step-1", step_type="static_general"),
    )
    assert "ALLSD" not in plan.cae_script


def test_compiler_refuses_contact_stabilization_in_explicit_dynamic():
    with pytest.raises(ContactStabilizationError) as excinfo:
        _compile(
            [_interaction("C1", step="Step-1")],
            step=IntentStepSpec(name="Step-1", step_type="explicit_dynamic"),
            contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
        )
    assert "implicit analysis step" in str(excinfo.value)


def test_compiler_refuses_contact_stabilization_without_contact():
    with pytest.raises(ContactStabilizationError):
        _compile(
            [],
            step=IntentStepSpec(name="Step-1", step_type="static_general"),
            contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
        )


def test_compiler_refuses_ambiguous_multi_contact_target():
    with pytest.raises(ContactStabilizationError) as excinfo:
        _compile(
            [_interaction("C1", step="Step-1"), _interaction("C2", step="Step-1")],
            step=IntentStepSpec(name="Step-1", step_type="static_general"),
            contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
        )
    assert "ambiguous" in str(excinfo.value)


def test_compiler_requires_target_step_across_multiple_static_steps():
    with pytest.raises(ContactStabilizationError) as excinfo:
        _compile(
            [_interaction("C1", step="Step-1")],
            steps=[
                IntentStepSpec(name="Step-1", step_type="static_general"),
                IntentStepSpec(name="Step-2", step_type="static_general", previous="Step-1"),
            ],
            contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4},
        )
    assert "explicit target_step" in str(excinfo.value)


def test_compiler_honours_explicit_target_step_across_multiple_steps():
    plan = _compile(
        [_interaction("C1", step="Step-1")],
        steps=[
            IntentStepSpec(name="Step-1", step_type="static_general"),
            IntentStepSpec(name="Step-2", step_type="static_general", previous="Step-1"),
        ],
        contract={"stabilize_choice": "AUTOMATIC", "damp_factor": 1e-4, "target_step": "Step-2"},
    )
    assert "setValuesInStep(stepName='Step-2', contactControls='CC-Stabilization')" in plan.cae_script


# --- step_controls routing (the silent-drop defect) -----------------------

def _intent(**metadata):
    return EngineeringIntent(
        id="INT-1",
        kind="linear_static",
        description="contact chatter with step controls",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        metadata=metadata,
    )


def test_step_controls_reach_single_step_path():
    intent = _intent(step_controls={"initial_inc": 0.01, "min_inc": 1e-8, "max_num_inc": 500})
    plan = compile_engineering_intent(
        intent,
        geometry=IntentGeometrySpec(shape="cantilever_box"),
        mesh=IntentMeshSpec(global_size=2.5, size_source="USER_SPECIFIED"),
    )
    assert "initialInc=0.01" in plan.cae_script
    assert "minInc=1e-08" in plan.cae_script
    assert "maxNumInc=500" in plan.cae_script


def test_step_controls_reach_steps_list_path():
    intent = _intent(
        step_controls={"initial_inc": 0.02, "min_inc": 1e-7, "max_num_inc": 300},
        steps=[
            IntentStepSpec(name="Step-1", step_type="static_general"),
            IntentStepSpec(name="Step-2", step_type="static_general", previous="Step-1"),
        ],
    )
    plan = compile_engineering_intent(
        intent,
        geometry=IntentGeometrySpec(shape="cantilever_box"),
        mesh=IntentMeshSpec(global_size=2.5, size_source="USER_SPECIFIED"),
    )
    script = plan.cae_script
    assert script.count("initialInc=0.02") == 2
    assert script.count("minInc=1e-07") == 2
    assert script.count("maxNumInc=300") == 2


def test_step_controls_reach_procedure_path():
    from abaqus_ai_agent.contracts.procedure import MultiStepProcedureSpec, StepDependency

    intent = _intent(
        step_controls={"initial_inc": 0.03, "min_inc": 1e-6, "max_num_inc": 250},
        procedure=MultiStepProcedureSpec(
            steps=(
                StepDependency(name="Step-1", procedure="static"),
                StepDependency(name="Step-2", procedure="static", previous="Step-1"),
            )
        ),
    )
    plan = compile_engineering_intent(
        intent,
        geometry=IntentGeometrySpec(shape="cantilever_box"),
        mesh=IntentMeshSpec(global_size=2.5, size_source="USER_SPECIFIED"),
    )
    script = plan.cae_script
    assert script.count("initialInc=0.03") == 2
    assert script.count("maxNumInc=250") == 2


def test_contact_damping_never_reaches_step_controls_end_to_end():
    intent = EngineeringIntent(
        id="INT-2",
        kind="contact_analysis",
        description="contact chatter",
        analysis_type="general_contact",
    )
    issue = DiagnosticIssue(
        diagnosis_id="CONTACT_CHATTER",
        severity="WARNING",
        supporting_evidence=("***WARNING: CONTACT CHATTER",),
        likely_cause="opening/closing oscillation",
        suggested_remediation="contact stabilization",
    )
    actions = SolverRemediator.generate_remediations([issue], intent)
    healed = SolverRemediator.apply_remediations(intent, actions)

    assert "contact_damping" not in healed.metadata.get("step_controls", {})
    proposals = [
        item for item in healed.metadata["proposed_remediations"]
        if item["category"] == "CONTACT_STABILIZATION"
    ]
    assert proposals[-1]["applied"] is False
    assert proposals[-1]["parameters"]["contact_damping"] is True
    assert "contact_stabilization" not in healed.metadata
