"""Delivery authorization contract: request, grant, and write are distinct.

These cases exist because the gate could refuse a record while the pipeline and
the file writer still produced a formal report from the same evidence.
"""

import json

import pytest

from abaqus_ai_agent.cli import main
from abaqus_ai_agent.contracts.provenance import verify_deliverable
from abaqus_ai_agent.reporting.delivery import write_gated_engineering_report

from test_delivery_gate import _stamped

# --- C-1 / C-2 negative cases: a refused delivery must not leave a formal file ---


def _granted_inputs(*, fidelity_blockers=()):
    from abaqus_ai_agent.validation.condition_fidelity import audit_condition_fidelity

    issued = _stamped(jev_routed=True)
    fidelity = dict(audit_condition_fidelity())
    if fidelity_blockers:
        fidelity["passed"] = False
        fidelity["formal_report_allowed"] = False
        fidelity["blockers"] = list(fidelity_blockers)
    return issued, {
        "provenance": issued,
        "results": [],
        "odb_sha256": issued.output_hash,
        "acceptance": {"status": "PASS", "deliverable": True},
        "condition_fidelity": fidelity,
    }


def test_fidelity_blocker_blocks_pipeline_formal_write(tmp_path, monkeypatch):
    """The blocker that the direct gate refuses must also be refused by the pipeline."""
    import hashlib

    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record
    from abaqus_ai_agent.reporting.figure_selector import FigureSelectionResult, FigureSelector
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
    from abaqus_ai_agent.validation.condition_fidelity import audit_condition_fidelity

    # Not under test here: figure selection needs a live Abaqus Viewer session.
    monkeypatch.setattr(
        FigureSelector,
        "select_figures",
        lambda *a, **k: FigureSelectionResult(scenario="none"),
    )

    odb = tmp_path / "job.odb"
    odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha = hashlib.sha256(odb.read_bytes()).hexdigest()
    issued = issue_agent_run_record(
        model_snapshot_hash='snap-test',
        content_hash_scope='content-test',
        action_plan_scope='plan-test',
        run_id="run-blocked",
        model_name="Blocked",
        job_name="case_blocked",
        input_hash="a" * 64,
        output_hash=odb_sha,
        requirement_kind="engineering_intent",
        jev_routed=False,
    )
    fidelity = dict(audit_condition_fidelity())
    fidelity["passed"] = False
    fidelity["formal_report_allowed"] = False
    fidelity["blockers"] = ["interface_modelled_as_tie_not_contact"]
    assert verify_deliverable(
        {
            "provenance": issued,
            "results": [],
            "acceptance": {"status": "PASS", "deliverable": True},
            "condition_fidelity": fidelity,
        }
    )["deliverable_file_allowed"] is False

    pipeline = DeterministicReportPipeline()
    with pytest.raises(PermissionError, match="interface_modelled_as_tie_not_contact"):
        pipeline.build_and_render(
            output_dir=tmp_path,
            title="Blocked",
            case_id="case_blocked",
            run_id="run-blocked",
            model_info={"name": "Blocked"},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            require_deliverable=True,
            provenance=issued,
            input_hash="a" * 64,
            odb_path=odb,
            condition_fidelity=fidelity,
        )
    assert not (tmp_path / "report.html").exists()


def test_fidelity_blocker_blocks_writer_formal_write(tmp_path):
    _, inputs = _granted_inputs(fidelity_blockers=("interface_modelled_as_tie_not_contact",))
    formal = tmp_path / "report.html"
    with pytest.raises(PermissionError, match="interface_modelled_as_tie_not_contact"):
        write_gated_engineering_report(
            formal,
            record=inputs,
            content="<html><body>claim</body></html>",
            allow_diagnostic_draft=False,
        )
    assert not formal.exists()


def test_non_kinematic_fidelity_blocker_blocks_pipeline_formal_write(tmp_path, monkeypatch):
    """A non-kinematic fidelity blocker (e.g. an unverifiable coating claim) must
    also be refused by the pipeline, not just tie-vs-contact kinematics."""
    import hashlib

    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record
    from abaqus_ai_agent.reporting.figure_selector import FigureSelectionResult, FigureSelector
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
    from abaqus_ai_agent.validation.condition_fidelity import audit_condition_fidelity

    monkeypatch.setattr(
        FigureSelector,
        "select_figures",
        lambda *a, **k: FigureSelectionResult(scenario="none"),
    )

    odb = tmp_path / "job.odb"
    odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    odb_sha = hashlib.sha256(odb.read_bytes()).hexdigest()
    issued = issue_agent_run_record(
        model_snapshot_hash='snap-test',
        content_hash_scope='content-test',
        action_plan_scope='plan-test',
        run_id="run-blocked-coating",
        model_name="BlockedCoating",
        job_name="case_blocked_coating",
        input_hash="a" * 64,
        output_hash=odb_sha,
        requirement_kind="engineering_intent",
        jev_routed=False,
    )
    fidelity = dict(audit_condition_fidelity())
    fidelity["passed"] = False
    fidelity["formal_report_allowed"] = False
    fidelity["blockers"] = ["coating_claim_without_surface_treatment_spec"]
    assert verify_deliverable(
        {
            "provenance": issued,
            "results": [],
            "acceptance": {"status": "PASS", "deliverable": True},
            "condition_fidelity": fidelity,
        }
    )["deliverable_file_allowed"] is False

    pipeline = DeterministicReportPipeline()
    with pytest.raises(PermissionError, match="coating_claim_without_surface_treatment_spec"):
        pipeline.build_and_render(
            output_dir=tmp_path,
            title="BlockedCoating",
            case_id="case_blocked_coating",
            run_id="run-blocked-coating",
            model_info={"name": "BlockedCoating"},
            results_info=(),
            acceptance_info={"status": "PASS", "deliverable": True},
            require_deliverable=True,
            provenance=issued,
            input_hash="a" * 64,
            odb_path=odb,
            condition_fidelity=fidelity,
        )
    assert not (tmp_path / "report.html").exists()


def test_missing_acceptance_is_blocked_not_downgraded(tmp_path):
    """Absent evidence must never be read as a passing verdict."""
    from abaqus_ai_agent.validation.condition_fidelity import audit_condition_fidelity

    issued = _stamped(jev_routed=True)
    gate = verify_deliverable(
        {
            "provenance": issued,
            "results": [],
            "condition_fidelity": audit_condition_fidelity(),
        },
        require_decision_inputs=True,
    )
    assert gate["status"] == "BLOCKED"
    assert "missing_acceptance_verdict" in gate["reasons"]


def test_missing_fidelity_is_blocked_not_downgraded():
    issued = _stamped(jev_routed=True)
    gate = verify_deliverable(
        {"provenance": issued, "results": [], "acceptance": {"status": "PASS", "deliverable": True}},
        require_decision_inputs=True,
    )
    assert gate["status"] == "BLOCKED"
    assert "missing_condition_fidelity" in gate["reasons"]


def test_acceptance_not_granted_blocks_even_with_clean_fidelity():
    from abaqus_ai_agent.validation.condition_fidelity import audit_condition_fidelity

    issued = _stamped(jev_routed=True)
    gate = verify_deliverable(
        {
            "provenance": issued,
            "results": [],
            "acceptance": {"status": "PASS", "deliverable": False},
            "condition_fidelity": audit_condition_fidelity(),
        },
        require_decision_inputs=True,
    )
    assert gate["status"] == "BLOCKED"
    assert "acceptance_not_granted" in gate["reasons"]


def test_refused_formal_write_leaves_preexisting_report_untouched_path_free(tmp_path):
    """A refusal must not create the formal file even when the directory already exists."""
    formal = tmp_path / "engineering_report.html"
    formal.write_text("<html>stale</html>", encoding="utf-8")
    _, inputs = _granted_inputs(fidelity_blockers=("contact_loading_has_no_contact_definition",))
    with pytest.raises(PermissionError):
        write_gated_engineering_report(
            formal,
            record=inputs,
            content="<html><body>new</body></html>",
            allow_diagnostic_draft=False,
        )
    assert formal.read_text(encoding="utf-8") == "<html>stale</html>"


def test_writer_reports_delivery_failure_without_claiming_a_deliverable(tmp_path):
    """Granted authorization is not a written deliverable."""
    issued, inputs = _granted_inputs()
    target = tmp_path / "report.html"
    target.mkdir()  # A directory at the target path makes the write fail.
    written = write_gated_engineering_report(
        target,
        record=inputs,
        content="<html><body>x</body></html>",
        allow_diagnostic_draft=False,
    )
    assert written["delivery_granted"] is True
    assert written["delivery_written"] is False
    assert written["kind"] == "delivery_write_failed"
    assert written["write_error"]


def test_cli_report_refuses_formal_write_when_fidelity_blocks(tmp_path, capsys):
    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record

    issued = issue_agent_run_record(
        model_snapshot_hash='snap-test',
        content_hash_scope='content-test',
        action_plan_scope='plan-test',
        run_id="run-cli-block",
        model_name="Handle",
        job_name="Job-1",
        output_hash="c" * 64,
        jev_routed=False,
        requirement_kind="engineering_intent",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "case_id": "probe",
                "odb_path": "job.odb",
                "results": {"max_mises": 1.0},
                "acceptance": {"status": "PASS", "deliverable": True},
                "condition_fidelity": {
                    "passed": False,
                    "formal_report_allowed": False,
                    "blockers": ["interface_modelled_as_tie_not_contact"],
                },
                "provenance": issued.to_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "customer" / "report"
    ret = main(["report", str(evidence), "-o", str(out)])
    err = capsys.readouterr().err
    assert ret == 2
    assert "interface_modelled_as_tie_not_contact" in err
    assert not out.with_suffix(".html").exists()


def test_cli_report_refuses_formal_write_when_fidelity_missing(tmp_path, capsys):
    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record

    issued = issue_agent_run_record(
        model_snapshot_hash='snap-test',
        content_hash_scope='content-test',
        action_plan_scope='plan-test',
        run_id="run-cli-no-fid",
        model_name="Handle",
        job_name="Job-1",
        output_hash="c" * 64,
        jev_routed=False,
        requirement_kind="engineering_intent",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "case_id": "probe",
                "odb_path": "job.odb",
                "results": {"max_mises": 1.0},
                "acceptance": {"status": "PASS", "deliverable": True},
                "provenance": issued.to_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "customer" / "report"
    ret = main(["report", str(evidence), "-o", str(out)])
    err = capsys.readouterr().err
    assert ret == 2
    assert "missing_condition_fidelity" in err
    assert not out.with_suffix(".html").exists()


# --- C-2 / B1: interface kinematics producer ---


def test_separation_question_modelled_only_as_tie_is_flagged():
    from abaqus_ai_agent.validation.condition_fidelity import audit_interface_kinematics

    verdict = audit_interface_kinematics(
        description="Silver button pull-off until unclipping; report the detent release force",
        plan_actions=({"action_type": "tie", "parameters": {}},),
    )
    assert verdict["separation_required"] is True
    assert "interface_modelled_as_tie_not_contact" in verdict["blockers"]


def test_tie_is_fine_when_no_separation_is_required():
    from abaqus_ai_agent.validation.condition_fidelity import audit_interface_kinematics

    verdict = audit_interface_kinematics(
        description="Linear static cantilever under a tip force",
        plan_actions=({"action_type": "tie", "parameters": {}},),
    )
    assert verdict["separation_required"] is False
    assert verdict["blockers"] == ()


def test_separation_with_contact_instead_of_tie_is_not_blocked():
    from abaqus_ai_agent.validation.condition_fidelity import audit_interface_kinematics

    verdict = audit_interface_kinematics(
        description="Snap-fit insertion until the latch releases",
        plan_actions=({"action_type": "contact", "parameters": {}},),
    )
    assert verdict["separation_required"] is True
    assert verdict["blockers"] == ()


def test_declared_open_expected_state_requires_separation():
    from abaqus_ai_agent.validation.condition_fidelity import audit_interface_kinematics

    verdict = audit_interface_kinematics(
        description="Static preload case",
        contacts=({"expected_state": "open"},),
        plan_actions=({"action_type": "tie", "parameters": {}},),
    )
    assert verdict["separation_required"] is True
    assert "interface_modelled_as_tie_not_contact" in verdict["blockers"]


def test_compile_refuses_tie_only_plan_for_separation_question():
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.planning.compiler import (
        IntentGeometrySpec,
        IntentInteractionSpec,
        compile_engineering_intent,
    )

    intent = EngineeringIntent(
        id="UNCLIP",
        kind="static",
        description="Pull the silver button until the detent releases (unclipping)",
        boundary_conditions=(
            {"type": "encastre", "region": "Base", "grounded_region": {"target": "Base"}},
        ),
        loads=(
            {
                "type": "concentrated_force",
                "region": "Button",
                "magnitude": 120.0,
                "direction": "-Z",
                "grounded_region": {"target": "Button"},
            },
        ),
        contacts=(
            IntentInteractionSpec(
                name="Tie1",
                interaction_type="tie",
                master_region="Base",
                slave_region="Button",
            ),
        ),
    )
    with pytest.raises(ValueError, match="interface_modelled_as_tie_not_contact"):
        compile_engineering_intent(
            intent,
            geometry=IntentGeometrySpec(shape="cantilever_box", length=10.0, width=10.0, height=10.0),
            material=MaterialDefinition(
                name="Steel",
                unit_system="MM_N_MPA",
                elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
            ),
        )


# --- Declared figure kinds must not be flattened into "all formal figures" ---


def _figure(kind, name="f.png"):
    return {"kind": kind, "path": name, "caption": kind}


def test_writer_honours_declared_figure_kinds_only(tmp_path):
    """A record naming one figure kind must not be judged against all three.

    The callers used to pass `bool(require_preprocessing_figures)`, which erased
    the declared kinds and made the gate demand every formal preprocessing
    figure. A report that only claims a boundary-condition figure was therefore
    refused even though it satisfied what it declared.
    """
    _, inputs = _granted_inputs()
    inputs["figures"] = [_figure("boundary_conditions")]
    inputs["required_preprocessing_figures"] = ["boundary_conditions"]
    formal = tmp_path / "report.html"
    written = write_gated_engineering_report(
        formal,
        record=inputs,
        content="<html><body>x</body></html>",
        allow_diagnostic_draft=False,
    )
    assert written["delivery_granted"] is True
    assert written["delivery_written"] is True
    assert formal.exists()


def test_writer_blocks_when_a_declared_figure_kind_is_missing(tmp_path):
    """Declared kinds are a requirement, not a way to narrow the check to none."""
    _, inputs = _granted_inputs()
    inputs["figures"] = [_figure("boundary_conditions")]
    inputs["required_preprocessing_figures"] = ["boundary_conditions", "contact_definition"]
    formal = tmp_path / "report.html"
    with pytest.raises(PermissionError, match="contact_definition"):
        write_gated_engineering_report(
            formal,
            record=inputs,
            content="<html><body>x</body></html>",
            allow_diagnostic_draft=False,
        )
    assert not formal.exists()


def test_cli_honours_declared_figure_kinds(tmp_path, capsys):
    from abaqus_ai_agent.contracts.provenance import issue_agent_run_record

    issued = issue_agent_run_record(
        model_snapshot_hash='snap-test',
        content_hash_scope='content-test',
        action_plan_scope='plan-test',
        run_id="run-fig",
        model_name="Handle",
        job_name="Job-1",
        output_hash="c" * 64,
        jev_routed=False,
        requirement_kind="engineering_intent",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "case_id": "probe",
                "odb_path": "job.odb",
                "results": {"max_mises": 1.0},
                "acceptance": {"status": "PASS", "deliverable": True},
                "condition_fidelity": {
                    "passed": True,
                    "formal_report_allowed": True,
                    "blockers": [],
                },
                "figures": [{"kind": "boundary_conditions", "path": "bc.png"}],
                "required_preprocessing_figures": ["boundary_conditions"],
                "provenance": issued.to_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "customer" / "report.html"
    ret = main(["report", str(evidence), "-o", str(out)])
    assert ret == 0, capsys.readouterr().err
    assert out.exists()
    assert "contact_definition" not in out.read_text(encoding="utf-8")
