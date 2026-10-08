"""Tracker and Profiler for Context Telemetry.

Provides zero-overhead observation and persistence of LLM context usage.
Strict rules:
1. Every LLM call receives a unique call_id linked to run_id and phase.
2. Token source is explicitly labeled (provider_reported vs local_tokenizer vs estimated).
3. Telemetry strictly writes to disk and returns only minimal status indicator.
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .contracts import (
    ArtifactContextMetrics,
    CallTelemetry,
    CaseTelemetrySummary,
    EngineeringPhase,
    PhaseSummary,
    TokenBreakdown,
    TokenCountSource,
)


def _heuristic_count_tokens(text: str) -> int:
    """Explicitly labeled heuristic fallback token counter when no tokenizer is present.

    Note: English words/code average ~3.8-4.0 chars/token; CJK characters average ~1.3-1.8 chars/token.
    """
    if not text:
        return 0
    zh_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - zh_chars
    # Heuristic: 1 Chinese char ~ 0.7 token (or 1.4 chars/token); 4 ASCII chars ~ 1 token
    est = int((zh_chars * 0.72) + (other_chars / 3.8))
    return max(1, est)


class ContextTelemetryTracker:
    """Manages context token profiling for a single case execution run."""

    def __init__(
        self,
        case_id: str,
        run_id: str,
        output_dir: Union[str, Path] = "runs",
        source: TokenCountSource = TokenCountSource.ESTIMATED,
    ):
        self.case_id = case_id
        self.run_id = run_id
        self.output_dir = Path(output_dir) / run_id / "telemetry"
        self.calls_dir = self.output_dir / "calls"
        self.calls_dir.mkdir(parents=True, exist_ok=True)

        self.default_source = source
        self.calls: List[CallTelemetry] = []
        self._seq = 0

    def record_call(
        self,
        phase: Union[EngineeringPhase, str],
        system_text: Optional[str] = None,
        tool_schema_text: Optional[str] = None,
        conversation_text: Optional[str] = None,
        tool_output_text: Optional[str] = None,
        user_input_text: Optional[str] = None,
        output_text: Optional[str] = None,
        # Or explicit token counts from provider / external tokenizer:
        system_tokens: Optional[int] = None,
        tool_schema_tokens: Optional[int] = None,
        conversation_tokens: Optional[int] = None,
        tool_output_tokens: Optional[int] = None,
        user_input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        source: Optional[TokenCountSource] = None,
        pointers_count: int = 0,
        pointers_size_bytes: int = 0,
        raw_artifacts_blocked: int = 0,
        deterministic_renderer_bytes: int = 0,
        data_plane_artifact_bytes: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CallTelemetry:
        """Record an LLM call invocation and immediately persist to disk."""
        self._seq += 1
        call_id = f"CALL-{self.run_id}-{self._seq:04d}"

        if isinstance(phase, str):
            try:
                phase_enum = EngineeringPhase(phase.lower())
            except ValueError:
                phase_enum = EngineeringPhase.OTHER
        else:
            phase_enum = phase

        effective_source = source or self.default_source

        # Compute counts: prioritize explicit token counts, then text tokenization
        s_tokens = system_tokens if system_tokens is not None else _heuristic_count_tokens(system_text or "")
        ts_tokens = tool_schema_tokens if tool_schema_tokens is not None else _heuristic_count_tokens(tool_schema_text or "")
        c_tokens = conversation_tokens if conversation_tokens is not None else _heuristic_count_tokens(conversation_text or "")
        to_tokens = tool_output_tokens if tool_output_tokens is not None else _heuristic_count_tokens(tool_output_text or "")
        u_tokens = user_input_tokens if user_input_tokens is not None else _heuristic_count_tokens(user_input_text or "")
        out_tokens = output_tokens if output_tokens is not None else _heuristic_count_tokens(output_text or "")

        breakdown = TokenBreakdown(
            system_tokens=s_tokens,
            tool_schema_tokens=ts_tokens,
            conversation_tokens=c_tokens,
            tool_output_tokens=to_tokens,
            user_input_tokens=u_tokens,
            output_tokens=out_tokens,
            source=effective_source,
            deterministic_renderer_bytes=deterministic_renderer_bytes,
            data_plane_artifact_bytes=data_plane_artifact_bytes,
        )

        artifacts = ArtifactContextMetrics(
            pointers_count=pointers_count,
            pointers_size_bytes=pointers_size_bytes,
            raw_artifacts_blocked_count=raw_artifacts_blocked,
        )

        record = CallTelemetry(
            call_id=call_id,
            run_id=self.run_id,
            case_id=self.case_id,
            phase=phase_enum,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            breakdown=breakdown,
            artifacts=artifacts,
            metadata=metadata or {},
        )

        # Persist individual call record to disk (Zero context pollution)
        call_file = self.calls_dir / f"{call_id}.json"
        with open(call_file, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, ensure_ascii=False)

        self.calls.append(record)
        return record

    def finalize(self) -> CaseTelemetrySummary:
        """Aggregate all calls in this case and emit summary.json."""
        phases_map: Dict[str, PhaseSummary] = {}
        for p in EngineeringPhase:
            phases_map[p.value] = PhaseSummary(phase=p.value)

        tot_input = 0
        tot_output = 0

        comp_totals = {
            "system_tokens": 0,
            "tool_schema_tokens": 0,
            "conversation_tokens": 0,
            "tool_output_tokens": 0,
            "user_input_tokens": 0,
            "output_tokens": 0,
        }

        sources = set()

        for c in self.calls:
            p_val = c.phase.value
            ps = phases_map[p_val]
            ps.calls_count += 1
            b = c.breakdown
            sources.add(b.source.value)

            ps.system_tokens += b.system_tokens
            ps.tool_schema_tokens += b.tool_schema_tokens
            ps.conversation_tokens += b.conversation_tokens
            ps.tool_output_tokens += b.tool_output_tokens
            ps.user_input_tokens += b.user_input_tokens
            ps.output_tokens += b.output_tokens

            tot_input += b.input_tokens
            tot_output += b.output_tokens

            comp_totals["system_tokens"] += b.system_tokens
            comp_totals["tool_schema_tokens"] += b.tool_schema_tokens
            comp_totals["conversation_tokens"] += b.conversation_tokens
            comp_totals["tool_output_tokens"] += b.tool_output_tokens
            comp_totals["user_input_tokens"] += b.user_input_tokens
            comp_totals["output_tokens"] += b.output_tokens

        total_tokens = tot_input + tot_output

        # Component percentages & ranking
        comp_pcts: Dict[str, float] = {}
        ranking_comp: List[Tuple[str, int, float]] = []
        for c_name, c_tokens in comp_totals.items():
            pct = (c_tokens / total_tokens * 100.0) if total_tokens > 0 else 0.0
            comp_pcts[c_name] = round(pct, 2)
            ranking_comp.append((c_name, c_tokens, round(pct, 2)))
        ranking_comp.sort(key=lambda x: x[1], reverse=True)

        # Phase ranking
        ranking_ph: List[Tuple[str, int, float]] = []
        for p_name, p_sum in phases_map.items():
            if p_sum.total_tokens > 0 or p_sum.calls_count > 0:
                p_pct = (p_sum.total_tokens / total_tokens * 100.0) if total_tokens > 0 else 0.0
                ranking_ph.append((p_name, p_sum.total_tokens, round(p_pct, 2)))
        ranking_ph.sort(key=lambda x: x[1], reverse=True)

        # Remove zero phases for clean output
        active_phases = {k: v for k, v in phases_map.items() if v.total_tokens > 0 or v.calls_count > 0}

        tot_renderer_bytes = sum(c.breakdown.deterministic_renderer_bytes for c in self.calls)
        tot_artifact_bytes = sum(c.breakdown.data_plane_artifact_bytes for c in self.calls)
        is_synthetic = any(c.breakdown.source in (TokenCountSource.SYNTHETIC_PROJECTION, TokenCountSource.ESTIMATED) for c in self.calls)

        accounting_source = ", ".join(sorted(sources)) if sources else "unknown"

        summary = CaseTelemetrySummary(
            case_id=self.case_id,
            run_id=self.run_id,
            total_calls=len(self.calls),
            total_input_tokens=tot_input,
            total_output_tokens=tot_output,
            total_tokens=total_tokens,
            phases=active_phases,
            component_totals=comp_totals,
            component_percentages=comp_pcts,
            ranking_by_component=ranking_comp,
            ranking_by_phase=ranking_ph,
            token_accounting_source=accounting_source,
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            deterministic_renderer_bytes=tot_renderer_bytes,
            data_plane_artifact_bytes=tot_artifact_bytes,
            is_synthetic_projection=is_synthetic,
        )

        summary_file = self.output_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)

        return summary

    def finalize_case(self) -> CaseTelemetrySummary:
        return self.finalize()

    def get_llm_status(self) -> Dict[str, str]:
        """Produce the ultra-compact status indicator safe for LLM context injection."""
        return {
            "telemetry_status": "available",
            "run_id": self.run_id,
        }
