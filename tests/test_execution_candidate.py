"""Offline contract tests for the pre-solve approval candidate lifecycle.

No Abaqus session, no executor, no I/O outside tmp_path: these tests pin the
state machine, drift detection, gate predicate, and persistence semantics
before any production entry point is wired to them (plan step 2).
"""

import dataclasses
import hashlib
import json

import pytest

from abaqus_ai_agent.contracts.approval import (
    ApprovalError,
    ApprovalRecord,
    CandidateDriftError,
    CandidateNotApprovedError,
    CandidateStateError,
    CandidateStatus,
    ExecutionCandidate,
    approve_candidate,
    assert_submittable,
    candidate_path,
    compute_execution_manifest_hash,
    compute_solver_config_hash,
    detect_drift,
    load_candidate,
    propose_candidate,
    supersede_candidate,
    write_candidate,
)

INP_A = hashlib.sha256(b"*Heading job-A").hexdigest()
INP_B = hashlib.sha256(b"*Heading job-B").hexdigest()
DEP = {"include/material.inc": hashlib.sha256(b"*Material").hexdigest()}
SOLVER_CFG = {"solver": "STANDARD", "step": "StaticStep", "nlgeom": False}


def _proposed(**overrides):
    kwargs = dict(
        candidate_id="cand-1",
        run_id="run-1",
        inp_sha256=INP_A,
        solver_config=SOLVER_CFG,
        generator_version="1.2.3",
        dependency_hashes=DEP,
        model_hash="m" * 64,
        intent_hash="i" * 64,
        action_plan_hash="a" * 64,
        created_at="2026-10-27T00:00:00+00:00",
    )
    kwargs.update(overrides)
    return propose_candidate(**kwargs)


def test_propose_yields_proposed_with_deterministic_manifest():
    c1 = _proposed()
    c2 = _proposed()
    assert c1.status is CandidateStatus.PROPOSED
    assert c1.approval is None
    assert c1.execution_manifest_hash == c2.execution_manifest_hash


def test_manifest_changes_with_any_content_field():
    base = _proposed().execution_manifest_hash
    assert _proposed(inp_sha256=INP_B).execution_manifest_hash != base
    assert _proposed(solver_config=dict(SOLVER_CFG, nlgeom=True)).execution_manifest_hash != base
    assert _proposed(generator_version="9.9.9").execution_manifest_hash != base
    other_dep = dict(DEP)
    other_dep["include/material.inc"] = hashlib.sha256(b"*Material changed").hexdigest()
    assert _proposed(dependency_hashes=other_dep).execution_manifest_hash != base


def test_manifest_requires_inp_hash():
    with pytest.raises(ValueError):
        _proposed(inp_sha256="")


def test_solver_config_hash_is_order_independent():
    assert compute_solver_config_hash({"a": 1, "b": 2}) == compute_solver_config_hash({"b": 2, "a": 1})


def test_approve_binds_candidate_and_manifest():
    c = approve_candidate(_proposed(), approved_by="chenlei", review_report_hash="r" * 64,
                          approved_at="2026-10-27T01:00:00+00:00")
    assert c.status is CandidateStatus.APPROVED
    assert c.approval.candidate_id == "cand-1"
    assert c.approval.execution_manifest_hash == c.execution_manifest_hash
    assert c.approval.review_report_hash == "r" * 64
    assert "not keyed signatures" in c.approval.disclaimer


def test_approval_does_not_change_manifest_hash():
    proposed = _proposed()
    approved = approve_candidate(proposed, approved_by="chenlei")
    assert approved.execution_manifest_hash == proposed.execution_manifest_hash


def test_double_approval_is_rejected():
    approved = approve_candidate(_proposed(), approved_by="chenlei")
    with pytest.raises(CandidateStateError):
        approve_candidate(approved, approved_by="chenlei")


def test_approval_requires_named_subject():
    with pytest.raises(ValueError):
        approve_candidate(_proposed(), approved_by="  ")


def test_approval_refused_on_tampered_manifest():
    tampered = dataclasses.replace(_proposed(), inp_sha256=INP_B)
    with pytest.raises(CandidateStateError):
        approve_candidate(tampered, approved_by="chenlei")


def test_superseded_candidate_is_terminal():
    c = _proposed()
    old = supersede_candidate(c, by_candidate_id="cand-2")
    assert old.status is CandidateStatus.SUPERSEDED
    assert old.superseded_by == "cand-2"
    with pytest.raises(CandidateStateError):
        approve_candidate(old, approved_by="chenlei")
    with pytest.raises(CandidateStateError):
        supersede_candidate(old, by_candidate_id="cand-3")
    with pytest.raises(ValueError):
        supersede_candidate(_proposed(), by_candidate_id="cand-1")


def test_no_drift_when_content_matches():
    c = _proposed()
    assert detect_drift(
        c,
        current_inp_sha256=INP_A,
        current_dependency_hashes=dict(DEP),
        current_solver_config=dict(SOLVER_CFG),
        current_generator_version="1.2.3",
    ) == ()


def test_drift_detects_each_dimension():
    c = _proposed()
    assert "inp_sha256_changed" in detect_drift(c, current_inp_sha256=INP_B)
    reasons = detect_drift(
        c,
        current_inp_sha256=INP_A,
        current_dependency_hashes={"include/material.inc": "0" * 64},
    )
    assert any(r.startswith("dependency_changed:") for r in reasons)
    reasons = detect_drift(
        c,
        current_inp_sha256=INP_A,
        current_dependency_hashes=dict(DEP, extra="1" * 64),
    )
    assert any(r.startswith("dependency_added:") for r in reasons)
    assert "solver_config_changed" in detect_drift(
        c, current_inp_sha256=INP_A, current_solver_config=dict(SOLVER_CFG, step="ExplicitDynamicsStep")
    )
    assert "generator_version_changed" in detect_drift(
        c, current_inp_sha256=INP_A, current_generator_version="2.0.0"
    )


def _approved():
    return approve_candidate(_proposed(), approved_by="chenlei")


def test_gate_rejects_missing_candidate():
    with pytest.raises(CandidateNotApprovedError):
        assert_submittable(None, current_inp_sha256=INP_A)


def test_gate_rejects_proposed_candidate():
    with pytest.raises(CandidateNotApprovedError):
        assert_submittable(_proposed(), current_inp_sha256=INP_A)


def test_gate_rejects_superseded_candidate():
    old = supersede_candidate(_approved(), by_candidate_id="cand-2")
    with pytest.raises(CandidateNotApprovedError):
        assert_submittable(old, current_inp_sha256=INP_A)


def test_gate_rejects_approval_not_bound_to_manifest():
    forged = dataclasses.replace(
        _approved(),
        approval=ApprovalRecord(
            candidate_id="cand-1",
            execution_manifest_hash="f" * 64,
            approved_by="mallory",
            approved_at="2026-10-27T02:00:00+00:00",
        ),
    )
    with pytest.raises(CandidateNotApprovedError):
        assert_submittable(forged, current_inp_sha256=INP_A)


def test_gate_rejects_drift_with_reasons():
    with pytest.raises(CandidateDriftError) as excinfo:
        assert_submittable(
            _approved(),
            current_inp_sha256=INP_B,
            current_dependency_hashes=dict(DEP),
            current_solver_config=dict(SOLVER_CFG),
        )
    assert "inp_sha256_changed" in excinfo.value.drift_reasons


def test_gate_admits_approved_candidate_without_drift():
    c = assert_submittable(
        _approved(),
        current_inp_sha256=INP_A,
        current_dependency_hashes=dict(DEP),
        current_solver_config=dict(SOLVER_CFG),
        current_generator_version="1.2.3",
    )
    assert c.status is CandidateStatus.APPROVED


def test_persistence_roundtrip(tmp_path):
    c = _approved()
    write_candidate(tmp_path, c)
    assert load_candidate(tmp_path) == c
    assert candidate_path(tmp_path).is_file()


def test_load_returns_none_when_absent(tmp_path):
    assert load_candidate(tmp_path) is None


def test_write_archives_previous_candidate(tmp_path):
    first = _proposed()
    second = _proposed(candidate_id="cand-2")
    write_candidate(tmp_path, first)
    write_candidate(tmp_path, second)
    assert load_candidate(tmp_path).candidate_id == "cand-2"
    archive = tmp_path / "execution_candidate.cand-1.json"
    assert archive.is_file()
    archived = ExecutionCandidate.from_dict(json.loads(archive.read_text(encoding="utf-8")))
    assert archived.candidate_id == "cand-1"


def test_load_fails_closed_on_corrupt_file(tmp_path):
    candidate_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ApprovalError):
        load_candidate(tmp_path)


def test_load_fails_closed_on_tampered_file(tmp_path):
    c = _approved()
    write_candidate(tmp_path, c)
    payload = json.loads(candidate_path(tmp_path).read_text(encoding="utf-8"))
    payload["inp_sha256"] = INP_B
    candidate_path(tmp_path).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ApprovalError):
        load_candidate(tmp_path)
