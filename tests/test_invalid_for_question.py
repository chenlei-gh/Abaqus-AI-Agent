"""Tests for INVALID_FOR_QUESTION semantics (T-P2).

A model whose interface is constrained to stay coincident cannot answer a
question that requires separation, sliding, or pull-out. The solve itself may
succeed; the result is invalid for the question, not a solver failure.
"""

import os

import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.contracts.task import TaskStatus
from abaqus_ai_agent.engineering_status import EngineeringStatus
from abaqus_ai_agent.execution.client import AbaqusExecutor
from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, IntentInteractionSpec
from abaqus_ai_agent.validation.condition_fidelity import InvalidForQuestionError


class _OdbBackedExecutor(AbaqusExecutor):
    """Deterministic in-memory AbaqusExecutor simulating live ODB result extraction."""

    def __init__(self):
        self.executed_scripts = []
        self.workdir = None

    def execute(self, code, timeout=120):
        self.executed_scripts.append(code)
        if self.workdir and os.path.isdir(self.workdir):
            import re
            m = re.search(r"Job_[a-zA-Z0-9_]+", code)
            job_prefix = m.group(0) if m else "Job_REQ_IFQ"
            for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
                p = os.path.join(self.workdir, f"{job_prefix}.{ext}")
                if not os.path.exists(p):
                    if ext == "odb":
                        with open(p, "wb") as f:
                            f.write(b"\x7fABAQUS_BINARY_ODB_MOCK\x00\x01\x02\x03" * 32)
                    else:
                        with open(p, "w", encoding="utf-8") as f:
                            f.write(f"Mock {ext}\n")
        if "verifyMeshQuality" in code:
            return {
                "part": "Part-1",
                "node_count": 408,
                "element_count": 195,
                "metrics": {"max_aspect_ratio": 2.279, "min_angle": 26.971, "max_angle": 114.747},
                "violations": [],
                "warnings": [],
                "evidence": ["native_verify:ASPECT_RATIO"],
                "status": "pass",
                "source": "native_abaqus_verifyMeshQuality",
                "failed_element_count": 0,
                "warning_element_count": 0,
                "unsupported_checks": [],
                "kind": "mesh_quality",
            }
        if "rootAssembly" in code:
            return {"steps": ["Step-1"], "instances": ["Part-1-1"], "step_frames": {"Step-1": 1}}
        if "odb.steps.keys()" in code:
            return "Step-1"
        if "fo=" in code:
            return {"values": [{"value": 120.0}]}
        return {"status": "COMPLETED", "output": "COMPLETED"}

    def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
        return {"status": "COMPLETED", "output": "COMPLETED"}

    def snapshot(self):
        return None


_GEOM = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
_MAT = MaterialDefinition(
    name="Steel_Q235",
    unit_system="MM_N_MPA",
    elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    density=7.85e-9,
)


def _separation_tie_intent():
    return EngineeringIntent(
        id="REQ-IFQ-COMPILE",
        kind="linear_static",
        description="Evaluate snap-fit separation force of the clip",
        material={"name": "Steel_Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "unit": "MPa"},
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 180.0, "direction": "-Y"},),
        contacts=(
            IntentInteractionSpec(
                name="Tie1",
                interaction_type="tie",
                master_region="ClipA",
                slave_region="ClipB",
            ),
        ),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},
        ),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )


def test_compile_gate_marks_tie_only_separation_question_invalid():
    """Compile gate: tie-only plan + separation question -> INVALID_FOR_QUESTION."""
    agent = AbaqusAIAgent(_OdbBackedExecutor())
    result = agent.solve_requirement(
        requirement=_separation_tie_intent(),
        geometry=_GEOM,
        material=_MAT,
    )

    assert result.status == TaskStatus.BLOCKED
    card = result.summary_card
    assert card["status"] == "INVALID_FOR_QUESTION"
    assert card["engineering_status"] == "INVALID_FOR_QUESTION"
    assert any("interface_modelled_as_tie_not_contact" in str(b) for b in card.get("fidelity_blockers", ()))
    assert any("interface_modelled_as_tie_not_contact" in err for err in result.errors)


def test_invalid_for_question_error_is_value_error_subclass():
    """Backward compatibility: existing except (ValueError, TypeError) still catches it."""
    err = InvalidForQuestionError(({"type": "interface_modelled_as_tie_not_contact", "message": "m"},))
    assert isinstance(err, ValueError)
    with pytest.raises(ValueError):
        raise err


def _full_closure_harness(tmp_path, monkeypatch, job_name):
    """Mirror the B5/full-closure harness: MockCaeExecutor + mocked ODB verify,
    mocked viewer rendering, mocked extraction. Returns (ctx, workdir, executor)."""
    from pathlib import Path
    from abaqus_ai_agent.contracts.report import ReportFigure
    from abaqus_ai_agent.contracts.results import ResultExtraction, ResultRequirement
    from abaqus_ai_agent.execution.odb_rendering import MINIMAL_VALID_PNG_BYTES
    from abaqus_ai_agent.paths import create_external_project_context
    from test_cae_pipeline_integration import MockCaeExecutor

    ctx = create_external_project_context(tmp_path / (job_name + "_proj"), enforce_outside_repo=False)
    workdir = ctx.create_run_solver_dir(job_name)
    executor = MockCaeExecutor(workdir, job_name=job_name)
    executor.launcher = "abaqus"
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: {"verified": True, "offline": False, "steps": {"Step-1": {"frames": [0, 1]}}, "fields": ["S", "U"]},
    )
    import abaqus_ai_agent.execution.odb_rendering as rend_mod

    def _mock_render_vis(odb_path, specs, output_dir, **kwargs):
        import hashlib
        from abaqus_ai_agent.execution.odb_rendering import (
            compute_viewer_session_token,
            create_render_execution_evidence,
        )
        rendered = []
        session_nonce = "0123456789abcdef0123456789abcdef"
        run_id = str(kwargs.get("run_id", "PROD")).strip()
        odb_sha256 = ""
        if odb_path and Path(odb_path).exists():
            odb_sha256 = hashlib.sha256(Path(odb_path).read_bytes()).hexdigest()
        input_hash = str(kwargs.get("input_hash") or "")
        rendered_summary = []
        for s in specs:
            out_file = Path(output_dir) / s.target_filename
            if not out_file.exists():
                out_file.write_bytes(MINIMAL_VALID_PNG_BYTES)
            img_bytes = out_file.read_bytes()
            sha = hashlib.sha256(img_bytes).hexdigest()
            rendered_summary.append({"filename": out_file.name, "image_sha256": sha})
        render_ev = create_render_execution_evidence(
            session_nonce=session_nonce, run_id=run_id, odb_sha256=odb_sha256,
            rendered_figures=rendered_summary, input_hash=input_hash,
        )
        for s in specs:
            out_file = Path(output_dir) / s.target_filename
            img_bytes = out_file.read_bytes()
            sha = hashlib.sha256(img_bytes).hexdigest()
            token = compute_viewer_session_token(
                session_nonce=session_nonce, run_id=run_id, odb_sha256=odb_sha256,
                target_filename=out_file.name, image_sha256=sha,
            )
            rendered.append(
                ReportFigure(
                    kind=s.visualization_type, path=str(out_file.as_posix()),
                    caption=getattr(s, "caption_zh", "") or getattr(s, "caption", ""),
                    source=f"{s.field_name}.{s.component}",
                    metadata={
                        "field": s.field_name, "component": s.component, "step": s.step_name,
                        "frame": s.frame_index, "actual_frame": s.actual_frame_index,
                        "region": getattr(s, "region", "WHOLE_MODEL"),
                        "output_position": getattr(s, "output_position", "INTEGRATION_POINT"),
                        "run_id": run_id, "input_hash": kwargs.get("input_hash", ""),
                        "odb_sha256": odb_sha256, "image_sha256": sha, "sha256": sha,
                        "viewer_rendered": True, "session_nonce": session_nonce,
                        "viewer_session_token": token,
                        "render_execution_evidence": render_ev.to_dict(),
                    },
                )
            )
        return rendered

    monkeypatch.setattr(rend_mod, "render_authentic_visualizations", _mock_render_vis)

    _METRIC_VALUES = {
        "max_mises": 150.0,
        "max_displacement": 0.42,
        "reaction_force": 1000.0,
        "contact_pressure": 12.0,
        "frictional_shear": 3.0,
    }

    def _fake_extract(executor, path, crit):
        extractions = []
        for item in crit or ():
            key = item.get("value_key") if isinstance(item, dict) else None
            if key not in _METRIC_VALUES:
                continue
            requirement = ResultRequirement(
                name=key, value_key=key,
                field=item.get("field") or (
                    "S" if key == "max_mises"
                    else "U" if key == "max_displacement"
                    else "CPRESS" if key == "contact_pressure"
                    else "CSHEAR" if key == "frictional_shear"
                    else "RF"
                ),
                step=item.get("step") or "Step-1", frame=-1, unit=item.get("unit") or "",
            )
            extractions.append(ResultExtraction(
                requirement=requirement, value=_METRIC_VALUES[key],
                locator={"step": "Step-1", "frame": -1, "source": "odb", "value_key": key},
            ))
        return extractions, ()

    import abaqus_ai_agent.execution.results as res_mod
    monkeypatch.setattr(res_mod, "extract_requirements", _fake_extract)

    # The contact domain profile requires CPRESS/CSHEAR criteria that have no
    # deterministic ODB mapping in the output planner; this test targets the
    # fidelity classification, not the contact extraction contract, so the
    # profile is narrowed to the static one the harness can actually satisfy.
    # capability.py binds the function at module import time, so its local name
    # must be patched as well.
    import abaqus_ai_agent.contracts.results as contracts_results
    import abaqus_ai_agent.contracts.capability as contracts_capability
    _real_profile = contracts_results.get_physics_result_profile
    monkeypatch.setattr(
        contracts_results,
        "get_physics_result_profile",
        lambda domain: _real_profile("static"),
    )
    monkeypatch.setattr(
        contracts_capability,
        "get_physics_result_profile",
        lambda domain: _real_profile("static"),
    )

    (workdir / "mises_stress_hotspot.png").write_bytes(MINIMAL_VALID_PNG_BYTES)
    (workdir / "total_displacement.png").write_bytes(MINIMAL_VALID_PNG_BYTES)
    return ctx, workdir, executor


def test_report_stage_diagnostic_path_marks_invalid_for_question(monkeypatch, tmp_path):
    """Report-stage fallback: even if the compile gate is bypassed, the diagnostic
    path must still mark the run INVALID_FOR_QUESTION instead of RESULT_VALID."""
    import abaqus_ai_agent.validation.condition_fidelity as fidelity_mod
    import abaqus_ai_agent.reasoning.engine as reasoning_engine_mod
    import abaqus_ai_agent.planning.compiler as compiler_mod

    real_kinematics = fidelity_mod.audit_interface_kinematics

    def _compile_gate_bypassed(intent=None, **kwargs):
        # Only the report-stage merged verdict passes ``interactions`` together
        # with a DIFFERENT ``contacts`` tuple (scope contacts vs intent contacts).
        # Every earlier caller — the compile gate (identical tuples) and the
        # reasoning engine's internal fidelity audit (no ``interactions`` kwarg)
        # — is bypassed to simulate their interception being skipped.
        contacts = tuple(kwargs.get("contacts") or ())
        interactions = kwargs.get("interactions")
        is_report_stage = interactions is not None and tuple(interactions) != contacts
        verdict = real_kinematics(intent, **kwargs)
        if is_report_stage:
            return verdict
        return {**verdict, "blockers": (), "warnings": ()}

    # compiler.py binds audit_interface_kinematics via a function-local import,
    # so patching the module attribute is enough. reasoning.engine binds
    # audit_condition_fidelity at import time; patch that binding as well.
    monkeypatch.setattr(fidelity_mod, "audit_interface_kinematics", _compile_gate_bypassed)
    monkeypatch.setattr(compiler_mod, "audit_interface_kinematics", _compile_gate_bypassed, raising=False)
    monkeypatch.setattr(reasoning_engine_mod, "audit_condition_fidelity", lambda *a, **k: dict(
        fidelity_mod.audit_condition_fidelity(*a, **k)
    ))

    ctx, workdir, executor = _full_closure_harness(tmp_path, monkeypatch, "Job_REQ_IFQ_DIAG")
    agent = AbaqusAIAgent(executor)
    intent = EngineeringIntent(
        id="REQ-IFQ-DIAG",
        kind="linear_static",
        description="Evaluate snap-fit separation force of the clip",
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 180.0, "direction": "-Y"},),
        contacts=(
            IntentInteractionSpec(
                name="Tie1",
                interaction_type="tie",
                master_region="ClipA",
                slave_region="ClipB",
            ),
        ),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa", "required": True},
        ),
    )
    result = agent.solve_requirement(
        requirement=intent,
        geometry=_GEOM,
        material=_MAT,
        workdir=str(workdir),
        project_context=ctx,
    )

    assert result.status == TaskStatus.FAILED, result.errors
    assert result.summary_card["engineering_status"] == "INVALID_FOR_QUESTION", (
        result.errors,
        result.summary_card,
    )
    assert result.is_completed is False
    # Guard against a trivial pass: the run must have actually reached the report
    # stage with real metrics before the fidelity verdict reclassified it.
    assert result.summary_card["metrics"].get("max_mises") == 150.0, result.summary_card


def test_non_kinematic_blocker_does_not_become_invalid_for_question(monkeypatch):
    """Scope discipline: a non-kinematic fidelity blocker (coating) must not be
    reclassified as INVALID_FOR_QUESTION; it keeps its own semantics."""
    import abaqus_ai_agent.validation.condition_fidelity as fidelity_mod

    real_audit = fidelity_mod.audit_condition_fidelity

    def _coating_blocked(intent=None, **kwargs):
        verdict = dict(real_audit(intent, **kwargs))
        verdict["passed"] = False
        verdict["formal_model_allowed"] = False
        verdict["blockers"] = ["coating_claim_without_surface_treatment_spec"]
        return verdict

    monkeypatch.setattr(fidelity_mod, "audit_condition_fidelity", _coating_blocked)
    import abaqus_ai_agent.reasoning.engine as reasoning_engine_mod
    monkeypatch.setattr(reasoning_engine_mod, "audit_condition_fidelity", _coating_blocked)

    executor = _OdbBackedExecutor()
    agent = AbaqusAIAgent(executor)
    intent = EngineeringIntent(
        id="REQ-IFQ-COATING",
        kind="linear_static",
        description="Cantilever beam under vertical 1kN tip load",
        material={"name": "Steel_Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "unit": "MPa"},
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},
        ),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )
    result = agent.solve_requirement(requirement=intent, geometry=_GEOM, material=_MAT)

    # The coating blocker fires at reasoning/compile time, so the run is blocked
    # before reaching the report stage; it must never be labelled INVALID_FOR_QUESTION.
    assert result.summary_card.get("engineering_status") != "INVALID_FOR_QUESTION"
    assert result.summary_card.get("status") != "INVALID_FOR_QUESTION"
