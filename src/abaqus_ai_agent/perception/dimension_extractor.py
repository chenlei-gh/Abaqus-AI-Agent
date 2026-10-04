"""P1.1 Engineering Dimension & Tolerance Extractor.

Specialized extractor for:
- Linear, radial, and diametral dimensions (e.g. 50 mm, Ø20, R15)
- Bilateral and limit tolerances (e.g. 100 ± 0.1 mm, +0.05 / -0.02)
- Geometric datum and leader line annotations

Architectural Invariants (P1.1 Interface Freeze):
- Decoupled from load/boundary condition interpretation.
- No Silent Clamping: Out-of-bounds coordinates (<0.0 or >1.0) are strictly rejected.
- Direct output of canonical VisualCallout(callout_type=DIMENSION).
- region_box must be ImageRegion, never a four-value tuple.
"""

import re
from typing import List, Optional, Sequence, Tuple

from ..contracts.geometry import ImagePoint, ImageRegion
from ..contracts.multimodal import CalloutType, VisualCallout
from .contracts import (
    ObservationProvenance,
    RawDimensionObservation,
    RawTextObservation,
    RejectedObservation,
)


class DimensionExtractor:
    """Extracts standardized VisualCallout objects for engineering dimensions and tolerances."""

    def __init__(self, prefix: str = "dim"):
        self.prefix = prefix
        self._dim_regex = re.compile(
            r"([ØRΦ])?\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*(?:±\s*([0-9]*\.?[0-9]+))?\s*([a-zA-Z]+)?"
        )

    def extract(
        self,
        dimensions: Sequence[RawDimensionObservation],
        text_blocks: Sequence[RawTextObservation] = (),
    ) -> Tuple[Tuple[VisualCallout, ...], Tuple[RejectedObservation, ...]]:
        """Process raw dimension observations and text blocks into canonical VisualCallout items."""
        valid_callouts: List[VisualCallout] = []
        rejected: List[RejectedObservation] = []

        callout_idx = 0

        # 1. Process explicit RawDimensionObservation instances
        for obs in dimensions:
            x, y = obs.location
            # Fail-closed check: coordinates must be strictly within [0.0, 1.0]
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                rejected.append(
                    RejectedObservation(
                        raw_observation=obs,
                        reason="COORDINATE_OUT_OF_BOUNDS",
                        detail=f"Dimension location ({x}, {y}) out of normalized [0, 1] range; clamping forbidden",
                        provenance=obs.provenance,
                    )
                )
                continue

            # Validate span coordinates if provided
            if obs.span_start:
                sx, sy = obs.span_start
                if not (0.0 <= sx <= 1.0 and 0.0 <= sy <= 1.0):
                    rejected.append(
                        RejectedObservation(
                            raw_observation=obs,
                            reason="COORDINATE_OUT_OF_BOUNDS",
                            detail=f"Dimension span_start ({sx}, {sy}) out of normalized [0, 1] range",
                            provenance=obs.provenance,
                        )
                    )
                    continue
            if obs.span_end:
                ex, ey = obs.span_end
                if not (0.0 <= ex <= 1.0 and 0.0 <= ey <= 1.0):
                    rejected.append(
                        RejectedObservation(
                            raw_observation=obs,
                            reason="COORDINATE_OUT_OF_BOUNDS",
                            detail=f"Dimension span_end ({ex}, {ey}) out of normalized [0, 1] range",
                            provenance=obs.provenance,
                        )
                    )
                    continue

            # Parse or normalize semantic intent
            semantic = "DIMENSION"
            upper_text = obs.text.upper()
            if "Ø" in obs.text or "Φ" in obs.text or "DIA" in upper_text:
                semantic = "DIAMETER"
            elif "R" in obs.text or "RAD" in upper_text:
                semantic = "RADIUS"

            nominal = obs.nominal_value
            unit = obs.unit
            tol_upper = obs.tolerance_upper
            tol_lower = obs.tolerance_lower

            if nominal is None and obs.text:
                parsed_nom, parsed_u, parsed_tu, parsed_tl = self._parse_text_dimension(obs.text)
                nominal = parsed_nom
                unit = unit or parsed_u
                tol_upper = tol_upper or parsed_tu
                tol_lower = tol_lower or parsed_tl

            region_box = None
            if obs.span_start and obs.span_end:
                sx, sy = obs.span_start
                ex, ey = obs.span_end
                w = max(0.005, abs(ex - sx))
                h = max(0.005, abs(ey - sy))
                if 0.0 < w <= 1.0 and 0.0 < h <= 1.0:
                    cx = (sx + ex) / 2.0
                    cy = (sy + ey) / 2.0
                    if 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0:
                        region_box = ImageRegion(center=ImagePoint(cx, cy), width=w, height=h)

            cid = f"{self.prefix}_{callout_idx}"
            callout_idx += 1

            meta = {
                "tolerance_upper": tol_upper,
                "tolerance_lower": tol_lower,
                "confidence": obs.confidence,
            }
            if obs.provenance:
                meta["provenance"] = obs.provenance

            valid_callouts.append(
                VisualCallout(
                    callout_id=cid,
                    callout_type=CalloutType.DIMENSION.value,
                    location=ImagePoint(x, y),
                    direction_vector=None,
                    region_box=region_box,
                    text_content=obs.text,
                    semantic_intent=semantic,
                    magnitude=nominal,
                    unit=unit,
                    metadata=meta,
                )
            )

        # Skip if text looks like load or boundary condition
        # 2. Extract dimensions from general text blocks matching dimension patterns
        for tb in text_blocks:
            lower = tb.text.lower()
            if any(
                w in lower
                for w in (
                    "fix",
                    "pin",
                    "load",
                    "force",
                    "moment",
                    "press",
                    "symm",
                    "f =",
                    "f=",
                    "p =",
                    "p=",
                    "material",
                    "mat:",
                    "mat.",
                    "steel",
                    "aluminum",
                    "alloy",
                    "grade",
                    "q235",
                    "title",
                    "scale",
                    "sheet",
                    "rev",
                    "dwg",
                )
            ):
                continue

            parsed_nom, parsed_u, parsed_tu, parsed_tl = self._parse_text_dimension(tb.text)
            if parsed_nom is None:
                continue

            # Check bounds of text block
            ymin, xmin, ymax, xmax = tb.box
            if not (0.0 <= xmin <= 1.0 and 0.0 <= xmax <= 1.0 and 0.0 <= ymin <= 1.0 and 0.0 <= ymax <= 1.0):
                rejected.append(
                    RejectedObservation(
                        raw_observation=tb,
                        reason="COORDINATE_OUT_OF_BOUNDS",
                        detail=f"Text block box {tb.box} out of normalized [0, 1] range; clamping forbidden",
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

            semantic = "DIMENSION"
            if "Ø" in tb.text or "Φ" in tb.text or "DIA" in tb.text.upper():
                semantic = "DIAMETER"
            elif "R" in tb.text or "RAD" in tb.text.upper():
                semantic = "RADIUS"

            cid = f"{self.prefix}_{callout_idx}"
            callout_idx += 1

            meta = {
                "tolerance_upper": parsed_tu,
                "tolerance_lower": parsed_tl,
                "confidence": tb.confidence,
                "is_vector": tb.is_vector,
            }
            if tb.provenance:
                meta["provenance"] = tb.provenance

            valid_callouts.append(
                VisualCallout(
                    callout_id=cid,
                    callout_type=CalloutType.DIMENSION.value,
                    location=ImagePoint(cx, cy),
                    direction_vector=None,
                    region_box=region_box,
                    text_content=tb.text,
                    semantic_intent=semantic,
                    magnitude=parsed_nom,
                    unit=parsed_u,
                    metadata=meta,
                )
            )

        return (tuple(valid_callouts), tuple(rejected))

    def _parse_text_dimension(
        self, text: str
    ) -> Tuple[Optional[float], Optional[str], Optional[float], Optional[float]]:
        """Parses nominal magnitude, unit, and tolerances from a dimension string."""
        match = self._dim_regex.search(text)
        if not match:
            return (None, None, None, None)

        nominal = None
        unit = None
        tol_upper = None
        tol_lower = None

        try:
            if match.group(4):
                unit_str = match.group(4).strip()
                # If unit is explicitly a force/pressure unit, reject as dimension
                if unit_str.lower() in ("n", "kn", "mn", "mpa", "pa", "kpa", "gpa", "bar", "psi", "nm"):
                    return (None, None, None, None)
                unit = unit_str

            nominal = float(match.group(2))
            if match.group(3):
                tol = float(match.group(3))
                tol_upper = tol
                tol_lower = -tol
        except (ValueError, TypeError):
            return (None, None, None, None)

        return (nominal, unit, tol_upper, tol_lower)
