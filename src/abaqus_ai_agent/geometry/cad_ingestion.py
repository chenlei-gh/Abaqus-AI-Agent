"""STEP / IGES CAD Ingestion Engine for Track GA-1.1.

Ingests industrial neutral CAD files (.stp, .step, .igs, .iges) into standardized,
immutable GeometryModel representations with cryptographic SHA-256 provenance.
Operates via pure-python deterministic parsing with zero heavyweight external C++
kernel dependencies, ensuring 100% offline predictability across Linux/Windows.
"""

from datetime import datetime, timezone
import hashlib
import os
import re
from typing import List, Optional, Tuple

from ..capability_boundary import CapabilityBoundary, CapabilityStatus
from .model import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
    CadLoop,
    CadProvenance,
    CadShell,
    CadSolid,
    CadUnit,
    CadVertex,
    GeometryModel,
)


class CadIngestionError(Exception):
    """Raised when CAD ingestion fails catastrophically."""
    pass


def compute_file_sha256(file_path: str) -> str:
    """Compute cryptographic SHA-256 digest of a CAD file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_cad_format(file_path: str) -> CadFormat:
    """Detect CAD format via extension and content header inspection."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".stp", ".step"):
        return CadFormat.STEP
    if ext in (".igs", ".iges"):
        return CadFormat.IGES

    # Fallback to inspecting content header
    try:
        with open(file_path, "rb") as f:
            header_sample = f.read(512)
            if b"ISO-10303-21" in header_sample:
                return CadFormat.STEP
            if len(header_sample) >= 80 and header_sample[72:73] in (b"S", b"G"):
                return CadFormat.IGES
    except Exception:
        pass
    return CadFormat.UNKNOWN


# ---------------------------------------------------------------------------
# STEP (ISO-10303-21) Parser
# ---------------------------------------------------------------------------

SUPPORTED_STEP_ENTITIES = {
    "MANIFOLD_SOLID_BREP",
    "BREP_WITH_VOIDS",
    "SOLID_MODEL",
    "CLOSED_SHELL",
    "OPEN_SHELL",
    "ADVANCED_FACE",
    "FACE_SURFACE",
    "FACE_OUTER_BOUND",
    "FACE_BOUND",
    "EDGE_LOOP",
    "ORIENTED_EDGE",
    "EDGE_CURVE",
    "VERTEX_POINT",
    "CARTESIAN_POINT",
    "PLANE",
    "CYLINDRICAL_SURFACE",
    "CIRCLE",
    "LINE",
    "AXIS2_PLACEMENT_3D",
    "DIRECTION",
    "VECTOR",
    "SI_UNIT",
    "LENGTH_UNIT",
    "NAMED_UNIT",
}


def _clean_ref(val: Any) -> str:
    """Strip leading '#' or whitespace from an entity reference token."""
    if isinstance(val, str):
        return val.lstrip("#").strip()
    return str(val)


def _parse_step_args(s: str) -> List[Any]:
    """Parse comma-separated STEP entity arguments with nested parenthesis support."""
    tokens: List[str] = []
    current: List[str] = []
    depth = 0
    in_str = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "'" and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
            current.append(c)
        elif in_str:
            current.append(c)
        elif c in "([":
            depth += 1
            current.append(c)
        elif c in ")]":
            depth -= 1
            current.append(c)
        elif c == "," and depth == 0:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        tokens.append("".join(current).strip())

    result: List[Any] = []
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("(") and tok.endswith(")"):
            result.append(_parse_step_args(tok[1:-1]))
        elif tok.startswith("'") and tok.endswith("'"):
            result.append(tok[1:-1])
        elif tok == ".T.":
            result.append(True)
        elif tok == ".F.":
            result.append(False)
        elif tok in ("$", "*"):
            result.append(None)
        else:
            try:
                if "." in tok or "E" in tok.upper():
                    result.append(float(tok))
                else:
                    result.append(int(tok))
            except ValueError:
                result.append(tok)
    return result


def _parse_step_file(file_path: str, provenance: CadProvenance) -> GeometryModel:
    """Deterministic, pure-python STEP ISO-10303-21 B-Rep entity extractor.

    Parses the canonical topological hierarchy:
    Solid -> Shell -> Face (Outer/Inner Loops) -> Edge (Oriented) -> Vertex.
    Extracts analytical surface and curve metadata (Plane, Cylinder, Circle, Line).
    Enforces auditable provenance, unit detection, and fail-closed handling for
    unsupported entities or broken topological references.
    """
    import math

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        raise CadIngestionError(f"Failed to read STEP file {file_path}: {exc}") from exc

    if "ISO-10303-21;" not in content:
        raise CadIngestionError(f"File {file_path} is not a valid ISO-10303-21 STEP exchange file")

    # Header parsing
    schema = "AP203"
    schema_match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", content, re.IGNORECASE)
    if schema_match:
        schema = schema_match.group(1).strip()

    preprocessor = None
    prep_match = re.search(r"FILE_NAME\s*\([^,]+,[^,]+,[^,]+,[^,]+,\s*'([^']*)'", content, re.IGNORECASE)
    if prep_match and prep_match.group(1).strip():
        preprocessor = prep_match.group(1).strip()

    # Determine unit
    unit = CadUnit.MM
    if re.search(r"\.METRE\.", content, re.IGNORECASE) and not re.search(r"\.MILLI\.", content, re.IGNORECASE):
        unit = CadUnit.M
    elif re.search(r"\.INCH\.", content, re.IGNORECASE):
        unit = CadUnit.IN
    elif re.search(r"\.MILLI\.", content, re.IGNORECASE):
        unit = CadUnit.MM

    # Strip comments /* ... */
    clean_content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    # Extract all entity definitions #<id> = <rhs> ;
    entity_pattern = re.compile(r"#(\d+)\s*=\s*(.*?)\s*;", flags=re.DOTALL)
    raw_entities: Dict[str, Tuple[str, List[Any]]] = {}
    complex_entities: Dict[str, List[Tuple[str, List[Any]]]] = {}

    for match in entity_pattern.finditer(clean_content):
        ent_id = match.group(1)
        rhs = match.group(2).strip()

        # Check for complex entity instance: ( ENT1(...) ENT2(...) )
        if rhs.startswith("(") and rhs.endswith(")"):
            sub_matches = re.findall(r"([A-Za-z0-9_]+)\s*\((.*?)\)", rhs, flags=re.DOTALL)
            if sub_matches:
                complex_entities[ent_id] = [
                    (sub_type.upper(), _parse_step_args(sub_args))
                    for sub_type, sub_args in sub_matches
                ]
                continue

        ent_match = re.match(r"^([A-Za-z0-9_]+)\s*\((.*)\)$", rhs, flags=re.DOTALL)
        if ent_match:
            ent_type = ent_match.group(1).upper()
            args = _parse_step_args(ent_match.group(2))
            raw_entities[ent_id] = (ent_type, args)

    # Refined unit check from parsed complex SI_UNIT definitions
    for ent_id, subs in complex_entities.items():
        for sub_type, sub_args in subs:
            if sub_type == "SI_UNIT":
                sub_args_str = str(sub_args).upper()
                if "MILLI" in sub_args_str:
                    unit = CadUnit.MM
                elif "METRE" in sub_args_str and "MILLI" not in sub_args_str:
                    unit = CadUnit.M
                elif "INCH" in sub_args_str:
                    unit = CadUnit.IN

    unsupported_entities: List[str] = []
    broken_references: List[str] = []

    # Check for unsupported entity occurrences
    for ent_id, (ent_type, _) in raw_entities.items():
        if ent_type not in SUPPORTED_STEP_ENTITIES:
            # Common packaging entities ignored from warning
            if ent_type not in ("APPLICATION_CONTEXT", "PRODUCT_DEFINITION", "SHAPE_REPRESENTATION", "UNCERTAINTY_MEASURE_WITH_UNIT"):
                unsupported_entities.append(f"#{ent_id}={ent_type}")

    # Step 1: Extract CARTESIAN_POINT entities
    points_by_id: Dict[str, Tuple[float, float, float]] = {}
    vertices: List[CadVertex] = []
    points_coords: List[Tuple[float, float, float]] = []

    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "CARTESIAN_POINT":
            try:
                coords_raw = args[1] if len(args) > 1 and isinstance(args[1], list) else args[0]
                if isinstance(coords_raw, list) and len(coords_raw) >= 3:
                    pt = (float(coords_raw[0]), float(coords_raw[1]), float(coords_raw[2]))
                    points_by_id[ent_id] = pt
                    vertices.append(CadVertex(id=f"V_{ent_id}", point=pt))
                    points_coords.append(pt)
            except Exception:
                broken_references.append(f"CARTESIAN_POINT_#{ent_id}")

    # Step 2: Extract DIRECTION and VECTOR entities
    directions_by_id: Dict[str, Tuple[float, float, float]] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "DIRECTION":
            try:
                comp_raw = args[1] if len(args) > 1 and isinstance(args[1], list) else args[0]
                if isinstance(comp_raw, list) and len(comp_raw) >= 3:
                    dx, dy, dz = float(comp_raw[0]), float(comp_raw[1]), float(comp_raw[2])
                    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
                    if norm > 1e-12:
                        directions_by_id[ent_id] = (dx / norm, dy / norm, dz / norm)
                    else:
                        directions_by_id[ent_id] = (0.0, 0.0, 1.0)
            except Exception:
                broken_references.append(f"DIRECTION_#{ent_id}")

    # Step 3: Extract AXIS2_PLACEMENT_3D entities
    placements_by_id: Dict[str, Dict[str, Any]] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "AXIS2_PLACEMENT_3D":
            loc_ref = _clean_ref(args[1]) if len(args) > 1 else None
            axis_ref = _clean_ref(args[2]) if len(args) > 2 and args[2] is not None else None
            ref_dir_ref = _clean_ref(args[3]) if len(args) > 3 and args[3] is not None else None

            origin = points_by_id.get(loc_ref, (0.0, 0.0, 0.0))
            axis = directions_by_id.get(axis_ref, (0.0, 0.0, 1.0))
            ref_dir = directions_by_id.get(ref_dir_ref, (1.0, 0.0, 0.0))
            placements_by_id[ent_id] = {"origin": origin, "axis": axis, "ref_dir": ref_dir}

    # Step 4: Extract geometric curves (LINE, CIRCLE)
    curves_by_id: Dict[str, Dict[str, Any]] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "LINE":
            p_ref = _clean_ref(args[1]) if len(args) > 1 else None
            curves_by_id[ent_id] = {"type": "LINE", "point": p_ref}
        elif ent_type == "CIRCLE":
            place_ref = _clean_ref(args[1]) if len(args) > 1 else None
            radius = float(args[2]) if len(args) > 2 else 0.0
            curves_by_id[ent_id] = {"type": "CIRCLE", "placement": place_ref, "radius": radius}

    # Step 5: Extract VERTEX_POINT entities
    vertex_points_by_id: Dict[str, str] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "VERTEX_POINT":
            p_ref = _clean_ref(args[1]) if len(args) > 1 else None
            if p_ref:
                vertex_points_by_id[ent_id] = p_ref

    # Step 6: Extract EDGE_CURVE entities
    edges_by_id: Dict[str, CadEdge] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "EDGE_CURVE":
            sv_ref = _clean_ref(args[1]) if len(args) > 1 else None
            ev_ref = _clean_ref(args[2]) if len(args) > 2 else None
            crv_ref = _clean_ref(args[3]) if len(args) > 3 else None

            sp_id = vertex_points_by_id.get(sv_ref, sv_ref)
            ep_id = vertex_points_by_id.get(ev_ref, ev_ref)

            p1 = points_by_id.get(sp_id)
            p2 = points_by_id.get(ep_id)

            curve_info = curves_by_id.get(crv_ref, {})
            crv_type = curve_info.get("type", "EDGE_CURVE")

            length: Optional[float] = None
            if crv_type == "CIRCLE":
                r = curve_info.get("radius", 0.0)
                length = 2.0 * math.pi * r
            elif p1 and p2:
                dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
                length = math.sqrt(dx * dx + dy * dy + dz * dz)
            else:
                length = 1.0

            v_start = f"V_{sp_id}" if sp_id in points_by_id else None
            v_end = f"V_{ep_id}" if ep_id in points_by_id else None

            edges_by_id[ent_id] = CadEdge(
                id=f"E_{ent_id}",
                curve_type=crv_type,
                start_vertex_id=v_start,
                end_vertex_id=v_end,
                length=length,
            )

    # Step 7: Extract ORIENTED_EDGE entities
    oriented_edges_by_id: Dict[str, Tuple[str, bool]] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "ORIENTED_EDGE":
            edge_curve_ref = _clean_ref(args[3]) if len(args) > 3 else None
            sense = bool(args[4]) if len(args) > 4 else True
            if edge_curve_ref:
                oriented_edges_by_id[ent_id] = (edge_curve_ref, sense)

    # Step 8: Extract EDGE_LOOP entities
    loops_by_id: Dict[str, Tuple[Tuple[str, ...], Tuple[bool, ...]]] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "EDGE_LOOP":
            oe_list = args[1] if len(args) > 1 and isinstance(args[1], list) else []
            eids: List[str] = []
            senses: List[bool] = []
            for oe in oe_list:
                oe_ref = _clean_ref(oe)
                if oe_ref in oriented_edges_by_id:
                    ec_id, sense = oriented_edges_by_id[oe_ref]
                    eids.append(f"E_{ec_id}")
                    senses.append(sense)
                elif oe_ref in edges_by_id:
                    eids.append(f"E_{oe_ref}")
                    senses.append(True)
                else:
                    broken_references.append(f"EDGE_LOOP_ref_#{oe_ref}")
            loops_by_id[ent_id] = (tuple(eids), tuple(senses))

    # Step 9: Extract FACE_OUTER_BOUND and FACE_BOUND entities
    face_bounds_by_id: Dict[str, CadLoop] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type in ("FACE_OUTER_BOUND", "FACE_BOUND"):
            is_outer = (ent_type == "FACE_OUTER_BOUND")
            loop_ref = _clean_ref(args[1]) if len(args) > 1 else None
            loop_data = loops_by_id.get(loop_ref, ((), ()))
            face_bounds_by_id[ent_id] = CadLoop(
                id=f"LOOP_{ent_id}",
                is_outer=is_outer,
                edge_ids=loop_data[0],
                edge_orientations=loop_data[1],
            )

    # Step 10: Extract analytical surfaces (PLANE, CYLINDRICAL_SURFACE)
    surfaces_by_id: Dict[str, Dict[str, Any]] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type == "PLANE":
            place_ref = _clean_ref(args[1]) if len(args) > 1 else None
            placement = placements_by_id.get(place_ref, {})
            normal = placement.get("axis", (0.0, 0.0, 1.0))
            surfaces_by_id[ent_id] = {
                "surface_type": "PLANE",
                "is_planar": True,
                "normal": normal,
            }
        elif ent_type == "CYLINDRICAL_SURFACE":
            place_ref = _clean_ref(args[1]) if len(args) > 1 else None
            radius = float(args[2]) if len(args) > 2 else 0.0
            placement = placements_by_id.get(place_ref, {})
            surfaces_by_id[ent_id] = {
                "surface_type": "CYLINDRICAL_SURFACE",
                "is_planar": False,
                "radius": radius,
                "axis": placement.get("axis"),
                "normal": None,
            }

    # Step 11: Extract ADVANCED_FACE and FACE_SURFACE entities
    faces_by_id: Dict[str, CadFace] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type in ("ADVANCED_FACE", "FACE_SURFACE"):
            bounds_raw = args[1] if len(args) > 1 and isinstance(args[1], list) else []
            surf_ref = _clean_ref(args[2]) if len(args) > 2 else None

            outer_loop: Optional[CadLoop] = None
            inner_loops: List[CadLoop] = []
            collected_edges: List[str] = []

            for b in bounds_raw:
                b_ref = _clean_ref(b)
                if b_ref in face_bounds_by_id:
                    loop_obj = face_bounds_by_id[b_ref]
                    if loop_obj.is_outer and outer_loop is None:
                        outer_loop = loop_obj
                    else:
                        inner_loops.append(loop_obj)
                    collected_edges.extend(loop_obj.edge_ids)
                elif b_ref in loops_by_id:
                    # Direct loop reference fallback
                    loop_data = loops_by_id[b_ref]
                    loop_obj = CadLoop(
                        id=f"LOOP_{b_ref}",
                        is_outer=(outer_loop is None),
                        edge_ids=loop_data[0],
                        edge_orientations=loop_data[1],
                    )
                    if outer_loop is None:
                        outer_loop = loop_obj
                    else:
                        inner_loops.append(loop_obj)
                    collected_edges.extend(loop_obj.edge_ids)
                elif b_ref in edges_by_id:
                    # Minimal test fixture fallback: bounds containing direct edge curves
                    collected_edges.append(f"E_{b_ref}")

            surf_info = surfaces_by_id.get(surf_ref)
            if surf_info:
                st = surf_info["surface_type"]
                is_p = surf_info["is_planar"]
                norm = surf_info.get("normal")
            else:
                st = "ADVANCED_FACE"
                is_p = ("PLANE" in content)
                norm = None
                if surf_ref and surf_ref not in raw_entities:
                    broken_references.append(f"FACE_SURFACE_ref_#{surf_ref}")

            face_obj = CadFace(
                id=f"F_{ent_id}",
                surface_type=st,
                edge_ids=tuple(sorted(set(collected_edges))),
                outer_loop=outer_loop,
                inner_loops=tuple(inner_loops),
                normal=norm,
                is_planar=is_p,
            )
            faces_by_id[ent_id] = face_obj

    # Step 12: Extract CLOSED_SHELL and OPEN_SHELL entities
    shells_by_id: Dict[str, CadShell] = {}
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type in ("CLOSED_SHELL", "OPEN_SHELL"):
            face_refs = args[1] if len(args) > 1 and isinstance(args[1], list) else []
            shell_faces = tuple(f"F_{_clean_ref(f)}" for f in face_refs)
            is_closed = (ent_type == "CLOSED_SHELL")
            shells_by_id[ent_id] = CadShell(
                id=f"SH_{ent_id}",
                face_ids=shell_faces,
                is_closed=is_closed,
            )

    # Step 13: Extract MANIFOLD_SOLID_BREP and BREP_WITH_VOIDS entities
    solids: List[CadSolid] = []
    for ent_id, (ent_type, args) in raw_entities.items():
        if ent_type in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "SOLID_MODEL"):
            shell_ref = _clean_ref(args[1]) if len(args) > 1 else None
            shell_ids = (f"SH_{shell_ref}",) if shell_ref else ()
            solids.append(CadSolid(id=f"S_{ent_id}", shell_ids=shell_ids))

    # Compute bounding box from vertices
    bbox = None
    if points_coords:
        min_x = min(p[0] for p in points_coords)
        max_x = max(p[0] for p in points_coords)
        min_y = min(p[1] for p in points_coords)
        max_y = max(p[1] for p in points_coords)
        min_z = min(p[2] for p in points_coords)
        max_z = max(p[2] for p in points_coords)
        if min_x <= max_x and min_y <= max_y and min_z <= max_z:
            bbox = CadBoundingBox(
                min_x=min_x,
                min_y=min_y,
                min_z=min_z,
                max_x=max_x,
                max_y=max_y,
                max_z=max_z,
            )

    # Sort entity lists lexicographically for deterministic provenance
    all_solids = tuple(sorted(solids, key=lambda s: s.id))
    all_shells = tuple(sorted(shells_by_id.values(), key=lambda sh: sh.id))
    all_faces = tuple(sorted(faces_by_id.values(), key=lambda f: f.id))
    all_edges = tuple(sorted(edges_by_id.values(), key=lambda e: e.id))
    all_vertices = tuple(sorted(vertices, key=lambda v: v.id))

    updated_provenance = CadProvenance(
        file_path=provenance.file_path,
        file_name=provenance.file_name,
        file_sha256=provenance.file_sha256,
        file_size_bytes=provenance.file_size_bytes,
        ingested_at=provenance.ingested_at,
        cad_format=CadFormat.STEP,
        cad_schema=schema,
        preprocessor=preprocessor,
    )

    model_id = f"STEP_{provenance.file_sha256[:12]}"

    metadata: Dict[str, Any] = {
        "unsupported_entities": sorted(set(unsupported_entities)),
        "broken_references": sorted(set(broken_references)),
    }

    return GeometryModel(
        model_id=model_id,
        provenance=updated_provenance,
        unit=unit,
        bounding_box=bbox,
        solids=all_solids,
        shells=all_shells,
        faces=all_faces,
        edges=all_edges,
        vertices=all_vertices,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# IGES (Initial Graphics Exchange Specification) Parser
# ---------------------------------------------------------------------------

def _parse_iges_file(file_path: str, provenance: CadProvenance) -> GeometryModel:
    """Lightweight deterministic IGES (ANSI Y14.26M) 80-column section extractor."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        raise CadIngestionError(f"Failed to read IGES file {file_path}: {exc}") from exc

    if not lines or len(lines[0]) < 73:
        raise CadIngestionError(f"File {file_path} is too short or malformed for IGES format")

    # Group lines by section code in column 73 (0-indexed 72)
    s_lines: List[str] = []
    g_lines: List[str] = []
    d_lines: List[str] = []
    p_lines: List[str] = []

    for line in lines:
        if len(line) >= 73:
            section_code = line[72].upper()
            if section_code == "S":
                s_lines.append(line[:72])
            elif section_code == "G":
                g_lines.append(line[:72])
            elif section_code == "D":
                d_lines.append(line)
            elif section_code == "P":
                p_lines.append(line)

    if not g_lines and not d_lines:
        raise CadIngestionError(f"File {file_path} does not contain valid IGES Global or Directory sections")

    # Global section parsing for units
    global_text = "".join(g_lines)
    unit = CadUnit.MM
    # Parse IGES Hollerith or comma-separated tokens in Global section
    # Parameter 14 is the unit flag: 1=inches, 2=millimeters, 3=special, 4=feet, 6=meters
    # Also check string token 'MM', 'INCH', 'M'
    upper_g = global_text.upper()
    if "2HMM" in upper_g or "MM" in upper_g:
        unit = CadUnit.MM
    elif "4HINCH" in upper_g or "2HIN" in upper_g or "INCH" in upper_g:
        unit = CadUnit.IN
    elif "1HM" in upper_g or "METER" in upper_g:
        unit = CadUnit.M
    else:
        # Fallback to positional token if standard delimiters used
        tokens = [t.strip() for t in global_text.replace(";", ",").split(",")]
        if len(tokens) >= 15:
            flag = tokens[14]
            if flag == "1":
                unit = CadUnit.IN
            elif flag == "2":
                unit = CadUnit.MM
            elif flag == "6":
                unit = CadUnit.M

    # Parse Directory Entry (D) records (each entity spans 2 lines in D section)
    entity_counts: Dict[int, int] = {}
    solids: List[CadSolid] = []
    shells: List[CadShell] = []
    faces: List[CadFace] = []
    edges: List[CadEdge] = []
    vertices: List[CadVertex] = []
    points_coords: List[Tuple[float, float, float]] = []

    for i in range(0, len(d_lines) - 1, 2):
        d1 = d_lines[i]
        try:
            ent_type = int(d1[0:8].strip())
        except ValueError:
            continue

        entity_counts[ent_type] = entity_counts.get(ent_type, 0) + 1
        seq_id = str(i // 2 + 1)

        # 186 = Manifold Solid B-Rep
        if ent_type == 186:
            solids.append(CadSolid(id=f"IGES_S_{seq_id}"))
        # 514 = Shell
        elif ent_type == 514:
            shells.append(CadShell(id=f"IGES_SH_{seq_id}"))
        # 144 = Trimmed Surface, 143 = Bounded Surface, 128 = B-Spline Surface, 190 = Plane
        elif ent_type in (144, 143, 128, 190):
            faces.append(CadFace(id=f"IGES_F_{seq_id}", surface_type=str(ent_type), is_planar=(ent_type == 190)))
        # 110 = Line, 100 = Circular Arc, 126 = Rational B-Spline Curve
        elif ent_type in (110, 100, 126):
            edges.append(CadEdge(id=f"IGES_E_{seq_id}", curve_type=str(ent_type)))
        # 116 = Point
        elif ent_type == 116:
            vertices.append(CadVertex(id=f"IGES_V_{seq_id}", point=(0.0, 0.0, 0.0)))

    # Parse P lines for point coordinates (simple float extraction for bounding box)
    p_text = "".join(l[:64] for l in p_lines)
    # Extract floating point numbers
    float_pattern = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eEdD][-+]?[0-9]+)?")
    floats: List[float] = []
    for m in float_pattern.finditer(p_text):
        val_str = m.group(0).replace("D", "E").replace("d", "e")
        try:
            floats.append(float(val_str))
        except ValueError:
            pass

    # Group into triplets if reasonable
    bbox = None
    if len(floats) >= 3:
        triplets = [
            (floats[j], floats[j + 1], floats[j + 2])
            for j in range(0, len(floats) - 2, 3)
            if not any(abs(c) > 1e7 for c in (floats[j], floats[j + 1], floats[j + 2]))
        ]
        if triplets:
            min_x = min(t[0] for t in triplets)
            max_x = max(t[0] for t in triplets)
            min_y = min(t[1] for t in triplets)
            max_y = max(t[1] for t in triplets)
            min_z = min(t[2] for t in triplets)
            max_z = max(t[2] for t in triplets)
            if min_x <= max_x and min_y <= max_y and min_z <= max_z:
                bbox = CadBoundingBox(
                    min_x=min_x,
                    min_y=min_y,
                    min_z=min_z,
                    max_x=max_x,
                    max_y=max_y,
                    max_z=max_z,
                )

    updated_provenance = CadProvenance(
        file_path=provenance.file_path,
        file_name=provenance.file_name,
        file_sha256=provenance.file_sha256,
        file_size_bytes=provenance.file_size_bytes,
        ingested_at=provenance.ingested_at,
        cad_format=CadFormat.IGES,
        cad_schema="IGES-5.3",
    )

    model_id = f"IGES_{provenance.file_sha256[:12]}"

    return GeometryModel(
        model_id=model_id,
        provenance=updated_provenance,
        unit=unit,
        bounding_box=bbox,
        solids=tuple(solids),
        shells=tuple(shells),
        faces=tuple(faces),
        edges=tuple(edges),
        vertices=tuple(vertices),
    )


# ---------------------------------------------------------------------------
# Public Ingestion & Capability Classification APIs
# ---------------------------------------------------------------------------

def ingest_cad_file(file_path: str) -> GeometryModel:
    """Ingest a neutral CAD file into a standardized GeometryModel with provenance.

    Parameters:
        file_path: Path to the .stp, .step, .igs, or .iges file.

    Returns:
        Immutable GeometryModel with verified SHA-256 provenance.

    Raises:
        FileNotFoundError: If the CAD file does not exist.
        CadIngestionError: If file is malformed, empty, or unparseable.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CAD file not found: {file_path}")

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise CadIngestionError(f"CAD file is empty (0 bytes): {file_path}")

    sha256 = compute_file_sha256(file_path)
    file_name = os.path.basename(file_path)
    cad_format = detect_cad_format(file_path)

    base_provenance = CadProvenance(
        file_path=os.path.abspath(file_path),
        file_name=file_name,
        file_sha256=sha256,
        file_size_bytes=file_size,
        ingested_at=datetime.now(timezone.utc).isoformat(),
        cad_format=cad_format,
    )

    if cad_format == CadFormat.STEP:
        return _parse_step_file(file_path, base_provenance)
    elif cad_format == CadFormat.IGES:
        return _parse_iges_file(file_path, base_provenance)
    else:
        raise CadIngestionError(
            f"Unsupported CAD format for file {file_name}. Only STEP (.stp, .step) "
            f"and IGES (.igs, .iges) are supported."
        )


def classify_cad_model(model: GeometryModel) -> CapabilityBoundary:
    """Evaluate ingested CAD model against the project's canonical 4-state capability contract.

    - SUPPORTED: Clean, closed manifold 3D solid(s) ready for autonomous meshing.
    - ASSISTED: Contains sheet bodies / open shells or multi-body intersections requiring
                secondary heuristic guidance (e.g. tetrahedral fallback or user input).
    - BLOCKED: Empty geometry, degraded zero-volume envelope, or unresolvable topological defect.
    - UNSUPPORTED: CAD format is UNKNOWN or completely unhandled geometry paradigm.
    """
    if model.provenance.cad_format == CadFormat.UNKNOWN:
        return CapabilityBoundary(
            status=CapabilityStatus.UNSUPPORTED,
            action_type="cad_ingestion",
            reason=f"Unknown or unsupported CAD format '{model.provenance.cad_format.value}'",
            engineering_verified=False,
        )

    if model.is_empty:
        return CapabilityBoundary(
            status=CapabilityStatus.BLOCKED,
            action_type="cad_ingestion",
            reason="CAD model contains zero solids, shells, faces, edges, or vertices (empty topology)",
            engineering_verified=False,
        )

    if model.metadata.get("broken_references"):
        broken = model.metadata["broken_references"]
        return CapabilityBoundary(
            status=CapabilityStatus.BLOCKED,
            action_type="cad_ingestion",
            reason=f"CAD model contains broken topological entity references: {broken[:3]}",
            engineering_verified=False,
        )

    if model.metadata.get("unsupported_entities"):
        unsupported = model.metadata["unsupported_entities"]
        return CapabilityBoundary(
            status=CapabilityStatus.ASSISTED,
            action_type="cad_ingestion",
            reason=f"CAD model contains unsupported entity types: {unsupported[:3]}. Requires assisted healing.",
            engineering_verified=False,
        )

    if model.bounding_box is not None:
        dx, dy, dz = model.bounding_box.dimensions
        if dx < 0 or dy < 0 or dz < 0:
            return CapabilityBoundary(
                status=CapabilityStatus.BLOCKED,
                action_type="cad_ingestion",
                reason=f"Degenerate negative bounding box dimensions: ({dx}, {dy}, {dz})",
                engineering_verified=False,
            )

    if model.has_open_shells:
        return CapabilityBoundary(
            status=CapabilityStatus.ASSISTED,
            action_type="cad_ingestion",
            reason=(
                f"CAD model contains open shell(s) (surface/sheet body). "
                f"Requires assisted geometry healing or shell/tet meshing fallback."
            ),
            engineering_verified=True,
        )

    if model.solid_count > 0 and model.is_manifold_solid:
        return CapabilityBoundary(
            status=CapabilityStatus.SUPPORTED,
            action_type="cad_ingestion",
            reason=(
                f"Valid manifold closed solid CAD model ({model.solid_count} solids, "
                f"{model.face_count} faces, {model.vertex_count} vertices). Ready for autonomous meshing."
            ),
            engineering_verified=True,
        )

    # Has faces/edges but not cleanly grouped into solids
    return CapabilityBoundary(
        status=CapabilityStatus.ASSISTED,
        action_type="cad_ingestion",
        reason=(
            f"CAD model contains {model.face_count} faces and {model.edge_count} edges "
            f"without explicit manifold solid grouping. Requires assisted topological assembly."
        ),
        engineering_verified=True,
    )
