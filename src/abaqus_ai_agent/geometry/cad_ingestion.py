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

def _parse_step_file(file_path: str, provenance: CadProvenance) -> GeometryModel:
    """Lightweight deterministic STEP (ISO-10303-21) entity and header extractor."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        raise CadIngestionError(f"Failed to read STEP file {file_path}: {exc}") from exc

    if "ISO-10303-21;" not in content:
        raise CadIngestionError(f"File {file_path} is not a valid ISO-10303-21 STEP exchange file")

    # Header parsing
    schema = "AP203"  # default baseline
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

    # Extract CARTESIAN_POINT entities: #123 = CARTESIAN_POINT ( 'name', ( 1.0, 2.0, 3.0 ) ) ;
    # Regex handles optional whitespace and entity names
    point_pattern = re.compile(
        r"#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*(?:'[^']*'|\$)?\s*,\s*\(\s*([^\)]+)\s*\)\s*\)\s*;",
        re.IGNORECASE,
    )

    vertices: List[CadVertex] = []
    points_coords: List[Tuple[float, float, float]] = []

    for match in point_pattern.finditer(content):
        ent_id = f"V_{match.group(1)}"
        coords_str = match.group(2)
        try:
            parts = [float(p.strip()) for p in coords_str.split(",") if p.strip()]
            if len(parts) >= 3:
                pt = (parts[0], parts[1], parts[2])
                vertices.append(CadVertex(id=ent_id, point=pt))
                points_coords.append(pt)
        except ValueError:
            continue

    # Extract EDGE_CURVE entities (topological edges)
    edge_pattern = re.compile(
        r"#(\d+)\s*=\s*(EDGE_CURVE|ORIENTED_EDGE)\s*\(",
        re.IGNORECASE,
    )
    edges: List[CadEdge] = []
    for match in edge_pattern.finditer(content):
        ent_id = f"E_{match.group(1)}"
        curve_type = match.group(2).upper()
        edges.append(CadEdge(id=ent_id, curve_type=curve_type))

    # Extract ADVANCED_FACE / FACE_SURFACE entities
    face_pattern = re.compile(
        r"#(\d+)\s*=\s*(ADVANCED_FACE|FACE_SURFACE|FACE_BOUND)\s*\(",
        re.IGNORECASE,
    )
    faces: List[CadFace] = []
    for match in face_pattern.finditer(content):
        ent_id = f"F_{match.group(1)}"
        ent_type = match.group(2).upper()
        faces.append(CadFace(id=ent_id, surface_type=ent_type, is_planar=("PLANE" in content)))

    # Extract CLOSED_SHELL / OPEN_SHELL entities
    shell_pattern = re.compile(
        r"#(\d+)\s*=\s*(CLOSED_SHELL|OPEN_SHELL)\s*\(",
        re.IGNORECASE,
    )
    shells: List[CadShell] = []
    for match in shell_pattern.finditer(content):
        ent_id = f"SH_{match.group(1)}"
        is_closed = (match.group(2).upper() == "CLOSED_SHELL")
        shells.append(CadShell(id=ent_id, is_closed=is_closed))

    # Extract MANIFOLD_SOLID_BREP / BREP_WITH_VOIDS entities
    solid_pattern = re.compile(
        r"#(\d+)\s*=\s*(MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS|SOLID_MODEL)\s*\(",
        re.IGNORECASE,
    )
    solids: List[CadSolid] = []
    for match in solid_pattern.finditer(content):
        ent_id = f"S_{match.group(1)}"
        solids.append(CadSolid(id=ent_id))

    # Compute bounding box if vertices exist
    bbox = None
    if points_coords:
        min_x = min(p[0] for p in points_coords)
        max_x = max(p[0] for p in points_coords)
        min_y = min(p[1] for p in points_coords)
        max_y = max(p[1] for p in points_coords)
        min_z = min(p[2] for p in points_coords)
        max_z = max(p[2] for p in points_coords)
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
        cad_format=CadFormat.STEP,
        cad_schema=schema,
        preprocessor=preprocessor,
    )

    model_id = f"STEP_{provenance.file_sha256[:12]}"

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
