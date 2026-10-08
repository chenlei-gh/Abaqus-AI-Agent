"""Dynamic Tool Router for Context Minimization.

Implements the capability-based dynamic routing pipeline:
Phase / Intent -> Capability Requirements -> Registry Match & Dependency Resolution -> Minimal Schemas

Rules:
- Never hardcode arbitrary static tool arrays.
- Filter by capabilities, physical domain relevancy, and resolve dependencies automatically.
- Provide transparent telemetry audit trail (tools_available, tools_selected, schema_tokens).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..telemetry.contracts import EngineeringPhase, TokenCountSource
from ..telemetry.tracker import _heuristic_count_tokens
from .registry import RiskLevel, ToolMetadata, ToolRegistry, build_default_cae_tool_registry


# Standard Phase-to-Capability mapping defaults
PHASE_DEFAULT_CAPABILITIES: Dict[str, Tuple[str, ...]] = {
    EngineeringPhase.INTENT.value: (
        "intent_resolution",
        "geometry_grounding",
        "feature_recognition",
    ),
    EngineeringPhase.PLANNING.value: (
        "geometry_grounding",
        "material_specification",
        "procedure_configuration",
        "load_compilation",
        "contact_formulation",
    ),
    EngineeringPhase.EXECUTION.value: (
        "mesh_generation",
        "abaqus_submit",
        "job_status",
    ),
    EngineeringPhase.VERIFICATION.value: (
        "result_query",
        "acceptance_gate",
        "artifact_generation",
    ),
    EngineeringPhase.REPORTING.value: (
        "report_summary",
    ),
}


@dataclass(frozen=True)
class DynamicRouteResult:
    """The authoritative outcome of dynamic tool capability resolution."""
    phase: EngineeringPhase
    selected_tools: Tuple[ToolMetadata, ...]
    minimal_schemas: Tuple[Dict[str, Any], ...]
    tools_available_count: int
    tools_selected_count: int
    selected_capabilities: Tuple[str, ...]
    schema_tokens: int
    measurement_source: str = "estimated"
    audit_trace: Dict[str, Any] = field(default_factory=dict)

    def to_telemetry_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "tools_available": self.tools_available_count,
            "tools_selected": self.tools_selected_count,
            "selected_capabilities": list(self.selected_capabilities),
            "selected_tool_names": [t.name for t in self.selected_tools],
            "schema_tokens": self.schema_tokens,
            "measurement_source": self.measurement_source,
        }

    def get_tool_names(self) -> Set[str]:
        return {t.name for t in self.selected_tools}


class DynamicToolRouter:
    """Selects the minimal requisite toolset per interaction turn."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or build_default_cae_tool_registry()

    def resolve_tools(
        self,
        phase: EngineeringPhase,
        required_capabilities: Optional[Sequence[str] | Set[str]] = None,
        physics_domain: Optional[str] = None,
        task_context: Optional[Dict[str, Any]] = None,
        minimal_schema: bool = True,
    ) -> DynamicRouteResult:
        """Resolve minimal toolset matching capabilities, domain constraints, and dependencies."""
        all_tools = self.registry.list_all()
        total_available = len(all_tools)

        # 1. Determine active capability set
        if required_capabilities:
            active_caps = set(required_capabilities)
        else:
            default_caps = PHASE_DEFAULT_CAPABILITIES.get(phase.value, ())
            active_caps = set(default_caps)

        # Context-based capability adjustments
        ctx = task_context or {}
        if ctx.get("needs_contact") is False and "contact_formulation" in active_caps:
            active_caps.remove("contact_formulation")

        # 2. Select initial candidate tools matching capabilities
        candidates: Dict[str, ToolMetadata] = {}
        for cap in active_caps:
            matched = self.registry.get_by_capability(cap)
            for tool in matched:
                # Physics domain filtering
                if physics_domain and tool.physics_domains:
                    # If tool requires a specific physics domain, check match
                    if not any(d in physics_domain.lower() for d in tool.physics_domains):
                        continue
                candidates[tool.tool_id] = tool

        # 3. Resolve Dependencies recursively
        resolved_tools: Dict[str, ToolMetadata] = dict(candidates)
        queue = list(candidates.values())
        visited_deps: Set[str] = set()

        while queue:
            current = queue.pop(0)
            for dep in current.dependencies:
                if dep in visited_deps:
                    continue
                visited_deps.add(dep)

                # dep can be a tool_id or a capability name
                dep_tool = self.registry.get(dep)
                if dep_tool:
                    if dep_tool.tool_id not in resolved_tools:
                        resolved_tools[dep_tool.tool_id] = dep_tool
                        queue.append(dep_tool)
                else:
                    # Check if dep is a capability
                    dep_matched = self.registry.get_by_capability(dep)
                    for dt in dep_matched:
                        if dt.tool_id not in resolved_tools:
                            resolved_tools[dt.tool_id] = dt
                            queue.append(dt)

        # Sort tools deterministically by tool_id for stable schemas
        sorted_tools = sorted(resolved_tools.values(), key=lambda t: t.tool_id)

        # 4. Generate minimal LLM schemas (compact JSON representation matching real API payloads)
        minimal_schemas = [t.to_openai_schema(minimal=minimal_schema) for t in sorted_tools]
        schema_json_str = json.dumps(minimal_schemas)
        schema_tokens = _heuristic_count_tokens(schema_json_str)

        audit_trace = {
            "requested_phase": phase.value,
            "active_capabilities": sorted(list(active_caps)),
            "resolved_dependencies": sorted(list(visited_deps)),
            "physics_domain_filter": physics_domain,
            "raw_candidate_count": len(candidates),
            "final_selected_count": len(sorted_tools),
        }

        return DynamicRouteResult(
            phase=phase,
            selected_tools=tuple(sorted_tools),
            minimal_schemas=tuple(minimal_schemas),
            tools_available_count=total_available,
            tools_selected_count=len(sorted_tools),
            selected_capabilities=tuple(sorted(list(active_caps))),
            schema_tokens=schema_tokens,
            measurement_source="estimated",
            audit_trace=audit_trace,
        )
