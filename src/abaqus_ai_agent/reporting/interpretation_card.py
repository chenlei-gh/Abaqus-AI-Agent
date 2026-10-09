"""Interpretation Card Contracts for the LLM Plane (P0-5).

Strict Engineering Rules:
1. LLMs NEVER generate complete report documents (Markdown/HTML/PDF).
2. LLMs only provide bounded semantic interpretations, observations, and recommendations.
3. LLMs CANNOT alter physical numerical metrics, gate statuses, or acceptance verdicts.
4. The output is bounded by strict character/item limits to prevent context bloat.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List, Optional, Tuple


class InterpretationCardError(ValueError):
    """Raised when an interpretation card violates length or integrity constraints."""
    pass


@dataclass(frozen=True)
class InterpretationCard:
    """Bounded semantic interpretation supplied by the LLM Plane."""
    interpretation_zh: str = ""
    interpretation_en: str = ""
    engineering_observations: Tuple[str, ...] = field(default_factory=tuple)
    risk_notes: Tuple[str, ...] = field(default_factory=tuple)
    recommendations: Tuple[str, ...] = field(default_factory=tuple)

    # Hard guardrail bounds
    MAX_TEXT_LEN: int = 500
    MAX_ITEMS: int = 4
    MAX_ITEM_LEN: int = 150

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Enforce strict bounding constraints."""
        if len(self.interpretation_zh) > self.MAX_TEXT_LEN:
            raise InterpretationCardError(
                f"interpretation_zh exceeds max length {self.MAX_TEXT_LEN} (got {len(self.interpretation_zh)})"
            )
        if len(self.interpretation_en) > self.MAX_TEXT_LEN:
            raise InterpretationCardError(
                f"interpretation_en exceeds max length {self.MAX_TEXT_LEN} (got {len(self.interpretation_en)})"
            )
        if len(self.engineering_observations) > self.MAX_ITEMS:
            raise InterpretationCardError(
                f"engineering_observations exceeds max items {self.MAX_ITEMS} (got {len(self.engineering_observations)})"
            )
        for obs in self.engineering_observations:
            if len(obs) > self.MAX_ITEM_LEN:
                raise InterpretationCardError(f"Observation exceeds max length {self.MAX_ITEM_LEN}: {obs[:30]}...")

        if len(self.risk_notes) > self.MAX_ITEMS:
            raise InterpretationCardError(
                f"risk_notes exceeds max items {self.MAX_ITEMS} (got {len(self.risk_notes)})"
            )
        if len(self.recommendations) > self.MAX_ITEMS:
            raise InterpretationCardError(
                f"recommendations exceeds max items {self.MAX_ITEMS} (got {len(self.recommendations)})"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interpretation_zh": self.interpretation_zh,
            "interpretation_en": self.interpretation_en,
            "engineering_observations": list(self.engineering_observations),
            "risk_notes": list(self.risk_notes),
            "recommendations": list(self.recommendations),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterpretationCard:
        return cls(
            interpretation_zh=data.get("interpretation_zh", ""),
            interpretation_en=data.get("interpretation_en", ""),
            engineering_observations=tuple(data.get("engineering_observations", ())),
            risk_notes=tuple(data.get("risk_notes", ())),
            recommendations=tuple(data.get("recommendations", ())),
        )


@dataclass(frozen=True)
class ReportDeliveryCard:
    """Ultra-lean delivery card returned from Data Plane to LLM Plane."""
    report_artifact_id: str
    report_title: str
    format: str                          # e.g., "bilingual_html", "markdown"
    location: str                        # File storage path in Data Plane
    acceptance_status: str               # Authoritative "PASS" or "FAIL"
    key_metrics: Dict[str, Any]          # Deterministic numbers (max_mises, max_u)
    active_sections: Tuple[str, ...]     # Dynamic sections included in this deliverable
    figures_count: int
    size_bytes: int
    checksum_sha256: str
    deliverable: bool = True

    def to_llm_card(self) -> Dict[str, Any]:
        return {
            "report_artifact_id": self.report_artifact_id,
            "report_title": self.report_title,
            "format": self.format,
            "location": self.location,
            "acceptance_status": self.acceptance_status,
            "deliverable": self.deliverable,
            "key_metrics": self.key_metrics,
            "active_sections": list(self.active_sections),
            "figures_count": self.figures_count,
            "size_bytes": self.size_bytes,
            "checksum_sha256": self.checksum_sha256,
        }

    def to_dict(self) -> Dict[str, Any]:
        return self.to_llm_card()
