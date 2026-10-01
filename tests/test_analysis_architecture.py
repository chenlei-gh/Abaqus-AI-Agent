from abaqus_ai_agent.contracts.model_snapshot import ModelSnapshot
from abaqus_ai_agent.state_diff import diff_snapshots
from abaqus_ai_agent.contracts.version import AbaqusRuntimeInfo
from abaqus_ai_agent.workflow import AnalysisWorkflow
from abaqus_ai_agent.contracts.mesh_quality import MeshQualityPolicy, MeshQualityResult
from abaqus_ai_agent.contracts.action import AbaqusAction
from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.execution.errors import classify_execution_error


def test_snapshot_diff_is_deterministic():
    before = ModelSnapshot(models=("M",), parts=("P",), materials=("Steel",))
    after = ModelSnapshot(models=("M",), parts=("P", "P2"), materials=("Al",))
    delta = diff_snapshots(before, after)
    assert delta.added["parts"] == ("P2",)
    assert delta.removed["materials"] == ("Steel",)


def test_runtime_capability_contract():
    info = AbaqusRuntimeInfo(version="2025", python_version="3.x",
                             gui_available=True, capabilities=("job", "odb"))
    assert info.supports("odb")
    assert not info.supports("contact")


def test_static_workflow_contains_complete_lifecycle():
    names = [step.name for step in AnalysisWorkflow.standard_static().steps]
    assert names[0] == "inspect_model"
    assert names[-1] == "evidence"
    assert "mesh_quality" in names
    assert "odb" in names


def test_mesh_quality_source_is_explicit():
    result = MeshQualityResult("pass", {"max_aspect_ratio": 2.0}, source="computed_quality")
    assert result.passed
    assert result.source == "computed_quality"


def test_execution_error_classification():
    assert classify_execution_error("SyntaxError: invalid syntax") == "syntax"
    assert classify_execution_error("Region not found") == "region_invalid"


def test_mesh_quality_policy_covers_native_verification():
    policy = MeshQualityPolicy(
        max_aspect_ratio=5.0,
        max_angular_deviation=20.0,
        max_geometric_deviation_factor=0.1,
        analysis_checks=True,
    )
    assert policy.analysis_checks
    assert policy.max_aspect_ratio == 5.0


def test_mesh_quality_script_uses_native_abaqus_verifier():
    action = AbaqusAction(
        action_type="mesh_quality",
        model_name="Model-1",
        target=None,
        parameters={
            "part": "Part-1",
            "max_aspect_ratio": 5.0,
            "max_angular_deviation": 20.0,
            "max_geometric_deviation_factor": 0.1,
            "analysis_checks": True,
        },
    )
    script = action_to_script(action)
    assert "verifyMeshQuality" in script
    assert "ASPECT_RATIO" in script
    assert "ANALYSIS_CHECKS" in script
    assert "computed_quality" not in script
