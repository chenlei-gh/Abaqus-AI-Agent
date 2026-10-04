"""P1.1 Engineering Drawing Benchmark & Ground Truth Contracts.

Provides immutable schema definitions for:
- DrawingDimensionTruth: Dimensional measurements and tolerances.
- DrawingBoundaryTruth: Support conditions (Fixed, Pin, Roller, Symmetry).
- DrawingLoadTruth: Mechanical loads (Concentrated force, Pressure, Moment).
- DrawingMaterialTruth: Material designation and elastic constants.
- DrawingVerificationTarget: Physics acceptance targets (Reaction force, Mises stress).
- DrawingGroundTruth: Master ground truth contract for an engineering blueprint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class DrawingDimensionTruth:
    """Ground truth for a dimensional measurement or callout."""
    dimension_id: str
    nominal_value: float
    unit: str
    tolerance_upper: Optional[float] = None
    tolerance_lower: Optional[float] = None
    text: str = ""
    feature_name: str = ""
    box: Optional[Tuple[float, float, float, float]] = None  # (ymin, xmin, ymax, xmax) in [0, 1]


@dataclass(frozen=True)
class DrawingBoundaryTruth:
    """Ground truth for a boundary condition constraint."""
    boundary_id: str
    bc_type: str  # FIXED_SUPPORT, ROLLER_SUPPORT, PINNED_SUPPORT, SYMMETRY
    target_region: str
    location: Tuple[float, float]  # Normalized (x, y)
    text: str = ""


@dataclass(frozen=True)
class DrawingLoadTruth:
    """Ground truth for a mechanical load application."""
    load_id: str
    load_type: str  # CONCENTRATED_FORCE, PRESSURE, MOMENT
    magnitude: float
    unit: str
    direction_vector: Optional[Tuple[float, float]] = None  # (dx, dy)
    target_region: str = ""
    location: Tuple[float, float] = (0.5, 0.5)
    text: str = ""


@dataclass(frozen=True)
class DrawingMaterialTruth:
    """Ground truth for material properties specification."""
    material_name: str
    elastic_modulus: float  # In MPa (SI_MM convention)
    poisson_ratio: float
    yield_strength: Optional[float] = None
    density: Optional[float] = None


@dataclass(frozen=True)
class DrawingVerificationTarget:
    """Ground truth physical simulation targets for real Abaqus verification."""
    expected_reaction_y: float  # Expected reaction force along Y (N)
    reaction_tolerance_ratio: float = 0.001  # Max allowed equilibrium error (0.1%)
    max_mises_min_mpa: float = 1.0  # Plausible lower bound
    max_mises_max_mpa: float = 500.0  # Plausible upper bound
    max_deflection_mm: float = 5.0


@dataclass(frozen=True)
class DrawingGroundTruth:
    """Master benchmark ground truth for an engineering blueprint or CAD drawing."""
    drawing_id: str
    tier: str  # tier1_vector_pdf, tier2_scan_pdf, tier3_screenshot
    file_path: str
    title: str
    unit_system: str  # e.g. SI_MM, SI_M
    material: DrawingMaterialTruth
    dimensions: Tuple[DrawingDimensionTruth, ...]
    boundary_conditions: Tuple[DrawingBoundaryTruth, ...]
    loads: Tuple[DrawingLoadTruth, ...]
    verification: Optional[DrawingVerificationTarget] = None
    notes: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DrawingGroundTruth:
        """Instantiate strongly-typed contract from dictionary."""
        mat_data = data.get("material", {})
        mat = DrawingMaterialTruth(
            material_name=mat_data.get("material_name", "Steel"),
            elastic_modulus=float(mat_data.get("elastic_modulus", 210000.0)),
            poisson_ratio=float(mat_data.get("poisson_ratio", 0.3)),
            yield_strength=float(mat_data["yield_strength"]) if "yield_strength" in mat_data and mat_data["yield_strength"] is not None else None,
            density=float(mat_data["density"]) if "density" in mat_data and mat_data["density"] is not None else None,
        )

        dims = []
        for d in data.get("dimensions", []):
            dims.append(
                DrawingDimensionTruth(
                    dimension_id=d["dimension_id"],
                    nominal_value=float(d["nominal_value"]),
                    unit=d["unit"],
                    tolerance_upper=float(d["tolerance_upper"]) if d.get("tolerance_upper") is not None else None,
                    tolerance_lower=float(d["tolerance_lower"]) if d.get("tolerance_lower") is not None else None,
                    text=d.get("text", ""),
                    feature_name=d.get("feature_name", ""),
                    box=tuple(d["box"]) if "box" in d and d["box"] is not None else None,
                )
            )

        bcs = []
        for b in data.get("boundary_conditions", []):
            bcs.append(
                DrawingBoundaryTruth(
                    boundary_id=b["boundary_id"],
                    bc_type=b["bc_type"],
                    target_region=b["target_region"],
                    location=tuple(b.get("location", (0.5, 0.5))),
                    text=b.get("text", ""),
                )
            )

        loads = []
        for l in data.get("loads", []):
            loads.append(
                DrawingLoadTruth(
                    load_id=l["load_id"],
                    load_type=l["load_type"],
                    magnitude=float(l["magnitude"]),
                    unit=l["unit"],
                    direction_vector=tuple(l["direction_vector"]) if l.get("direction_vector") is not None else None,
                    target_region=l.get("target_region", ""),
                    location=tuple(l.get("location", (0.5, 0.5))),
                    text=l.get("text", ""),
                )
            )

        verif = None
        if "verification" in data and data["verification"]:
            v = data["verification"]
            verif = DrawingVerificationTarget(
                expected_reaction_y=float(v["expected_reaction_y"]),
                reaction_tolerance_ratio=float(v.get("reaction_tolerance_ratio", 0.001)),
                max_mises_min_mpa=float(v.get("max_mises_min_mpa", 1.0)),
                max_mises_max_mpa=float(v.get("max_mises_max_mpa", 500.0)),
                max_deflection_mm=float(v.get("max_deflection_mm", 5.0)),
            )

        return cls(
            drawing_id=data["drawing_id"],
            tier=data["tier"],
            file_path=data["file_path"],
            title=data.get("title", ""),
            unit_system=data.get("unit_system", "SI_MM"),
            material=mat,
            dimensions=tuple(dims),
            boundary_conditions=tuple(bcs),
            loads=tuple(loads),
            verification=verif,
            notes=tuple(data.get("notes", ())),
            metadata=data.get("metadata", {}),
        )

    def save_json(self, path: Path) -> None:
        """Write ground truth to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, path: Path) -> DrawingGroundTruth:
        """Load ground truth from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
