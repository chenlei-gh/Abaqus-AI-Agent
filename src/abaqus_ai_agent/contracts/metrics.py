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
    region: Optional[str] = None
    required: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            raise ValueError("metric name is required")
        if not isinstance(self.value, (int, float)):
            raise TypeError("metric value must be numeric")

    def is_traceable(self) -> bool:
        """Verify whether metric is traceable to ODB evidence or locator."""
        if not self.source:
            return False
        if self.evidence:
            return True
        if self.location and any(k in self.location for k in ("element_label", "node_label", "history_region", "coordinates")):
            return True
        if self.step is not None:
            return True
        return False

    def traceability_summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "step": self.step,
            "frame": self.frame,
            "region": self.region,
            "has_location": bool(self.location),
            "has_evidence": bool(self.evidence),
            "is_traceable": self.is_traceable(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "quantity": self.quantity,
            "location": dict(self.location) if isinstance(self.location, dict) else self.location,
            "step": self.step,
            "frame": self.frame,
            "component": self.component,
            "source": self.source,
            "region": self.region,
            "required": self.required,
            "evidence": list(self.evidence),
            "traceable": self.is_traceable(),
            "metadata": dict(self.metadata),
        }

def metric_from_extraction(extraction):
    req = extraction.requirement
    locator = dict(extraction.locator or {})
    metadata = {
        "value_key": req.value_key,
        "aggregation": req.aggregation,
        "reducer": req.reducer or req.aggregation,
        "output_kind": req.output_kind,
        "field": req.field,
        "history_variable": req.history_variable,
    }
    metadata.update(dict(req.metadata or {}))
    return EngineeringMetric(
        name=req.name,
        value=float(extraction.value),
        unit=req.unit,
        quantity=req.quantity,
        location=locator or None,
        step=locator.get("step") or req.step,
        frame=locator.get("frame") if locator.get("frame") is not None else req.frame,
        component=req.component or req.invariant,
        source=req.source or "odb",
        evidence=tuple(extraction.evidence or ()),
        region=req.region,
        required=req.required,
        metadata=metadata,
    )

def metrics_from_extractions(extractions):
    return tuple(metric_from_extraction(item) for item in extractions or ())
