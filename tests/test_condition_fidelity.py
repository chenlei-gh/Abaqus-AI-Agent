"""Condition fidelity must fail closed without inventing plating or indenter data."""

import hashlib

import pytest

from abaqus_ai_agent.contracts.condition import (
    ConditionContractError,
    ContactLoadingSpec,
    SurfaceTreatmentSpec,
)
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.provenance import attach_delivery_stamp, AnalysisProvenance, verify_deliverable
from abaqus_ai_agent.contracts.report import ReportFigure
from abaqus_ai_agent.reasoning.engine import IntentReasoningEngine
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.validation.condition_fidelity import audit_condition_fidelity


def _beam_intent(**overrides):
    payload = dict(
        id="MS13L-HANDLE",
        kind="linear_static",
        description="Analyze the plated handle. A block pushes the handle; it is not a fixed connection.",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "PA66", "elastic_modulus": 3000.0, "poisson_ratio": 0.35},
        boundary_conditions=({"type": "ENCASTRE", "region": "MountFace"},),
        loads=({"type": "concentrated_force", "region": "HandleFace", "magnitude": 50.0, "direction": "CF2"},),
        metadata={"geometry": {"shape": "cantilever_box", "length": 80.0, "width": 12.0, "height": 8.0}},
    )
    payload.update(overrides)
    return EngineeringIntent(**payload)


def test_plating_word_does_not_invent_thickness_or_modulus():
    verdict = audit_condition_fidelity(_beam_intent())
    assert verdict["formal_model_allowed"] is False
    assert "coating_claim_without_surface_treatment_spec" in verdict["blockers"]
    assert "point_force_is_not_indenter_contact" in verdict["blockers"]
    assert verdict["surface_treatments"] == ()


def test_unknown_surface_treatment_cannot_authorize_a_formal_conclusion():
    spec = SurfaceTreatmentSpec(name="chrome", evidence_status="UNKNOWN")
    verdict = audit_condition_fidelity(_beam_intent(), surface_treatments=(spec,))
    assert spec.authorizes_formal_conclusion is False
    assert "surface_treatment_thickness_unknown" in verdict["blockers"]
    assert "surface_treatment_modulus_unknown" in verdict["blockers"]
    assert "surface_treatment_failure_modes_not_separated" in verdict["blockers"]


def test_assumed_numbers_remain_assumptions():
    spec = SurfaceTreatmentSpec(
        name="chrome",
        evidence_status="ASSUMED",
        source="unverified example",
        covered_region="OuterSkin",
        region_resolved=True,
        thickness=0.03,
        elastic_modulus=180000.0,
        critical_tensile_strain=0.012,
        failure_modes=("substrate_yield", "coating_crack", "interface_debond"),
    )
    assert spec.authorizes_formal_conclusion is False
    assert "surface_treatment_evidence_assumed" in spec.gaps()


def test_user_specified_contact_loading_can_authorize_only_with_complete_evidence():
    spec = ContactLoadingSpec(
        name="push_block",
        application="rigid_indenter_contact",
        evidence_status="USER_SPECIFIED",
        source="engineer confirmation 2026-03-20",
        target_region="HandlePocket",
        region_resolved=True,
        indenter_geometry="rectangular_block",
        indenter_width=18.0,
        indenter_length=12.0,
        dimension_unit="mm",
        direction="-Y",
        control="force",
        friction_coefficient=0.2,
        friction_source="engineer specified dry contact",
        user_confirmed=True,
    )
    verdict = audit_condition_fidelity(
        _beam_intent(description="Handle strength check"),
        contact_loadings=(spec,),
        contacts=({"name": "BlockToHandle", "master": "Block", "slave": "HandlePocket"},),
    )
    assert spec.authorizes_formal_model is True
    assert "point_force_is_not_indenter_contact" not in verdict["blockers"]


def test_regulation_name_cannot_be_stored_as_a_fixture_mapping():
    with pytest.raises(ConditionContractError, match="regulation"):
        ContactLoadingSpec(
            name="ece",
            application="rigid_indenter_contact",
            evidence_status="ASSUMED",
            regulation_mapping="ECE R21",
            regulation_verified=False,
        )


def test_reasoning_blocks_unresolved_plating_and_indenter_claims():
    result = IntentReasoningEngine.reason(_beam_intent())
    assert result.is_executable is False
    assert any("Condition fidelity is unresolved" in item for item in result.blockers)
    assert any("coating_claim_without_surface_treatment_spec" in item for item in result.blockers)


def test_plain_beam_without_coating_or_indenter_claim_is_not_blocked_by_this_gate():
    intent = _beam_intent(description="Cantilever beam under a tip force")
    result = IntentReasoningEngine.reason(intent)
    assert not any("condition fidelity" in item for item in result.blockers)


def test_formal_report_without_preprocessing_figures_is_blocked(tmp_path):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"odb-bytes-for-figure-gate")
    odb_hash = hashlib.sha256(odb.read_bytes()).hexdigest()
    provenance = attach_delivery_stamp(AnalysisProvenance(
        run_id="run-fig",
        model_name="Handle",
        job_name="Job-1",
        input_hash="a" * 64,
        output_hash=odb_hash,
        executor="BatchExecutor",
        metadata={"agent_issued": True, "agent_entry": "solve_requirement", "requirement_kind": "engineering_intent"},
    ))
    gate = verify_deliverable({
        "provenance": provenance.to_dict(),
        "results": [{"name": "u", "value": 1.0}],
        "odb_path": "job.odb",
        "require_preprocessing_figures": True,
        "figures": [{"kind": "stress_contour", "path": "stress.png"}],
    })
    assert gate["deliverable_file_allowed"] is False
    assert any(item.startswith("formal_report_missing_preprocessing_figures") for item in gate["reasons"])

    class _Acceptance:
        status = "PASS"
        deliverable = True

    pipeline = DeterministicReportPipeline()
    with pytest.raises(PermissionError, match="preprocessing evidence"):
        pipeline.build_and_render(
            output_dir=tmp_path,
            title="Handle",
            case_id="Job-1",
            run_id="run-fig",
            model_info={"name": "Handle"},
            results_info=(),
            provenance=provenance,
            acceptance_info=_Acceptance(),
            figures=(ReportFigure(kind="stress_contour", path=str(tmp_path / "stress.png"), caption="stress"),),
            visualization_specs=(),
            odb_path=str(odb),
            input_hash="a" * 64,
            required_preprocessing_figures=("boundary_conditions", "contact_definition", "load_application"),
        )
    assert not (tmp_path / "report.html").exists()
