from abaqus_ai_agent.contracts.results import (
    ResultRequirement, requirement_from_criterion, required_field_variables
)
from abaqus_ai_agent.execution.artifacts import JobArtifacts, JobArtifact
from abaqus_ai_agent.execution.results import extract_criteria


def test_common_criteria_map_to_deterministic_odb_queries():
    stress = requirement_from_criterion({
        "name": "stress", "value_key": "max_stress",
        "operator": "<", "limit": 250, "unit": "MPa",
        "step": "Step-1"
    })
    disp = requirement_from_criterion({
        "name": "disp", "value_key": "max_displacement",
        "operator": "<=", "limit": 2, "unit": "mm",
        "step": "Step-1"
    })
    assert stress.field == "S"
    assert stress.invariant == "MISES"
    assert disp.field == "U"
    assert disp.invariant == "MAGNITUDE"
    assert required_field_variables((stress, disp)) == ("S", "U")


def test_explicit_result_mapping_is_supported():
    req = requirement_from_criterion({
        "value_key": "tip_u2",
        "operator": "<=",
        "limit": 1.0,
        "result": {
            "field": "U", "component": "U2",
            "aggregation": "max", "step": "Step-1"
        }
    })
    assert req.component == "U2"
    assert req.invariant is None


def test_result_extraction_uses_max_locator():
    class FakeExecutor:
        def execute(self, code, timeout=None):
            return {
                "meta": {"step": "Step-1", "frame_index": -1},
                "values": [
                    {"data": 10.0, "node_label": 1, "instance": "PART-1-1"},
                    {"data": 25.0, "node_label": 2, "instance": "PART-1-1"},
                ]
            }

    values, evidence = extract_criteria(FakeExecutor(), "job.odb", [{
        "value_key": "max_stress", "operator": "<", "limit": 30,
        "step": "Step-1"
    }])
    assert values["max_stress"] == 25.0
    assert evidence[0].metadata["value_key"] == "max_stress"
    assert evidence[0].locator.find("'node_label': 2") >= 0


def test_artifact_missing_is_explicit():
    artifacts = JobArtifacts("job", ".", (
        JobArtifact("job", ".odb", "./job.odb", False),
        JobArtifact("job", ".sta", "./job.sta", True, 100),
    ))
    assert artifacts.missing() and artifacts.missing()[0].suffix == ".odb"


def test_history_requirement_is_first_class():
    req = requirement_from_criterion({
        "value_key": "energy", "operator": ">=", "limit": 10,
        "result": {
            "output_kind": "history",
            "history_variable": "ALLIE",
            "history_region": "Assembly ASSEMBLY",
            "aggregation": "last",
            "step": "Step-1"
        }
    })
    assert req.output_kind == "history"
    assert req.history_variable == "ALLIE"


def test_history_output_plan_preserves_step_boundaries():
    from abaqus_ai_agent.planning.output import plan_outputs, actions_from_output_plan

    criteria = [
        {
            "value_key": "energy_1",
            "operator": ">=",
            "limit": 1,
            "result": {
                "output_kind": "history",
                "history_variable": "ALLIE",
                "step": "Step-1",
                "history_region_expression": "model.rootAssembly.nodeSets['N1']",
            },
        },
        {
            "value_key": "energy_2",
            "operator": ">=",
            "limit": 1,
            "result": {
                "output_kind": "history",
                "history_variable": "ALLKE",
                "step": "Step-2",
                "history_region_expression": "model.rootAssembly.nodeSets['N2']",
            },
        },
    ]

    plan = plan_outputs(criteria)
    actions = actions_from_output_plan("M", plan)
    assert len(actions) == 2
    assert actions[0].parameters["step"] == "Step-1"
    assert actions[0].parameters["variables"] == ("ALLIE",)
    assert actions[0].parameters["region_expression"].endswith("['N1']")
    assert actions[1].parameters["step"] == "Step-2"
    assert actions[1].parameters["variables"] == ("ALLKE",)
    assert actions[1].parameters["region_expression"].endswith("['N2']")
