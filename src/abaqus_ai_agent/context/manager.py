"""State-Based Context Compaction Manager (P0-3).

Transitions conversational agents from conversation-driven (raw message appending)
to state-driven execution.

Architecture:
- HOT: Current authoritative EngineeringState + Recent Intent + Current Phase + Artifact References.
- WARM: Recent key engineering decisions and compact tool cards.
- COLD: Raw conversational transcripts, full tool payloads, solver logs, and ODB text
        persisted deterministically to Data Plane, queryable via ArtifactPointer.

Rules:
1. No Engineering Fact Loss: Crucial physical quantities and statuses remain intact in state.
2. Graceful Degradation: Cold history is relegated to disk/archive, never deleted.
3. Deterministic Governance: State mutations are driven by deterministic verification, not LLM inference.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..contracts.artifact import ArtifactPointer
from ..telemetry.contracts import EngineeringPhase, TokenCountSource
from ..telemetry.tracker import _heuristic_count_tokens
from .state import (
    EngineeringState,
    ExecutionState,
    GeometryState,
    ModelState,
    VerificationState,
)


@dataclass(frozen=True)
class ToolExecutionRecord:
    """Record of a tool invocation in conversation history."""
    turn_id: int
    tool_name: str
    tool_input: Dict[str, Any]
    tool_output_raw: Any
    artifact_pointer: Optional[ArtifactPointer] = None
    summary_card: str = ""
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output_raw": self.tool_output_raw,
            "artifact_pointer": self.artifact_pointer.to_dict() if self.artifact_pointer else None,
            "summary_card": self.summary_card,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class CompactedContext:
    """The authoritative minimal context payload delivered to the LLM Plane."""
    run_id: str
    phase: EngineeringPhase
    hot_state: Dict[str, Any]
    recent_intent: Dict[str, Any]
    warm_decisions: Tuple[str, ...]
    warm_tool_summaries: Tuple[str, ...]
    cold_archive_pointer: Optional[ArtifactPointer]
    context_tokens: int
    uncompacted_tokens: int
    reduction_pct: float
    measurement_source: str = TokenCountSource.ESTIMATED.value

    def to_llm_system_context(self) -> str:
        """Render compact context markdown/JSON string for LLM system/developer prompt."""
        payload = {
            "current_engineering_state": self.hot_state,
            "recent_intent": self.recent_intent,
            "recent_decisions": list(self.warm_decisions),
            "recent_tool_summaries": list(self.warm_tool_summaries),
        }
        if self.cold_archive_pointer:
            payload["cold_history_artifact_id"] = self.cold_archive_pointer.artifact_id
        return json.dumps(payload, ensure_ascii=False)


class StateBasedContextManager:
    """Manages multi-turn engineering agent context with state-based compaction."""

    def __init__(self, initial_state: Optional[EngineeringState] = None, max_warm_items: int = 4):
        self.state: EngineeringState = initial_state or EngineeringState(
            run_id="RUN-DEFAULT",
            phase=EngineeringPhase.INTENT,
        )
        self.max_warm_items = max_warm_items

        # COLD Plane (Full history)
        self._raw_messages: List[Dict[str, Any]] = []
        self._tool_executions: List[ToolExecutionRecord] = []
        self._turn_counter: int = 0

        # WARM Plane
        self._key_decisions: List[str] = []
        self._recent_tool_summaries: List[str] = []

        # Archived Pointers
        self._cold_archive_pointer: Optional[ArtifactPointer] = None

    @property
    def current_state(self) -> EngineeringState:
        return self.state

    def append_user_message(self, content: str) -> None:
        """Record raw user message and update last user intent."""
        self._turn_counter += 1
        self._raw_messages.append({
            "turn": self._turn_counter,
            "role": "user",
            "content": content,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        # Deterministically track last user intent in state
        self._update_state_internal(last_user_intent=content)

    def append_assistant_message(self, content: str) -> None:
        """Record raw assistant message."""
        self._turn_counter += 1
        self._raw_messages.append({
            "turn": self._turn_counter,
            "role": "assistant",
            "content": content,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    def append_tool_execution(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        artifact_pointer: Optional[ArtifactPointer] = None,
        compact_summary: Optional[str] = None,
    ) -> None:
        """Record raw tool execution and maintain warm summary card."""
        self._turn_counter += 1
        summary = compact_summary or f"Tool '{tool_name}' executed with status SUCCESS."

        record = ToolExecutionRecord(
            turn_id=self._turn_counter,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output_raw=tool_output,
            artifact_pointer=artifact_pointer,
            summary_card=summary,
        )
        self._tool_executions.append(record)

        # Update Warm buffer
        self._recent_tool_summaries.append(summary)
        if len(self._recent_tool_summaries) > self.max_warm_items:
            self._recent_tool_summaries.pop(0)

        # If an artifact pointer was generated, bind to state
        if artifact_pointer:
            current_pointers = list(self.state.artifact_pointers)
            if not any(p.artifact_id == artifact_pointer.artifact_id for p in current_pointers):
                current_pointers.append(artifact_pointer)
                self._update_state_internal(artifact_pointers=tuple(current_pointers))

    def add_key_decision(self, decision: str) -> None:
        """Register an engineering decision into warm memory."""
        self._key_decisions.append(decision)
        if len(self._key_decisions) > self.max_warm_items:
            self._key_decisions.pop(0)

    def update_engineering_state(
        self,
        phase: Optional[EngineeringPhase] = None,
        active_task: Optional[str] = None,
        geometry: Optional[GeometryState] = None,
        model: Optional[ModelState] = None,
        execution: Optional[ExecutionState] = None,
        verification: Optional[VerificationState] = None,
        unresolved_questions: Optional[Sequence[str]] = None,
        physics_domain: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EngineeringState:
        """Authoritatively update engineering state from verified program hooks."""
        kwargs: Dict[str, Any] = {}
        if phase is not None:
            kwargs["phase"] = phase
        if active_task is not None:
            kwargs["active_task"] = active_task
        if geometry is not None:
            kwargs["geometry"] = geometry
        if model is not None:
            kwargs["model"] = model
        if execution is not None:
            kwargs["execution"] = execution
        if verification is not None:
            kwargs["verification"] = verification
        if unresolved_questions is not None:
            kwargs["unresolved_questions"] = tuple(unresolved_questions)
        if physics_domain is not None:
            kwargs["physics_domain"] = physics_domain
        if metadata is not None:
            new_meta = dict(self.state.metadata)
            new_meta.update(metadata)
            kwargs["metadata"] = new_meta

        self._update_state_internal(**kwargs)
        return self.state

    def _update_state_internal(self, **kwargs) -> None:
        """Internal helper to construct a new immutable EngineeringState."""
        self.state = replace(self.state, **kwargs)

    def compact(self, storage_dir: Optional[Path] = None) -> CompactedContext:
        """Produce compacted state-driven context and relegate raw history to Cold Storage."""
        # 1. Hot State
        hot_payload = self.state.to_minimal_context_dict()

        # 2. Recent Intent
        recent_intent = {
            "active_task": self.state.active_task,
            "last_user_intent": self.state.last_user_intent,
            "unresolved_questions": list(self.state.unresolved_questions),
        }

        # 3. Warm Elements
        warm_decisions = tuple(self._key_decisions[-self.max_warm_items:])
        warm_summaries = tuple(self._recent_tool_summaries[-self.max_warm_items:])

        # 4. Cold History Relegation (Persist to Data Plane)
        cold_data = {
            "run_id": self.state.run_id,
            "archived_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "raw_messages": self._raw_messages,
            "tool_executions": [t.to_dict() for t in self._tool_executions],
            "full_state_snapshot": self.state.to_full_dict(),
        }
        cold_bytes = json.dumps(cold_data, indent=2, ensure_ascii=False).encode("utf-8")
        cold_sha256 = hashlib.sha256(cold_bytes).hexdigest()

        if storage_dir:
            target_dir = Path(storage_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            cold_file = target_dir / f"cold_history_{self.state.run_id}_{self._turn_counter}.json"
            cold_file.write_bytes(cold_bytes)
            archive_location = str(cold_file.as_posix())
        else:
            archive_location = f"virtual/cold_history/{self.state.run_id}_{self._turn_counter}.json"

        self._cold_archive_pointer = ArtifactPointer(
            artifact_id=f"COLD-HIST-{self.state.run_id}-{self._turn_counter}",
            type="log",
            media_type="application/json",
            location=archive_location,
            size_bytes=len(cold_bytes),
            created_by="state_based_compactor",
            storage_scope="run",
            access_policy="engineering_internal",
            checksum_sha256=cold_sha256,
        )

        # 5. Measure Token Footprints (Heuristic / Estimated)
        # Uncompacted baseline: All raw messages + all raw tool executions
        raw_full_conversation = {
            "messages": self._raw_messages,
            "tool_executions": [t.to_dict() for t in self._tool_executions],
            "initial_system": "Standard CAE System Prompt with full memory",
        }
        uncompacted_tokens = _heuristic_count_tokens(json.dumps(raw_full_conversation))

        # Compacted context: Hot State + Recent Intent + Warm Summaries
        compact_payload = {
            "current_engineering_state": hot_payload,
            "recent_intent": recent_intent,
            "recent_decisions": list(warm_decisions),
            "recent_tool_summaries": list(warm_summaries),
            "cold_archive_pointer": self._cold_archive_pointer.artifact_id,
        }
        compact_tokens = _heuristic_count_tokens(json.dumps(compact_payload))

        if uncompacted_tokens > 0:
            reduction_pct = max(0.0, (uncompacted_tokens - compact_tokens) / uncompacted_tokens * 100.0)
        else:
            reduction_pct = 0.0

        return CompactedContext(
            run_id=self.state.run_id,
            phase=self.state.phase,
            hot_state=hot_payload,
            recent_intent=recent_intent,
            warm_decisions=warm_decisions,
            warm_tool_summaries=warm_summaries,
            cold_archive_pointer=self._cold_archive_pointer,
            context_tokens=compact_tokens,
            uncompacted_tokens=uncompacted_tokens,
            reduction_pct=round(reduction_pct, 1),
            measurement_source=TokenCountSource.ESTIMATED.value,
        )

    @classmethod
    def restore(
        cls,
        state_dict: Dict[str, Any],
        cold_archive_pointer: Optional[ArtifactPointer] = None,
        warm_decisions: Optional[Sequence[str]] = None,
    ) -> StateBasedContextManager:
        """Deterministically resurrect agent execution context from state snapshot.

        Enables the Compaction -> Wipe Context -> Restore -> Continue execution cycle.
        """
        reconstituted_state = EngineeringState.from_dict(state_dict)
        manager = cls(initial_state=reconstituted_state)

        if cold_archive_pointer:
            manager._cold_archive_pointer = cold_archive_pointer

        if warm_decisions:
            for d in warm_decisions:
                manager.add_key_decision(d)

        return manager
