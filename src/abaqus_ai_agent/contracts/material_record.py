"""MaterialRecord semantic contracts for engineering polymers and external databases (CAMPUS, Manufacturer TDS).

This layer encapsulates real-world material identity, source provenance, conditioning state,
standardized ISO properties, and experimental multi-point curves.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MaterialIdentity:
    """Canonical real-world identity of a commercial or experimental material."""
    polymer_family: str                      # e.g. "PA66", "POM", "PBT", "Steel"
    manufacturer: str                        # e.g. "BASF", "DuPont", "Covestro"
    grade: str                               # e.g. "Ultramid A3WG6", "Delrin 100"
    trade_name: Optional[str] = None         # e.g. "Ultramid"
    reinforcement_type: Optional[str] = None # e.g. "glass_fiber", "carbon_fiber"
    reinforcement_content: Optional[float] = None  # in wt%, e.g. 30.0
    filler_type: Optional[str] = None        # e.g. "mineral", "ptfe"
    variant: Optional[str] = None            # e.g. "heat_stabilized", "impact_modified"

    def __post_init__(self):
        if not self.polymer_family:
            raise ValueError("polymer_family is required")
        if not self.manufacturer:
            raise ValueError("manufacturer is required")
        if not self.grade:
            raise ValueError("grade is required")
        if self.reinforcement_content is not None and not (0.0 <= self.reinforcement_content <= 100.0):
            raise ValueError("reinforcement_content must be between 0.0 and 100.0 wt%")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "polymer_family": self.polymer_family,
            "manufacturer": self.manufacturer,
            "grade": self.grade,
            "trade_name": self.trade_name,
            "reinforcement_type": self.reinforcement_type,
            "reinforcement_content": self.reinforcement_content,
            "filler_type": self.filler_type,
            "variant": self.variant,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialIdentity":
        return cls(
            polymer_family=data["polymer_family"],
            manufacturer=data["manufacturer"],
            grade=data["grade"],
            trade_name=data.get("trade_name"),
            reinforcement_type=data.get("reinforcement_type"),
            reinforcement_content=float(data["reinforcement_content"]) if data.get("reinforcement_content") is not None else None,
            filler_type=data.get("filler_type"),
            variant=data.get("variant"),
        )


@dataclass(frozen=True)
class MaterialSource:
    """Provenance and authority metadata for a material data record."""
    provider: str                            # e.g. "CAMPUS", "Manufacturer_TDS", "Lab_Test"
    source_type: str                         # e.g. "iso_database", "datasheet_pdf", "internal"
    locator: str                             # URL, DOI, document ID, or internal accession
    retrieved_at: str                        # ISO-8601 UTC timestamp
    source_version: Optional[str] = None     # Database or revision version
    evidence_level: str = "manufacturer_published"  # "certified_lab", "manufacturer_published", "handbook", "estimate"
    license_note: Optional[str] = None

    def __post_init__(self):
        if not self.provider:
            raise ValueError("provider is required")
        if not self.locator:
            raise ValueError("locator is required")
        if not self.retrieved_at:
            raise ValueError("retrieved_at timestamp is required")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "source_type": self.source_type,
            "locator": self.locator,
            "retrieved_at": self.retrieved_at,
            "source_version": self.source_version,
            "evidence_level": self.evidence_level,
            "license_note": self.license_note,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialSource":
        return cls(
            provider=data["provider"],
            source_type=data.get("source_type", "iso_database"),
            locator=data["locator"],
            retrieved_at=data["retrieved_at"],
            source_version=data.get("source_version"),
            evidence_level=data.get("evidence_level", "manufacturer_published"),
            license_note=data.get("license_note"),
        )


@dataclass(frozen=True)
class MaterialCondition:
    """Testing or operating environmental state."""
    temperature: float                       # in declared unit (e.g. 23.0)
    temperature_unit: str = "C"              # "C" or "K"
    humidity_state: str = "dry"              # "dry", "conditioned", "saturated", "ambient"
    relative_humidity: Optional[float] = None  # in %, e.g. 50.0
    test_standard: Optional[str] = None      # e.g. "ISO 527-1/-2", "ISO 178", "ISO 1183"
    strain_rate: Optional[float] = None      # in 1/s, e.g. 0.001
    test_time: Optional[float] = None        # in seconds, e.g. for creep relaxation
    frequency: Optional[float] = None        # in Hz, e.g. for dynamic mechanical analysis (DMA)
    stress_level: Optional[float] = None     # in MPa, e.g. sustained stress for isochronous curves

    def matches(self, other: "MaterialCondition", temp_tol: float = 0.5) -> bool:
        """Check if this condition satisfies the requested target condition."""
        if abs(self.temperature - other.temperature) > temp_tol:
            return False
        if self.humidity_state.lower() != other.humidity_state.lower():
            return False
        # If relative humidity is explicitly provided in both, check within 5%
        if self.relative_humidity is not None and other.relative_humidity is not None:
            if abs(self.relative_humidity - other.relative_humidity) > 5.0:
                return False
        # If strain_rate is specified in target, condition must match within 20%
        if other.strain_rate is not None:
            if self.strain_rate is None or abs(self.strain_rate - other.strain_rate) / max(other.strain_rate, 1e-9) > 0.2:
                return False
        # If frequency is specified in target, condition must match within 10%
        if other.frequency is not None:
            if self.frequency is None or abs(self.frequency - other.frequency) / max(other.frequency, 1e-9) > 0.1:
                return False
        # If test_time (creep) is specified in target, condition must match within 15%
        if other.test_time is not None:
            if self.test_time is None or abs(self.test_time - other.test_time) / max(other.test_time, 1e-9) > 0.15:
                return False
        # If test_standard is specified in target, must match or be compatible family
        if other.test_standard is not None and self.test_standard is not None:
            norm_self = self.test_standard.strip().lower().replace(" ", "").replace("-", "")
            norm_other = other.test_standard.strip().lower().replace(" ", "").replace("-", "")
            if norm_self != norm_other and not (norm_self.startswith(norm_other) or norm_other.startswith(norm_self)):
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "temperature_unit": self.temperature_unit,
            "humidity_state": self.humidity_state,
            "relative_humidity": self.relative_humidity,
            "test_standard": self.test_standard,
            "strain_rate": self.strain_rate,
            "test_time": self.test_time,
            "frequency": self.frequency,
            "stress_level": self.stress_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialCondition":
        return cls(
            temperature=float(data.get("temperature", 23.0)),
            temperature_unit=data.get("temperature_unit", "C"),
            humidity_state=data.get("humidity_state", "dry"),
            relative_humidity=float(data["relative_humidity"]) if data.get("relative_humidity") is not None else None,
            test_standard=data.get("test_standard"),
            strain_rate=float(data["strain_rate"]) if data.get("strain_rate") is not None else None,
            test_time=float(data["test_time"]) if data.get("test_time") is not None else None,
            frequency=float(data["frequency"]) if data.get("frequency") is not None else None,
            stress_level=float(data["stress_level"]) if data.get("stress_level") is not None else None,
        )


@dataclass(frozen=True)
class MaterialProperty:
    """Standardized scalar material property with environmental condition."""
    name: str                                # e.g. "youngs_modulus", "yield_stress", "density"
    value: float
    unit: str                                # e.g. "MPa", "g/cm3", "W/(m*K)", "1/K"
    quantity: str                            # e.g. "stress", "density", "thermal_conductivity"
    condition: Optional[MaterialCondition] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("property name is required")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "quantity": self.quantity,
            "condition": self.condition.to_dict() if self.condition else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialProperty":
        cond = MaterialCondition.from_dict(data["condition"]) if data.get("condition") else None
        return cls(
            name=data["name"],
            value=float(data["value"]),
            unit=data["unit"],
            quantity=data.get("quantity", "stress"),
            condition=cond,
        )


@dataclass(frozen=True)
class MaterialCurve:
    """Multi-point experimental curve (e.g. ISO 11403-1 stress-strain, isochronous creep)."""
    curve_type: str                          # "stress_strain", "modulus_temperature", "creep_isochronous", "dma"
    x_name: str                              # e.g. "nominal_strain"
    x_unit: str                              # e.g. "mm/mm", "%"
    y_name: str                              # e.g. "nominal_stress"
    y_unit: str                              # e.g. "MPa"
    points: Tuple[Tuple[float, float], ...]  # ((x0, y0), (x1, y1), ...)
    condition: MaterialCondition

    def __post_init__(self):
        if not self.curve_type:
            raise ValueError("curve_type is required")
        if len(self.points) < 2:
            raise ValueError("curve must contain at least 2 points")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "curve_type": self.curve_type,
            "x_name": self.x_name,
            "x_unit": self.x_unit,
            "y_name": self.y_name,
            "y_unit": self.y_unit,
            "points": [list(pt) for pt in self.points],
            "condition": self.condition.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialCurve":
        return cls(
            curve_type=data["curve_type"],
            x_name=data["x_name"],
            x_unit=data["x_unit"],
            y_name=data["y_name"],
            y_unit=data["y_unit"],
            points=tuple((float(p[0]), float(p[1])) for p in data["points"]),
            condition=MaterialCondition.from_dict(data["condition"]),
        )


@dataclass(frozen=True)
class MaterialRecord:
    """Canonical real-world material envelope encapsulating identity, source, properties, and curves."""
    identity: MaterialIdentity
    source: MaterialSource
    properties: Tuple[MaterialProperty, ...] = ()
    curves: Tuple[MaterialCurve, ...] = ()
    default_condition: MaterialCondition = field(default_factory=lambda: MaterialCondition(temperature=23.0, humidity_state="dry"))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_property(self, name: str, condition: Optional[MaterialCondition] = None) -> Optional[MaterialProperty]:
        """Retrieve scalar property by name, strictly matching condition when requested.
        
        Anti-Hallucination Gate: If a specific environmental condition is requested
        and no property entry matches that condition, returns None (fail-closed)
        rather than returning an arbitrary unconditioned property.
        """
        candidates = [p for p in self.properties if p.name == name]
        if not candidates:
            return None
        if condition is None:
            # Return unconditionally or default-matched
            return candidates[0]
        # Multi-dimensional matching via condition.matches
        for p in candidates:
            if p.condition and p.condition.matches(condition):
                return p
        # Strict fail-closed: Do NOT fallback to unconditioned or mismatched room temp!
        return None

    def get_curve(self, curve_type: str, condition: Optional[MaterialCondition] = None) -> Optional[MaterialCurve]:
        """Retrieve multi-point curve by type, strictly matching condition when requested."""
        candidates = [c for c in self.curves if c.curve_type == curve_type]
        if not candidates:
            return None
        if condition is None:
            return candidates[0]
        for c in candidates:
            if c.condition and c.condition.matches(condition):
                return c
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "source": self.source.to_dict(),
            "properties": [p.to_dict() for p in self.properties],
            "curves": [c.to_dict() for c in self.curves],
            "default_condition": self.default_condition.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialRecord":
        return cls(
            identity=MaterialIdentity.from_dict(data["identity"]),
            source=MaterialSource.from_dict(data["source"]),
            properties=tuple(MaterialProperty.from_dict(p) for p in data.get("properties", [])),
            curves=tuple(MaterialCurve.from_dict(c) for c in data.get("curves", [])),
            default_condition=MaterialCondition.from_dict(data.get("default_condition", {})),
            metadata=dict(data.get("metadata", {})),
        )
