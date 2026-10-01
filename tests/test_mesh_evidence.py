from abaqus_ai_agent.actions import verify_mesh_quality
from abaqus_ai_agent.actions.runner import preview
from abaqus_ai_agent.evidence.model import EvidenceBundle


def test_mesh_verification_script_preserves_native_result_contract():
    code = preview(verify_mesh_quality("M", "P", criterion="ASPECT_RATIO", threshold=5.0))
    assert "verifyMeshQuality" in code
    assert "failed_element_labels" in code
    assert "warning_element_labels" in code
    assert "source" in code
    assert "abaqus_native_verify" in code


def test_mesh_quality_evidence_is_typed_without_score_conversion():
    # EvidenceBundle is intentionally generic; execute_verified adds the typed
    # mesh_quality_verification item while preserving the executor's raw result.
    bundle = EvidenceBundle().add(__import__("abaqus_ai_agent.evidence.model", fromlist=["Evidence"]).Evidence(
        kind="mesh_quality_verification",
        source="abaqus_native_verify",
        locator="P",
        value={"criterion": "ASPECT_RATIO", "failed_element_labels": [7]},
        metadata={"threshold": 5.0},
    ))
    item = bundle.require("mesh_quality_verification", "abaqus_native_verify")[0]
    assert item.value["failed_element_labels"] == [7]
    assert item.metadata["threshold"] == 5.0
