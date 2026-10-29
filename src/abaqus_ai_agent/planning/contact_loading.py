"""Rigid punch construction for contact-driven loading.

A contact load (a punch, a top block, a platen) is not a pressure on a face and
not a point force. Both of those are cheaper to write and both answer a
different question: a pressure patch has no rim singularity and a point force
has no contact patch at all. This module builds the third thing -- a rigid body
that touches the target across an area and is driven through a reference point.

Two build routes exist because the punch shape decides which one is possible:

* A **cylindrical flat-bottom punch** is a body of revolution, which is one of
  the three shapes an *analytical rigid surface* can describe. That route needs
  no mesh at all: the surface is a profile, not elements. It is the preferred
  route -- SIMULIA states analytical rigid parts are cheaper than discrete ones
  and should be used "if possible".
* A **rectangular block** cannot be described analytically. Analytical rigid
  surfaces in 3D are limited to planar, swept and revolved profiles; a sweep
  extends to infinity and a revolve is a body of revolution, so a finite
  rectangular block is not expressible. That route is a discrete rigid part,
  which must be meshed with ``R3D4`` shell elements. Those elements carry no
  material and no internal degrees of freedom, so the cost is negligible, but
  the facets are what define the contact surface.

Both routes honour the same rules, which are not negotiable:

* the rigid body is the **main** surface in Abaqus/Standard contact;
* the punch starts ``standoff`` away from the target and travels *along* the
  drive axis, so contact begins open and closes;
* the reference point carries the drive, and every other degree of freedom is
  held in the Initial step -- a free rigid body under load accelerates instead
  of reaching equilibrium.

Nothing here chooses a size, a standoff, a stroke, a rim radius, or a friction
coefficient. Every one of those arrives on ``ContactLoadingSpec`` and is refused
when absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from ..contracts.condition import ContactLoadingSpec

# Punch motion is applied at the reference point along a single global axis.
_AXIS_VECTORS = {
    "X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}
_DIRECTION_ALIASES = {
    "+X": "X", "X+": "X", "CF1": "X", "+CF1": "X",
    "+Y": "Y", "Y+": "Y", "CF2": "Y", "+CF2": "Y",
    "+Z": "Z", "Z+": "Z", "CF3": "Z", "+CF3": "Z",
    "-CF1": "-X", "X-": "-X",
    "-CF2": "-Y", "Y-": "-Y",
    "-CF3": "-Z", "Z-": "-Z",
}

_FORCE_CONTROL = ("force", "load")
_DISPLACEMENT_CONTROL = ("displacement", "displacement_controlled", "stroke")

# Geometry tokens that describe a body of revolution about the drive axis. These
# are the only punches that can be built without any mesh.
CYLINDRICAL_GEOMETRIES = (
    "cylindrical_flat",
    "cylindrical_flat_bottom",
    "circular_flat",
    "disc_flat",
    "cylindrical",
    "cylinder",
)
# Geometry tokens that describe a flat-faced block. These cannot be analytical.
BLOCK_GEOMETRIES = (
    "rectangular_block",
    "flat_block",
    "rectangular",
    "block",
)


class ContactLoadingBuildError(ValueError):
    """The punch cannot be built from the evidence supplied."""


@dataclass(frozen=True)
class PunchAxis:
    """Resolved punch drive: which way it moves, and how hard it is pushed."""

    token: str
    vector: Tuple[float, float, float]
    control: str
    magnitude: float

    @property
    def is_force_controlled(self) -> bool:
        return self.control in _FORCE_CONTROL

    @property
    def dof_index(self) -> int:
        """0-based component index of the drive axis."""
        for index, component in enumerate(self.vector):
            if component != 0.0:
                return index
        raise ContactLoadingBuildError("punch drive vector has no non-zero component")

    @property
    def signed(self) -> float:
        return self.vector[self.dof_index] * self.magnitude


def resolve_punch_axis(spec: ContactLoadingSpec) -> PunchAxis:
    """Map the declared direction/control onto one global axis.

    A skewed drive is refused instead of being snapped to the nearest axis: a
    punch driven 20 degrees off normal is a different test, and silently moving
    it to an axis would answer a question nobody asked.
    """
    raw = str(spec.direction or "").strip().upper()
    token = _DIRECTION_ALIASES.get(raw, raw)
    if token not in _AXIS_VECTORS:
        raise ContactLoadingBuildError(
            "contact loading %r declares direction %r; punch motion must be a single "
            "global axis (X, -X, Y, -Y, Z, -Z). A skewed drive is a different test and "
            "is not silently snapped to an axis." % (spec.name, spec.direction)
        )
    control = str(spec.control or "").strip().lower()
    if control in _FORCE_CONTROL:
        control = "force"
    elif control in _DISPLACEMENT_CONTROL:
        control = "displacement"
    else:
        raise ContactLoadingBuildError(
            "contact loading %r declares control %r; expected force or displacement"
            % (spec.name, spec.control)
        )
    if spec.magnitude is None:
        raise ContactLoadingBuildError(
            "contact loading %r is %s controlled but carries no magnitude"
            % (spec.name, control)
        )
    return PunchAxis(
        token=token,
        vector=_AXIS_VECTORS[token],
        control=control,
        magnitude=float(spec.magnitude),
    )


def _required_placement(spec: ContactLoadingSpec) -> Tuple[Tuple[float, float, float], float]:
    point = spec.contact_point
    if point is None or len(point) != 3:
        raise ContactLoadingBuildError(
            "contact loading %r has no resolved contact point; the punch cannot be "
            "placed without one" % (spec.name,)
        )
    standoff = spec.standoff
    if standoff is None or float(standoff) <= 0:
        raise ContactLoadingBuildError(
            "contact loading %r has no positive standoff; contact must start open, "
            "and overclosure is returned to CAD rather than adjusted away" % (spec.name,)
        )
    return tuple(float(value) for value in point), float(standoff)


def is_cylindrical(spec: ContactLoadingSpec) -> bool:
    """Whether the declared punch is a body of revolution."""
    token = str(spec.indenter_geometry or "").strip().lower().replace(" ", "_").replace("-", "_")
    if token in CYLINDRICAL_GEOMETRIES:
        return True
    if token in BLOCK_GEOMETRIES:
        return False
    raise ContactLoadingBuildError(
        "contact loading %r declares indenter_geometry %r; expected a cylindrical "
        "flat-bottom punch (%s) or a flat block (%s). The build route is decided by "
        "the shape, so an unknown token cannot be guessed."
        % (spec.name, spec.indenter_geometry, ", ".join(CYLINDRICAL_GEOMETRIES),
           ", ".join(BLOCK_GEOMETRIES))
    )


def punch_radius(spec: ContactLoadingSpec) -> float:
    """Diameter of a cylindrical punch, from the width/length pair.

    Both are required by the contract and both must agree: a cylinder has one
    diameter, and accepting two different numbers would mean quietly picking one
    of them and reporting a contact area that was never declared.
    """
    width = float(spec.indenter_width)
    length = float(spec.indenter_length)
    if abs(width - length) > 1e-9 * max(width, length, 1.0):
        raise ContactLoadingBuildError(
            "contact loading %r describes a cylindrical punch but declares width "
            "%.6f and length %.6f. A cylinder has a single diameter, so both must be "
            "equal; declaring two different values would report a contact area that "
            "was never specified." % (spec.name, width, length)
        )
    return width / 2.0


def punch_master_variable(part_name: str) -> str:
    """Name of the script variable holding the punch's main surface.

    The interaction is created further down the script, so it binds the surface
    through this variable rather than re-looking it up by an auto-generated CAE
    name that this module does not control.
    """
    return "_punch_master_" + "".join(
        character if character.isalnum() else "_" for character in str(part_name)
    )


def _analytic_rotation(axis: PunchAxis) -> Tuple[Tuple[float, float, float], float]:
    """Rotation mapping the revolved profile onto the drive direction.

    The profile revolves about local +Y and its body sits on that side, so the
    face normal is local -Y. Contact needs that normal pointing along the drive
    (toward the deformable body), which means local +Y must map to *minus* the
    drive vector -- the punch body then extends away from the target. Rotating
    the other way would bury the punch in the part and point the main surface
    normal away from the secondary nodes, which Abaqus reports as severe
    overclosure at every node.
    """
    table = {
        "X": ((0.0, 0.0, 1.0), 90.0),
        "-X": ((0.0, 0.0, 1.0), -90.0),
        "Y": ((1.0, 0.0, 0.0), 180.0),
        "-Y": ((1.0, 0.0, 0.0), 0.0),
        "Z": ((1.0, 0.0, 0.0), -90.0),
        "-Z": ((1.0, 0.0, 0.0), 90.0),
    }
    return table[axis.token]


def _discrete_rotation(axis: PunchAxis) -> Tuple[Tuple[float, float, float], float]:
    """Rotation mapping the sketch sheet onto the drive direction.

    A sheet drawn in the sketch X-Y plane has its single face normal along local
    +Z, so +Z must map onto the drive vector. The sheet has no thickness, so
    only the normal direction matters here.
    """
    table = {
        "X": ((0.0, 1.0, 0.0), 90.0),
        "-X": ((0.0, 1.0, 0.0), -90.0),
        "Y": ((1.0, 0.0, 0.0), -90.0),
        "-Y": ((1.0, 0.0, 0.0), 90.0),
        "Z": ((1.0, 0.0, 0.0), 0.0),
        "-Z": ((1.0, 0.0, 0.0), 180.0),
    }
    return table[axis.token]


def _analytic_punch_lines(
    spec: ContactLoadingSpec,
    axis: PunchAxis,
    *,
    model_name: str,
    part_name: str,
    face,
) -> List[str]:
    """Build the punch as a revolved analytical rigid surface -- no mesh at all.

    Abaqus/Standard requires the main surface of a contact pair to have a
    continuous normal. An analytical rigid surface has no ``FILLET RADIUS``
    entry point in CAE, so the rim of a flat-bottom punch must be drawn smooth in
    the sketch itself. Without that rim arc the profile has a 90-degree corner,
    which is exactly the discontinuity that makes finite-sliding contact fail to
    converge. The radius is therefore required, never defaulted: it changes the
    contact area, and inventing it would silently change the test.
    """
    radius = punch_radius(spec)
    edge = spec.indenter_edge_radius
    if edge is None:
        raise ContactLoadingBuildError(
            "contact loading %r is a flat-bottom punch with no indenter_edge_radius. "
            "Abaqus/Standard needs a continuous normal on the main surface, and a "
            "sharp rim is a normal discontinuity; finite-sliding contact usually fails "
            "to converge on it. CAE has no FILLET RADIUS equivalent, so the rim arc has "
            "to be drawn in the profile, which requires the physical rim radius from "
            "the tool drawing. It is not defaulted because it sets the contact area."
            % (spec.name,)
        )
    edge = float(edge)
    if edge >= radius:
        raise ContactLoadingBuildError(
            "contact loading %r declares rim radius %.6f against punch radius %.6f; the "
            "rim arc must be smaller than the face, otherwise no flat face remains and "
            "the declared contact area does not exist." % (spec.name, edge, radius)
        )

    # Constructional extent, not a measured dimension: the wall only has to be
    # tall enough that secondary nodes cannot slide off the edge and "fall
    # behind" the surface, which is a documented convergence failure mode.
    wall = radius
    inst = "%s-1" % part_name

    return [
        "# Action: rigid punch (%s contact loading, analytical revolved surface)"
        % spec.application,
        "# Face dia %.6f mm, rim radius %.6f mm, standoff %.6f mm along %s, %s controlled"
        % (radius * 2.0, edge, float(spec.standoff), axis.token, axis.control),
        "s_punch = mdb.models['%s'].ConstrainedSketch(name='__punch_%s__', sheetSize=%.6f)"
        % (model_name, part_name, radius * 6.0),
        # The profile is traversed so that every outward normal ends up pointing
        # away from the punch body, i.e. towards the deformable part. By the
        # 90-degree counter-clockwise rule, a segment's normal is its direction
        # rotated CCW, so: the face runs +X -> -X (normal -Y, into the target)
        # and the wall runs +Y -> -Y (normal +X, radially outward). Reversing
        # either would point normals into the punch, and Abaqus would report
        # severe overclosure at every secondary node.
        "s_punch.Line(point1=(%.6f, %.6f), point2=(%.6f, %.6f))"
        % (radius, wall, radius, edge),
        "s_punch.ArcByCenterEnds(center=(%.6f, %.6f), point1=(%.6f, %.6f), "
        "point2=(%.6f, %.6f), direction=CLOCKWISE)"
        % (radius - edge, edge, radius, edge, radius - edge, 0.0),
        "s_punch.Line(point1=(%.6f, %.6f), point2=(%.6f, %.6f))"
        % (radius - edge, 0.0, 0.0, 0.0),
        "p_punch = mdb.models['%s'].Part("
        "name='%s', dimensionality=THREE_D, type=ANALYTIC_RIGID_SURFACE)"
        % (model_name, part_name),
        "p_punch.AnalyticRigidSurfRevolve(sketch=s_punch)",
        "del mdb.models['%s'].sketches['__punch_%s__']" % (model_name, part_name),
        # An analytical rigid part is a profile, so there is nothing to seed,
        # nothing to type, and nothing to generate. No section is assigned
        # either: the surface carries no material.
        "a = mdb.models['%s'].rootAssembly" % model_name,
        "a.Instance(name='%s', part=p_punch, dependent=ON)" % inst,
        "a.rotate(instanceList=('%s',), axisPoint=(0.0, 0.0, 0.0), "
        "axisDirection=(%.1f, %.1f, %.1f), angle=%.1f)"
        % ((inst,) + tuple(_analytic_rotation(axis)[0]) + (_analytic_rotation(axis)[1],)),
        "a.translate(instanceList=('%s',), vector=(%.6f, %.6f, %.6f))"
        % ((inst,) + tuple(face)),
        # CAE creates the rigid body reference point when an analytical rigid
        # part is made. It is read back rather than created again, so a missing
        # one is an error instead of a second, contradictory rigid body.
        "_punch_inst = a.instances['%s']" % inst,
        "_punch_rps = _punch_inst.referencePoints",
        "if not _punch_rps:\n"
        "    raise RuntimeError('contact_loading_punch_reference_point_missing:%s')"
        % part_name,
        "a.Set(name='%s_RP', referencePoints=(_punch_rps[list(_punch_rps.keys())[0]],))"
        % part_name,
        # The surface CAE names for an analytical rigid part is auto-generated,
        # so it is bound through the instance repository instead of being looked
        # up by a name this module would have to guess.
        "_punch_surfs = _punch_inst.surfaces",
        "if not _punch_surfs:\n"
        "    raise RuntimeError('contact_loading_punch_surface_missing:%s')" % part_name,
        "%s = _punch_surfs[list(_punch_surfs.keys())[0]]" % punch_master_variable(part_name),
    ]


def _discrete_punch_lines(
    spec: ContactLoadingSpec,
    axis: PunchAxis,
    *,
    model_name: str,
    part_name: str,
    face,
) -> List[str]:
    """Build the punch as a meshed sheet of rigid elements.

    A *solid* discrete rigid part cannot be instanced at all: CAE refuses it and
    requires the faces to be converted to shells. An *extruded* shell is a set
    of side walls with no cap, so it has no contact face; the sheet is the face.
    """
    width = float(spec.indenter_width)
    length = float(spec.indenter_length)
    # Rigid facet size. Derived from the punch itself, not a physical dimension:
    # a rigid surface's smoothness is set by its facet count, nothing else.
    mesh_size = spec.mesh_size if spec.mesh_size is not None else min(width, length) / 6.0
    inst = "%s-1" % part_name
    rot_axis, rot_angle = _discrete_rotation(axis)

    return [
        "# Action: rigid punch (%s contact loading, discrete rigid sheet)" % spec.application,
        "# Face %s x %s mm, standoff %.6f mm along %s, %s controlled"
        % (width, length, float(spec.standoff), axis.token, axis.control),
        "s_punch = mdb.models['%s'].ConstrainedSketch(name='__punch_%s__', sheetSize=%.6f)"
        % (model_name, part_name, max(width, length) * 4.0),
        "s_punch.rectangle(point1=(%.6f, %.6f), point2=(%.6f, %.6f))"
        % (-width / 2.0, -length / 2.0, width / 2.0, length / 2.0),
        # A discrete rigid part made of shells is the only rigid part CAE can
        # instance; a solid one is refused outright at instancing time.
        "p_punch = mdb.models['%s'].Part("
        "name='%s', dimensionality=THREE_D, type=DISCRETE_RIGID_SURFACE)"
        % (model_name, part_name),
        "p_punch.BaseShell(sketch=s_punch)",
        "del mdb.models['%s'].sketches['__punch_%s__']" % (model_name, part_name),
        "import mesh",
        "from abaqusConstants import *",
        "p_punch.setMeshControls(regions=p_punch.faces, elemShape=QUAD, technique=FREE)",
        "p_punch.seedPart(size=%.6f, deviationFactor=0.1, minSizeFactor=0.1)" % mesh_size,
        # R3D4 is the 4-node 3D bilinear rigid element. It carries no material,
        # so no section assignment is made and none is required.
        "p_punch.setElementType("
        "regions=(p_punch.faces,), "
        "elemTypes=(mesh.ElemType(elemCode=R3D4, elemLibrary=STANDARD),))",
        "p_punch.generateMesh()",
        # All punch motion and reaction reporting happen at this reference
        # point. The point itself lives on the *part* -- that is what makes it
        # the rigid body reference point, and it appears on every instance.
        "rp_punch = p_punch.ReferencePoint(point=(0.0, 0.0, 0.0))",
        "a = mdb.models['%s'].rootAssembly" % model_name,
        "a.Instance(name='%s', part=p_punch, dependent=ON)" % inst,
        # Orient the sheet normal onto the drive axis before positioning.
        "a.rotate(instanceList=('%s',), axisPoint=(0.0, 0.0, 0.0), "
        "axisDirection=(%.1f, %.1f, %.1f), angle=%.1f)"
        % (inst, rot_axis[0], rot_axis[1], rot_axis[2], rot_angle),
        "a.translate(instanceList=('%s',), vector=(%.6f, %.6f, %.6f))"
        % ((inst,) + tuple(face)),
        # Rigid surfaces are always the main surface in Abaqus/Standard.
        "a.Surface(side1Faces=a.instances['%s'].faces, name='%s_Master')"
        % (inst, part_name),
        # Loads and boundary conditions take an assembly-level region, so the
        # set the drive refers to has to exist at assembly scope. It is built
        # from the instance's own reference point, which is the form the
        # shipped Abaqus scripts use; naming a part set and then reading it
        # back through ``a.sets`` is not the same repository.
        "_punch_rps = a.instances['%s'].referencePoints" % inst,
        "if not _punch_rps:\n"
        "    raise RuntimeError('contact_loading_punch_reference_point_missing:%s')"
        % part_name,
        "a.Set(name='%s_RP', referencePoints=(_punch_rps[list(_punch_rps.keys())[0]],))"
        % part_name,
        "%s = a.surfaces['%s_Master']" % (punch_master_variable(part_name), part_name),
    ]


def punch_script_lines(
    spec: ContactLoadingSpec,
    axis: PunchAxis,
    *,
    model_name: str,
    part_name: str,
) -> List[str]:
    """Render the punch as a list of CAE statements.

    Deliberately a statement list rather than a builder chain: the punch is the
    one object whose construction order is load-bearing (sheet -> mesh control
    -> element type -> mesh -> reference point -> instance -> placement ->
    surface), and a chain would hide that order.
    """
    point, standoff = _required_placement(spec)
    # The face starts `standoff` *behind* the target, i.e. against the drive
    # direction: driving along -Y means the punch begins above the target and
    # travels down into it. Offsetting along the drive vector instead would
    # start the punch already past the surface.
    face = tuple(point[i] - standoff * axis.vector[i] for i in range(3))

    if is_cylindrical(spec):
        return _analytic_punch_lines(
            spec, axis, model_name=model_name, part_name=part_name, face=face,
        )
    return _discrete_punch_lines(
        spec, axis, model_name=model_name, part_name=part_name, face=face,
    )


def punch_guide_lines(
    axis: PunchAxis,
    *,
    model_name: str,
    part_name: str,
) -> List[str]:
    """Constrain the punch to a single translational DOF before the step.

    A rigid body carrying a force with no constraint accelerates instead of
    reaching equilibrium, so a static step diverges. Every translational and
    rotational DOF except the drive is held in the Initial step; the drive DOF
    is left free here and receives either a force or a stroke later.
    """
    free_dof = axis.dof_index + 1
    args = []
    for dof in range(1, 7):
        if dof == free_dof:
            continue
        args.append("u%d=0.0" % dof)
    return [
        "# Action: rigid punch guide (free DOF %d only)" % free_dof,
        "mdb.models['%s'].DisplacementBC("
        "name='%s_Guide', createStepName='Initial', region=a.sets['%s_RP'], %s)"
        % (model_name, part_name, part_name, ", ".join(args)),
    ]


def punch_load_lines(
    axis: PunchAxis,
    *,
    model_name: str,
    part_name: str,
    step: str,
) -> List[str]:
    """Apply the drive: a force, or a prescribed stroke, on the reference point."""
    dof = axis.dof_index + 1
    if axis.is_force_controlled:
        return [
            "# Action: rigid punch force (%.6f %s along %s)"
            % (axis.magnitude, "force units", axis.token),
            "mdb.models['%s'].ConcentratedForce("
            "name='%s_Force', createStepName='%s', region=a.sets['%s_RP'], cf%d=%.6f)"
            % (model_name, part_name, step, part_name, dof, axis.signed),
        ]
    return [
        "# Action: rigid punch stroke (%.6f along %s)" % (axis.magnitude, axis.token),
        "mdb.models['%s'].DisplacementBC("
        "name='%s_Stroke', createStepName='%s', region=a.sets['%s_RP'], u%d=%.6f)"
        % (model_name, part_name, step, part_name, dof, axis.signed),
    ]


def punch_friction(spec: ContactLoadingSpec) -> float:
    """Contact friction, or zero when none was declared.

    Zero here means "not declared", which Abaqus already treats as frictionless.
    It is never replaced by a plausible-looking number.
    """
    if spec.friction_coefficient is None:
        return 0.0
    return float(spec.friction_coefficient)


__all__ = [
    "BLOCK_GEOMETRIES",
    "CYLINDRICAL_GEOMETRIES",
    "ContactLoadingBuildError",
    "PunchAxis",
    "is_cylindrical",
    "punch_friction",
    "punch_guide_lines",
    "punch_load_lines",
    "punch_master_variable",
    "punch_radius",
    "punch_script_lines",
    "resolve_punch_axis",
]
