"""P1.3 Result Intelligence & Engineering Deliverable Contracts.

Defines:
1. XYPoint & XYCurveData for complete history and parametric response tracking.
2. SpatialHotspot for Top-K localized stress/deformation concentration identification.
3. DerivedEngineeringMetrics for force equilibrium, energy balance, and factor of safety.
4. ResultIntelligenceBundle consolidating physical extractions, curves, hotspots, and derived facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class XYPoint:
    """A single coordinate pair on an engineering response curve."""
    x: float
    y: float

    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class XYCurveData:
    """Deterministic time-history or parametric response curve."""
    curve_name: str
    x_label: str = "Time"
    y_label: str = "Value"
    x_unit: str = "s"
    y_unit: str = ""
    points: Tuple[XYPoint, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def x_values(self) -> Tuple[float, ...]:
        return tuple(p.x for p in self.points)

    @property
    def y_values(self) -> Tuple[float, ...]:
        return tuple(p.y for p in self.points)

    @property
    def min_y(self) -> float:
        return min(self.y_values) if self.points else 0.0

    @property
    def max_y(self) -> float:
        return max(self.y_values) if self.points else 0.0

    @property
    def peak_abs_y(self) -> float:
        return max(abs(y) for y in self.y_values) if self.points else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "curve_name": self.curve_name,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "x_unit": self.x_unit,
            "y_unit": self.y_unit,
            "point_count": self.point_count,
            "min_y": self.min_y,
            "max_y": self.max_y,
            "peak_abs_y": self.peak_abs_y,
            "points": [p.to_tuple() for p in self.points],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SpatialHotspot:
    """Localized spatial concentration identification in 3D FE continuum."""
    rank: int
    value: float
    field_name: str = "S"
    component: str = "Mises"
    unit: str = "MPa"
    coordinates: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    instance: str = "PART-1-1"
    element_label: Optional[int] = None
    node_label: Optional[int] = None
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "value": self.value,
            "field_name": self.field_name,
            "component": self.component,
            "unit": self.unit,
            "coordinates": list(self.coordinates),
            "instance": self.instance,
            "element_label": self.element_label,
            "node_label": self.node_label,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ReactionForceBalance:
    """Deterministic physical equilibrium check between applied loads and reactions."""
    applied_magnitude: float
    reaction_magnitude: float
    balance_error_percent: float
    is_balanced: bool
    applied_components: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    reaction_components: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    unit: str = "N"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied_magnitude": self.applied_magnitude,
            "reaction_magnitude": self.reaction_magnitude,
            "balance_error_percent": self.balance_error_percent,
            "is_balanced": self.is_balanced,
            "applied_components": list(self.applied_components),
            "reaction_components": list(self.reaction_components),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class EnergyStability:
    """Numerical stability and energy conservation metrics."""
    total_energy_drift_ratio: float
    kinetic_energy_ratio: Optional[float] = None
    is_stable: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_energy_drift_ratio": self.total_energy_drift_ratio,
            "kinetic_energy_ratio": self.kinetic_energy_ratio,
            "is_stable": self.is_stable,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class FactorOfSafetyMetric:
    """Derived engineering factor of safety and margin of safety.
    
    NOTE: Factor of safety is a derived physical fact relative to nominal strength.
    Structural adequacy/pass is strictly evaluated by the Acceptance Engine.
    """
    max_stress: float
    yield_strength: float
    factor_of_safety: float
    margin_of_safety: float
    stress_component: str = "Mises"
    material_name: str = "Q235"
    unit: str = "MPa"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_stress": self.max_stress,
            "yield_strength": self.yield_strength,
            "factor_of_safety": self.factor_of_safety,
            "margin_of_safety": self.margin_of_safety,
            "stress_component": self.stress_component,
            "material_name": self.material_name,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class DerivedEngineeringMetrics:
    """Consolidated set of derived physical and structural metrics."""
    force_balance: Optional[ReactionForceBalance] = None
    energy_stability: Optional[EnergyStability] = None
    safety_factor: Optional[FactorOfSafetyMetric] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "force_balance": self.force_balance.to_dict() if self.force_balance else None,
            "energy_stability": self.energy_stability.to_dict() if self.energy_stability else None,
            "safety_factor": self.safety_factor.to_dict() if self.safety_factor else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResultIntelligenceBundle:
    """Top-level container for all P1.3 result delivery assets."""
    primary_metrics: Dict[str, float] = field(default_factory=dict)
    hotspots: Tuple[SpatialHotspot, ...] = ()
    curves: Tuple[XYCurveData, ...] = ()
    derived_metrics: Optional[DerivedEngineeringMetrics] = None
    figure_paths: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_metrics": dict(self.primary_metrics),
            "hotspot_count": len(self.hotspots),
            "hotspots": [h.to_dict() for h in self.hotspots],
            "curve_count": len(self.curves),
            "curves": [c.to_dict() for c in self.curves],
            "derived_metrics": self.derived_metrics.to_dict() if self.derived_metrics else None,
            "figure_paths": list(self.figure_paths),
            "metadata": dict(self.metadata),
        }
