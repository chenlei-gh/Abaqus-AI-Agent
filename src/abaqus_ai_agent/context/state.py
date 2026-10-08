"""Authoritative Engineering State Contracts for Context Compaction (P0-3).

Three-Plane Architecture Principle:
The LLM Plane receives only authoritative, minimal, structured state representations
instead of raw conversational bloat or bulky ODB field arrays.

Rules:
1. Deterministic Ownership: Engineering states are computed and updated by verified
   Python programs and solver hooks, NEVER hallucinated or synthesized by LLMs.
2. Zero Fact Loss: Critical parameters (loads, materials, element formulations,
   hotspots, acceptance verdicts) are preserved with 100% precision in state fields.
3. Cross-Phase Restorability: Any state snapshot can be serialized and fully
   restored to resume agent workflows without depending on raw chat history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..contracts.artifact import ArtifactPointer
from ..telemetry.contracts import EngineeringPhase


@dataclass(frozen=True)
class GeometryState:
    """Deterministic CAD geometry and topological grounding state."""
    status: str = "uninitialized"  # "uninitialized", "ingested", "grounded", "failed"
    cad_file: Optional[str] = None
    bounding_box: Optional[Dict[str, float]] = None
    recognized_features: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    grounded_regions: Dict[str, Any] = field(default_factory=dict)
    artifact_id: Optional[str] = None

    def to_minimal_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "cad_file": self.cad_file,
            "grounded_regions_count": len(self.grounded_regions),
            "grounded_regions": self.grounded_regions,
            "artifact_id": self.artifact_id,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "cad_file": self.cad_file,
            "bounding_box": self.bounding_box,
            "recognized_features": list(self.recognized_features),
            "grounded_regions": dict(self.grounded_regions),
            "artifact_id": self.artifact_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GeometryState:
        return cls(
            status=data.get("status", "uninitialized"),
            cad_file=data.get("cad_file"),
            bounding_box=data.get("bounding_box"),
            recognized_features=tuple(data.get("recognized_features", ())),
            grounded_regions=data.get("grounded_regions", {}),
            artifact_id=data.get("artifact_id"),
        )


@dataclass(frozen=True)
class ModelState:
    """Deterministic finite element model definition state."""
    status: str = "uncompiled"  # "uncompiled", "compiled", "meshed", "error"
    model_name: str = "Model-1"
    element_type: Optional[str] = None  # e.g., "C3D10", "C3D8R"
    material_parameters: Dict[str, Any] = field(default_factory=dict)
    boundary_conditions: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    loads: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    contact_pairs: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    mesh_stats: Dict[str, Any] = field(default_factory=dict)  # nodes, elements
    inp_artifact_id: Optional[str] = None

    def to_minimal_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "model_name": self.model_name,
            "element_type": self.element_type,
            "material_parameters": self.material_parameters,
            "bc_count": len(self.boundary_conditions),
            "loads": list(self.loads),
            "mesh_stats": self.mesh_stats,
            "inp_artifact_id": self.inp_artifact_id,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "model_name": self.model_name,
            "element_type": self.element_type,
            "material_parameters": dict(self.material_parameters),
            "boundary_conditions": list(self.boundary_conditions),
            "loads": list(self.loads),
            "contact_pairs": list(self.contact_pairs),
            "mesh_stats": dict(self.mesh_stats),
            "inp_artifact_id": self.inp_artifact_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModelState:
        return cls(
            status=data.get("status", "uncompiled"),
            model_name=data.get("model_name", "Model-1"),
            element_type=data.get("element_type"),
            material_parameters=data.get("material_parameters", {}),
            boundary_conditions=tuple(data.get("boundary_conditions", ())),
            loads=tuple(data.get("loads", ())),
            contact_pairs=tuple(data.get("contact_pairs", ())),
            mesh_stats=data.get("mesh_stats", {}),
            inp_artifact_id=data.get("inp_artifact_id"),
        )


@dataclass(frozen=True)
class ExecutionState:
    """Deterministic Abaqus solver execution and job state."""
    status: str = "idle"  # "idle", "submitted", "running", "completed", "failed"
    job_name: str = "Job-1"
    job_id: Optional[str] = None
    solver_version: Optional[str] = None
    exit_code: Optional[int] = None
    odb_artifact_id: Optional[str] = None
    log_artifact_id: Optional[str] = None
    execution_time_seconds: Optional[float] = None

    def to_minimal_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "job_name": self.job_name,
            "job_id": self.job_id,
            "odb_artifact_id": self.odb_artifact_id,
            "exit_code": self.exit_code,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "job_name": self.job_name,
            "job_id": self.job_id,
            "solver_version": self.solver_version,
            "exit_code": self.exit_code,
            "odb_artifact_id": self.odb_artifact_id,
            "log_artifact_id": self.log_artifact_id,
            "execution_time_seconds": self.execution_time_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionState:
        return cls(
            status=data.get("status", "idle"),
            job_name=data.get("job_name", "Job-1"),
            job_id=data.get("job_id"),
            solver_version=data.get("solver_version"),
            exit_code=data.get("exit_code"),
            odb_artifact_id=data.get("odb_artifact_id"),
            log_artifact_id=data.get("log_artifact_id"),
            execution_time_seconds=data.get("execution_time_seconds"),
        )


@dataclass(frozen=True)
class VerificationState:
    """Deterministic engineering verification, result metrics, and acceptance gate state."""
    status: str = "unverified"  # "unverified", "evaluating", "passed", "failed"
    acceptance_status: str = "PENDING"  # "PASS", "FAIL", "BLOCKED", "PENDING"
    max_mises_mpa: Optional[float] = None
    max_displacement_mm: Optional[float] = None
    reaction_force_balance_pct: Optional[float] = None
    critical_hotspots: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    acceptance_id: Optional[str] = None
    evidence_manifest_artifact_id: Optional[str] = None

    def to_minimal_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "acceptance": self.acceptance_status,
            "max_mises_mpa": self.max_mises_mpa,
            "max_displacement_mm": self.max_displacement_mm,
            "reaction_force_balance_pct": self.reaction_force_balance_pct,
            "acceptance_id": self.acceptance_id,
            "evidence_manifest_artifact_id": self.evidence_manifest_artifact_id,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "acceptance_status": self.acceptance_status,
            "max_mises_mpa": self.max_mises_mpa,
            "max_displacement_mm": self.max_displacement_mm,
            "reaction_force_balance_pct": self.reaction_force_balance_pct,
            "critical_hotspots": list(self.critical_hotspots),
            "acceptance_id": self.acceptance_id,
            "evidence_manifest_artifact_id": self.evidence_manifest_artifact_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerificationState:
        return cls(
            status=data.get("status", "unverified"),
            acceptance_status=data.get("acceptance_status", "PENDING"),
            max_mises_mpa=data.get("max_mises_mpa"),
            max_displacement_mm=data.get("max_displacement_mm"),
            reaction_force_balance_pct=data.get("reaction_force_balance_pct"),
            critical_hotspots=tuple(data.get("critical_hotspots", ())),
            acceptance_id=data.get("acceptance_id"),
            evidence_manifest_artifact_id=data.get("evidence_manifest_artifact_id"),
        )


@dataclass(frozen=True)
class EngineeringState:
    """Unified, authoritative snapshot of an engineering task lifecycle."""
    run_id: str
    phase: EngineeringPhase
    physics_domain: str = "structural"
    case_id: Optional[str] = None
    active_task: str = "Initialize task"
    last_user_intent: str = ""
    unresolved_questions: Tuple[str, ...] = field(default_factory=tuple)
    geometry: GeometryState = field(default_factory=GeometryState)
    model: ModelState = field(default_factory=ModelState)
    execution: ExecutionState = field(default_factory=ExecutionState)
    verification: VerificationState = field(default_factory=VerificationState)
    artifact_pointers: Tuple[ArtifactPointer, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_minimal_context_dict(self) -> Dict[str, Any]:
        """Generate the lean, structured Hot State payload for the LLM Context."""
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "phase": self.phase.value,
            "physics_domain": self.physics_domain,
            "active_task": self.active_task,
            "last_user_intent": self.last_user_intent,
            "unresolved_questions": list(self.unresolved_questions),
            "geometry": self.geometry.to_minimal_dict(),
            "model": self.model.to_minimal_dict(),
            "execution": self.execution.to_minimal_dict(),
            "verification": self.verification.to_minimal_dict(),
            "artifact_ids": [p.artifact_id for p in self.artifact_pointers],
        }

    def to_full_dict(self) -> Dict[str, Any]:
        """Produce full deterministic representation suitable for persistence and restoration."""
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "phase": self.phase.value,
            "physics_domain": self.physics_domain,
            "active_task": self.active_task,
            "last_user_intent": self.last_user_intent,
            "unresolved_questions": list(self.unresolved_questions),
            "geometry": self.geometry.to_full_dict(),
            "model": self.model.to_full_dict(),
            "execution": self.execution.to_full_dict(),
            "verification": self.verification.to_full_dict(),
            "artifact_pointers": [p.to_dict() if hasattr(p, "to_dict") else asdict(p) for p in self.artifact_pointers],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EngineeringState:
        """Deterministically reconstitute state snapshot from data dict."""
        pointers = []
        for p_data in data.get("artifact_pointers", []):
            if isinstance(p_data, ArtifactPointer):
                pointers.append(p_data)
            elif isinstance(p_data, dict):
                pointers.append(ArtifactPointer(**p_data))

        phase_val = data.get("phase", EngineeringPhase.INTENT.value)
        phase_enum = EngineeringPhase(phase_val) if isinstance(phase_val, str) else phase_val

        return cls(
            run_id=data["run_id"],
            case_id=data.get("case_id"),
            phase=phase_enum,
            physics_domain=data.get("physics_domain", "structural"),
            active_task=data.get("active_task", ""),
            last_user_intent=data.get("last_user_intent", ""),
            unresolved_questions=tuple(data.get("unresolved_questions", ())),
            geometry=GeometryState.from_dict(data.get("geometry", {})),
            model=ModelState.from_dict(data.get("model", {})),
            execution=ExecutionState.from_dict(data.get("execution", {})),
            verification=VerificationState.from_dict(data.get("verification", {})),
            artifact_pointers=tuple(pointers),
            metadata=data.get("metadata", {}),
        )

    def assert_fact_preservation(self, expected_facts: Dict[str, Any]) -> None:
        """Verify that mandatory engineering facts have not suffered data loss."""
        # Check loads
        if "load_magnitude" in expected_facts:
            matched_load = any(
                l.get("magnitude") == expected_facts["load_magnitude"]
                for l in self.model.loads
            )
            assert matched_load, f"Fact loss: load_magnitude {expected_facts['load_magnitude']} not found in state!"

        if "load_direction" in expected_facts:
            matched_dir = any(
                l.get("direction") == expected_facts["load_direction"]
                for l in self.model.loads
            )
            assert matched_dir, f"Fact loss: load_direction {expected_facts['load_direction']} not found in state!"

        if "element_type" in expected_facts:
            assert self.model.element_type == expected_facts["element_type"], (
                f"Fact loss: element_type mismatch! Expected {expected_facts['element_type']}, got {self.model.element_type}"
            )

        if "acceptance_status" in expected_facts:
            assert self.verification.acceptance_status == expected_facts["acceptance_status"], (
                f"Fact loss: acceptance_status mismatch! Expected {expected_facts['acceptance_status']}, got {self.verification.acceptance_status}"
            )

        if "odb_artifact_id" in expected_facts:
            assert self.execution.odb_artifact_id == expected_facts["odb_artifact_id"], (
                f"Fact loss: odb_artifact_id mismatch! Expected {expected_facts['odb_artifact_id']}, got {self.execution.odb_artifact_id}"
            )
