"""Kinematic Connector Intent and Specification Contracts."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple, Union


class ConnectorType(str, Enum):
    """Standard kinematic and assembled connection types supported in Abaqus."""
    HINGE = "HINGE"
    BEAM = "BEAM"
    TRANSLATOR = "TRANSLATOR"
    SLIDER = "SLIDER"
    CYLINDRICAL = "CYLINDRICAL"
    PLANAR = "PLANAR"
    UJOINT = "UJOINT"
    UNIVERSAL = "UNIVERSAL"
    BALL = "BALL"
    JOIN = "JOIN"
    LINK = "LINK"
    PIN = "PIN"
    SLOT = "SLOT"
    WELD = "WELD"
    BUSHING = "BUSHING"
    CARDAN = "CARDAN"
    EULER = "EULER"
    FLEXION_TORSION = "FLEXION_TORSION"
    PROJECTION_CARTESIAN = "PROJECTION_CARTESIAN"
    PROJECTION_FLEXION_TORSION = "PROJECTION_FLEXION_TORSION"
    REVOLUTE = "REVOLUTE"
    RETRACTOR = "RETRACTOR"


# Connectors requiring local coordinate system orientation in Abaqus
CONNECTOR_TYPES_REQUIRING_ORIENTATION = frozenset({
    "HINGE", "REVOLUTE", "TRANSLATOR", "SLIDER", "CYLINDRICAL",
    "PLANAR", "UJOINT", "UNIVERSAL", "SLOT", "BUSHING", "CARDAN",
    "EULER", "FLEXION_TORSION", "PROJECTION_CARTESIAN", "PROJECTION_FLEXION_TORSION"
})


@dataclass(frozen=True)
class ConnectorEndpointSpec:
    """Endpoint specification for a connector attachment point."""
    name: str
    semantic_region: Optional[str] = None          # e.g. "Elbow1", "RP_Arm1"
    point_coords: Optional[Tuple[float, float, float]] = None # (x, y, z)
    reference_point_name: Optional[str] = None     # RP name in assembly
    node_set_name: Optional[str] = None            # Node set name
    expression: Optional[str] = None               # Custom expression
    grounded_region_id: Optional[str] = None       # Link to GroundedRegion if applicable

    @property
    def identifier(self) -> str:
        return self.reference_point_name or self.semantic_region or self.name


@dataclass(frozen=True)
class ConnectorOrientationSpec:
    """Local coordinate system orientation for connector relative kinematics."""
    name: str = "ConnectorCsys"
    csys_type: str = "CARTESIAN"                    # "CARTESIAN", "CYLINDRICAL", "SPHERICAL"
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    point1: Tuple[float, float, float] = (0.0, 0.0, 1.0) # Local axis 1 (or normal)
    point2: Tuple[float, float, float] = (1.0, 0.0, 0.0) # Local axis 2 (in 1-2 plane)
    axis: Optional[Tuple[float, float, float]] = None    # Direct axis vector shorthand (e.g. (0,0,1))
    angle: float = 0.0
    orient2_same_as_1: bool = True
    csys_id: Optional[Union[str, int]] = None            # Reference to pre-existing DatumCsys feature/name


@dataclass(frozen=True)
class ConnectorElasticitySpec:
    """Elastic constitutive behavior for connector components of relative motion."""
    components: Tuple[int, ...] = (1,)              # 1-6 components (1=trans 1, 4=rot 1)
    stiffness: Tuple[float, ...] = (1000.0,)        # Stiffness values for respective components
    is_nonlinear: bool = False
    table: Tuple[Tuple[float, ...], ...] = ()       # Optional force-displacement / moment-rotation table


@dataclass(frozen=True)
class ConnectorDampingSpec:
    """Damping constitutive behavior for connector relative motion."""
    components: Tuple[int, ...] = (1,)
    damping_coefficient: Tuple[float, ...] = (10.0,)
    is_nonlinear: bool = False
    table: Tuple[Tuple[float, ...], ...] = ()


@dataclass(frozen=True)
class ConnectorBehaviorSpec:
    """Constitutive and kinematic behavior assigned to a ConnectorSection."""
    name: str
    elasticity: Optional[ConnectorElasticitySpec] = None
    damping: Optional[ConnectorDampingSpec] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentConnectorSpec:
    """High-level engineering intent for a kinematic connector or joint."""
    name: str
    connector_type: str                            # e.g. "HINGE", "TRANSLATOR", "BEAM", "SLOT", "JOIN"
    endpoint_a: ConnectorEndpointSpec
    endpoint_b: ConnectorEndpointSpec
    orientation: Optional[ConnectorOrientationSpec] = None
    behavior: Optional[ConnectorBehaviorSpec] = None
    wire_feature_name: Optional[str] = None
    wire_set_name: Optional[str] = None
    section_name: Optional[str] = None
    step_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        norm_type = str(self.connector_type).strip().upper()
        object.__setattr__(self, "connector_type", norm_type)
        if not self.section_name:
            object.__setattr__(self, "section_name", f"ConnSec_{self.name}")
        if not self.wire_set_name:
            object.__setattr__(self, "wire_set_name", f"ConnWireSet_{self.name}")
        if not self.wire_feature_name:
            object.__setattr__(self, "wire_feature_name", f"ConnWire_{self.name}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "connector_type": self.connector_type,
            "endpoint_a": {
                "name": self.endpoint_a.name,
                "semantic_region": self.endpoint_a.semantic_region,
                "point_coords": list(self.endpoint_a.point_coords) if self.endpoint_a.point_coords else None,
                "reference_point_name": self.endpoint_a.reference_point_name,
            },
            "endpoint_b": {
                "name": self.endpoint_b.name,
                "semantic_region": self.endpoint_b.semantic_region,
                "point_coords": list(self.endpoint_b.point_coords) if self.endpoint_b.point_coords else None,
                "reference_point_name": self.endpoint_b.reference_point_name,
            },
            "orientation": {
                "name": self.orientation.name,
                "origin": list(self.orientation.origin),
                "point1": list(self.orientation.point1),
                "point2": list(self.orientation.point2),
            } if self.orientation else None,
            "behavior": {
                "name": self.behavior.name,
                "elasticity": {
                    "components": list(self.behavior.elasticity.components),
                    "stiffness": list(self.behavior.elasticity.stiffness),
                } if self.behavior.elasticity else None,
                "damping": {
                    "components": list(self.behavior.damping.components),
                    "damping_coefficient": list(self.behavior.damping.damping_coefficient),
                } if self.behavior.damping else None,
            } if self.behavior else None,
            "section_name": self.section_name,
            "wire_set_name": self.wire_set_name,
            "wire_feature_name": self.wire_feature_name,
        }


@dataclass(frozen=True)
class ConnectorKinematicsVerification:
    """Verification result for connector kinematics and element evidence in ODB."""
    passed: bool
    status: str = "pass"                            # "pass", "fail", "warning", "blocked"
    failures: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    extracted_fields: Tuple[str, ...] = ()          # e.g. ("CU", "CTF", "CP")
    connector_names: Tuple[str, ...] = ()           # Verified connector names
    metrics: Dict[str, Any] = field(default_factory=dict) # e.g. {"joint_drift": 9.78e-6, ...}
    details: Dict[str, Any] = field(default_factory=dict)
