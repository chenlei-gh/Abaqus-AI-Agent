"""Tool Registry and Metadata Contracts for Abaqus-AI-Agent.

Implements strict capability-based registration:
- tool_id, capability, phase, risk_level, input_schema, output_contract, dependencies.
- Prevents hardcoded 'if phase == X' branches and allows dynamic capability resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..telemetry.contracts import EngineeringPhase


class RiskLevel(str, Enum):
    """Execution risk tier for CAE operations."""
    READ_ONLY = "read_only"      # Query, inspect, check - zero model mutations
    LOW = "low"                  # Ingestion, definition, setup
    MEDIUM = "medium"            # Meshing, parameter changes
    HIGH = "high"                # Heavy solver execution, batch run, file deletion


@dataclass(frozen=True)
class ToolMetadata:
    """Rigorous metadata registration for an agent tool."""
    tool_id: str
    name: str
    capability: str              # e.g., "intent_resolution", "geometry_grounding", "result_query"
    phase: EngineeringPhase
    risk_level: RiskLevel
    description: str
    input_schema: Dict[str, Any]
    output_contract: str         # e.g., "GroundedRegion", "CompiledPlan", "OdbHotspotSummary"
    dependencies: Tuple[str, ...] = field(default_factory=tuple)  # Required prerequisite tool_ids or capabilities
    physics_domains: Tuple[str, ...] = field(default_factory=tuple)  # e.g., ("thermal", "structural", "contact")
    tags: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "capability": self.capability,
            "phase": self.phase.value,
            "risk_level": self.risk_level.value,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_contract": self.output_contract,
            "dependencies": list(self.dependencies),
            "physics_domains": list(self.physics_domains),
            "tags": list(self.tags),
        }

    def to_openai_schema(self, minimal: bool = True) -> Dict[str, Any]:
        """Produce an LLM-ready tool schema, optionally minimizing descriptions."""
        schema: Dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description if not minimal else self.description.split("\n")[0][:120],
                "parameters": self.input_schema,
            }
        }
        return schema


class ToolRegistry:
    """Authoritative repository of registered tools with capability indexing."""

    def __init__(self):
        self._tools_by_id: Dict[str, ToolMetadata] = {}
        self._tools_by_capability: Dict[str, List[ToolMetadata]] = {}
        self._tools_by_phase: Dict[str, List[ToolMetadata]] = {}

    def register(self, tool: ToolMetadata) -> None:
        """Register a tool and index by capability and phase."""
        if tool.tool_id in self._tools_by_id:
            raise ValueError(f"Tool with tool_id '{tool.tool_id}' is already registered.")

        self._tools_by_id[tool.tool_id] = tool

        # Index by capability
        self._tools_by_capability.setdefault(tool.capability, []).append(tool)

        # Index by phase
        self._tools_by_phase.setdefault(tool.phase.value, []).append(tool)

    def get(self, tool_id: str) -> Optional[ToolMetadata]:
        return self._tools_by_id.get(tool_id)

    def get_by_name(self, name: str) -> Optional[ToolMetadata]:
        for t in self._tools_by_id.values():
            if t.name == name:
                return t
        return None

    def get_by_capability(self, capability: str) -> List[ToolMetadata]:
        return list(self._tools_by_capability.get(capability, []))

    def get_by_phase(self, phase: EngineeringPhase) -> List[ToolMetadata]:
        return list(self._tools_by_phase.get(phase.value, []))

    def list_all(self) -> List[ToolMetadata]:
        return list(self._tools_by_id.values())

    def count(self) -> int:
        return len(self._tools_by_id)


def build_default_cae_tool_registry() -> ToolRegistry:
    """Build the comprehensive authoritative 24-tool CAE registry."""
    reg = ToolRegistry()

    # --- Phase: INTENT ---
    reg.register(ToolMetadata(
        tool_id="tool_ingest_cad_brep",
        name="ingest_cad_brep",
        capability="geometry_grounding",
        phase=EngineeringPhase.INTENT,
        risk_level=RiskLevel.READ_ONLY,
        description="Ingests a CAD STEP or SAT file, computes topological entities (solids, faces, edges) and bounding boxes.",
        input_schema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to CAD file"},
                "unit_system": {"type": "string", "enum": ["mm", "m"]}
            },
            "required": ["filepath"]
        },
        output_contract="CadModelBRep",
        physics_domains=("structural", "thermal", "contact"),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_inspect_geometry_health",
        name="inspect_geometry_health",
        capability="geometry_grounding",
        phase=EngineeringPhase.INTENT,
        risk_level=RiskLevel.READ_ONLY,
        description="Checks CAD manifoldness, detects tiny faces, sliver edges, and manifold validity.",
        input_schema={
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "tolerance": {"type": "number", "default": 1e-4}
            },
            "required": ["model_id"]
        },
        output_contract="GeometryHealthReport",
        dependencies=("tool_ingest_cad_brep",),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_detect_fastener_holes",
        name="detect_cylindrical_fastener_holes",
        capability="feature_recognition",
        phase=EngineeringPhase.INTENT,
        risk_level=RiskLevel.READ_ONLY,
        description="Recognizes cylindrical bore holes, extracts hole diameters, axes, and clearance margins.",
        input_schema={
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "diameter_min": {"type": "number"},
                "diameter_max": {"type": "number"}
            },
            "required": ["model_id"]
        },
        output_contract="FastenerHoleList",
        dependencies=("tool_ingest_cad_brep",),
        tags=("fastener", "contact"),
    ))

    # --- Phase: PLANNING ---
    reg.register(ToolMetadata(
        tool_id="tool_ground_semantic_region",
        name="ground_semantic_region",
        capability="geometry_grounding",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.READ_ONLY,
        description="Grounds high-level semantic descriptions ('mounting flange', 'fixed face') into findAt coordinates.",
        input_schema={
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "semantic_name": {"type": "string"},
                "geometric_filter": {"type": "string", "enum": ["planar_zmax", "planar_zmin", "cylindrical_inner", "cylindrical_outer"]}
            },
            "required": ["model_id", "semantic_name"]
        },
        output_contract="GroundedRegion",
        dependencies=("tool_ingest_cad_brep",),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_define_elastic_material",
        name="define_linear_elastic_material",
        capability="material_specification",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Defines an isotropic linear elastic material with Young's Modulus and Poisson's ratio.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "youngs_modulus": {"type": "number"},
                "poisson_ratio": {"type": "number"},
                "density": {"type": "number"}
            },
            "required": ["name", "youngs_modulus", "poisson_ratio"]
        },
        output_contract="MaterialDefinition",
        physics_domains=("structural", "thermal"),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_define_thermal_conductivity",
        name="define_thermal_conductivity",
        capability="material_specification",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Defines temperature-dependent thermal conductivity, specific heat, and thermal expansion coefficients.",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string"},
                "conductivity": {"type": "number"},
                "specific_heat": {"type": "number"},
                "expansion_coefficient": {"type": "number"}
            },
            "required": ["material_name", "conductivity"]
        },
        output_contract="ThermalProperties",
        physics_domains=("thermal",),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_create_static_general_step",
        name="create_static_general_step",
        capability="procedure_configuration",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Creates an Abaqus/Standard Static General step with initial and max increments, enabling NLGEOM if requested.",
        input_schema={
            "type": "object",
            "properties": {
                "step_name": {"type": "string"},
                "previous_step": {"type": "string"},
                "time_period": {"type": "number", "default": 1.0},
                "nlgeom": {"type": "boolean", "default": True}
            },
            "required": ["step_name", "previous_step"]
        },
        output_contract="StepDefinition",
        physics_domains=("structural", "contact"),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_create_heat_transfer_step",
        name="create_steady_heat_transfer_step",
        capability="procedure_configuration",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Creates a steady-state or transient heat transfer analysis step in Abaqus/Standard.",
        input_schema={
            "type": "object",
            "properties": {
                "step_name": {"type": "string"},
                "previous_step": {"type": "string"},
                "steady_state": {"type": "boolean", "default": True}
            },
            "required": ["step_name", "previous_step"]
        },
        output_contract="HeatTransferStepDefinition",
        physics_domains=("thermal",),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_apply_clamped_bc",
        name="apply_clamped_boundary_condition",
        capability="load_compilation",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Encastres or constrains specified degrees of freedom on a designated region expression.",
        input_schema={
            "type": "object",
            "properties": {
                "bc_name": {"type": "string"},
                "step_name": {"type": "string"},
                "region_expression": {"type": "string"}
            },
            "required": ["bc_name", "step_name", "region_expression"]
        },
        output_contract="BoundaryConditionAction",
        dependencies=("tool_ground_semantic_region",),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_apply_bolt_pretension",
        name="apply_bolt_pretension_load",
        capability="load_compilation",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Applies an internal bolt pretension load on fastener shank split surfaces with APPLY_FORCE or LOCK_LENGTH condition.",
        input_schema={
            "type": "object",
            "properties": {
                "load_name": {"type": "string"},
                "step_name": {"type": "string"},
                "region_expression": {"type": "string"},
                "preload_magnitude": {"type": "number"},
                "condition": {"type": "string", "enum": ["APPLY_FORCE", "LOCK_LENGTH"]}
            },
            "required": ["load_name", "step_name", "region_expression"]
        },
        output_contract="BoltPretensionAction",
        dependencies=("tool_ground_semantic_region",),
        tags=("fastener", "contact"),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_create_contact_interaction",
        name="create_surface_contact_interaction",
        capability="contact_formulation",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Creates surface-to-surface penalty contact pair with hard normal contact and Coulomb friction.",
        input_schema={
            "type": "object",
            "properties": {
                "interaction_name": {"type": "string"},
                "step_name": {"type": "string"},
                "master_surface": {"type": "string"},
                "slave_surface": {"type": "string"},
                "friction_coefficient": {"type": "number", "default": 0.2}
            },
            "required": ["interaction_name", "step_name", "master_surface", "slave_surface"]
        },
        output_contract="ContactInteractionAction",
        dependencies=("tool_ground_semantic_region",),
        physics_domains=("contact", "structural"),
    ))

    # --- Phase: EXECUTION ---
    reg.register(ToolMetadata(
        tool_id="tool_mesh_part_assembly",
        name="mesh_part_assembly",
        capability="mesh_generation",
        phase=EngineeringPhase.EXECUTION,
        risk_level=RiskLevel.MEDIUM,
        description="Assigns element types (C3D8R, C3D10, DC3D8), global seed size, and triggers native mesh generation.",
        input_schema={
            "type": "object",
            "properties": {
                "part_name": {"type": "string"},
                "element_code": {"type": "string"},
                "seed_size": {"type": "number"}
            },
            "required": ["part_name", "element_code", "seed_size"]
        },
        output_contract="MeshAuditSummary",
    ))

    reg.register(ToolMetadata(
        tool_id="tool_submit_abaqus_job",
        name="submit_abaqus_job",
        capability="abaqus_submit",
        phase=EngineeringPhase.EXECUTION,
        risk_level=RiskLevel.HIGH,
        description="Generates input deck (.inp), launches Abaqus/Standard or Explicit solver, and monitors job completion.",
        input_schema={
            "type": "object",
            "properties": {
                "job_name": {"type": "string"},
                "cpus": {"type": "integer", "default": 4}
            },
            "required": ["job_name"]
        },
        output_contract="JobExecutionReceipt",
        dependencies=("tool_mesh_part_assembly",),
    ))

    reg.register(ToolMetadata(
        tool_id="tool_poll_job_status",
        name="poll_job_status",
        capability="job_status",
        phase=EngineeringPhase.EXECUTION,
        risk_level=RiskLevel.READ_ONLY,
        description="Checks status of submitted Abaqus job and summarizes convergence increments from .sta/.msg.",
        input_schema={
            "type": "object",
            "properties": {"job_name": {"type": "string"}},
            "required": ["job_name"]
        },
        output_contract="ConvergenceSummary",
        dependencies=("tool_submit_abaqus_job",),
    ))

    # --- Phase: VERIFICATION ---
    reg.register(ToolMetadata(
        tool_id="tool_query_result_hotspots",
        name="query_result_hotspots",
        capability="result_query",
        phase=EngineeringPhase.VERIFICATION,
        risk_level=RiskLevel.READ_ONLY,
        description="Performs deterministic spatial search for top-k maximum and minimum values of a field without dumping all nodal arrays.",
        input_schema={
            "type": "object",
            "properties": {
                "result_id": {"type": "string"},
                "field_name": {"type": "string"},
                "top_k": {"type": "integer", "default": 5}
            },
            "required": ["result_id", "field_name"]
        },
        output_contract="HotspotSummaryList",
    ))

    reg.register(ToolMetadata(
        tool_id="tool_evaluate_acceptance",
        name="evaluate_deterministic_acceptance",
        capability="acceptance_gate",
        phase=EngineeringPhase.VERIFICATION,
        risk_level=RiskLevel.READ_ONLY,
        description="Executes single-exit multi-gate engineering checks against criteria thresholds and code limits.",
        input_schema={
            "type": "object",
            "properties": {
                "result_id": {"type": "string"},
                "criteria_profile": {"type": "string"}
            },
            "required": ["result_id", "criteria_profile"]
        },
        output_contract="AcceptanceResult",
    ))

    reg.register(ToolMetadata(
        tool_id="tool_render_headless_contour_images",
        name="render_headless_contour_images",
        capability="artifact_generation",
        phase=EngineeringPhase.VERIFICATION,
        risk_level=RiskLevel.LOW,
        description="Spawns Abaqus Viewer in off-screen headless mode to render high-resolution PNG contour figures.",
        input_schema={
            "type": "object",
            "properties": {
                "odb_path": {"type": "string"},
                "requests": {"type": "array", "items": {"type": "object"}}
            },
            "required": ["odb_path", "requests"]
        },
        output_contract="ArtifactPointerList",
    ))

    # --- Phase: REPORTING ---
    reg.register(ToolMetadata(
        tool_id="tool_render_engineering_report",
        name="render_engineering_report",
        capability="report_summary",
        phase=EngineeringPhase.REPORTING,
        risk_level=RiskLevel.LOW,
        description="Invokes the deterministic report renderer to produce complete bilingual Markdown and HTML reports.",
        input_schema={
            "type": "object",
            "properties": {
                "report_data_json": {"type": "string"},
                "output_formats": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["report_data_json"]
        },
        output_contract="ReportReceipt",
    ))

    return reg
