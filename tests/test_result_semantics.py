import pytest
from abaqus_ai_agent.contracts.results import (
    ResultRequirement,
    ResultExtraction,
    requirement_from_criterion,
    requirements_from_criteria,
)
from abaqus_ai_agent.contracts.metrics import (
    EngineeringMetric,
    metric_from_extraction,
    metrics_from_extractions,
)
from abaqus_ai_agent.planning.output import plan_outputs, actions_from_output_plan


def test_declarative_result_requirement_semantics():
    req = ResultRequirement(
        name="max_root_mises",
        value_key="max_mises",
        field="S",
        invariant="MISES",
        region="ROOT",
        reducer="max",
        unit="MPa",
        quantity="stress",
        required=True,
    )
    assert req.aggregation == "max"
    assert req.reducer == "max"
    assert req.source == "odb"
    assert req.required is True
    assert req.region == "ROOT"

    d = req.to_dict()
    assert d["name"] == "max_root_mises"
    assert d["field"] == "S"
    assert d["invariant"] == "MISES"
    assert d["region"] == "ROOT"
    assert d["reducer"] == "max"
    assert d["required"] is True


def test_result_requirement_reducer_aliases():
    req_mean = ResultRequirement(
        name="avg_stress",
        value_key="avg_s",
        field="S",
        reducer="mean",
    )
    assert req_mean.aggregation == "average"
    assert req_mean.reducer == "average"

    with pytest.raises(ValueError, match="unsupported aggregation/reducer"):
        ResultRequirement(name="bad", value_key="bad", field="S", reducer="unsupported_reducer")


def test_requirement_from_criterion_with_metadata_and_region():
    criterion = {
        "name": "critical_stress",
        "value_key": "max_mises",
        "region": "CRITICAL_SET",
        "reducer": "max",
        "unit": "MPa",
        "unit_system": "SI_MM",
        "required": True,
        "source": "odb",
    }
    req = requirement_from_criterion(criterion)
    assert req.name == "critical_stress"
    assert req.field == "S"
    assert req.invariant == "MISES"
    assert req.region == "CRITICAL_SET"
    assert req.aggregation == "max"
    assert req.required is True
    assert req.source == "odb"


def test_output_planning_driven_by_result_requirements():
    req1 = ResultRequirement(
        name="tip_disp",
        value_key="max_u",
        field="U",
        invariant="MAGNITUDE",
    )
    req2 = ResultRequirement(
        name="energy_balance",
        value_key="history_ALLKE",
        output_kind="history",
        history_variable="ALLKE",
        step="Step-1",
    )

    plan = plan_outputs(requirements=(req1, req2))
    assert "U" in plan.field_variables
    assert "ALLKE" in plan.history_variables
    assert len(plan.history_requests) == 1
    assert plan.history_requests[0][0] == "Step-1"
    assert "ALLKE" in plan.history_requests[0][2]

    # Can be materialized into actions
    actions = actions_from_output_plan("Model-1", plan)
    assert len(actions) == 2
    types = [a.action_type for a in actions]
    assert "field_output" in types
    assert "history_output" in types


def test_engineering_metric_traceability():
    req = ResultRequirement(
        name="root_stress",
        value_key="max_mises",
        field="S",
        invariant="MISES",
        region="ROOT",
        unit="MPa",
        quantity="stress",
    )
    extraction = ResultExtraction(
        requirement=req,
        value=150.5,
        locator={
            "step": "Step-1",
            "frame": -1,
            "element_label": 42,
            "position": "INTEGRATION_POINT",
        },
        evidence=(
            {"kind": "odb_result", "source": "odb", "value": 150.5, "unit": "MPa"},
        ),
    )

    metric = metric_from_extraction(extraction)
    assert metric.name == "root_stress"
    assert metric.value == 150.5
    assert metric.unit == "MPa"
    assert metric.region == "ROOT"
    assert metric.step == "Step-1"
    assert metric.frame == -1
    assert metric.location["element_label"] == 42
    assert metric.is_traceable() is True

    summary = metric.traceability_summary()
    assert summary["is_traceable"] is True
    assert summary["has_location"] is True
    assert summary["has_evidence"] is True
    assert summary["region"] == "ROOT"

    d = metric.to_dict()
    assert d["traceable"] is True
    assert d["region"] == "ROOT"
    assert d["location"]["element_label"] == 42
