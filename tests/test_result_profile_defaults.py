from abaqus_ai_agent.contracts.results import requirement_from_criterion
from abaqus_ai_agent.execution.results import extract_requirement
from abaqus_ai_agent.planning.output import criteria_from_postprocess_profile
from abaqus_ai_agent.contracts.postprocess import profile_for_solver_selection


def test_result_extraction_defaults_missing_step_to_last_odb_step():
    class FakeExecutor:
        def execute(self, code, timeout=None):
            if "names=list(odb.steps.keys())" in code:
                return "Step-2"
            return {
                "meta": {"step": "Step-2", "frame_index": -1},
                "values": [{"data": 42.0, "node_label": 7, "instance": "PART-1-1"}],
            }

    result = extract_requirement(
        FakeExecutor(),
        "job.odb",
        requirement_from_criterion({"value_key": "max_mises"}),
    )
    assert result.value == 42.0
    assert result.locator["step"] == "Step-2"


def test_buckling_profile_uses_frame_value_not_frequency():
    class Selection:
        strategy = "BUCKLING"

    profile = profile_for_solver_selection(Selection())
    criteria = criteria_from_postprocess_profile(profile)
    assert criteria[0]["value_key"] == "buckling_factor"
    assert criteria[0]["result"]["output_kind"] == "frame_value"


def test_buckling_profile_criteria_are_extractable():
    class Selection:
        strategy = "BUCKLING"

    criteria = criteria_from_postprocess_profile(profile_for_solver_selection(Selection()))
    req = requirement_from_criterion(criteria[0])
    assert req.output_kind == "frame_value"
    assert req.step is None
