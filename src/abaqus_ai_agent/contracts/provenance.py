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
    abaqus_version: Optional[str] = None
    python_version: Optional[str] = None
    executor: Optional[str] = None
    action_plan: Tuple[Dict[str, Any], ...] = ()
    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
