from dataclasses import dataclass, field
from typing import Dict, Tuple

@dataclass(frozen=True)
class AbaqusRuntimeInfo:
    version: str="unknown"
    python_version: str="unknown"
    gui_available: bool=False
    capabilities: Tuple[str,...]=()
    metadata: Dict[str,str]=field(default_factory=dict)
    def supports(self, capability): return capability in self.capabilities
