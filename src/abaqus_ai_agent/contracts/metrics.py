from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

@dataclass(frozen=True)
class EngineeringMetric:
    """Normalized engineering result consumable by checks, acceptance and reports."""
    name: str
    value: float
    unit: str = ""
    quantity: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    step: Optional[str] = None
    frame: Optional[int] = None
    component: Optional[str] = None
    source: str = "odb"
    evidence: Tuple[Dict[str, Any], ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)
    def __post_init__(self):
        if not self.name: raise ValueError("metric name is required")
        if not isinstance(self.value, (int, float)): raise TypeError("metric value must be numeric")

def metric_from_extraction(extraction):
    req = extraction.requirement
    locator = dict(extraction.locator or {})
    return EngineeringMetric(req.name, float(extraction.value), req.unit, req.quantity, locator or None, locator.get("step"), locator.get("frame"), req.component or req.invariant, "odb", tuple(extraction.evidence or ()), {"value_key": req.value_key, "aggregation": req.aggregation, "output_kind": req.output_kind, "field": req.field, "history_variable": req.history_variable})

def metrics_from_extractions(extractions):
    return tuple(metric_from_extraction(item) for item in extractions or ())
