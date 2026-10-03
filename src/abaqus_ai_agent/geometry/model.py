"""Standardized CAD Geometry Model contracts for Track GA-1.1.

Provides immutable, strongly-typed geometric and topological data structures
for neutral CAD models (STEP/IGES) with complete cryptographic provenance.
Zero duplicate CAD kernel rule: this module acts as a canonical intermediate
representation and data exchange contract; all simulation actions ultimately
compile to native Abaqus CAE/Python directives.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple
import math


class CadFormat(str, Enum):
    """Supported neutral CAD exchange formats."""
    STEP = "STEP"
    IGES = "IGES"
    UNKNOWN = "UNKNOWN"


class CadUnit(str, Enum):
    """Linear unit system declared or inferred in the CAD source."""
    MM = "mm"
    M = "m"
    IN = "in"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CadBoundingBox:
    """Axis-aligned bounding box of geometric entities."""
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def __post_init__(self):
        if self.min_x > self.max_x or self.min_y > self.max_y or self.min_z > self.max_z:
            raise ValueError(
                f"invalid bounding box: min ({self.min_x}, {self.min_y}, {self.min_z}) > "
                f"max ({self.max_x}, {self.max_y}, {self.max_z})"
            )

    @property
    def dimensions(self) -> Tuple[float, float, float]:
        """Length along (X, Y, Z) axes."""
        return (
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )

    @property
    def center(self) -> Tuple[float, float, float]:
        """Centroid of the bounding box."""
        return (
            (self.min_x + self.max_x) / 2.0,
            (self.min_y + self.max_y) / 2.0,
            (self.min_z + self.max_z) / 2.0,
        )

    @property
    def diagonal(self) -> float:
        """Space diagonal length."""
        dx, dy, dz = self.dimensions
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass(frozen=True)
class CadVertex:
    """Topological vertex anchoring edge boundaries."""
    id: str
    point: Tuple[float, float, float]

    def __post_init__(self):
        if not self.id:
            raise ValueError("CadVertex id cannot be empty")
        if len(self.point) != 3:
            raise ValueError("CadVertex point must be a 3-element tuple (x, y, z)")


@dataclass(frozen=True)
class CadEdge:
    """Topological edge bounded by vertices."""
    id: str
    curve_type: str = "UNKNOWN"
    start_vertex_id: Optional[str] = None
    end_vertex_id: Optional[str] = None
    length: Optional[float] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("CadEdge id cannot be empty")
        if self.length is not None and self.length < 0:
            raise ValueError("CadEdge length cannot be negative")


@dataclass(frozen=True)
class CadLoop:
    """Closed loop of oriented edges defining a face outer or inner boundary."""
    id: str
    is_outer: bool = True
    edge_ids: Tuple[str, ...] = ()
    edge_orientations: Tuple[bool, ...] = ()

    def __post_init__(self):
        if not self.id:
            raise ValueError("CadLoop id cannot be empty")


@dataclass(frozen=True)
class CadFace:
    """Topological boundary face bounding shells and solids."""
    id: str
    surface_type: str = "UNKNOWN"
    edge_ids: Tuple[str, ...] = ()
    outer_loop: Optional[CadLoop] = None
    inner_loops: Tuple[CadLoop, ...] = ()
    orientation: bool = True
    area: Optional[float] = None
    normal: Optional[Tuple[float, float, float]] = None
    is_planar: bool = False

    def __post_init__(self):
        if not self.id:
            raise ValueError("CadFace id cannot be empty")
        if self.area is not None and self.area < 0:
            raise ValueError("CadFace area cannot be negative")
        if self.normal is not None and len(self.normal) != 3:
            raise ValueError("CadFace normal must be a 3-element vector")
        # Backwards compatibility: collect edge_ids from loops if not explicitly passed
        if not self.edge_ids and (self.outer_loop or self.inner_loops):
            collected = list(self.outer_loop.edge_ids) if self.outer_loop else []
            for iloop in self.inner_loops:
                collected.extend(iloop.edge_ids)
            object.__setattr__(self, "edge_ids", tuple(collected))


@dataclass(frozen=True)
class CadShell:
    """Connected collection of boundary faces."""
    id: str
    face_ids: Tuple[str, ...] = ()
    is_closed: bool = True

    def __post_init__(self):
        if not self.id:
            raise ValueError("CadShell id cannot be empty")


@dataclass(frozen=True)
class CadSolid:
    """3D volumetric entity bounded by closed shells."""
    id: str
    shell_ids: Tuple[str, ...] = ()
    volume: Optional[float] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("CadSolid id cannot be empty")
        if self.volume is not None and self.volume < 0:
            raise ValueError("CadSolid volume cannot be negative")


@dataclass(frozen=True)
class CadProvenance:
    """Cryptographic and semantic provenance of the ingested CAD model."""
    file_path: str
    file_name: str
    file_sha256: str
    file_size_bytes: int
    ingested_at: str
    cad_format: CadFormat
    cad_schema: Optional[str] = None
    preprocessor: Optional[str] = None
    author: Optional[str] = None
    organization: Optional[str] = None

    def __post_init__(self):
        if not self.file_sha256 or len(self.file_sha256) != 64:
            raise ValueError("valid SHA-256 hash (64 hex characters) required for CadProvenance")
        if self.file_size_bytes < 0:
            raise ValueError("file_size_bytes cannot be negative")


@dataclass(frozen=True)
class GeometryModel:
    """Standardized canonical CAD geometry representation for GA-1.1.

    Acts as the single source of truth for downstream geometry health
    inspection (GA-1.2), feature recognition (GA-1.3), and meshability
    assessment (GA-1.4).
    """
    model_id: str
    provenance: CadProvenance
    unit: CadUnit = CadUnit.MM
    bounding_box: Optional[CadBoundingBox] = None
    solids: Tuple[CadSolid, ...] = ()
    shells: Tuple[CadShell, ...] = ()
    faces: Tuple[CadFace, ...] = ()
    edges: Tuple[CadEdge, ...] = ()
    vertices: Tuple[CadVertex, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.model_id:
            raise ValueError("GeometryModel model_id cannot be empty")

    @property
    def solid_count(self) -> int:
        return len(self.solids)

    @property
    def shell_count(self) -> int:
        return len(self.shells)

    @property
    def face_count(self) -> int:
        return len(self.faces)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def is_empty(self) -> bool:
        """True if model contains zero topological primitives."""
        return (
            self.solid_count == 0
            and self.shell_count == 0
            and self.face_count == 0
            and self.edge_count == 0
            and self.vertex_count == 0
        )

    @property
    def has_open_shells(self) -> bool:
        """True if any shell in the model is marked unclosed/sheet."""
        return any(not shell.is_closed for shell in self.shells)

    @property
    def is_manifold_solid(self) -> bool:
        """True if model contains at least one solid and zero open shells."""
        if self.solid_count == 0:
            return False
        if self.has_open_shells:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize standardized geometry summary."""
        return {
            "model_id": self.model_id,
            "format": self.provenance.cad_format.value,
            "unit": self.unit.value,
            "sha256": self.provenance.file_sha256,
            "counts": {
                "solids": self.solid_count,
                "shells": self.shell_count,
                "faces": self.face_count,
                "edges": self.edge_count,
                "vertices": self.vertex_count,
            },
            "bounding_box": (
                {
                    "min": [self.bounding_box.min_x, self.bounding_box.min_y, self.bounding_box.min_z],
                    "max": [self.bounding_box.max_x, self.bounding_box.max_y, self.bounding_box.max_z],
                    "dimensions": list(self.bounding_box.dimensions),
                    "center": list(self.bounding_box.center),
                }
                if self.bounding_box
                else None
            ),
            "is_manifold_solid": self.is_manifold_solid,
            "has_open_shells": self.has_open_shells,
        }
