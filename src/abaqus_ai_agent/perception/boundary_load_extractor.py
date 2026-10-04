"""P1.1 Boundary Condition & Mechanical Load Extractor.

Specialized extractor for:
- Concentrated forces and traction arrows (e.g. F = 5000 N, downward arrow)
- Pressure and distributed load symbols (e.g. p = 2.5 MPa)
- Support conditions (Fixed, Pinned, Roller, Encastre)
- Symmetry boundary condition planes (Symmetry X, Y, Z)

Architectural Invariants (P1.1 Interface Freeze):
- No Silent Repair: Coordinates < 0 or > 1 are strictly rejected (COORDINATE_OUT_OF_BOUNDS).
- Zero Direction Vectors are strictly rejected (ZERO_DIRECTION_VECTOR); never invent default.
- Outputs canonical VisualCallout(callout_type=ARROW or SYMBOL).
- Never constructs direct solver actions or Abaqus scripts.
"""

import math
import re
from typing import List, Optional, Sequence, Tuple

from ..contracts.geometry import ImagePoint, ImageRegion
from ..contracts.multimodal import CalloutType, VisualCallout
from .contracts import (
    ObservationProvenance,
    RawSymbolObservation,
    RawTextObservation,
    RejectedObservation,
)


class BoundaryLoadExtractor:
    """Extracts standardized VisualCallout objects for boundary conditions and mechanical loads."""

    def __init__(self, prefix: str = "load"):
        self.prefix = prefix
        self._load_regex = re.compile(
            r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([a-zA-Z*^/]+)?"
        )

    def extract(
        self,
        symbols: Sequence[RawSymbolObservation],
        text_blocks: Sequence[RawTextObservation] = (),
    ) -> Tuple[Tuple[VisualCallout, ...], Tuple[RejectedObservation, ...]]:
        """Process raw symbol observations and text cues into canonical VisualCallout items."""
        valid_callouts: List[VisualCallout] = []
        rejected: List[RejectedObservation] = []

        callout_idx = 0

        # 1. Process explicit RawSymbolObservation instances
        processed_texts = set()
        for obs in symbols:
            if obs.text_content:
                processed_texts.add(obs.text_content.strip())
            x, y = obs.location
            # Fail-closed coordinate validation
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                rejected.append(
                    RejectedObservation(
                        raw_observation=obs,
                        reason="COORDINATE_OUT_OF_BOUNDS",
                        detail=f"Symbol location ({x}, {y}) out of normalized [0, 1] range; clamping forbidden",
                        provenance=obs.provenance,
                    )
                )
                continue

            # Direction vector validation
            norm_direction = None
            if obs.direction is not None:
                dx, dy = obs.direction
                length = math.hypot(dx, dy)
                if length == 0.0 or (dx == 0.0 and dy == 0.0):
                    rejected.append(
                        RejectedObservation(
                            raw_observation=obs,
                            reason="ZERO_DIRECTION_VECTOR",
                            detail="Symbol direction vector has zero length; inventing direction is forbidden",
                            provenance=obs.provenance,
                        )
                    )
                    continue
                norm_direction = (dx / length, dy / length)

            # Determine semantic intent
            semantic, default_type = self._map_symbol_type(obs.symbol_type, obs.text_content)
            if semantic == "UNKNOWN_SYMBOL":
                rejected.append(
                    RejectedObservation(
                        raw_observation=obs,
                        reason="UNKNOWN_SYMBOL_TYPE",
                        detail=f"Unrecognized symbol type '{obs.symbol_type}' cannot be converted to engineering intent; guessing as force is forbidden",
                        provenance=obs.provenance,
                    )
                )
                continue

            callout_type = (
                CalloutType.ARROW.value if norm_direction is not None else default_type
            )

            # Parse magnitude and unit if text content is available
            magnitude = None
            unit = None
            if obs.text_content:
                parsed_mag, parsed_unit = self._parse_magnitude_unit(obs.text_content)
                magnitude = parsed_mag
                unit = parsed_unit

            cid = f"{self.prefix}_{callout_idx}"
            callout_idx += 1

            meta = {
                "confidence": obs.confidence,
                "raw_symbol_type": obs.symbol_type,
            }
            if norm_direction is None and semantic == "CONCENTRATED_FORCE":
                meta["direction_status"] = "UNKNOWN"
            if obs.provenance:
                meta["provenance"] = obs.provenance

            valid_callouts.append(
                VisualCallout(
                    callout_id=cid,
                    callout_type=callout_type,
                    location=ImagePoint(x, y),
                    direction_vector=norm_direction,
                    region_box=None,
                    text_content=obs.text_content,
                    semantic_intent=semantic,
                    magnitude=magnitude,
                    unit=unit,
                    metadata=meta,
                )
            )

        # 2. Extract load / support callouts from text blocks describing loads or boundary conditions
        for tb in text_blocks:
            if tb.text.strip() in processed_texts:
                continue
            lower = tb.text.lower()
            semantic = None
            direction_vec = None
            callout_type = CalloutType.SYMBOL.value

            # Symmetry cues
            if any(w in lower for w in ("symm", "symmetry", "对称")):
                if "x" in lower:
                    semantic = "SYMMETRY_X"
                elif "y" in lower:
                    semantic = "SYMMETRY_Y"
                elif "z" in lower:
                    semantic = "SYMMETRY_Z"
                else:
                    semantic = "SYMMETRY_PLANE"
            # Support cues: specific types first
            elif any(w in lower for w in ("roller", "滚支")):
                semantic = "ROLLER_SUPPORT"
            elif any(w in lower for w in ("pin", "pinned", "铰支", "简支")):
                semantic = "PINNED_SUPPORT"
            elif any(w in lower for w in ("fix", "encastre", "clamp", "fixed", "固定", "固支", "constraint", "support", "约束")):
                semantic = "FIXED_SUPPORT"
            # Load cues
            elif any(w in lower for w in ("pressure", "press", "压强", "压力")):
                semantic = "PRESSURE"
            elif any(
                w in lower
                for w in (
                    "force",
                    "load",
                    "traction",
                    "concentrated",
                    "集中力",
                    "载荷",
                    "拉力",
                    "推力",
                    "f =",
                    "f=",
                    "downward",
                    "upward",
                    "kn",
                )
            ):
                semantic = "CONCENTRATED_FORCE"
                if "downward" in lower or "down" in lower or "向下" in lower:
                    direction_vec = (0.0, -1.0)
                elif "upward" in lower or "up" in lower or "向上" in lower:
                    direction_vec = (0.0, 1.0)
                elif "rightward" in lower or "right" in lower or "向右" in lower:
                    direction_vec = (1.0, 0.0)
                elif "leftward" in lower or "left" in lower or "向左" in lower:
                    direction_vec = (-1.0, 0.0)
                else:
                    direction_vec = None
            elif any(w in lower for w in ("moment", "torque", "扭矩", "力矩")):
                semantic = "MOMENT"

            if not semantic:
                continue

            # Validate text box bounds
            ymin, xmin, ymax, xmax = tb.box
            if not (0.0 <= xmin <= 1.0 and 0.0 <= xmax <= 1.0 and 0.0 <= ymin <= 1.0 and 0.0 <= ymax <= 1.0):
                rejected.append(
                    RejectedObservation(
                        raw_observation=tb,
                        reason="COORDINATE_OUT_OF_BOUNDS",
                        detail=f"Load text box {tb.box} out of normalized [0, 1] range; clamping forbidden",
                        provenance=tb.provenance,
                    )
                )
                continue

            cx = (xmin + xmax) / 2.0
            cy = (ymin + ymax) / 2.0
            w = max(0.001, xmax - xmin)
            h = max(0.001, ymax - ymin)

            region_box = None
            if 0.0 < w <= 1.0 and 0.0 < h <= 1.0:
                region_box = ImageRegion(center=ImagePoint(cx, cy), width=w, height=h)

            magnitude, unit = self._parse_magnitude_unit(tb.text)

            cid = f"{self.prefix}_{callout_idx}"
            callout_idx += 1

            meta = {
                "confidence": tb.confidence,
                "is_vector": tb.is_vector,
            }
            if direction_vec is None and semantic == "CONCENTRATED_FORCE":
                meta["direction_status"] = "UNKNOWN"
            if tb.provenance:
                meta["provenance"] = tb.provenance

            valid_callouts.append(
                VisualCallout(
                    callout_id=cid,
                    callout_type=CalloutType.ARROW.value if direction_vec else callout_type,
                    location=ImagePoint(cx, cy),
                    direction_vector=direction_vec,
                    region_box=region_box,
                    text_content=tb.text,
                    semantic_intent=semantic,
                    magnitude=magnitude,
                    unit=unit,
                    metadata=meta,
                )
            )

        return (tuple(valid_callouts), tuple(rejected))

    def _map_symbol_type(self, raw_type: str, text: Optional[str]) -> Tuple[str, str]:
        """Maps symbol string and optional text to canonical semantic intent and CalloutType."""
        upper = raw_type.upper()
        if "FIX" in upper or "ENCASTRE" in upper:
            return ("FIXED_SUPPORT", CalloutType.SYMBOL.value)
        if "PIN" in upper:
            return ("PINNED_SUPPORT", CalloutType.SYMBOL.value)
        if "ROLLER" in upper:
            return ("ROLLER_SUPPORT", CalloutType.SYMBOL.value)
        if "SYMM" in upper:
            if "X" in upper:
                return ("SYMMETRY_X", CalloutType.SYMBOL.value)
            if "Y" in upper:
                return ("SYMMETRY_Y", CalloutType.SYMBOL.value)
            if "Z" in upper:
                return ("SYMMETRY_Z", CalloutType.SYMBOL.value)
            return ("SYMMETRY_PLANE", CalloutType.SYMBOL.value)
        if "PRESSURE" in upper:
            return ("PRESSURE", CalloutType.SYMBOL.value)
        if "MOMENT" in upper or "TORQUE" in upper:
            return ("MOMENT", CalloutType.SYMBOL.value)
        if "ARROW" in upper or "FORCE" in upper or "LOAD" in upper:
            return ("CONCENTRATED_FORCE", CalloutType.ARROW.value)

        # Fallback to checking text if available
        if text:
            lower = text.lower()
            if any(w in lower for w in ("fix", "固定")):
                return ("FIXED_SUPPORT", CalloutType.SYMBOL.value)
            if any(w in lower for w in ("pin", "铰支", "简支")):
                return ("PINNED_SUPPORT", CalloutType.SYMBOL.value)
            if any(w in lower for w in ("roller", "滚支")):
                return ("ROLLER_SUPPORT", CalloutType.SYMBOL.value)
            if any(w in lower for w in ("moment", "torque", "扭矩", "力矩")):
                return ("MOMENT", CalloutType.SYMBOL.value)
            if any(w in lower for w in ("press", "压力", "压强")):
                return ("PRESSURE", CalloutType.SYMBOL.value)
            if any(w in lower for w in ("force", "load", "集中力", "载荷")):
                return ("CONCENTRATED_FORCE", CalloutType.ARROW.value)

        return ("UNKNOWN_SYMBOL", CalloutType.SYMBOL.value)

    def _parse_magnitude_unit(self, text: str) -> Tuple[Optional[float], Optional[str]]:
        """Parses numeric magnitude and engineering unit from text."""
        match = self._load_regex.search(text)
        if not match:
            return (None, None)

        try:
            magnitude = float(match.group(1))
            unit = match.group(2).strip() if match.group(2) else None
            return (magnitude, unit)
        except (ValueError, TypeError):
            return (None, None)
