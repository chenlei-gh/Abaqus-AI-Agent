"""Mechanism Graph: General Declarative Topology for Multibody and Flexible Mechanisms.

Provides high-level topological abstractions for rigid, flexible, and ground bodies,
inter-body joints (revolute, prismatic, cylindrical, etc.), flexible-body kinematic/distributing
coupling interfaces, and actuator/load definitions.

Enables automated topology validation, Grübler/Kutzbach degrees-of-freedom evaluation,
and compilation into structured native AbaqusActions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..contracts.action import AbaqusAction
from ..actions.builders import (
    connector_section,
    wire_connector,
    reference_point,
    rigid_body,
    coupling_constraint,
    gravity,
    concentrated_force,
)


class BodyType(str, Enum):
    RIGID = "rigid"
    FLEXIBLE = "flexible"
    GROUND = "ground"


class JointType(str, Enum):
    REVOLUTE = "revolute"          # HINGE (CONN3D2)
    PRISMATIC = "prismatic"        # SLIDER
    CYLINDRICAL = "cylindrical"    # CYLINDRICAL
    SPHERICAL = "spherical"        # JOIN
    UNIVERSAL = "universal"        # U-JOINT
    CARTESIAN = "cartesian"        # CARTESIAN
    SLOT = "slot"                  # SLOT
    WELD = "weld"                  # WELD / TIE


@dataclass(frozen=True)
class BodySpec:
    """Specification of a single body in a mechanism (rigid, flexible, or ground)."""
    name: str
    body_type: str = "rigid"  # "rigid", "flexible", "ground"
    part_name: Optional[str] = None
    instance_name: Optional[str] = None
    ref_point_coords: Optional[Tuple[float, float, float]] = None
    ref_point_name: Optional[str] = None
    mass: Optional[float] = None
    rotary_inertia: Optional[Tuple[float, float, float]] = None
    youngs_modulus: Optional[float] = None
    poisson_ratio: Optional[float] = None
    density: Optional[float] = None
    mesh_size: Optional[float] = None
    element_code: Optional[str] = None
    geometry_expression: Optional[str] = None


@dataclass(frozen=True)
class FlexibleInterfaceSpec:
    """Coupling interface between a flexible finite element body and a connector RP."""
    name: str
    body_name: str
    interface_region: str
    ref_point_name: str
    ref_point_coords: Tuple[float, float, float]
    coupling_type: str = "KINEMATIC"  # "KINEMATIC" or "DISTRIBUTING"
    influence_radius: Optional[float] = None
    u1: bool = True
    u2: bool = True
    u3: bool = True
    ur1: bool = True
    ur2: bool = True
    ur3: bool = True


@dataclass(frozen=True)
class JointSpec:
    """Kinematic joint/connector connecting two bodies or a body to ground."""
    name: str
    joint_type: str = "revolute"
    body_a: str = "ground"
    body_b: str = ""
    point_a_name: Optional[str] = None
    point_b_name: Optional[str] = None
    location: Optional[Tuple[float, float, float]] = None
    axis: Optional[Tuple[float, float, float]] = None
    assembled_type: Optional[str] = None
    rotational_type: Optional[str] = None
    translational_type: Optional[str] = None
    behavior_name: Optional[str] = None
    orientation: Optional[Any] = None


@dataclass(frozen=True)
class MechanismLoadSpec:
    """Load or actuator applied to a mechanism body or joint."""
    name: str
    target_name: str
    load_type: str = "gravity"  # "gravity", "force", "torque"
    vector: Tuple[float, float, float] = (0.0, -9810.0, 0.0)
    magnitude: Optional[float] = None
    step_name: str = "Step-1"
    amplitude: Optional[str] = None


@dataclass(frozen=True)
class MechanismTopologyReport:
    """Audit report for mechanism topological validity and kinematics."""
    is_valid: bool
    num_bodies: int
    num_rigid_bodies: int
    num_flexible_bodies: int
    num_joints: int
    num_interfaces: int
    estimated_dof_spatial: int
    estimated_dof_planar: int
    has_ground: bool
    closed_loops_count: int
    warnings: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()


# Constraint DOF reduction per joint type in 3D (Spatial) and 2D (Planar)
_JOINT_CONSTRAINTS_3D = {
    JointType.REVOLUTE: 5,     # 1 DOF rotation free, 5 constrained
    JointType.PRISMATIC: 5,    # 1 DOF translation free, 5 constrained
    JointType.CYLINDRICAL: 4,  # 1 trans + 1 rot free, 4 constrained
    JointType.SPHERICAL: 3,    # 3 rot free, 3 trans constrained
    JointType.UNIVERSAL: 4,    # 2 rot free, 4 constrained
    JointType.CARTESIAN: 3,    # 3 trans constrained (or free depending on sec)
    JointType.SLOT: 5,
    JointType.WELD: 6,         # completely locked
}

_JOINT_CONSTRAINTS_2D = {
    JointType.REVOLUTE: 2,     # 2 trans locked, 1 rot free (1 DOF left)
    JointType.PRISMATIC: 2,    # 1 trans free, 1 trans + 1 rot locked
    JointType.CYLINDRICAL: 1,
    JointType.SPHERICAL: 0,
    JointType.UNIVERSAL: 1,
    JointType.CARTESIAN: 1,
    JointType.SLOT: 2,
    JointType.WELD: 3,
}


class MechanismGraph:
    """Declarative graph representing a complete multibody or flexible mechanism."""

    def __init__(self, name: str = "Mechanism"):
        self.name = name
        self.bodies: Dict[str, BodySpec] = {}
        self.interfaces: Dict[str, FlexibleInterfaceSpec] = {}
        self.joints: Dict[str, JointSpec] = {}
        self.loads: List[MechanismLoadSpec] = []

    def add_body(
        self,
        name: str,
        body_type: str = "rigid",
        part_name: Optional[str] = None,
        instance_name: Optional[str] = None,
        ref_point_coords: Optional[Tuple[float, float, float]] = None,
        ref_point_name: Optional[str] = None,
        mass: Optional[float] = None,
        rotary_inertia: Optional[Tuple[float, float, float]] = None,
        youngs_modulus: Optional[float] = None,
        poisson_ratio: Optional[float] = None,
        density: Optional[float] = None,
        mesh_size: Optional[float] = None,
        element_code: Optional[str] = None,
        geometry_expression: Optional[str] = None,
    ) -> "MechanismGraph":
        b_type = str(body_type).lower()
        if b_type not in (BodyType.RIGID.value, BodyType.FLEXIBLE.value, BodyType.GROUND.value):
            raise ValueError("Unsupported body_type: %s" % body_type)
        self.bodies[name] = BodySpec(
            name=name,
            body_type=b_type,
            part_name=part_name or name,
            instance_name=instance_name or (name + "-1"),
            ref_point_coords=ref_point_coords,
            ref_point_name=ref_point_name or ("RP-" + name),
            mass=mass,
            rotary_inertia=rotary_inertia,
            youngs_modulus=youngs_modulus,
            poisson_ratio=poisson_ratio,
            density=density,
            mesh_size=mesh_size,
            element_code=element_code,
            geometry_expression=geometry_expression,
        )
        return self

    def add_flexible_interface(
        self,
        name: str,
        body_name: str,
        interface_region: str,
        ref_point_name: str,
        ref_point_coords: Tuple[float, float, float],
        coupling_type: str = "KINEMATIC",
        influence_radius: Optional[float] = None,
        u1: bool = True,
        u2: bool = True,
        u3: bool = True,
        ur1: bool = True,
        ur2: bool = True,
        ur3: bool = True,
    ) -> "MechanismGraph":
        self.interfaces[name] = FlexibleInterfaceSpec(
            name=name,
            body_name=body_name,
            interface_region=interface_region,
            ref_point_name=ref_point_name,
            ref_point_coords=ref_point_coords,
            coupling_type=str(coupling_type).upper(),
            influence_radius=influence_radius,
            u1=u1,
            u2=u2,
            u3=u3,
            ur1=ur1,
            ur2=ur2,
            ur3=ur3,
        )
        return self

    def add_joint(
        self,
        name: str,
        joint_type: str = "revolute",
        body_a: str = "ground",
        body_b: str = "",
        point_a_name: Optional[str] = None,
        point_b_name: Optional[str] = None,
        location: Optional[Tuple[float, float, float]] = None,
        axis: Optional[Tuple[float, float, float]] = None,
        assembled_type: Optional[str] = None,
        rotational_type: Optional[str] = None,
        translational_type: Optional[str] = None,
        behavior_name: Optional[str] = None,
        orientation: Optional[Any] = None,
    ) -> "MechanismGraph":
        j_type = str(joint_type).lower()
        self.joints[name] = JointSpec(
            name=name,
            joint_type=j_type,
            body_a=body_a,
            body_b=body_b,
            point_a_name=point_a_name,
            point_b_name=point_b_name,
            location=location,
            axis=axis,
            assembled_type=assembled_type,
            rotational_type=rotational_type,
            translational_type=translational_type,
            behavior_name=behavior_name,
            orientation=orientation,
        )
        return self

    def add_load(
        self,
        name: str,
        target_name: str,
        load_type: str = "gravity",
        vector: Tuple[float, float, float] = (0.0, -9810.0, 0.0),
        magnitude: Optional[float] = None,
        step_name: str = "Step-1",
        amplitude: Optional[str] = None,
    ) -> "MechanismGraph":
        self.loads.append(MechanismLoadSpec(
            name=name,
            target_name=target_name,
            load_type=load_type,
            vector=vector,
            magnitude=magnitude,
            step_name=step_name,
            amplitude=amplitude,
        ))
        return self

    def validate_topology(self) -> MechanismTopologyReport:
        """Validate mechanism topological connectivity, constraints, and mobility."""
        errors: List[str] = []
        warnings: List[str] = []

        all_body_names = set(self.bodies.keys())
        has_ground = any(b.body_type == BodyType.GROUND.value for b in self.bodies.values())
        if "ground" not in all_body_names and not has_ground:
            warnings.append("No explicit ground body defined; joints to 'ground' will act as inertial fixed anchors.")

        connected_bodies: Set[str] = set()

        for j_name, joint in self.joints.items():
            if joint.body_a != "ground" and joint.body_a not in all_body_names:
                errors.append("Joint '%s' references unknown body_a: '%s'" % (j_name, joint.body_a))
            else:
                connected_bodies.add(joint.body_a)

            if not joint.body_b:
                errors.append("Joint '%s' missing required body_b." % j_name)
            elif joint.body_b != "ground" and joint.body_b not in all_body_names:
                errors.append("Joint '%s' references unknown body_b: '%s'" % (j_name, joint.body_b))
            else:
                connected_bodies.add(joint.body_b)

        # Check for isolated bodies
        for b_name in all_body_names:
            if b_name not in connected_bodies:
                warnings.append("Body '%s' is completely isolated (not connected to any joint)." % b_name)

        # Validate flexible interfaces
        for if_name, iface in self.interfaces.items():
            if iface.body_name not in all_body_names:
                errors.append("Interface '%s' references unknown body: '%s'" % (if_name, iface.body_name))
            else:
                body = self.bodies[iface.body_name]
                if body.body_type != BodyType.FLEXIBLE.value:
                    warnings.append(
                        "Interface '%s' attached to body '%s' which has type '%s', expected 'flexible'."
                        % (if_name, iface.body_name, body.body_type)
                    )

        # Grübler / Kutzbach Mobility analysis
        # Number of moving bodies (excluding ground)
        moving_bodies = [b for b in self.bodies.values() if b.body_type != BodyType.GROUND.value]
        n = len(moving_bodies)

        total_c_3d = 0
        total_c_2d = 0
        for joint in self.joints.values():
            jt = JointType(joint.joint_type) if joint.joint_type in JointType._value2member_map_ else JointType.REVOLUTE
            total_c_3d += _JOINT_CONSTRAINTS_3D.get(jt, 5)
            total_c_2d += _JOINT_CONSTRAINTS_2D.get(jt, 2)

        # Spatial DOF: 6 * n - constraints
        # Planar DOF: 3 * n - constraints
        dof_3d = (6 * n) - total_c_3d if n > 0 else 0
        dof_2d = (3 * n) - total_c_2d if n > 0 else 0

        # Loop count estimation (Euler formula for graphs: L = E - V + 1)
        # Vertices = bodies + ground (1)
        v = n + 1
        e = len(self.joints)
        closed_loops = max(0, e - v + 1)

        num_rigid = sum(1 for b in self.bodies.values() if b.body_type == BodyType.RIGID.value)
        num_flex = sum(1 for b in self.bodies.values() if b.body_type == BodyType.FLEXIBLE.value)

        return MechanismTopologyReport(
            is_valid=(len(errors) == 0),
            num_bodies=len(self.bodies),
            num_rigid_bodies=num_rigid,
            num_flexible_bodies=num_flex,
            num_joints=len(self.joints),
            num_interfaces=len(self.interfaces),
            estimated_dof_spatial=dof_3d,
            estimated_dof_planar=dof_2d,
            has_ground=("ground" in all_body_names or has_ground),
            closed_loops_count=closed_loops,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def compile_to_actions(self, model_name: str, step_name: str = "Step-1") -> List[AbaqusAction]:
        """Compile high-level mechanism graph into ordered, deterministic AbaqusActions."""
        report = self.validate_topology()
        if not report.is_valid:
            raise ValueError("Cannot compile invalid mechanism topology: %s" % (report.errors,))

        actions: List[AbaqusAction] = []

        # 1. Reference Points for rigid bodies and flexible interfaces
        created_rps: Set[str] = set()

        for b in self.bodies.values():
            if b.body_type == BodyType.RIGID.value and b.ref_point_coords and b.ref_point_name:
                actions.append(reference_point(model_name, name=b.ref_point_name, coordinates=b.ref_point_coords))
                created_rps.add(b.ref_point_name)

        for iface in self.interfaces.values():
            if iface.ref_point_name not in created_rps:
                actions.append(reference_point(
                    model_name,
                    name=iface.ref_point_name,
                    coordinates=iface.ref_point_coords,
                ))
                created_rps.add(iface.ref_point_name)

        # 2. RigidBody Constraints for rigid bodies
        for b in self.bodies.values():
            if b.body_type == BodyType.RIGID.value and b.ref_point_name:
                ref_expr = "a.sets[%r]" % b.ref_point_name
                body_expr = b.geometry_expression
                actions.append(rigid_body(
                    model_name,
                    name="RB-" + b.name,
                    ref_point_expression=ref_expr,
                    body_expression=body_expr,
                ))

        # 3. Flexible Interfaces (Coupling constraints)
        for iface in self.interfaces.values():
            actions.append(coupling_constraint(
                model_name,
                name=iface.name,
                control_point_name=iface.ref_point_name,
                surface_name=iface.interface_region,
                coupling_type=iface.coupling_type,
                influence_radius=iface.influence_radius,
                u1=iface.u1,
                u2=iface.u2,
                u3=iface.u3,
                ur1=iface.ur1,
                ur2=iface.ur2,
                ur3=iface.ur3,
            ))

        # 4. Connector Sections and Wire Connectors for Joints
        sec_names: Set[str] = set()
        for j_name, joint in self.joints.items():
            jt = joint.joint_type.lower()
            sec_name = "Sec-Joint-" + jt.upper()
            if sec_name not in sec_names:
                if jt in ("revolute", "hinge"):
                    actions.append(connector_section(
                        model_name,
                        name=sec_name,
                        assembled_type="HINGE",
                        behavior_name=joint.behavior_name,
                    ))
                elif jt in ("prismatic", "slider"):
                    actions.append(connector_section(
                        model_name,
                        name=sec_name,
                        assembled_type="SLIDER",
                        behavior_name=joint.behavior_name,
                    ))
                elif jt in ("spherical", "join"):
                    actions.append(connector_section(
                        model_name,
                        name=sec_name,
                        assembled_type="JOIN",
                        behavior_name=joint.behavior_name,
                    ))
                elif jt == "weld":
                    actions.append(connector_section(
                        model_name,
                        name=sec_name,
                        assembled_type="WELD",
                        behavior_name=joint.behavior_name,
                    ))
                else:
                    actions.append(connector_section(
                        model_name,
                        name=sec_name,
                        assembled_type=joint.assembled_type or jt.upper(),
                        rotational_type=joint.rotational_type,
                        translational_type=joint.translational_type,
                        behavior_name=joint.behavior_name,
                    ))
                sec_names.add(sec_name)

            # Determine point 1 and point 2 for wire connector
            # If explicit point names given, use them; otherwise resolve from bodies/interfaces
            p1 = joint.point_a_name
            if not p1 and joint.body_a in self.bodies:
                b_a = self.bodies[joint.body_a]
                p1 = b_a.ref_point_name

            p2 = joint.point_b_name
            if not p2 and joint.body_b in self.bodies:
                b_b = self.bodies[joint.body_b]
                p2 = b_b.ref_point_name

            actions.append(wire_connector(
                model_name,
                name="Conn-" + j_name,
                section_name=sec_name,
                point1_name=p1,
                point2_name=p2,
                orientation=joint.orientation or True,
            ))

        # 5. Loads and Gravity
        for load in self.loads:
            if load.load_type == "gravity":
                actions.append(gravity(
                    model_name,
                    name=load.name,
                    comp1=load.vector[0],
                    comp2=load.vector[1],
                    comp3=load.vector[2],
                    step=load.step_name or step_name,
                    amplitude=load.amplitude,
                ))
            elif load.load_type == "force" and load.magnitude is not None:
                actions.append(concentrated_force(
                    model_name,
                    name=load.name,
                    region_expression="a.sets[%r]" % load.target_name,
                    cf1=load.vector[0] * load.magnitude,
                    cf2=load.vector[1] * load.magnitude,
                    cf3=load.vector[2] * load.magnitude,
                    step=load.step_name or step_name,
                    amplitude=load.amplitude,
                ))

        return actions
