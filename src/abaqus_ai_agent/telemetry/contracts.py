"""Contracts for Context Telemetry and Token Profiling.

Strict engineering rules:
- Telemetry NEVER feeds back into LLM Context (Zero Context Pollution).
- Token counts distinguish between provider-reported, local tokenizer, and estimated counts.
- Telemetry observes, measures, and persists to Data Plane (runs/{run_id}/telemetry/).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TokenCountSource(str, Enum):
    """Authority tier of token accounting."""
    PROVIDER_USAGE = "provider_usage"        # Real provider usage reported by LLM API (Highest Trust)
    PROVIDER_REPORTED = "provider_reported"  # Backward compatibility alias
    TOKENIZER = "tokenizer"                  # Exact token count via local library (e.g. tiktoken)
    LOCAL_TOKENIZER = "local_tokenizer"      # Backward compatibility alias
    ESTIMATED = "estimated"                  # Heuristic character-ratio fallback (Explicitly labeled)
    SYNTHETIC_PROJECTION = "synthetic_projection"  # Model/simulation projection, not physical API traffic
    UNKNOWN = "unknown"


class EngineeringPhase(str, Enum):
    """Standard lifecycle phases of an engineering case."""
    INTENT = "intent"
    PLANNING = "planning"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    REPORTING = "reporting"
    OTHER = "other"


@dataclass(frozen=True)
class TokenComponentMetric:
    """Individual component token count with explicit source provenance."""
    value: int
    source: str = "estimated"  # "provider_usage", "tokenizer", "estimated", "synthetic_projection", "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "source": self.source}


@dataclass(frozen=True)
class TokenBreakdown:
    """Component-level token breakdown for a single interaction."""
    system_tokens: int = 0
    tool_schema_tokens: int = 0
    conversation_tokens: int = 0
    tool_output_tokens: int = 0
    user_input_tokens: int = 0
    output_tokens: int = 0
    source: TokenCountSource = TokenCountSource.ESTIMATED
    # Physical separation of Data Plane renderer & artifacts
    deterministic_renderer_bytes: int = 0
    data_plane_artifact_bytes: int = 0

    @property
    def input_tokens(self) -> int:
        return (
            self.system_tokens
            + self.tool_schema_tokens
            + self.conversation_tokens
            + self.tool_output_tokens
            + self.user_input_tokens
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def is_estimated(self) -> bool:
        return self.source in (
            TokenCountSource.ESTIMATED,
            TokenCountSource.SYNTHETIC_PROJECTION,
            TokenCountSource.UNKNOWN,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["input_tokens"] = self.input_tokens
        d["total_tokens"] = self.total_tokens
        d["is_estimated"] = self.is_estimated
        d["deterministic_renderer_bytes"] = self.deterministic_renderer_bytes
        d["data_plane_artifact_bytes"] = self.data_plane_artifact_bytes
        return d


@dataclass(frozen=True)
class ArtifactContextMetrics:
    """Statistics about artifacts referenced or blocked in context."""
    pointers_count: int = 0
    pointers_size_bytes: int = 0
    raw_artifacts_blocked_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CallTelemetry:
    """Telemetry record for a single model call."""
    call_id: str
    run_id: str
    case_id: str
    phase: EngineeringPhase
    timestamp: str
    breakdown: TokenBreakdown
    artifacts: ArtifactContextMetrics = field(default_factory=ArtifactContextMetrics)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "phase": self.phase.value,
            "timestamp": self.timestamp,
            "breakdown": self.breakdown.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "metadata": self.metadata,
        }


@dataclass
class PhaseSummary:
    """Aggregated token consumption for an engineering phase."""
    phase: str
    calls_count: int = 0
    system_tokens: int = 0
    tool_schema_tokens: int = 0
    conversation_tokens: int = 0
    tool_output_tokens: int = 0
    user_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def input_tokens(self) -> int:
        return (
            self.system_tokens
            + self.tool_schema_tokens
            + self.conversation_tokens
            + self.tool_output_tokens
            + self.user_input_tokens
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "calls_count": self.calls_count,
            "system_tokens": self.system_tokens,
            "tool_schema_tokens": self.tool_schema_tokens,
            "conversation_tokens": self.conversation_tokens,
            "tool_output_tokens": self.tool_output_tokens,
            "user_input_tokens": self.user_input_tokens,
            "output_tokens": self.output_tokens,
            "input_tokens": self.input_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class CaseTelemetrySummary:
    """Authoritative case-level token cost matrix and black-hole ranking."""
    case_id: str
    run_id: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    phases: Dict[str, PhaseSummary]
    component_totals: Dict[str, int]
    component_percentages: Dict[str, float]
    ranking_by_component: List[Tuple[str, int, float]]  # [(name, tokens, pct), ...]
    ranking_by_phase: List[Tuple[str, int, float]]      # [(phase, tokens, pct), ...]
    token_accounting_source: str
    generated_at: str
    deterministic_renderer_bytes: int = 0
    data_plane_artifact_bytes: int = 0
    is_synthetic_projection: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
            "component_totals": self.component_totals,
            "component_percentages": self.component_percentages,
            "ranking_by_component": [
                {"component": c, "tokens": t, "percentage": p}
                for c, t, p in self.ranking_by_component
            ],
            "ranking_by_phase": [
                {"phase": ph, "tokens": t, "percentage": p}
                for ph, t, p in self.ranking_by_phase
            ],
            "token_accounting_source": self.token_accounting_source,
            "generated_at": self.generated_at,
            "deterministic_renderer_bytes": self.deterministic_renderer_bytes,
            "data_plane_artifact_bytes": self.data_plane_artifact_bytes,
            "is_synthetic_projection": self.is_synthetic_projection,
        }
