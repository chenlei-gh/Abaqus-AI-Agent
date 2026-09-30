from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class SessionHealth:
    connected: bool
    abaqus_version: str = "unknown"
    python_version: str = ""
    gui_available: bool = False
    current_model: Optional[str] = None
    current_viewport: Optional[str] = None
    workdir: Optional[str] = None
    model_count: int = 0
    job_count: int = 0
    capabilities: Tuple[str, ...] = ()
    last_job_status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def supports(self, capability):
        return capability in self.capabilities
