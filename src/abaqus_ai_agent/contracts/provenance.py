from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class AnalysisProvenance:
    """Reproducibility metadata for one analysis run."""
    run_id: str
    model_name: str
    job_name: str
    model_hash: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    artifact_manifest_hash: Optional[str] = None
    intent_hash: Optional[str] = None
    action_plan_hash: Optional[str] = None
    abaqus_version: Optional[str] = None
    python_version: Optional[str] = None
    executor: Optional[str] = None
    action_plan: Tuple[Dict[str, Any], ...] = ()
    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_name": self.model_name,
            "job_name": self.job_name,
            "model_hash": self.model_hash,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "intent_hash": self.intent_hash,
            "action_plan_hash": self.action_plan_hash,
            "abaqus_version": self.abaqus_version,
            "python_version": self.python_version,
            "executor": self.executor,
            "action_plan": list(self.action_plan),
            "environment": dict(self.environment),
            "metadata": dict(self.metadata),
        }
