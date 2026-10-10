"""P1.2 Intent Reasoning, Engineering Plausibility & Tiered HITL Engine."""

from .engine import IntentReasoningEngine
from .material_catalog import (
    STANDARD_MATERIALS,
    StandardMaterialProfile,
    match_engineering_material,
    resolve_material_to_definition,
)
from .mesh_inference import infer_mesh_specification
from .plausibility import audit_engineering_plausibility

__all__ = [
    "IntentReasoningEngine",
    "STANDARD_MATERIALS",
    "StandardMaterialProfile",
    "match_engineering_material",
    "resolve_material_to_definition",
    "infer_mesh_specification",
    "audit_engineering_plausibility",
]
