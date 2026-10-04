"""P1.1 Provider-Neutral Vision & Perception Provider Abstraction.

Defines:
- BaseVisionProvider: Abstract base class decoupling downstream perception from
  specific OCR/Vision models or external API vendors.
- MockVisionProvider: Deterministic offline provider for CI and hermetic testing.
- RuleBasedVisionProvider: Deterministic text/vector parser utilizing regex patterns.

Architectural Invariant:
- Providers emit raw observations with provenance and confidence.
- Providers MUST NEVER emit Abaqus Python, Abaqus region expressions, or engineering claims.
"""

from abc import ABC, abstractmethod
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .contracts import (
    ObservationProvenance,
    RawDimensionObservation,
    RawSymbolObservation,
    RawTextObservation,
)


class BaseVisionProvider(ABC):
    """Abstract provider-neutral vision and OCR interface."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier."""
        ...

    @abstractmethod
    def extract_text_blocks(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawTextObservation]:
        """Extract textual content and normalized bounding boxes from a page."""
        ...

    @abstractmethod
    def detect_symbols(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawSymbolObservation]:
        """Detect mechanical symbols, load arrows, and boundary condition markers."""
        ...

    @abstractmethod
    def detect_dimensions(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawDimensionObservation]:
        """Detect dimension annotations, tolerance callouts, and leader lines."""
        ...


class MockVisionProvider(BaseVisionProvider):
    """Deterministic, offline mock vision provider for testing and CI validation."""

    def __init__(
        self,
        text_blocks: Optional[Sequence[RawTextObservation]] = None,
        symbols: Optional[Sequence[RawSymbolObservation]] = None,
        dimensions: Optional[Sequence[RawDimensionObservation]] = None,
        provider_id: str = "mock_vision_provider",
    ):
        self._provider_id = provider_id
        self._text_blocks = tuple(text_blocks or ())
        self._symbols = tuple(symbols or ())
        self._dimensions = tuple(dimensions or ())

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def set_fixtures(
        self,
        text_blocks: Optional[Sequence[RawTextObservation]] = None,
        symbols: Optional[Sequence[RawSymbolObservation]] = None,
        dimensions: Optional[Sequence[RawDimensionObservation]] = None,
    ) -> None:
        """Configure mock fixtures dynamically."""
        if text_blocks is not None:
            self._text_blocks = tuple(text_blocks)
        if symbols is not None:
            self._symbols = tuple(symbols)
        if dimensions is not None:
            self._dimensions = tuple(dimensions)

    def extract_text_blocks(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawTextObservation]:
        if self._text_blocks:
            return self._text_blocks
        # Fallback: check if page_data has vector text elements
        vector_elems = getattr(page_data, "vector_text_elements", None)
        if vector_elems:
            results = []
            for elem in vector_elems:
                text = elem.get("text", "")
                box = elem.get("box", (0.0, 0.0, 0.0, 0.0))
                conf = float(elem.get("confidence", 1.0))
                results.append(
                    RawTextObservation(
                        text=text,
                        box=box,
                        confidence=conf,
                        is_vector=True,
                        provenance=provenance,
                    )
                )
            return tuple(results)
        return ()

    def detect_symbols(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawSymbolObservation]:
        return self._symbols

    def detect_dimensions(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawDimensionObservation]:
        return self._dimensions


class RuleBasedVisionProvider(BaseVisionProvider):
    """Deterministic rule-based extractor using regular expressions on text elements."""

    def __init__(self, provider_id: str = "rule_based_vision_provider"):
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def extract_text_blocks(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawTextObservation]:
        vector_elems = getattr(page_data, "vector_text_elements", ())
        results = []
        for elem in vector_elems:
            results.append(
                RawTextObservation(
                    text=elem.get("text", ""),
                    box=elem.get("box", (0.0, 0.0, 0.0, 0.0)),
                    confidence=float(elem.get("confidence", 1.0)),
                    is_vector=True,
                    provenance=provenance,
                )
            )
        return tuple(results)

    def detect_symbols(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawSymbolObservation]:
        # Detect load / boundary symbols from text patterns in vector elements
        text_blocks = self.extract_text_blocks(page_data, provenance)
        symbols = []
        for tb in text_blocks:
            lower = tb.text.lower()
            sym_type = None
            direction = None

            if any(w in lower for w in ("fix", "encastre", "clamp", "fixed", "固定", "固支")):
                sym_type = "FIXED"
            elif any(w in lower for w in ("pin", "pinned", "铰支", "简支")):
                sym_type = "PINNED"
            elif any(w in lower for w in ("pressure", "压强", "压力")):
                sym_type = "PRESSURE"
                direction = (0.0, -1.0)
            elif any(w in lower for w in ("force", "load", "集中力", "载荷", "拉力", "推力")):
                sym_type = "ARROW"
                direction = (0.0, -1.0)  # Downward default in 2D drawing unless specified
            elif any(w in lower for w in ("symm", "symmetry", "对称")):
                if "x" in lower:
                    sym_type = "SYMMETRY_X"
                elif "y" in lower:
                    sym_type = "SYMMETRY_Y"
                elif "z" in lower:
                    sym_type = "SYMMETRY_Z"
                else:
                    sym_type = "SYMMETRY_PLANE"

            if sym_type:
                symbols.append(
                    RawSymbolObservation(
                        symbol_type=sym_type,
                        location=tb.center,
                        direction=direction,
                        confidence=tb.confidence,
                        text_content=tb.text,
                        provenance=provenance,
                    )
                )
        return tuple(symbols)

    def detect_dimensions(
        self,
        page_data: Any,
        provenance: ObservationProvenance,
    ) -> Sequence[RawDimensionObservation]:
        # Detect dimensions like "100 mm", "Ø50", "R10 ± 0.05"
        text_blocks = self.extract_text_blocks(page_data, provenance)
        dims = []
        dim_pattern = re.compile(
            r"(?:[ØRΦ]\s*)?([-+]?[0-9]*\.?[0-9]+)\s*(?:±\s*([0-9]*\.?[0-9]+))?\s*([a-zA-Z]+)?"
        )
        for tb in text_blocks:
            match = dim_pattern.search(tb.text)
            if match and any(c.isdigit() for c in tb.text):
                # Avoid matching pure load text like "1000 N" as dimension
                unit = match.group(3) or "mm"
                if unit.lower() in ("n", "kn", "mpa", "pa", "bar", "psi", "nm"):
                    continue
                try:
                    nominal = float(match.group(1))
                    tol = float(match.group(2)) if match.group(2) else None
                    dims.append(
                        RawDimensionObservation(
                            text=tb.text,
                            location=tb.center,
                            nominal_value=nominal,
                            tolerance_upper=tol,
                            tolerance_lower=(-tol if tol is not None else None),
                            unit=unit,
                            confidence=tb.confidence,
                            provenance=provenance,
                        )
                    )
                except (ValueError, TypeError):
                    pass
        return tuple(dims)
