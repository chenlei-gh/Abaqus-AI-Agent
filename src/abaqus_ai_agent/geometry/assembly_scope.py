"""Multi-part assembly scope: screen by the analysis requirement, then ground.

A product STEP file is an inventory, not an analysis boundary. The requirement
names the object of analysis; only that object and the parts required to carry
its load or hold it in place stay in the model. Everything else is excluded
with a reason, or held as pending when the evidence is not unique.

- retained solids become analysis parts;
- opposing, nearly coincident planar faces on retained parts become contact pairs;
- an installation fixture is accepted only with an explicit or semantic ground.

A missing requirement, an ambiguous part identity, or an ungrounded fixture is
a gap. Callers must not fall back to analyzing every solid, or to one solid.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

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
class ScreenedPart:
    """One solid after requirement screening. Identity is never inferred here."""

    solid_id: str
    disposition: str
    role: str
    reason: str
    evidence: Tuple[str, ...] = ()
    confidence: Optional[float] = None

    def __post_init__(self):
        if self.disposition not in ("retain", "exclude", "pending"):
            raise ValueError(f"invalid screening disposition {self.disposition!r}")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("screening confidence must be between 0 and 1")


@dataclass(frozen=True)
class AnalysisScreen:
    """Requirement-driven keep / drop / confirm list for one CAD inventory."""

    requirement: str
    decisions: Tuple[ScreenedPart, ...]
    source: str = "explicit"

    @property
    def retained_ids(self) -> Tuple[str, ...]:
        return tuple(item.solid_id for item in self.decisions if item.disposition == "retain")

    @property
    def excluded_ids(self) -> Tuple[str, ...]:
        return tuple(item.solid_id for item in self.decisions if item.disposition == "exclude")

    @property
    def pending_ids(self) -> Tuple[str, ...]:
        return tuple(item.solid_id for item in self.decisions if item.disposition == "pending")

    @property
    def is_resolved(self) -> bool:
        return bool(self.retained_ids) and not self.pending_ids and len(self.decisions) > 0

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "source": self.source,
            "retained": list(self.retained_ids),
            "excluded": list(self.excluded_ids),
            "pending": list(self.pending_ids),
            "decisions": [
                {
                    "solid_id": item.solid_id,
                    "disposition": item.disposition,
                    "role": item.role,
                    "reason": item.reason,
                    "evidence": list(item.evidence),
                    "confidence": item.confidence,
                }
                for item in self.decisions
            ],
        }


@dataclass(frozen=True)
class AssemblyScope:
    """Explicit analysis boundary for the solids the requirement retained."""

    parts: Tuple[AssemblyPart, ...]
    contacts: Tuple[MatingContact, ...]
    fixture: Optional[InstallationFixture]
    gaps: Tuple[str, ...]
    source_model_id: str
    screen: Optional[AnalysisScreen] = None
    excluded_solid_ids: Tuple[str, ...] = ()

    @property
    def part_count(self) -> int:
        return len(self.parts)

    @property
    def is_complete(self) -> bool:
        screened = self.screen is None or self.screen.is_resolved
        return (
            self.part_count >= 1
            and screened
            and self.fixture is not None
            and not self.gaps
            and (self.part_count == 1 or bool(self.contacts))
        )

    def to_dict(self) -> dict:
        return {
            "source_model_id": self.source_model_id,
            "part_count": self.part_count,
            "parts": [part.solid_id for part in self.parts],
            "excluded": list(self.excluded_solid_ids),
            "contacts": [contact.name for contact in self.contacts],
            "fixture": None if self.fixture is None else self.fixture.set_name,
            "gaps": list(self.gaps),
            "is_complete": self.is_complete,
            "screen": None if self.screen is None else self.screen.to_dict(),
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


_TARGET_CUES = (
    "handle", "lever", "grip", "knob", "拉手", "手柄", "把手",
)
_LOAD_PATH_CUES = (
    "pin", "shaft", "axle", "clip", "spring", "销", "轴", "卡扣", "弹簧",
)
_INSTALL_CUES = (
    "base", "mount", "housing", "bracket", "fix", "底座", "安装", "支架", "壳体",
)
_FASTENER_CUES = ("screw", "bolt", "nut", "washer", "rivet", "螺钉", "螺栓", "螺母", "垫圈")


def _requirement_text(requirement: Optional[Union[str, Mapping[str, object]]]) -> str:
    if requirement is None:
        return ""
    if isinstance(requirement, str):
        return requirement.strip()
    parts = []
    for key in ("description", "text", "requirement", "analysis_object"):
        value = requirement.get(key)
        if value:
            parts.append(str(value))
    return " ".join(parts).strip()


def _explicit_ids(requirement: Optional[Union[str, Mapping[str, object]]]) -> Optional[Tuple[str, ...]]:
    if not isinstance(requirement, Mapping):
        return None
    raw = requirement.get("include_solid_ids") or requirement.get("retained_solid_ids")
    if raw is None:
        return None
    return tuple(str(item) for item in raw)


def screen_assembly_requirement(
    model: GeometryModel,
    requirement: Optional[Union[str, Mapping[str, object]]] = None,
    *,
    judgments: Optional[Mapping[str, Mapping[str, object]]] = None,
    retain_threshold: float = 0.8,
    exclude_threshold: float = 0.2,
) -> AnalysisScreen:
    """Classify every solid as retain, exclude, or pending.

    Code owns the inventory and the thresholds. A caller may supply one JEV
    judgment per solid id; a judgment never invents a solid, and a value between
    the two thresholds stays pending instead of being forced into the analysis.
    Without a requirement, nothing is retained: analyzing the whole product is
    not the default.
    """
    if not 0.0 <= exclude_threshold < retain_threshold <= 1.0:
        raise ValueError("screening thresholds must satisfy 0 <= exclude < retain <= 1")
    text = _requirement_text(requirement)
    explicit = _explicit_ids(requirement)
    known = {solid.id for solid in model.solids}
    decisions: List[ScreenedPart] = []

    if explicit is not None:
        unknown = [item for item in explicit if item not in known]
        if unknown:
            raise ValueError(
                "requirement names solids that are not in the CAD inventory: "
                + ",".join(unknown)
            )
        wanted = set(explicit)
        for solid in model.solids:
            if solid.id in wanted:
                decisions.append(ScreenedPart(
                    solid.id, "retain", "analysis_object",
                    "named by the analysis requirement",
                    evidence=("explicit_solid_id",),
                    confidence=1.0,
                ))
            else:
                decisions.append(ScreenedPart(
                    solid.id, "exclude", "out_of_scope",
                    "not named by the analysis requirement",
                    evidence=("explicit_solid_id",),
                    confidence=1.0,
                ))
        return AnalysisScreen(text or "explicit solid ids", tuple(decisions), source="explicit")

    folded = text.lower()
    asks_full_product = any(token in folded for token in ("全部零件", "所有零件", "entire product", "all parts", "whole assembly"))
    for solid in model.solids:
        label = solid.id.lower()
        judgment = (judgments or {}).get(solid.id)
        if judgment is not None:
            probability = judgment.get("probability", judgment.get("noul"))
            if not isinstance(probability, (int, float)) or isinstance(probability, bool):
                decisions.append(ScreenedPart(
                    solid.id, "pending", "unclassified",
                    "JEV judgment for this solid has no probability",
                    evidence=("jev",),
                ))
                continue
            probability = float(probability)
            if probability >= retain_threshold:
                disposition, role = "retain", str(judgment.get("role") or "analysis_path")
            elif probability <= exclude_threshold:
                disposition, role = "exclude", "out_of_scope"
            else:
                disposition, role = "pending", "unclassified"
            decisions.append(ScreenedPart(
                solid.id, disposition, role,
                str(judgment.get("reason") or "JEV relevance judgment"),
                evidence=("jev",),
                confidence=probability,
            ))
            continue
        if not text:
            decisions.append(ScreenedPart(
                solid.id, "pending", "unclassified",
                "no analysis requirement was supplied",
                evidence=("missing_requirement",),
            ))
            continue
        if asks_full_product:
            decisions.append(ScreenedPart(
                solid.id, "retain", "analysis_object",
                "requirement explicitly asks for the whole product",
                evidence=("requirement_text",),
                confidence=1.0,
            ))
            continue
        named_roles = []
        if any(cue in folded and cue in label for cue in _TARGET_CUES):
            named_roles.append("analysis_object")
        if any(cue in folded and cue in label for cue in _LOAD_PATH_CUES):
            named_roles.append("load_path")
        if any(cue in folded and cue in label for cue in _INSTALL_CUES):
            named_roles.append("installation")
        if named_roles:
            decisions.append(ScreenedPart(
                solid.id, "retain", named_roles[0],
                "solid id matches a part named by the requirement",
                evidence=("requirement_text", "solid_id"),
                confidence=0.9,
            ))
        elif any(cue in label for cue in _FASTENER_CUES) and not any(cue in folded for cue in _FASTENER_CUES):
            decisions.append(ScreenedPart(
                solid.id, "exclude", "fastener",
                "fastener is outside the named analysis object",
                evidence=("solid_id",),
                confidence=0.9,
            ))
        else:
            decisions.append(ScreenedPart(
                solid.id, "pending", "unclassified",
                "solid identity is not uniquely tied to the requirement",
                evidence=("insufficient_identity",),
            ))
    source = "jev" if judgments else "requirement"
    return AnalysisScreen(text, tuple(decisions), source=source)


def build_assembly_scope(
    model: GeometryModel,
    *,
    friction_coefficient: float = 0.15,
    fixture_face_id: Optional[str] = None,
    allow_unverified_exterior_fixture: bool = False,
    requirement: Optional[Union[str, Mapping[str, object]]] = None,
    screen: Optional[AnalysisScreen] = None,
    judgments: Optional[Mapping[str, Mapping[str, object]]] = None,
    include_all_solids: bool = False,
) -> AssemblyScope:
    """Ground the solids retained for this requirement, then their contact and fixture.

    Contact is accepted only when two planar faces belong to different retained
    solids, their normals oppose, and the faces are within a small gap. The
    installation fixture still requires an explicit face or semantic ground.
    A missing or ambiguous screen is recorded as a gap; it never expands back
    to the full product inventory.
    """
    if friction_coefficient < 0.0:
        raise ValueError(f"friction_coefficient cannot be negative, got {friction_coefficient}")

    shells = {shell.id: shell for shell in model.shells}
    faces = {face.id: face for face in model.faces}
    vertices = {vertex.id: vertex.point for vertex in model.vertices}
    edges = {edge.id: (edge.start_vertex_id, edge.end_vertex_id) for edge in model.edges}

    active_screen = screen
    if active_screen is None and not include_all_solids and (
        requirement is not None or judgments is not None or len(model.solids) > 1
    ):
        active_screen = screen_assembly_requirement(model, requirement, judgments=judgments)
    if active_screen is not None and (active_screen.pending_ids or not active_screen.retained_ids):
        inventory: Sequence[CadSolid] = ()
    elif active_screen is None:
        inventory = model.solids
    else:
        retained_ids = set(active_screen.retained_ids)
        inventory = tuple(solid for solid in model.solids if solid.id in retained_ids)

    parts: List[AssemblyPart] = []
    face_owner: Dict[str, AssemblyPart] = {}
    # Keep STEP file order. Sorting by name would bind the wrong bodyNum.
    ordered_solids = tuple(sorted(
        inventory,
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
    if active_screen is not None:
        if not active_screen.requirement and all(
            "missing_requirement" in item.evidence for item in active_screen.decisions
        ):
            gaps.append("analysis_requirement_missing")
        elif active_screen.pending_ids:
            gaps.append("screening_pending:" + ",".join(active_screen.pending_ids))
        if not active_screen.retained_ids:
            gaps.append("screening_retained_nothing")
        unknown_retained = [item for item in active_screen.retained_ids if item not in {solid.id for solid in model.solids}]
        if unknown_retained:
            gaps.append("screening_unknown_solid:" + ",".join(unknown_retained))
    elif requirement is None and judgments is None and len(model.solids) > 1 and not include_all_solids:
        gaps.append("analysis_requirement_missing")
    if len(parts) >= 2 and any(part.step_body_index is None for part in parts):
        missing = [part.solid_id for part in parts if part.step_body_index is None]
        gaps.append("step_body_index_missing:" + ",".join(missing))
    if not parts:
        gaps.append("screening_retained_nothing")
    isolated = [part.solid_id for part in parts if not any(
        part.solid_id in (contact.master_part, contact.slave_part) for contact in contacts
    )]
    if isolated and len(parts) >= 2:
        gaps.append("parts_without_mating_contact:" + ",".join(isolated))
    if fixture is None and parts:
        gaps.append("installation_fixture_not_grounded")

    excluded = ()
    if active_screen is not None:
        excluded = active_screen.excluded_ids
    return AssemblyScope(
        parts=tuple(parts),
        contacts=tuple(contacts),
        fixture=fixture,
        gaps=tuple(dict.fromkeys(gaps)),
        source_model_id=model.model_id,
        screen=active_screen,
        excluded_solid_ids=excluded,
    )


def require_complete_assembly_scope(scope: AssemblyScope) -> AssemblyScope:
    """Refuse a scope whose retained parts, contact, or fixture are not grounded."""
    if not scope.is_complete:
        raise ValueError(
            "Incomplete assembly scope: the requirement screen must resolve, every retained "
            "solid must be mapped, mating contact is required when more than one solid is retained, "
            f"and one installation fixture is required. gaps={list(scope.gaps)}"
        )
    return scope
