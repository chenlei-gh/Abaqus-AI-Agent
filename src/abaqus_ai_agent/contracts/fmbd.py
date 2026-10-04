"""Flexible Multibody Dynamics (FMBD) Intent, Rigid-Flexible Coupling & Verification Contracts."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from .connector import IntentConnectorSpec


class BodyType(str, Enum):
    """Body structural representation in multibody and FMBD mechanisms."""
    RIGID = "RIGID"
    FLEXIBLE = "FLEXIBLE"
    GROUND = "GROUND"


@dataclass(frozen=True)
class RigidBodySpec:
    """Specification of a rigid body constraint in an FMBD assembly."""
    name: str
    ref_point_name: str
    body_region: Optional[str] = None          # e.g. "a.sets['CrankCells']"
    tie_region: Optional[str] = None           # e.g. "a.sets['RP_ElbowCrank']"
    pin_region: Optional[str] = None
    point_coords: Optional[Tuple[float, float, float]] = None  # Reference Point coordinates (x, y, z)
    part_name: Optional[str] = None
    instance_name: Optional[str] = None

    @property
    def ref_point_expression(self) -> str:
        return f"a.sets['{self.ref_point_name}']"


@dataclass(frozen=True)
class FlexibleInterfaceSpec:
    """Coupling interface between a flexible finite element body and a connector/reference point."""
    name: str
    control_point_name: Optional[str] = None
    ref_point_name: Optional[str] = None
    point_coords: Optional[Tuple[float, float, float]] = None
    ref_point_coords: Optional[Tuple[float, float, float]] = None
    surface_region: Optional[str] = None
    surface_expression: Optional[str] = None
    interface_region: Optional[str] = None
    body_name: Optional[str] = None
    coupling_type: str = "KINEMATIC"           # "KINEMATIC" or "DISTRIBUTING"
    influence_radius: Optional[float] = None
    u1: bool = True
    u2: bool = True
    u3: bool = True
    ur1: bool = True
    ur2: bool = True
    ur3: bool = True

    @property
    def effective_control_point(self) -> str:
        return self.control_point_name or self.ref_point_name or f"{self.name}_RP"

    @property
    def effective_surface_region(self) -> str:
        res = self.surface_region or self.surface_expression or self.interface_region
        if not res:
            raise ValueError(f"FlexibleInterfaceSpec '{self.name}' must provide surface_region or surface_expression")
        return res

    @property
    def effective_coords(self) -> Optional[Tuple[float, float, float]]:
        return self.point_coords or self.ref_point_coords


@dataclass(frozen=True)
class IntentFMBDSpec:
    """High-level engineering intent for flexible multibody coupled dynamics."""
    name: str = "FMBD_Spec"
    rigid_bodies: Sequence[RigidBodySpec] = field(default_factory=tuple)
    flexible_interfaces: Sequence[FlexibleInterfaceSpec] = field(default_factory=tuple)
    connectors: Sequence[IntentConnectorSpec] = field(default_factory=tuple)
    gravity: Optional[Tuple[float, float, float]] = None  # (comp1, comp2, comp3) e.g. (0.0, -9810.0, 0.0)
    time_period: float = 1.0
    initial_inc: float = 0.005
    max_inc: float = 0.01
    min_inc: float = 1e-6
    max_num_inc: int = 500
    nlgeom: bool = True
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "rigid_bodies_count": len(self.rigid_bodies),
            "flexible_interfaces_count": len(self.flexible_interfaces),
            "connectors_count": len(self.connectors),
            "gravity": self.gravity,
            "time_period": self.time_period,
            "nlgeom": self.nlgeom,
        }


@dataclass(frozen=True)
class FMBDKinematicsVerification:
    """Verification results extracted from live Abaqus ODB for FMBD dynamics."""
    status: str = "pass"
    joint_drift_max_mm: float = 0.0
    max_mises_stress_mpa: float = 0.0
    strain_energy_ratio: float = 0.0
    energy_dissipation_ratio: float = 0.0
    frame_count: int = 0
    extracted_fields: Tuple[str, ...] = ("S", "U", "CU", "CTF")
    failures: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "pass" and len(self.failures) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "joint_drift_max_mm": self.joint_drift_max_mm,
            "max_mises_stress_mpa": self.max_mises_stress_mpa,
            "strain_energy_ratio": self.strain_energy_ratio,
            "energy_dissipation_ratio": self.energy_dissipation_ratio,
            "frame_count": self.frame_count,
            "extracted_fields": list(self.extracted_fields),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "details": self.details,
        }
