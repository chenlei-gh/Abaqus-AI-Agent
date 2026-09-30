from abaqus_ai_agent.evidence import classify_job_status, summarize_odb


def test_job_status_classification():
    assert classify_job_status("COMPLETED") == "completed"
    assert classify_job_status("RUNNING") == "running"
    assert classify_job_status("ABORTED") == "failed"


def test_odb_summary():
    out = summarize_odb({"steps": ["Step-1"], "instances": ["PART-1-1"], "step_frames": {"Step-1": 3}})
    assert out["step_count"] == 1
    assert out["step_frames"]["Step-1"] == 3
