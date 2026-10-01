def test_extract_contact_field_generates_explicit_missing_output_state():
    from abaqus_ai_agent.execution.odb import extract_contact_field

    class FakeExecutor:
        def __init__(self):
            self.code = None
        def execute(self, code):
            self.code = code
            return {"status": "unavailable"}

    executor = FakeExecutor()
    result = extract_contact_field(executor, "job.odb", "Step-1", "CPRESS")
    assert result["status"] == "unavailable"
    assert "field_output_missing" in executor.code
    assert "available=list(fr.fieldOutputs.keys())" in executor.code


def test_extract_contact_history_keeps_missing_variable_distinct_from_zero():
    from abaqus_ai_agent.execution.odb import extract_contact_history

    class FakeExecutor:
        def execute(self, code):
            assert "history_output_missing" in code
            return {"status": "available", "variables": {
                "CPRESS": {"status": "available", "data": [(0.0, 0.0)]},
                "COPEN": {"status": "unavailable", "reason": "history_output_missing"},
            }}

    result = extract_contact_history(
        FakeExecutor(), "job.odb", "Step-1",
        region="Assembly ASSEMBLY", variables=("CPRESS", "COPEN"))
    assert result["variables"]["CPRESS"]["status"] == "available"
    assert result["variables"]["CPRESS"]["data"][-1][1] == 0.0
    assert result["variables"]["COPEN"]["status"] == "unavailable"