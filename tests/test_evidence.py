from abaqus_ai_agent.evidence import classify_job_status, summarize_odb


def test_job_status_classification():
    assert classify_job_status("COMPLETED") == "completed"
    assert classify_job_status("RUNNING") == "running"
    assert classify_job_status("ABORTED") == "failed"


def test_odb_summary():
    out = summarize_odb({"steps": ["Step-1"], "instances": ["PART-1-1"], "step_frames": {"Step-1": 3}})
    assert out["step_count"] == 1
    assert out["step_frames"]["Step-1"] == 3


def test_evidence_bundle_is_typed_and_queryable():
    from abaqus_ai_agent.evidence import Evidence, EvidenceBundle
    bundle = EvidenceBundle().add(Evidence("odb_result", "odb", value=12.0))
    assert len(bundle) == 1
    assert bundle.require("odb_result", "odb")[0].value == 12.0


def test_evidence_bundle_rejects_untyped_items():
    from abaqus_ai_agent.evidence import EvidenceBundle
    try:
        EvidenceBundle().add({"kind": "odb_result"})
    except TypeError:
        pass
    else:
        raise AssertionError("expected typed evidence rejection")
