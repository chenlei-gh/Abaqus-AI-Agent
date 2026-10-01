from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.execution.analysis_run import _provenance_with_artifacts
from abaqus_ai_agent.execution.artifacts import JobArtifact


def test_artifact_manifest_is_stable_and_attached_to_provenance():
    p = AnalysisProvenance(run_id="r1", model_name="M", job_name="J", executor="Fake")
    artifacts = (JobArtifact("J", ".odb", "/tmp/J.odb", True, 12, 1.0),)
    updated = _provenance_with_artifacts(p, artifacts)
    assert updated.artifact_manifest_hash
    assert updated.artifact_manifest_hash == _provenance_with_artifacts(p, artifacts).artifact_manifest_hash
    assert updated.run_id == "r1"
