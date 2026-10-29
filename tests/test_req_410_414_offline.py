"""Offline coverage for REQ-4.10 through REQ-4.14.

These tests do not open an ODB, submit a job, or claim machine validation.
"""

from types import SimpleNamespace

import pytest

from abaqus_ai_agent.adapters.abaqus.locator_validation import (
    locator_guard_script,
    reject_locator_identity,
    validate_locator,
)
from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.contact_diagnostics import diagnose_contact_from_odb
from abaqus_ai_agent.contracts.diagnostics import (
    RemediationAction,
    RemediationCategory,
    RemediationRisk,
)
from abaqus_ai_agent.contracts.geometry import GeometryCandidate
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.task import TaskStatus
from abaqus_ai_agent.diagnostics.remediator import SolverRemediator
from abaqus_ai_agent.execution.analysis_run import (
    _contact_step_name,
    _decode_contact_evidence,
    _note_verification_entries,
)
from abaqus_ai_agent.execution.convergence_loop import (
    default_runner_convergence_note,
    run_explicit_convergence_study,
)
from abaqus_ai_agent.execution.odb import extract_contact_evidence
from abaqus_ai_agent.contracts.mesh import LocalSeed
from abaqus_ai_agent.planning.compiler import IntentMeshSpec, _guarded_find_at
from abaqus_ai_agent.sensitivity import sensitivity_from_intent


def _intent(**metadata):
    return EngineeringIntent(
        id="REQ-OFFLINE",
        kind="contact",
        description="offline contract",
        metadata=metadata,
    )


def _field(status="available", data=(1.0,)):
    return {
        "status": status,
        "values": [{"data": value} for value in data],
    }


def _consistent_fields():
    return {
        "CSTATUS": _field(data=(1.0,)),
        "COPEN": _field(data=(0.0,)),
        "CPRESS": _field(data=(10.0,)),
    }


def _expected(**extra):
    payload = {
        "declared": True,
        "contact_required": True,
        "expected_state": "contact",
        "expected_separation": 0.0,
        "allowed_initial_interference": 0.0,
    }
    payload.update(extra)
    return payload


class _CountingExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, code, timeout=None):
        self.calls.append(code)
        raise AssertionError("offline path must not execute Abaqus")


def test_contact_missing_expectation_is_not_a_pass():
    report = diagnose_contact_from_odb(
        _intent(contact_diagnostic_requested=True),
        {"fields": _consistent_fields()},
    )
    assert report.passed is False
    assert report.diagnostics[0].status == "insufficient_evidence"


def test_contact_missing_field_is_not_a_pass():
    fields = _consistent_fields()
    fields["CPRESS"] = {"status": "unavailable", "reason": "field_output_missing"}
    report = diagnose_contact_from_odb(
        _intent(expected_contact=_expected()),
        {"fields": fields, "history": {"status": "available"}},
    )
    assert report.diagnostics[0].status == "insufficient_evidence"


def test_contact_field_conflict_is_not_a_pass():
    fields = _consistent_fields()
    fields["CSTATUS"] = {"status": "ambiguous", "reason": "multiple_history_regions"}
    report = diagnose_contact_from_odb(
        _intent(expected_contact=_expected()),
        {"fields": fields},
    )
    assert report.diagnostics[0].status == "insufficient_evidence"


def test_three_consistent_contact_fields_can_be_diagnosed():
    report = diagnose_contact_from_odb(
        _intent(expected_contact=_expected()),
        {
            "region": None,
            "fields": _consistent_fields(),
            "history": {"status": "available"},
        },
    )
    assert report.diagnostics[0].status == "pass"
    assert any(item.name == "expected_contact_state" and item.status == "pass"
               for item in report.diagnostics)


def test_contact_step_uses_declaration_and_refuses_to_guess():
    declared, reason = _contact_step_name(
        _intent(contact_step="Load"),
        {"steps": ["Initial", "Other", "Load"]},
    )
    assert declared == "Load"
    assert reason is None

    only, only_reason = _contact_step_name(
        _intent(expected_contact=_expected()),
        {"steps": ["Initial", "Step-1"]},
    )
    assert only == "Step-1"
    assert only_reason is None

    missing, missing_reason = _contact_step_name(
        _intent(expected_contact=_expected()),
        {"steps": ["Step-1", "Step-2"]},
    )
    assert missing is None
    assert missing_reason == "contact_step_not_declared"


def test_contact_evidence_decodes_executor_repr_without_inventing_region():
    raw = {
        "step": "Step-1",
        "region": None,
        "fields": {
            "CSTATUS": "{'status': 'available', 'values': [{'data': 1.0}]}",
            "COPEN": "{'status': 'available', 'values': [{'data': 0.0}]}",
            "CPRESS": "{'status': 'available', 'values': [{'data': 12.5}]}",
        },
        "history": "{'status': 'available', 'variables': {}}",
    }
    decoded = _decode_contact_evidence(raw)
    assert decoded["region"] is None
    assert decoded["fields"]["CPRESS"]["values"][0]["data"] == 12.5
    assert decoded["history"]["status"] == "available"


def test_contact_extraction_script_is_read_only_and_does_not_submit():
    calls = []

    def execute(code, timeout=None):
        calls.append(code)
        return "{'status': 'unavailable'}"

    executor = SimpleNamespace(execute=execute)
    extract_contact_evidence(executor, "job.odb", "Step-1")
    joined = "\n".join(calls)
    assert "openOdb" in joined
    assert "readOnly=True" in joined
    assert "mdb.Job" not in joined
    assert ".submit(" not in joined


def test_default_convergence_note_does_not_solve():
    executor = _CountingExecutor()
    note = default_runner_convergence_note(_intent(), mesh_quality=SimpleNamespace(status="pass"))
    assert note["status"] == "NOT_CONVERGENCE"
    assert note["extra_solves"] == 0
    assert note["converged"] is False
    assert executor.calls == []


def test_incomplete_convergence_request_is_refused():
    note = default_runner_convergence_note(_intent(mesh_convergence_study={
        "requested": True,
        "quantity": "mises",
    }))
    assert note["status"] == "NOT_CONVERGENCE"
    assert note["explicit_request"] is True
    assert note["extra_solves"] == 0
    assert str(note["study_refused"]).startswith("convergence_study_refused:")


def test_explicit_three_level_plan_is_recorded_without_a_default_solve():
    note = default_runner_convergence_note(_intent(mesh_convergence_study={
        "requested": True,
        "quantity": "mises",
        "location": "notch",
        "refinement_ratio": 0.5,
        "levels": 3,
    }))
    assert note["status"] == "NOT_EXECUTED"
    assert note["levels"] == 3
    assert note["extra_solves"] == 0


def test_declared_singularity_is_not_reported_as_converged():
    calls = []

    def step_runner(level, spec):
        calls.append(level)
        return object(), {
            "peak_s11": 100.0 + level * 0.01,
            "max_u1": 1.0,
            "rf_error_pct": 0.0,
            "global_size": 8.0 / (2 ** (level - 1)),
        }

    outcome, notes = run_explicit_convergence_study(
        _intent(mesh_convergence_study={
            "requested": True,
            "quantity": "peak_s11",
            "location": "reentrant_corner",
            "refinement_ratio": 0.5,
            "levels": 3,
            "singularity_locations": ("reentrant_corner",),
        }),
        step_runner,
        IntentMeshSpec(
            global_size=8.0,
            size_source="USER_SPECIFIED",
            local_seeds=(LocalSeed(region_expression="edge", size=4.0),),
         primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED'),
    )
    assert len(calls) == 3
    assert outcome.status == "SINGULARITY_REPORTED"
    assert outcome.is_converged is False
    assert notes == ("singularity_reported:reentrant_corner",)


def test_notes_use_independent_verification_keys():
    entries = _note_verification_entries(
        {"status": "NOT_CONVERGENCE", "extra_solves": 0},
        {"scope": "local_screening", "cases": ()},
    )
    assert set(entries) == {"mesh_convergence_note", "sensitivity_note"}
    assert "mesh_convergence" not in entries
    assert "sensitivity" not in entries


def test_integer_locator_is_rejected_but_catalog_index_is_not():
    face = object()
    catalog = GeometryCandidate(
        entity_type="Face",
        name="P-1",
        index=1,
        centroid=(1.0, 2.0, 3.0),
        normal=(0.0, 0.0, 1.0),
        area=1.0,
        distance_score=1.0,
        visual_score=1.0,
        topology_score=1.0,
        locator_point=(1.0, 2.0, 3.0),
    )
    assert reject_locator_identity(catalog) is None
    assert validate_locator(SimpleNamespace(faces=_Repo([face], face)), catalog).valid

    integer = SimpleNamespace(entity_id=7, locator_point=None, centroid=None)
    assert reject_locator_identity(integer) == "integer_id_not_a_locator"


class _Repo:
    def __init__(self, entities, result):
        self.entities = entities
        self.result = result

    def findAt(self, coordinates):
        return self.result

    def __iter__(self):
        return iter(self.entities)


def test_non_unique_findat_is_rejected():
    first, second = object(), object()
    candidate = GeometryCandidate(
        entity_type="Face", name="P-1", index=1,
        centroid=(1.0, 2.0, 3.0), normal=(0.0, 0.0, 1.0), area=1.0,
        distance_score=1.0, visual_score=1.0, topology_score=1.0,
        locator_point=(1.0, 2.0, 3.0),
    )
    result = validate_locator(
        SimpleNamespace(faces=_Repo([first, second], (first, second))),
        candidate,
    )
    assert result.valid is False
    assert result.reason == "findAt_not_unique"


def test_generated_region_script_injects_locator_guard():
    script = _guarded_find_at("a.instances['Part-1-1'].faces", "((1.0, 2.0, 3.0),)", "BC-1")
    assert "_abqai_bind_region" in script
    assert "findAt_not_unique" in locator_guard_script()
    assert "integer_id_or_bad_point" in script


def _proposal(category):
    return RemediationAction(
        action_id="offline",
        category=category,
        diagnosis_id="OFFLINE",
        description="proposal only",
        parameters={"must_not_apply": True},
        risk_level=RemediationRisk.HIGH,
    )


@pytest.mark.parametrize("category", [
    RemediationCategory.BOUNDARY_CONDITION,
    RemediationCategory.DAMPING,
    RemediationCategory.CONTACT_STABILIZATION,
])
def test_confirmed_model_change_still_does_not_apply_physics(category):
    intent = _intent(confirm_model_change=True)
    updated = SolverRemediator.apply_remediations(intent, (_proposal(category),))
    assert updated.boundary_conditions == ()
    assert updated.metadata["model_change_auto_apply"] is False
    proposal = updated.metadata["proposed_remediations"][-1]
    assert proposal["applied"] is False
    assert proposal["requires_new_engineering_decision"] is True
    assert "boundary_conditions" not in updated.metadata
    assert "damping" not in updated.metadata
    assert "contact_stabilization" not in updated.metadata


def test_sensitivity_defaults_to_no_study():
    assert sensitivity_from_intent(_intent()) is None


def test_sensitivity_without_source_is_refused_and_not_solved():
    report = sensitivity_from_intent(_intent(sensitivity_study={
        "requested": True,
        "cases": [{"name": "load", "factors": {"load": {"value": 1.1}}}],
    }))
    assert report.cases[0].status == "refused"
    assert "missing_source" in report.cases[0].diagnostics[0]["error"]


def test_one_factor_sensitivity_is_a_plan_not_a_solve():
    plan = sensitivity_from_intent(_intent(sensitivity_study={
        "requested": True,
        "cases": [{
            "name": "load",
            "factors": {"load": {"value": 1.1, "source": "drawing_note"}},
        }],
    }))
    assert plan["scope"] == "local_screening"
    assert plan["baseline_frozen"] is True
    assert plan["cases"][0]["source"] == "drawing_note"
    assert "executed" not in plan


def test_product_entry_rejects_injected_contact_diagnostics():
    result = AbaqusAIAgent(executor=None).solve_requirement(
        _intent(),
        contact_diagnostics=object(),
        submit_job=False,
    )
    assert result.status == TaskStatus.BLOCKED
    assert result.summary_card["status"] == "INJECTION_BLOCKED"
    assert "contact_diagnostics" in result.summary_card["forbidden_keys"]
