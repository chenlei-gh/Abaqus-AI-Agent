"""Offline contract tests for tools/run_live_report_gate.py (pilot 2).

Covers the remediation review items:
- T1: rendered CAE script parses; no tabs; no unconditional success marker.
- T2: blocked (unapproved) solve_requirement -> explicit AWAITING_APPROVAL,
  never PASS, and no solve-submission evidence is fabricated.
- T3: full-pass facts -> PASS; removing any single gate -> not PASS.
- T4: pseudo-kernel drives the migrated _run_code from the rendered script:
  exception propagation, stdout restore, no stale result, caller isolation.
- T7: host terminal-state gates (rc != 0, settled False, missing facts).
- T8: stale artifacts / foreign run identity never pass.
"""

import ast
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_live_report_gate import (
    FACTS_BEGIN,
    FACTS_END,
    build_live_gate_cae_script,
    compute_live_gate_verdict,
    extract_facts,
    _prepare_workdir,
)

RUN_ID = "testrunid001"


def _render() -> str:
    return build_live_gate_cae_script(
        workdir=Path("D:/x/wd"),
        launcher="abaqus",
        prompt="demo prompt",
        job_name="JobX",
        model_name="ModelX",
        run_id=RUN_ID,
    )


# --- T1: generated-script syntax gate -----------------------------------------

def test_rendered_cae_script_parses_and_has_no_tabs():
    rendered = _render()
    ast.parse(rendered)
    assert "\t" not in rendered


def test_rendered_script_has_no_unconditional_success_marker():
    rendered = _render()
    assert "AIAgent_LIVE_GATE_SUCCESS" not in rendered
    assert FACTS_BEGIN in rendered and FACTS_END in rendered


def test_rendered_script_binds_run_id_and_uses_kernel_namespace():
    rendered = _render()
    assert RUN_ID in rendered
    assert "KernelNamespace" in rendered
    assert "globals()" not in rendered


# --- facts extraction ----------------------------------------------------------

def _facts_stream(facts: dict) -> str:
    import json
    return "noise\n" + FACTS_BEGIN + "\n" + json.dumps(facts) + "\n" + FACTS_END + "\n"


def test_extract_facts_rejects_foreign_run_id():
    facts = {"run_id": "other-run", "task_status": "COMPLETED"}
    assert extract_facts(_facts_stream(facts), expected_run_id=RUN_ID) is None
    assert extract_facts(_facts_stream(facts), expected_run_id="other-run") == facts


def test_extract_facts_rejects_missing_markers():
    assert extract_facts("{\"run_id\": \"x\"}", expected_run_id="x") is None


# --- T2: blocked path is explicit, never PASS ---------------------------------

def _blocked_facts():
    return {
        "run_id": RUN_ID,
        "task_status": "BLOCKED",
        "summary_card_status": "AWAITING_APPROVAL",
        "candidate_id": "JobX-deadbeef1234",
        "execution_manifest_hash": "ab" * 32,
        "solver_completed": False,
        "acceptance_passed": False,
        "delivery": {"attempted": False, "filed": False, "error": None},
    }


def test_blocked_facts_yield_awaiting_approval_not_pass():
    verdict = compute_live_gate_verdict(
        _blocked_facts(),
        process_returncode=0,
        process_settled=True,
        artifacts={},
        expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "AWAITING_APPROVAL"
    assert verdict["candidate_id"] == "JobX-deadbeef1234"


def test_blocked_status_without_awaiting_card_is_fail_not_pass():
    facts = _blocked_facts()
    facts["summary_card_status"] = "COMPLETED"
    verdict = compute_live_gate_verdict(
        facts, process_returncode=0, process_settled=True,
        artifacts={}, expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb"],
    )
    assert verdict["verdict"] == "FAIL"


# --- T3: approved path requires every gate -------------------------------------

def _pass_facts():
    return {
        "run_id": RUN_ID,
        "task_status": "COMPLETED",
        "summary_card_status": "COMPLETED",
        "engineering_status": "RESULT_VALID",
        "run_state": "accepted",
        "acceptance_passed": True,
        "solver_completed": True,
        "odb_path": "D:/x/wd/JobX.odb",
        "errors": [],
        "delivery": {"attempted": True, "filed": True, "error": None},
    }


def _pass_artifacts():
    return {
        "JobX.odb": {"exists": True, "sha256": "ab" * 32, "size_bytes": 100},
        "engineering_report.html": {"exists": True, "sha256": "cd" * 32, "size_bytes": 50},
    }


def test_full_pass_facts_and_artifacts_yield_pass():
    verdict = compute_live_gate_verdict(
        _pass_facts(), process_returncode=0, process_settled=True,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "PASS", verdict


@pytest.mark.parametrize("break_key", [
    "task_status", "solver_completed", "run_state", "engineering_status",
    "acceptance_passed", "delivery",
])
def test_each_missing_gate_breaks_pass(break_key):
    facts = _pass_facts()
    if break_key == "delivery":
        facts["delivery"] = {"attempted": True, "filed": False, "error": "DeliveryRefused: no"}
    elif break_key == "solver_completed" or break_key == "acceptance_passed":
        facts[break_key] = False
    elif break_key == "run_state":
        facts["run_state"] = "failed"
    elif break_key == "engineering_status":
        facts["engineering_status"] = "RESULT_INVALID"
    else:
        facts["task_status"] = "FAILED"
    verdict = compute_live_gate_verdict(
        facts, process_returncode=0, process_settled=True,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] != "PASS"
    assert verdict["reasons"]


def test_delivery_refusal_classified_as_delivery_blocked():
    facts = _pass_facts()
    facts["delivery"] = {"attempted": True, "filed": False, "error": "DeliveryRefused: gate"}
    verdict = compute_live_gate_verdict(
        facts, process_returncode=0, process_settled=True,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "DELIVERY_BLOCKED"


# --- T7: host terminal-state gates ---------------------------------------------

def test_nonzero_returncode_blocks_pass():
    verdict = compute_live_gate_verdict(
        _pass_facts(), process_returncode=1, process_settled=True,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "FAIL"
    assert any("return_code" in r for r in verdict["reasons"])


def test_unsettled_artifacts_block_pass():
    verdict = compute_live_gate_verdict(
        _pass_facts(), process_returncode=0, process_settled=False,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "FAIL"
    assert any("settled" in r for r in verdict["reasons"])


def test_missing_facts_is_fail():
    verdict = compute_live_gate_verdict(
        None, process_returncode=0, process_settled=True,
        artifacts={}, expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb"],
    )
    assert verdict["verdict"] == "FAIL"


# --- T8: stale artifacts / identity ---------------------------------------------

def test_stale_facts_with_wrong_run_id_fail():
    facts = _pass_facts()
    facts["run_id"] = "stale-run"
    verdict = compute_live_gate_verdict(
        facts, process_returncode=0, process_settled=True,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "FAIL"
    assert any("identity" in r for r in verdict["reasons"])


def test_missing_required_artifact_fails():
    artifacts = _pass_artifacts()
    artifacts["JobX.odb"] = {"exists": False}
    verdict = compute_live_gate_verdict(
        _pass_facts(), process_returncode=0, process_settled=True,
        artifacts=artifacts, expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "FAIL"
    assert any("JobX.odb" in r for r in verdict["reasons"])


def test_nonempty_workdir_refused_without_reuse(tmp_path):
    (tmp_path / "stale.txt").write_text("old")
    with pytest.raises(RuntimeError, match="not empty"):
        _prepare_workdir(tmp_path, reuse_workdir=False)
    # explicit reuse is allowed (phase-B resume)
    _prepare_workdir(tmp_path, reuse_workdir=True)


# --- T4: pseudo-kernel drives the migrated harness -----------------------------

def _fake_cae_modules(monkeypatch):
    fake_abaqus = types.ModuleType("abaqus")
    fake_abaqus.mdb = object()
    fake_abaqus.session = object()
    fake_abaqus.__all__ = ["mdb"]
    fake_const = types.ModuleType("abaqusConstants")
    fake_const.LOG = "SymbolicConstant<LOG>"
    fake_const.__all__ = ["LOG"]
    monkeypatch.setitem(sys.modules, "abaqus", fake_abaqus)
    monkeypatch.setitem(sys.modules, "abaqusConstants", fake_const)


def _extract_harness(rendered: str) -> str:
    head, sep, rest = rendered.partition("_NS = KernelNamespace")
    assert sep
    block = sep + rest.split("class CAEExecutor", 1)[0]
    return (
        "from abaqus_ai_agent.execution.kernel_namespace import "
        "KernelNamespace, build_cae_seed\n" + block
    )


def test_migrated_harness_isolation_and_exception_contract(monkeypatch):
    _fake_cae_modules(monkeypatch)
    env = {}
    exec(_extract_harness(_render()), env)
    run_code = env["_run_code"]

    sentinel = object()
    globals()["LOG"] = sentinel
    try:
        assert run_code("result = {\"log\": LOG}") == {"log": "SymbolicConstant<LOG>"}
        assert globals()["LOG"] is sentinel
        run_code("carried = 7")
        assert run_code("result = {\"v\": carried}") == {"v": 7}
        assert run_code("noop = 1") == {"status": "COMPLETED"}
        with pytest.raises(RuntimeError):
            run_code("raise RuntimeError(\"fragment-fail\")")
        # after a failed fragment no stale result leaks
        assert run_code("post = 1") == {"status": "COMPLETED"}
    finally:
        globals().pop("LOG", None)
    assert "carried" not in env and "result" not in env
def test_delivery_blocked_via_task_error_text():
    facts = _pass_facts()
    facts["task_status"] = "FAILED"
    facts["delivery"] = {"attempted": False, "filed": False, "error": None}
    facts["errors"] = ["Engineering status: DELIVERY_BLOCKED", "Official delivery blocked: ..."]
    verdict = compute_live_gate_verdict(
        facts, process_returncode=0, process_settled=True,
        artifacts=_pass_artifacts(), expected_run_id=RUN_ID,
        required_artifacts=["JobX.odb", "engineering_report.html"],
    )
    assert verdict["verdict"] == "DELIVERY_BLOCKED"
    assert verdict["verdict"] != "PASS"
