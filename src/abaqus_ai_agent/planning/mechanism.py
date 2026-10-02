"""Mechanism Graph: General Declarative Topology for Multibody and Flexible Mechanisms.

Provides high-level topological abstractions for rigid, flexible, and ground bodies,
inter-body joints (revolute, prismatic, cylindrical, etc.), flexible-body kinematic/distributing
coupling interfaces, dynamic procedures, and actuator/load definitions.

Enables automated topology validation, Grübler/Kutzbach degrees-of-freedom evaluation,
and full-stack compilation into structured native AbaqusActions adhering strictly to
Abaqus CAE topological dependency ordering.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
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
    material_elastic,
    material_density,
    solid_section,
    section_assignment,
    seed_part,
    element_type,
    generate_mesh,
    implicit_dynamic_step,
    field_output,
    history_output,
    create_job,
    displacement_bc,
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
    # Material specification
    material_name: Optional[str] = None
    youngs_modulus: Optional[float] = None
    poisson_ratio: Optional[float] = None
    density: Optional[float] = None
    section_name: Optional[str] = None
    # Meshing specification
    mesh_size: Optional[float] = None
    element_code: Optional[str] = None  # e.g. "C3D8R"
    element_library: Optional[str] = "STANDARD"
    # Geometry sets and tie regions
    geometry_expression: Optional[str] = None
    part_cells_set: Optional[str] = "Cells"
    assembly_cells_set: Optional[str] = None
    tie_regions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FlexibleInterfaceSpec:
    """Coupling interface between a flexible finite element body and a connector RP."""
    name: str
    body_name: str
    interface_region: str
    ref_point_name: str
    ref_point_coords: Tuple[float, float, float]
    interface_name: Optional[str] = None
    role: Optional[str] = None  # e.g. "revolute", "prismatic", "coupling"
    surface_name: Optional[str] = None
    surface_expression: Optional[str] = None
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
    wire_feature_name: Optional[str] = None
    wire_set_name: Optional[str] = None
    interface_a_name: Optional[str] = None
    interface_b_name: Optional[str] = None


@dataclass(frozen=True)
class MechanismLoadSpec:
    """Load or actuator applied to a mechanism body or joint."""
    name: str
    target_name: str
    load_type: str = "gravity"  # "gravity", "force", "torque"
    vector: Tuple[float, float, float] = (0.0, -9810.0, 0.0)
    magnitude: Optional[float] = None
    step_name: Optional[str] = None
    amplitude: Optional[str] = None


@dataclass(frozen=True)
class MechanismAnalysisSpec:
    """Dynamic analysis procedure and output specification for a mechanism."""
    step_name: str = "Step-1"
    job_name: Optional[str] = None
    time_period: float = 1.0
    initial_inc: float = 0.01
    min_inc: float = 1e-6
    max_inc: float = 0.01
    max_num_inc: int = 1000
    nlgeom: bool = True
    application: str = "MODERATE_DISSIPATION"
    nohaf: bool = True
    field_variables: Tuple[str, ...] = ("U", "UR", "V", "VR", "S", "RF", "RM")
    history_variables: Tuple[str, ...] = ("ALLIE", "ALLKE", "ALLWK", "ALLSE", "ETOTAL")
    field_frequency: int = 1


@dataclass(frozen=True)
class MechanismTopologyReport:
    """Audit report for mechanism topological validity and kinematics."""
    is_valid: bool
    num_bodies: int
    num_rigid_bodies: int
    num_flexible_bodies: int
    num_joints: int
    num_interfaces: int
    mobility_rigid_spatial: int
    mobility_rigid_planar: int
    joint_constraints_spatial: int
    joint_constraints_planar: int
    closed_loops_count: int
    has_ground: bool
    warnings: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()
    flexible_continuum_note: str = (
        "Rigid mobility DOFs apply strictly to the macro-kinematic skeleton. "
        "Flexible bodies introduce infinite-dimensional continuum displacement fields "
        "discretized by FE nodal DOFs, which do not alter the macro-kinematic constraint mobility."
    )

    @property
    def rigid_mobility_dof_spatial(self) -> int:
        return self.mobility_rigid_spatial

    @property
    def rigid_mobility_dof_planar(self) -> int:
        return self.mobility_rigid_planar

    @property
    def estimated_dof_spatial(self) -> int:
        return self.mobility_rigid_spatial

    @property
    def estimated_dof_planar(self) -> int:
        return self.mobility_rigid_planar

    @property
    def flexible_bodies_count(self) -> int:
        return self.num_flexible_bodies

    @property
    def flexible_interfaces_count(self) -> int:
        return self.num_interfaces


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
    """Declarative mechanism topology graph supporting rigid, flexible, and ground bodies."""

    def __init__(self, name: str = "Mechanism") -> None:
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
        material_name: Optional[str] = None,
        youngs_modulus: Optional[float] = None,
        poisson_ratio: Optional[float] = None,
        density: Optional[float] = None,
        section_name: Optional[str] = None,
        mesh_size: Optional[float] = None,
        element_code: Optional[str] = None,
        element_library: Optional[str] = "STANDARD",
        geometry_expression: Optional[str] = None,
        part_cells_set: Optional[str] = "Cells",
        assembly_cells_set: Optional[str] = None,
        tie_regions: Tuple[str, ...] = (),
    ) -> "MechanismGraph":
        """Add a body (rigid, flexible, or ground) to the mechanism."""
        self.bodies[name] = BodySpec(
            name=name,
            body_type=body_type.lower(),
            part_name=part_name or name,
            instance_name=instance_name or (name + "-1"),
            ref_point_coords=ref_point_coords,
            ref_point_name=ref_point_name or ("RP_" + name.upper()),
            mass=mass,
            rotary_inertia=rotary_inertia,
            material_name=material_name,
            youngs_modulus=youngs_modulus,
            poisson_ratio=poisson_ratio,
            density=density,
            section_name=section_name,
            mesh_size=mesh_size,
            element_code=element_code,
            element_library=element_library,
            geometry_expression=geometry_expression,
            part_cells_set=part_cells_set,
            assembly_cells_set=assembly_cells_set,
            tie_regions=tuple(tie_regions),
        )
        return self

    def add_flexible_interface(
        self,
        name: str,
        body_name: str,
        interface_region: str,
        ref_point_name: str,
        ref_point_coords: Tuple[float, float, float],
        interface_name: Optional[str] = None,
        role: Optional[str] = None,
        surface_name: Optional[str] = None,
        surface_expression: Optional[str] = None,
        coupling_type: str = "KINEMATIC",
        influence_radius: Optional[float] = None,
        u1: bool = True,
        u2: bool = True,
        u3: bool = True,
        ur1: bool = True,
        ur2: bool = True,
        ur3: bool = True,
    ) -> "MechanismGraph":
        """Add a kinematic or distributing coupling interface on a flexible body."""
        self.interfaces[name] = FlexibleInterfaceSpec(
            name=name,
            body_name=body_name,
            interface_region=interface_region,
            ref_point_name=ref_point_name,
            ref_point_coords=ref_point_coords,
            interface_name=interface_name or name,
            role=role,
            surface_name=surface_name,
            surface_expression=surface_expression,
            coupling_type=coupling_type.upper(),
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
        wire_feature_name: Optional[str] = None,
        wire_set_name: Optional[str] = None,
        interface_a_name: Optional[str] = None,
        interface_b_name: Optional[str] = None,
    ) -> "MechanismGraph":
        """Add a kinematic joint between two bodies or a body and ground."""
        self.joints[name] = JointSpec(
            name=name,
            joint_type=joint_type.lower(),
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
            wire_feature_name=wire_feature_name,
            wire_set_name=wire_set_name,
            interface_a_name=interface_a_name,
            interface_b_name=interface_b_name,
        )
        return self

    def add_load(
        self,
        name: str,
        target_name: str,
        load_type: str = "gravity",
        vector: Tuple[float, float, float] = (0.0, -9810.0, 0.0),
        magnitude: Optional[float] = None,
        step_name: Optional[str] = None,
        amplitude: Optional[str] = None,
    ) -> "MechanismGraph":
        """Add a load or actuator to the mechanism."""
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

        # Grübler / Kutzbach Mobility analysis for macro kinematic skeleton
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

        # Loop count estimation (Euler formula for planar/spatial graphs: L = E - V + 1)
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
            mobility_rigid_spatial=dof_3d,
            mobility_rigid_planar=dof_2d,
            joint_constraints_spatial=total_c_3d,
            joint_constraints_planar=total_c_2d,
            has_ground=("ground" in all_body_names or has_ground),
            closed_loops_count=closed_loops,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def _resolve_joint_endpoint(self, joint: JointSpec, is_side_a: bool, ground_rp_map: Dict[str, str]) -> str:
        """Deterministically resolve connector reference point for joint endpoint A or B.
        
        Resolution priority:
          1. Explicit point name (`point_a_name` / `point_b_name`)
          2. Semantic interface identity (`interface_a_name` / `interface_b_name`)
          3. Single available interface on flexible body
          4. Geometric proximity fallback (`joint.location` within 1.0mm tolerance, unambiguous)
          5. Explicit ValueError if unresolvable or ambiguous
        """
        body_name = joint.body_a if is_side_a else joint.body_b
        explicit_pt = joint.point_a_name if is_side_a else joint.point_b_name
        req_iface_name = joint.interface_a_name if is_side_a else joint.interface_b_name

        if explicit_pt:
            return explicit_pt

        # Ground endpoint resolution
        if body_name == "ground":
            return ground_rp_map.get(joint.name, "RP_GROUND")

        # Body endpoint resolution
        if body_name not in self.bodies:
            return "RP_" + body_name.upper()

        body = self.bodies[body_name]
        if body.body_type == BodyType.RIGID.value:
            if req_iface_name:
                return req_iface_name
            # If joint location matches a tie region RP, match it
            if joint.location and body.tie_regions:
                for tr in body.tie_regions:
                    if joint.name in tr or (joint.point_a_name and joint.point_a_name in tr):
                        return tr
            return body.ref_point_name or ("RP_" + body.name.upper())

        if body.body_type == BodyType.FLEXIBLE.value:
            candidate_ifaces = [iface for iface in self.interfaces.values() if iface.body_name == body.name]

            # 1. Semantic resolution: exact interface name match
            if req_iface_name:
                for iface in candidate_ifaces:
                    if iface.name == req_iface_name or iface.interface_name == req_iface_name:
                        return iface.ref_point_name
                raise ValueError(
                    f"Joint '{joint.name}' specifies interface '{req_iface_name}' for flexible body '{body_name}', "
                    f"but no matching interface found among {[c.name for c in candidate_ifaces]}."
                )

            if not candidate_ifaces:
                if body.ref_point_name:
                    return body.ref_point_name
                raise ValueError(
                    f"Joint '{joint.name}' connects to flexible body '{body_name}', but no flexible interfaces or RP are defined."
                )

            if len(candidate_ifaces) == 1:
                return candidate_ifaces[0].ref_point_name

            # 2. Geometric fallback: match by spatial location proximity
            if joint.location:
                distances = [
                    (math.dist(iface.ref_point_coords, joint.location), iface)
                    for iface in candidate_ifaces
                ]
                distances.sort(key=lambda x: x[0])
                best_dist, best_iface = distances[0]
                if best_dist <= 1.0:
                    if len(distances) > 1 and abs(distances[1][0] - best_dist) < 1e-4:
                        raise ValueError(
                            f"Ambiguous interfaces for joint '{joint.name}' on flexible body '{body_name}'. "
                            f"Interfaces '{best_iface.name}' and '{distances[1][1].name}' are equidistant ({best_dist:.4f} mm) "
                            f"to joint location {joint.location}. Please specify 'interface_{'a' if is_side_a else 'b'}_name'."
                        )
                    return best_iface.ref_point_name
                else:
                    raise ValueError(
                        f"No interface found within tolerance (1.0 mm) for joint '{joint.name}' on flexible body '{body_name}'. "
                        f"Closest interface '{best_iface.name}' is {best_dist:.4f} mm away from joint location {joint.location}. "
                        f"Please specify 'interface_{'a' if is_side_a else 'b'}_name' explicitly."
                    )

            raise ValueError(
                f"Flexible body '{body_name}' has multiple interfaces {[c.name for c in candidate_ifaces]}, "
                f"but joint '{joint.name}' did not specify 'interface_{'a' if is_side_a else 'b'}_name' or 'location'."
            )

        return "RP_" + body_name.upper()

    def compile_to_actions(
        self,
        model_name: str,
        analysis: Optional[MechanismAnalysisSpec] = None,
        step_name: str = "Step-1",
        job_name: Optional[str] = None,
    ) -> List[AbaqusAction]:
        """Compile high-level mechanism graph into ordered, deterministic AbaqusActions.

        Strictly follows CAE topological dependency ordering:
          1. Part-level Materials, Sections & Section Assignments
          2. Part-level Finite Element Meshing (SeedPart, ElementType, GenerateMesh)
          3. Assembly-level Reference Points & Multi-Ground Anchor BCs
          4. Assembly-level Kinematic Constraints (RigidBody & Flexible Coupling)
          5. Assembly-level Connector Elements (ConnectorSection & WireConnector)
          6. Step-level Analysis Procedures & Sensor Output Requests
          7. Step-level Actuation, Gravity & External Loads
          8. Model-level Simulation Job Creation
        """
        report = self.validate_topology()
        if not report.is_valid:
            raise ValueError("Cannot compile invalid mechanism topology: %s" % (report.errors,))

        actions: List[AbaqusAction] = []
        eff_step = analysis.step_name if analysis else step_name
        eff_job = job_name or (analysis.job_name if analysis else None)

        # ---------------------------------------------------------------------
        # 1. Part-level Materials, Solid Sections, and Section Assignments
        # ---------------------------------------------------------------------
        created_materials: Set[str] = set()
        created_sections: Set[str] = set()

        for b in self.bodies.values():
            if b.youngs_modulus is not None:
                mat_name = b.material_name or ("Mat-" + b.name)
                if mat_name not in created_materials:
                    actions.append(material_elastic(
                        model_name,
                        mat_name,
                        youngs_modulus=b.youngs_modulus,
                        poisson=b.poisson_ratio if b.poisson_ratio is not None else 0.3,
                    ))
                    if b.density is not None:
                        actions.append(material_density(
                            model_name,
                            mat_name,
                            density=b.density,
                        ))
                    created_materials.add(mat_name)

                sec_name = b.section_name or ("Sec-Solid-" + mat_name)
                if sec_name not in created_sections:
                    actions.append(solid_section(
                        model_name,
                        sec_name,
                        material=mat_name,
                    ))
                    created_sections.add(sec_name)

                if b.part_name:
                    cells_set = b.part_cells_set or "Cells"
                    reg_expr = "mdb.models[%r].parts[%r].sets[%r]" % (model_name, b.part_name, cells_set)
                    actions.append(section_assignment(
                        model_name,
                        b.part_name,
                        sec_name,
                        reg_expr,
                    ))

        # ---------------------------------------------------------------------
        # 2. Part-level Finite Element Meshing (Must precede Assembly Constraints!)
        # ---------------------------------------------------------------------
        for b in self.bodies.values():
            if b.mesh_size is not None and b.part_name:
                actions.append(seed_part(model_name, b.part_name, size=b.mesh_size))
                if b.element_code:
                    elem_reg = "mdb.models[%r].parts[%r].sets[%r]" % (model_name, b.part_name, b.part_cells_set or "Cells")
                    actions.append(element_type(
                        model_name,
                        b.part_name,
                        region_expression=elem_reg,
                        elem_code=b.element_code,
                        library=b.element_library or "STANDARD",
                    ))
                actions.append(generate_mesh(model_name, b.part_name))

        # ---------------------------------------------------------------------
        # 3. Assembly-level Reference Points & Multi-Ground Anchor BCs
        # ---------------------------------------------------------------------
        created_rps: Set[str] = set()
        ground_rp_map: Dict[str, str] = {}  # joint_name -> ground_rp_name
        ground_coords_to_rp: Dict[Tuple[float, float, float], str] = {}

        # 3.1 Ground multi-interface reference points
        for j_name, joint in self.joints.items():
            if joint.body_a == "ground" or joint.body_b == "ground":
                coords = joint.location or (0.0, 0.0, 0.0)
                # Check if an explicit ground point name was passed
                explicit_pt = joint.point_a_name if joint.body_a == "ground" else joint.point_b_name
                if explicit_pt:
                    rp_name = explicit_pt
                elif coords in ground_coords_to_rp:
                    rp_name = ground_coords_to_rp[coords]
                else:
                    rp_name = "RP_GROUND_" + j_name

                ground_rp_map[j_name] = rp_name
                ground_coords_to_rp[coords] = rp_name

                if rp_name not in created_rps:
                    actions.append(reference_point(
                        model_name,
                        name=rp_name,
                        coordinates=coords,
                    ))
                    created_rps.add(rp_name)

                    # Fix this ground anchor RP in all 6 degrees of freedom
                    bc_reg = "mdb.models[%r].rootAssembly.sets[%r]" % (model_name, rp_name)
                    actions.append(displacement_bc(
                        model_name,
                        name="BC-Ground-" + rp_name,
                        region_expression=bc_reg,
                        step="Initial",
                        u1=0.0, u2=0.0, u3=0.0, ur1=0.0, ur2=0.0, ur3=0.0,
                    ))

        # 3.2 Reference points for rigid bodies
        for b in self.bodies.values():
            if b.body_type == BodyType.RIGID.value and b.ref_point_coords and b.ref_point_name:
                if b.ref_point_name not in created_rps:
                    actions.append(reference_point(
                        model_name,
                        name=b.ref_point_name,
                        coordinates=b.ref_point_coords,
                    ))
                    created_rps.add(b.ref_point_name)

        # 3.3 Reference points for flexible interfaces
        for iface in self.interfaces.values():
            if iface.ref_point_name not in created_rps:
                actions.append(reference_point(
                    model_name,
                    name=iface.ref_point_name,
                    coordinates=iface.ref_point_coords,
                ))
                created_rps.add(iface.ref_point_name)

        # 3.4 Explicit Joint reference points that are not yet created
        for j in self.joints.values():
            for pt_name in (j.point_a_name, j.point_b_name):
                if pt_name and pt_name not in created_rps and pt_name not in ground_rp_map.values():
                    if pt_name.startswith("RP_") and j.location:
                        actions.append(reference_point(
                            model_name,
                            name=pt_name,
                            coordinates=j.location,
                        ))
                        created_rps.add(pt_name)

        # ---------------------------------------------------------------------
        # 4. Assembly-level Kinematic Constraints (RigidBody & Coupling)
        # ---------------------------------------------------------------------
        # Rigid body constraints
        for b in self.bodies.values():
            if b.body_type == BodyType.RIGID.value and b.ref_point_name:
                ref_expr = "a.sets[%r]" % b.ref_point_name
                body_expr = b.geometry_expression
                if not body_expr and b.assembly_cells_set:
                    body_expr = "a.sets[%r]" % b.assembly_cells_set
                tie_expr = None
                if b.tie_regions:
                    tie_expr = ", ".join("a.sets[%r]" % r for r in b.tie_regions)

                actions.append(rigid_body(
                    model_name,
                    name="RB-" + b.name,
                    ref_point_expression=ref_expr,
                    body_expression=body_expr,
                    tie_region=tie_expr,
                ))

        # Flexible interfaces (Coupling constraints)
        for iface in self.interfaces.values():
            surf_name = iface.surface_name or iface.interface_region
            surf_expr = iface.surface_expression
            if not surf_expr and iface.body_name in self.bodies:
                b_flex = self.bodies[iface.body_name]
                if b_flex.instance_name and "." not in surf_name:
                    surf_expr = "a.instances[%r].surfaces[%r]" % (b_flex.instance_name, surf_name)

            actions.append(coupling_constraint(
                model_name,
                name=iface.name,
                control_point_name=iface.ref_point_name,
                surface_name=surf_name if not surf_expr else None,
                surface_expression=surf_expr,
                coupling_type=iface.coupling_type,
                influence_radius=iface.influence_radius,
                u1=iface.u1,
                u2=iface.u2,
                u3=iface.u3,
                ur1=iface.ur1,
                ur2=iface.ur2,
                ur3=iface.ur3,
            ))

        # ---------------------------------------------------------------------
        # 5. Assembly-level Connector Sections and Wire Connectors
        # ---------------------------------------------------------------------
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
                elif jt in ("prismatic", "slider", "translator"):
                    actions.append(connector_section(
                        model_name,
                        name=sec_name,
                        assembled_type="TRANSLATOR",
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

            p1 = self._resolve_joint_endpoint(joint, is_side_a=True, ground_rp_map=ground_rp_map)
            p2 = self._resolve_joint_endpoint(joint, is_side_a=False, ground_rp_map=ground_rp_map)

            actions.append(wire_connector(
                model_name,
                name="Conn-" + j_name,
                section_name=sec_name,
                point1_name=p1,
                point2_name=p2,
                wire_feature_name=joint.wire_feature_name or ("Wire-" + j_name),
                wire_set_name=joint.wire_set_name or ("Set-Wire-" + j_name),
                orientation=joint.orientation or True,
            ))

        # ---------------------------------------------------------------------
        # 6. Step-level Dynamic Analysis Procedure and Sensor Outputs
        # ---------------------------------------------------------------------
        if analysis:
            actions.append(implicit_dynamic_step(
                model_name,
                name=analysis.step_name,
                previous="Initial",
                time_period=analysis.time_period,
                max_num_inc=analysis.max_num_inc,
                initial_inc=analysis.initial_inc,
                min_inc=analysis.min_inc,
                max_inc=analysis.max_inc,
                nlgeom=analysis.nlgeom,
                application=analysis.application,
                nohaf=analysis.nohaf,
            ))
            actions.append(field_output(
                model_name,
                variables=analysis.field_variables,
                request="F-Output-Mechanism",
                step=analysis.step_name,
                frequency=analysis.field_frequency,
            ))
            actions.append(history_output(
                model_name,
                variables=analysis.history_variables,
                request="H-Output-Mechanism",
                step=analysis.step_name,
            ))

        # ---------------------------------------------------------------------
        # 7. Step-level Actuation, Gravity, and External Loads
        # ---------------------------------------------------------------------
        for load in self.loads:
            target_step = load.step_name or eff_step
            if load.load_type == "gravity":
                actions.append(gravity(
                    model_name,
                    name=load.name,
                    comp1=load.vector[0],
                    comp2=load.vector[1],
                    comp3=load.vector[2],
                    step=target_step,
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
                    step=target_step,
                    amplitude=load.amplitude,
                ))

        # ---------------------------------------------------------------------
        # 8. Model-level Simulation Job Creation
        # ---------------------------------------------------------------------
        if eff_job:
            actions.append(create_job(
                model_name,
                eff_job,
                job_type="STANDARD",
            ))

        return actions
