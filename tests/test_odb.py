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
def test_extract_reaction_evidence_uses_rf_field_and_history():
    from abaqus_ai_agent.execution.odb import extract_reaction_evidence

    class FakeExecutor:
        def __init__(self):
            self.calls = []
        def execute(self, code):
            self.calls.append(code)
            return {"status": "available"}

    executor = FakeExecutor()
    result = extract_reaction_evidence(
        executor, "job.odb", "Step-1",
        history_region="Node PART-1-1.1",
        component="RF1",
    )
    assert result["step"] == "Step-1"
    assert len(executor.calls) == 2
    assert "'RF'" in executor.calls[0]
    assert "historyRegions" in executor.calls[1]


def test_extract_energy_evidence_requests_standard_energy_history():
    from abaqus_ai_agent.execution.odb import extract_energy_evidence

    class FakeExecutor:
        def __init__(self):
            self.code = None
        def execute(self, code):
            self.code = code
            return {"step": "Step-1", "region": "Assembly ASSEMBLY",
                    "variables": {"ALLIE": [(0.0, 1.0)], "ALLKE": None}}

    executor = FakeExecutor()
    result = extract_energy_evidence(
        executor, "job.odb", "Step-1", "Assembly ASSEMBLY"
    )
    assert result["step"] == "Step-1"
    assert "ALLIE" in result["variables"]
    assert "ALLKE" in result["variables"]
    assert "ALLWK" in result["variables"]
    assert "ALLAE" in result["variables"]
    assert "historyRegions" in executor.code
    assert "historyOutputs" in executor.code
