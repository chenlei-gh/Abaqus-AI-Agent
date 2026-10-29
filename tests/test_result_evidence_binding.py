"""C-2 result/evidence binding: one vocabulary, one severity rule, one producer.

These cases exist because the mesh quality result had three incompatible
producers (``status`` lowercase, ``gate_status`` uppercase, and a dataclass that
was never constructed on the product path) and two consumers that each read a
different field. A check could therefore run, fail, and still leave the
acceptance gate reading ``SKIPPED``.
"""

import hashlib
import json

import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.mesh_quality import (
    MeshQualityBinding,
    MeshQualityResult,
    default_severity_for_status,
    mesh_quality_binding_gaps,
    mesh_quality_expiry_reasons,
    normalize_mesh_quality_status,
)


# --- D1: one canonical status vocabulary ------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("PASS", "pass"),
        ("PASS(0)", "pass"),
        ("pass", "pass"),
        ("WARNING", "warning"),
        ("warn", "warning"),
        ("BLOCKED", "fail"),
        ("FAIL", "fail"),
        ("unknown", "not_run"),
        ("NOT_CHECKED", "not_run"),
        ("SKIPPED", "not_run"),
        ("unsupported", "unsupported"),
        ("expired", "expired"),
        (None, "not_run"),
    ],
)
def test_status_spellings_normalize_to_one_vocabulary(raw, expected):
    assert normalize_mesh_quality_status(raw) == expected


def test_gate_status_is_read_when_status_is_absent():
    """The INP auditor wrote `gate_status` only; that must not read as not_run."""
    result = MeshQualityResult.from_mapping({"gate_status": "WARNING", "warnings": ["aspect"]})
    assert result.status == "warning"


def test_unrecognized_status_never_becomes_pass():
    result = MeshQualityResult.from_mapping({"status": "probably_fine"})
    assert result.status == "not_run"


def test_unsupported_checks_imply_unsupported_not_not_run():
    result = MeshQualityResult.from_mapping({"unsupported_checks": ["ANALYSIS_CHECKS:ValueError"]})
    assert result.status == "unsupported"
    assert result.unsupported_checks == ("ANALYSIS_CHECKS:ValueError",)


# --- D2: stable serialization -----------------------------------------------


def test_result_serializes_to_mapping_with_all_contract_fields():
    result = MeshQualityResult(
        status="warning",
        metrics={"max_aspect_ratio": 12.5},
        warnings=("aspect",),
        job_name="Job-1",
        part_name="Part-1",
        unsupported_checks=("min_jacobian_not_mapped",),
    )
    payload = result.to_dict()
    assert payload["schema"] == "result_item_v1"
    assert payload["kind"] == "mesh_quality"
    assert payload["status"] == "warning"
    assert payload["severity"] == "advisory"
    assert payload["metrics"] == {"max_aspect_ratio": 12.5}
    assert payload["unsupported_checks"] == ["min_jacobian_not_mapped"]
    json.dumps(payload)  # must be JSON-serializable, not a repr string


def test_round_trip_through_mapping_preserves_status():
    original = MeshQualityResult(status="fail", violations=("inverted",), job_name="J")
    assert MeshQualityResult.from_mapping(original.to_dict()).status == "fail"


# --- D1/D13: severity is a policy decision, not a synonym for status --------


def test_warning_is_advisory_and_fail_is_blocking_by_default():
    assert default_severity_for_status("pass") == "none"
    assert default_severity_for_status("warning") == "advisory"
    assert default_severity_for_status("fail") == "blocking"
    # A missing check is not blocking until the domain says it is required.
    assert default_severity_for_status("not_run") == "advisory"


def test_explicit_severity_overrides_the_default():
    result = MeshQualityResult(status="warning", severity="blocking")
    assert result.effective_severity == "blocking"
    assert result.blocks_delivery is True


def test_invalid_severity_is_rejected():
    with pytest.raises(ValueError, match="invalid severity"):
        MeshQualityResult(status="pass", severity="fatal")


# --- Acceptance mapping -----------------------------------------------------


def _accept(mesh_quality, required_gates=None):
    return evaluate_result_acceptance(
        result_status="completed",
        mesh_quality=mesh_quality,
        values={"disp": 1.0},
        criteria=(),
        required_gates=required_gates,
    )


def test_fatal_defect_is_a_physical_failure_not_a_missing_gate():
    res = _accept({"status": "fail"})
    assert res.gates["mesh_quality"] == "FAIL"
    assert res.status == "FAIL"
    assert "mesh_quality_failed" in res.failures


def test_warning_does_not_pass_and_does_not_fail_outright():
    """A warning may not be silently accepted, and may not be called a defect."""
    res = _accept({"status": "warning", "warnings": ["high_aspect_ratio"]})
    assert res.gates["mesh_quality"] == "WARNING"
    assert "mesh_quality_failed" not in res.failures
    assert "high_aspect_ratio" in res.gate_justifications["mesh_quality"]


def test_warning_can_be_made_blocking_by_the_domain():
    res = _accept({"status": "warning", "severity": "blocking"})
    assert res.gates["mesh_quality"] == "WARNING"
    assert "mesh_quality_warning_blocking" in res.blocked


def test_unsupported_in_a_required_domain_blocks_instead_of_skipping():
    res = _accept({"status": "unsupported", "unsupported_checks": ["C3D10M"]}, required_gates=("mesh_quality",))
    assert res.gates["mesh_quality"] == "UNSUPPORTED"
    assert res.gates["mesh_quality"] != "SKIPPED"
    assert any("mesh_quality_unsupported" in b for b in res.blocked)


def test_not_run_in_a_required_domain_blocks_instead_of_skipping():
    res = _accept({"status": "not_run"}, required_gates=("mesh_quality",))
    assert res.gates["mesh_quality"] != "SKIPPED"
    assert "mesh_quality_not_run" in res.blocked


def test_missing_result_in_a_required_domain_is_blocked():
    res = _accept(None, required_gates=("mesh_quality",))
    assert res.gates["mesh_quality"] == "BLOCKED"
    assert "missing_mandatory_gate:mesh_quality" in res.failures


def test_absent_result_without_a_requirement_stays_skipped_and_auditable():
    res = _accept(None)
    assert res.gates["mesh_quality"] == "SKIPPED"


def test_uppercase_producer_dict_is_read_correctly():
    """The INP auditor's uppercase `gate_status` must not become FAIL by accident."""
    res = _accept({"gate_status": "WARNING", "warnings": ["policy_aspect"]})
    assert res.gates["mesh_quality"] == "WARNING"


def test_clean_result_passes():
    res = _accept({"status": "pass", "metrics": {"max_aspect_ratio": 2.0}})
    assert res.gates["mesh_quality"] == "PASS"
    assert res.passed is True


# --- D5: binding and expiry -------------------------------------------------


def test_mismatched_job_name_expires_the_result():
    result = MeshQualityResult(status="pass", job_name="Job-OLD")
    reasons = mesh_quality_expiry_reasons(result, MeshQualityBinding(job_name="Job-NEW"))
    assert reasons == ("job_name_mismatch",)


@pytest.mark.parametrize("field_name", ["run_id", "input_sha256", "odb_sha256"])
def test_each_binding_key_can_expire_a_result(field_name):
    result = MeshQualityResult(status="pass", **{field_name: "old"})
    reasons = mesh_quality_expiry_reasons(result, MeshQualityBinding(**{field_name: "new"}))
    assert reasons == ("%s_mismatch" % field_name,)


def test_part_outside_the_assembly_expires_the_result():
    result = MeshQualityResult(status="pass", part_name="Ghost")
    reasons = mesh_quality_expiry_reasons(result, MeshQualityBinding(part_names=("Base", "Slider")))
    assert reasons == ("part_name_not_in_assembly",)


def test_unrecorded_binding_is_a_gap_not_a_contradiction():
    """A result that never claimed an ODB hash is incomplete, not wrong."""
    result = MeshQualityResult(status="pass", job_name="Job-1")
    binding = MeshQualityBinding(job_name="Job-1", odb_sha256="abc")
    assert mesh_quality_expiry_reasons(result, binding) == ()
    assert mesh_quality_binding_gaps(result, binding) == ("odb_sha256_unbound",)


def test_matching_binding_reports_nothing():
    result = MeshQualityResult(
        status="pass", job_name="J", run_id="R", input_sha256="a", odb_sha256="b"
    )
    binding = MeshQualityBinding(job_name="J", run_id="R", input_sha256="a", odb_sha256="b")
    assert mesh_quality_expiry_reasons(result, binding) == ()
    assert mesh_quality_binding_gaps(result, binding) == ()


# --- D3/D4/D7: the producer path -------------------------------------------


def test_compiler_emits_a_mesh_quality_action_after_generate_mesh():
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
        mesh=IntentMeshSpec(global_size=2.0, size_source="USER_SPECIFIED", primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED'),
        material=MaterialDefinition(
            name="Q235",
            unit_system="MM_N_MPA",
            elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        ),
    ).actions
    types = [a.action_type for a in actions]
    assert "mesh_quality" in types
    # The check must come after the mesh exists. This template emits the mesh step
    # as a raw `python` action, so compare against the last mesh-producing action.
    mesh_steps = [i for i, a in enumerate(actions) if "generateMesh" in str(a.parameters.get("code", ""))]
    assert mesh_steps, "expected a generateMesh step in the compiled plan"
    assert types.index("mesh_quality") > mesh_steps[-1]
    mq = next(a for a in actions if a.action_type == "mesh_quality")
    assert mq.parameters["part"] == "P"


def test_plan_result_becomes_a_bound_mesh_quality_verdict(tmp_path):
    from abaqus_ai_agent.agent import AbaqusAIAgent

    workdir = tmp_path
    (workdir / "Job-1.inp").write_text("*NODE\n", encoding="utf-8")
    expected_hash = hashlib.sha256((workdir / "Job-1.inp").read_bytes()).hexdigest()

    raw = json.dumps({"status": "warning", "part": "Part-1", "warnings": ["aspect"], "metrics": {}})
    agent = AbaqusAIAgent(executor=None)

    class _Plan:
        job_name = "Job-1"
        model_name = "Model-1"

    verdict = agent._mesh_quality_from_plan(
        {"mesh_quality": [raw]}, plan=_Plan(), workdir=str(workdir)
    )
    assert verdict is not None
    assert verdict.status == "warning"
    assert verdict.job_name == "Job-1"
    assert verdict.input_sha256 == expected_hash


def test_unparsable_plan_result_is_not_a_pass():
    from abaqus_ai_agent.agent import AbaqusAIAgent

    agent = AbaqusAIAgent(executor=None)

    class _Plan:
        job_name = "Job-1"
        model_name = "Model-1"

    verdict = agent._mesh_quality_from_plan({"mesh_quality": ["<not a payload>"]}, plan=_Plan())
    assert verdict.status == "not_run"
    assert verdict.execution_error


def test_no_mesh_quality_action_returns_no_verdict():
    from abaqus_ai_agent.agent import AbaqusAIAgent

    agent = AbaqusAIAgent(executor=None)
    assert agent._mesh_quality_from_plan({}, plan=None) is None


def test_worst_part_verdict_wins_the_aggregate():
    from abaqus_ai_agent.agent import _combine_mesh_quality_results

    clean = MeshQualityResult(status="pass", part_name="Base")
    bad = MeshQualityResult(status="fail", part_name="Slider", violations=("inverted",))
    combined = _combine_mesh_quality_results([clean, bad])
    assert combined.status == "fail"
    assert "Slider:inverted" in combined.violations
    assert "Base" in combined.part_name and "Slider" in combined.part_name


def test_structured_result_payload_never_degrades_to_repr():
    """A dict must not fall through to str(dict) in the verification map."""
    from abaqus_ai_agent.execution.analysis_run import _structured_result_payload

    assert _structured_result_payload({"status": "pass"}) == {"status": "pass"}
    assert _structured_result_payload(MeshQualityResult(status="pass"))["status"] == "pass"
    unknown = _structured_result_payload(object())
    assert unknown["status"] == "not_run"
    assert "unsupported_result_type" in unknown["execution_error"]


# --- D9: unsupported element family is not an empty deck --------------------


def test_tetrahedral_quality_is_not_a_hand_written_inp_audit():
    """C3D10M quality comes from native verifyMeshQuality, not a retired INP Jacobian auditor."""
    from abaqus_ai_agent.contracts.mesh_quality import mesh_submission_blockers

    blockers = mesh_submission_blockers({
        "status": "unsupported",
        "unsupported_checks": ("element_type_not_supported:C3D10M",),
        "violations": (),
    })
    assert "mesh_quality_unsupported" in blockers
    assert "inp_contains_zero_auditable_finite_elements" not in blockers


def test_missing_mesh_quality_is_not_an_empty_deck_pass():
    from abaqus_ai_agent.contracts.mesh_quality import mesh_submission_blockers

    assert "mesh_quality_missing" in mesh_submission_blockers(None)


def test_native_script_records_unmapped_metrics_as_unsupported():
    """`min_jacobian` has no native criterion; that is a blind spot, not a pass."""
    from abaqus_ai_agent.actions.builders import mesh_quality
    from abaqus_ai_agent.actions.script import action_to_script

    action = mesh_quality("M", "P", min_jacobian=0.4, max_skew=45.0, job_name="Job-1")
    script = action_to_script(action)
    assert "unsupported_checks" in script
    assert "min_jacobian_not_mapped_to_native_criterion" in script
    assert "max_skew_not_mapped_to_native_criterion" in script
    # It must not be reported as a quality warning that reads like a defect.
    assert "min_jacobian_requires_native_analysis_check_or_element_specific_api" not in script
    assert "os.replace" in script
    assert ".result_items.json" in script
    assert "Job-1" in script


def test_result_items_sidecar_writes_to_the_bound_results_directory(tmp_path):
    """The reader looks in the workdir, so the writer must be told that same directory.

    Measured on the real kernel: with `result_dir` set, the file lands there and
    does not appear in the session's cwd (see _probe_d17_result_dir.json).
    """
    from abaqus_ai_agent.actions.builders import mesh_quality
    from abaqus_ai_agent.actions.script import action_to_script

    bound = tmp_path / "bound_results"
    bound.mkdir()
    action = mesh_quality("M", "P", job_name="Job-1", result_dir=str(bound))
    script = action_to_script(action)
    assert "getcwd" not in script

    namespace = {}
    payload = {"status": "pass", "kind": "mesh_quality", "job_name": "Job-1"}
    exec(
        "result = %r\n" % (payload,) + script.split("print(result)")[1].lstrip(),
        namespace,
    )
    written = bound / "Job-1.result_items.json"
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["job_name"] == "Job-1"


def test_unbound_sidecar_still_defaults_to_the_session_directory(tmp_path, monkeypatch):
    """Legacy callers keep working; the location is explicit only when supplied."""
    from abaqus_ai_agent.actions.builders import mesh_quality
    from abaqus_ai_agent.actions.script import action_to_script

    action = mesh_quality("M", "P", job_name="Job-2")
    script = action_to_script(action)
    assert "_os.getcwd()" in script

    monkeypatch.chdir(tmp_path)
    payload = {"status": "pass", "kind": "mesh_quality", "job_name": "Job-2"}
    exec("result = %r\n" % (payload,) + script.split("print(result)")[1].lstrip(), {})
    assert (tmp_path / "Job-2.result_items.json").is_file()


def test_apply_plan_with_evidence_binds_the_result_directory():
    """The agent must inject its resolved workdir, not leave the writer guessing."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.action import AbaqusAction
    from abaqus_ai_agent.execution.client import AbaqusExecutor
    from abaqus_ai_agent.planning.compiler import CompiledAgentPlan

    captured = {}

    class _Executor(AbaqusExecutor):
        def execute(self, code, timeout=120):
            captured["code"] = code
            return {"status": "pass", "kind": "mesh_quality", "job_name": "J"}

    action = AbaqusAction(
        action_type="mesh_quality",
        model_name="M",
        target="P",
        parameters={"part": "P", "job_name": "J"},
        requires_confirmation=False,
    )
    plan = CompiledAgentPlan(
        model_name="M",
        part_name="P",
        job_name="J",
        actions=(action,),
        cae_script="",
        intent_summary={},
    )
    agent = AbaqusAIAgent(executor=_Executor())
    agent.apply_plan_with_evidence(plan, result_dir="/tmp/bound-run")
    assert "/tmp/bound-run" in captured["code"]


def test_result_items_sidecar_is_atomic_and_bound(tmp_path, monkeypatch):
    """The fallback file is read only when it belongs to this job."""
    from abaqus_ai_agent.agent import _load_result_items_sidecar

    target = tmp_path / "Job-1.result_items.json"
    target.write_text(json.dumps({
        "schema": "result_items_v1",
        "job_name": "Job-1",
        "items": [{"kind": "mesh_quality", "status": "pass", "job_name": "Job-1"}],
    }), encoding="utf-8")
    loaded = _load_result_items_sidecar(tmp_path, "Job-1")
    assert loaded["status"] == "pass"

    foreign = tmp_path / "Other.result_items.json"
    foreign.write_text(json.dumps({"job_name": "Job-1", "items": [{"status": "pass"}]}), encoding="utf-8")
    rejected = _load_result_items_sidecar(tmp_path, "Other")
    assert rejected["execution_error"] == "expired_result_items"

    broken = tmp_path / "Broken.result_items.json"
    broken.write_text("{not json", encoding="utf-8")
    unreadable = _load_result_items_sidecar(tmp_path, "Broken")
    assert unreadable["execution_error"] == "result_items_unreadable"
