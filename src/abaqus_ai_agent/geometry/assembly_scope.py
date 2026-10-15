"""Multi-part assembly scope: keep every solid, then ground contact and fixtures.

A handle assembly is not one solid. Dropping the pin, base, or clips and solving
the handle alone is a scope error, not a simplification. This module turns an
ingested multi-solid model into an explicit scope:

- every closed solid is an included part;
- opposing, nearly coincident planar faces on different parts become contact pairs;
- the largest exterior planar face becomes the installation fixture.

Pairs or fixtures that cannot be grounded stay as explicit gaps. Callers must
not treat a gapped scope as a solvable single-part model.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .model import CadFace, CadSolid, GeometryModel


_GAP_ABS = 0.5
_GAP_REL = 0.002
_NORMAL_ALIGN = 0.95
_MIN_FACE_AREA = 1.0


@dataclass(frozen=True)
class AssemblyPart:
    solid_id: str
    name: str
    instance_name: str
    shell_ids: Tuple[str, ...]
    face_ids: Tuple[str, ...]
    step_body_index: Optional[int] = None


@dataclass(frozen=True)
class MatingContact:
    name: str
    master_part: str
    slave_part: str
    master_instance: str
    slave_instance: str
    master_face_id: str
    slave_face_id: str
    master_surface: str
    slave_surface: str
    master_point: Tuple[float, float, float]
    slave_point: Tuple[float, float, float]
    gap: float
    friction_coefficient: float = 0.15


@dataclass(frozen=True)
class InstallationFixture:
    name: str
    part_id: str
    instance_name: str
    face_id: str
    set_name: str
    point: Tuple[float, float, float]
    normal: Tuple[float, float, float]
    area: float


@dataclass(frozen=True)
class AssemblyScope:
    """Explicit analysis boundary for a multi-solid CAD model."""

    parts: Tuple[AssemblyPart, ...]
    contacts: Tuple[MatingContact, ...]
    fixture: Optional[InstallationFixture]
    gaps: Tuple[str, ...]
    source_model_id: str

    @property
    def part_count(self) -> int:
        return len(self.parts)

    @property
    def is_complete(self) -> bool:
        return self.part_count >= 2 and bool(self.contacts) and self.fixture is not None and not self.gaps

    def to_dict(self) -> dict:
        return {
            "source_model_id": self.source_model_id,
            "part_count": self.part_count,
            "parts": [part.solid_id for part in self.parts],
            "contacts": [contact.name for contact in self.contacts],
            "fixture": None if self.fixture is None else self.fixture.set_name,
            "gaps": list(self.gaps),
            "is_complete": self.is_complete,
        }


def _safe_name(raw: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}".strip("_")
    return cleaned[:40] or fallback


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _sub(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (float(a[0]) - float(b[0]), float(a[1]) - float(b[1]), float(a[2]) - float(b[2]))


def _face_point(face: CadFace, vertices: Dict[str, Tuple[float, float, float]], edges: Dict[str, Tuple[Optional[str], Optional[str]]]) -> Optional[Tuple[float, float, float]]:
    points: List[Tuple[float, float, float]] = []
    for edge_id in face.edge_ids:
        start_id, end_id = edges.get(edge_id, (None, None))
        for vertex_id in (start_id, end_id):
            point = vertices.get(vertex_id or "")
            if point is not None and point not in points:
                points.append(point)
    if not points:
        return None
    count = float(len(points))
    return (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
        sum(point[2] for point in points) / count,
    )


def build_assembly_scope(
    model: GeometryModel,
    *,
    friction_coefficient: float = 0.15,
    fixture_face_id: Optional[str] = None,
    allow_unverified_exterior_fixture: bool = False,
) -> AssemblyScope:
    """Ground every solid, mating contact, and one installation fixture.

    Contact is accepted only when two planar faces belong to different solids,
    their normals oppose, and the faces are within a small absolute/relative gap.
    Installation fixture requires explicit semantic ground (e.g. named fixture_face_id
    or verifiable base/mount/fixture semantics) to prevent assigning constraints to
    movable components such as pins or handles. Missing verified fixture records
    'installation_fixture_not_grounded'.
    """
    if friction_coefficient < 0.0:
        raise ValueError(f"friction_coefficient cannot be negative, got {friction_coefficient}")

    shells = {shell.id: shell for shell in model.shells}
    faces = {face.id: face for face in model.faces}
    vertices = {vertex.id: vertex.point for vertex in model.vertices}
    edges = {edge.id: (edge.start_vertex_id, edge.end_vertex_id) for edge in model.edges}

    parts: List[AssemblyPart] = []
    face_owner: Dict[str, AssemblyPart] = {}
    # Keep STEP file order. Sorting by name would bind the wrong bodyNum.
    ordered_solids = tuple(sorted(
        model.solids,
        key=lambda item: (
            item.step_body_index is None,
            item.step_body_index if item.step_body_index is not None else 0,
            item.id,
        ),
    ))
    seen_body_indexes = set()
    for index, solid in enumerate(ordered_solids):
        face_ids: List[str] = []
        for shell_id in solid.shell_ids:
            shell = shells.get(shell_id)
            if shell is None:
                continue
            face_ids.extend(shell.face_ids)
        unique_faces = tuple(dict.fromkeys(face_ids))
        name = _safe_name(solid.id, f"Part{index + 1}")
        body_index = solid.step_body_index
        if body_index is not None:
            if body_index in seen_body_indexes:
                raise ValueError(
                    f"Duplicate STEP body index {body_index} on solid {solid.id}; "
                    "refusing to bind two parts to one imported body"
                )
            seen_body_indexes.add(body_index)
        part = AssemblyPart(
            solid_id=solid.id,
            name=name,
            instance_name=f"{name}-1",
            shell_ids=solid.shell_ids,
            face_ids=unique_faces,
            step_body_index=body_index,
        )
        parts.append(part)
        for face_id in unique_faces:
            face_owner[face_id] = part

    planar: List[Tuple[AssemblyPart, CadFace, Tuple[float, float, float], Tuple[float, float, float]]] = []
    for part in parts:
        for face_id in part.face_ids:
            face = faces.get(face_id)
            if face is None or not face.is_planar or face.normal is None:
                continue
            if face.area is not None and face.area < _MIN_FACE_AREA:
                continue
            point = _face_point(face, vertices, edges)
            if point is None:
                continue
            planar.append((part, face, face.normal, point))

    contacts: List[MatingContact] = []
    used_faces = set()
    candidates: List[Tuple[float, int, int]] = []
    for i, left in enumerate(planar):
        for j in range(i + 1, len(planar)):
            right = planar[j]
            if left[0].solid_id == right[0].solid_id:
                continue
            alignment = _dot(left[2], right[2])
            if alignment > -_NORMAL_ALIGN:
                continue
            gap = abs(_dot(_sub(right[3], left[3]), left[2]))
            span = 1.0
            if model.bounding_box is not None:
                span = max(model.bounding_box.dimensions)
            if gap > max(_GAP_ABS, _GAP_REL * span):
                continue
            candidates.append((gap, i, j))

    for _, i, j in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
        left = planar[i]
        right = planar[j]
        if left[1].id in used_faces or right[1].id in used_faces:
            continue
        used_faces.add(left[1].id)
        used_faces.add(right[1].id)
        master, slave = (left, right) if left[0].solid_id <= right[0].solid_id else (right, left)
        pair_index = len(contacts) + 1
        contacts.append(MatingContact(
            name=f"Contact_{pair_index}",
            master_part=master[0].solid_id,
            slave_part=slave[0].solid_id,
            master_instance=master[0].instance_name,
            slave_instance=slave[0].instance_name,
            master_face_id=master[1].id,
            slave_face_id=slave[1].id,
            master_surface=f"Contact_{pair_index}_Main",
            slave_surface=f"Contact_{pair_index}_Secondary",
            master_point=master[3],
            slave_point=slave[3],
            gap=abs(_dot(_sub(slave[3], master[3]), master[2])),
            friction_coefficient=float(friction_coefficient),
        ))

    centroid = (0.0, 0.0, 0.0)
    if model.bounding_box is not None:
        centroid = model.bounding_box.center
    fixture: Optional[InstallationFixture] = None

    # Priority 1: Explicitly requested fixture_face_id
    if fixture_face_id is not None:
        for part, face, normal, point in planar:
            if face.id == fixture_face_id:
                fixture = InstallationFixture(
                    name="InstallationFixed",
                    part_id=part.solid_id,
                    instance_name=part.instance_name,
                    face_id=face.id,
                    set_name="InstallationFixed",
                    point=point,
                    normal=normal,
                    area=float(face.area or 0.0),
                )
                break

    # Priority 2: Semantic name matching on Face ID or Part ID (e.g. FIX, BASE, MOUNT, GROUND)
    if fixture is None:
        semantic_keywords = ("fix", "base", "mount", "ground", "housing")
        disqualified_faces = ("pin", "lever", "spring", "bolt", "screw")
        semantic_candidates = []
        for part, face, normal, point in planar:
            if face.id in used_faces:
                continue
            face_tag = face.id.lower()
            part_tag = part.solid_id.lower()
            if any(dq in face_tag for dq in disqualified_faces):
                continue
            if any(kw in face_tag for kw in semantic_keywords) or any(kw in part_tag for kw in semantic_keywords):
                outward = _dot(_sub(point, centroid), normal)
                if outward > 1e-6:
                    area = float(face.area or 0.0)
                    semantic_candidates.append((area, part, face, normal, point))
        if semantic_candidates:
            # Pick the largest area among semantic base faces
            semantic_candidates.sort(key=lambda item: item[0], reverse=True)
            chosen = semantic_candidates[0]
            fixture = InstallationFixture(
                name="InstallationFixed",
                part_id=chosen[1].solid_id,
                instance_name=chosen[1].instance_name,
                face_id=chosen[2].id,
                set_name="InstallationFixed",
                point=chosen[4],
                normal=chosen[3],
                area=chosen[0],
            )

    # Priority 3: Fallback ONLY if explicitly allowed by allow_unverified_exterior_fixture=True
    if fixture is None and allow_unverified_exterior_fixture:
        best_key: Optional[Tuple[int, float]] = None
        for part, face, normal, point in planar:
            if face.id in used_faces:
                continue
            outward = _dot(_sub(point, centroid), normal)
            if outward <= 1e-6:
                continue
            axis = max(range(3), key=lambda i: abs(normal[i]))
            if abs(normal[axis]) < 0.95:
                continue
            signed = point[axis] if normal[axis] > 0.0 else -point[axis]
            same_direction = [
                (item[3][axis] if item[2][axis] > 0.0 else -item[3][axis])
                for item in planar
                if item[1].id not in used_faces and abs(item[2][axis]) >= 0.95 and (item[2][axis] > 0.0) == (normal[axis] > 0.0)
            ]
            if abs(signed - max(same_direction)) > 1e-6:
                continue
            area = float(face.area or 0.0)
            key = (signed, area)
            if best_key is not None and key <= best_key:
                continue
            best_key = key
            fixture = InstallationFixture(
                name="InstallationFixed",
                part_id=part.solid_id,
                instance_name=part.instance_name,
                face_id=face.id,
                set_name="InstallationFixed",
                point=point,
                normal=normal,
                area=area,
            )

    gaps: List[str] = []
    if len(parts) >= 2 and any(part.step_body_index is None for part in parts):
        missing = [part.solid_id for part in parts if part.step_body_index is None]
        gaps.append("step_body_index_missing:" + ",".join(missing))
    if len(parts) < 2:
        gaps.append("assembly_requires_at_least_two_solids")
    isolated = [part.solid_id for part in parts if not any(
        part.solid_id in (contact.master_part, contact.slave_part) for contact in contacts
    )]
    if isolated and len(parts) >= 2:
        gaps.append("parts_without_mating_contact:" + ",".join(isolated))
    if fixture is None and len(parts) >= 2:
        gaps.append("installation_fixture_not_grounded")

    return AssemblyScope(
        parts=tuple(parts),
        contacts=tuple(contacts),
        fixture=fixture,
        gaps=tuple(gaps),
        source_model_id=model.model_id,
    )


def require_complete_assembly_scope(scope: AssemblyScope) -> AssemblyScope:
    """Refuse a scope that would again drop parts, contact, or the fixture."""
    if not scope.is_complete:
        raise ValueError(
            "Incomplete assembly scope: every related solid, at least one mating "
            f"contact, and one installation fixture are required. gaps={list(scope.gaps)}"
        )
    return scope
