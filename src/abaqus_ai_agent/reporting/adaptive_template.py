"""Adaptive & Polymorphic Report Template Orchestration (P0-5).

Solves the core requirement:
The report structure and template MUST adapt dynamically according to the
analysis physics domain (structural, thermal, contact, dynamic) and engineering objective
(strength, bolted joint sealing, fatigue durability, thermal compliance).

Architecture:
Canonical Report Data Model -> Dynamic Section Composition -> Localized Label Map -> Deterministic Renderer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..contracts.report import EngineeringReportData, ReportFigure
from .interpretation_card import InterpretationCard
from .visualization_spec import VisualizationSpec


class AnalysisObjective(str, Enum):
    """Specific engineering objective dictating the dynamic report sections."""
    STATIC_STRENGTH = "static_strength"          # von Mises, yield limit, displacement margin
    BOLTED_SEALING = "bolted_sealing"            # Bolt pretension, flange separation, CPRESS
    FATIGUE_DURABILITY = "fatigue_durability"    # Stress amplitude, fatigue cycles, damage ratio
    THERMAL_COMPLIANCE = "thermal_compliance"    # Heat flux, temperature gradient, thermal stress
    GENERAL_FEA = "general_fea"                  # Standard baseline structural analysis


class AdaptiveReportBuilder:
    """Dynamically assembles an EngineeringReportData model based on domain & objective."""

    def __init__(
        self,
        physics_domain: str = "structural",
        objective: AnalysisObjective = AnalysisObjective.GENERAL_FEA,
    ):
        self.physics_domain = physics_domain.lower()
        self.objective = objective

    def determine_active_sections(self) -> Tuple[str, ...]:
        """Compute the dynamic list of report sections based on domain & objective."""
        # Baseline sections applicable to all engineering evaluations
        sections: List[str] = [
            "executive_summary",
            "model_overview",
            "material_properties",
            "boundary_conditions_and_loads",
            "mesh_and_discretization",
            "solver_and_convergence",
            "primary_field_results",
        ]

        # Domain & Objective Adaptive Sections
        if self.objective == AnalysisObjective.BOLTED_SEALING:
            sections.append("fastener_preload_diagnostics")
            sections.append("contact_pressure_and_closure")
        elif "contact" in self.physics_domain:
            # General contact analysis focuses on contact pressure and interaction status,
            # not fastener preload diagnostics or gasket sealing criteria.
            sections.append("contact_pressure_and_closure")

        if self.objective == AnalysisObjective.FATIGUE_DURABILITY or "fatigue" in self.physics_domain:
            sections.append("fatigue_life_and_damage")

        if self.objective == AnalysisObjective.THERMAL_COMPLIANCE or "thermal" in self.physics_domain:
            sections.append("thermal_conduction_and_gradients")

        # Mandatory Governance & Evidence Sections
        sections.append("acceptance_gate_verdict")
        sections.append("engineering_interpretation")
        sections.append("provenance_and_audit_trail")

        return tuple(sections)

    def build_report_data(
        self,
        title: str,
        case_id: str,
        run_id: str,
        model_info: Dict[str, Any],
        results_info: Sequence[Any],
        acceptance_info: Any,
        figures: Sequence[ReportFigure] = (),
        interpretation_card: Optional[InterpretationCard] = None,
        solver_info: Optional[Dict[str, Any]] = None,
        mesh_info: Optional[Dict[str, Any]] = None,
        materials_info: Sequence[Dict[str, Any]] = (),
        loads_info: Sequence[Dict[str, Any]] = (),
        bcs_info: Sequence[Dict[str, Any]] = (),
        language: str = "bilingual",
    ) -> EngineeringReportData:
        """Deterministically assemble the polymorphic EngineeringReportData."""
        active_sections = self.determine_active_sections()

        # Build metadata with dynamic section list and localization settings
        meta: Dict[str, Any] = {
            "case_id": case_id,
            "run_id": run_id,
            "physics_domain": self.physics_domain,
            "objective": self.objective.value,
            "active_sections": list(active_sections),
            "language": language,
            "bilingual": language.lower() in ("bilingual", "dual", "zh_en"),
        }

        # Embed Interpretation Card if provided (read-only for LLM thoughts)
        assumptions: List[str] = []
        limitations: List[str] = []
        if interpretation_card:
            meta["interpretation_zh"] = interpretation_card.interpretation_zh
            meta["interpretation_en"] = interpretation_card.interpretation_en
            meta["engineering_observations"] = list(interpretation_card.engineering_observations)
            meta["risk_notes"] = list(interpretation_card.risk_notes)
            meta["recommendations"] = list(interpretation_card.recommendations)
            meta["design_recommendations"] = [
                {"title": f"工程对策 #{idx+1}", "details": rec, "benefit": "保障结构力学与服役安全裕度", "priority": "High"}
                for idx, rec in enumerate(interpretation_card.recommendations)
            ]
            limitations.extend(interpretation_card.risk_notes)

        # Objective description with embedded bilingual engineering interpretation
        objective_text = f"Evaluation of {self.physics_domain} performance against {self.objective.value} requirements."
        if interpretation_card:
            interp_blocks = []
            if interpretation_card.interpretation_zh:
                interp_blocks.append(f"**工程语义解释 / Engineering Interpretation (ZH)**:\n{interpretation_card.interpretation_zh}")
            if interpretation_card.interpretation_en:
                interp_blocks.append(f"**Engineering Interpretation (EN)**:\n{interpretation_card.interpretation_en}")
            if interpretation_card.engineering_observations:
                obs_text = "\n".join(f"- {obs}" for obs in interpretation_card.engineering_observations)
                interp_blocks.append(f"**关键工程观察 / Key Observations**:\n{obs_text}")
            if interp_blocks:
                objective_text = f"{objective_text}\n\n" + "\n\n".join(interp_blocks)

        # Objective-specific diagnostics injection (strictly from evidence, no forged constants)
        contact_diag = None
        fatigue_diag = None
        if "contact_pressure_and_closure" in active_sections:
            extracted_contact = model_info.get("contact_diagnostics")
            if isinstance(extracted_contact, dict):
                contact_diag = dict(extracted_contact)
            else:
                contact_diag = {
                    "max_cpress_mpa": model_info.get("max_cpress_mpa", "未提取 / 证据不足"),
                    "friction_formulation": model_info.get("friction_formulation", "未指定"),
                    "chatter_status": model_info.get("chatter_status", "未检测"),
                }
                # Only include closure_status when objective is bolted_sealing or domain involves sealing
                if self.objective == AnalysisObjective.BOLTED_SEALING or "sealing" in self.physics_domain:
                    contact_diag["closure_status"] = model_info.get("closure_status", "未评估 / 证据不足")
                else:
                    contact_diag["closure_status"] = "不适用 (非密封评估意图)"

        if "fatigue_life_and_damage" in active_sections:
            extracted_fatigue = model_info.get("fatigue_diagnostics") or model_info.get("fatigue")
            if isinstance(extracted_fatigue, dict):
                fatigue_diag = dict(extracted_fatigue)
            else:
                fatigue_diag = {
                    "fatigue_criterion": model_info.get("fatigue_criterion", "未指定 / 未评估"),
                    "minimum_cycles": model_info.get("minimum_cycles", "未计算 / 证据不足"),
                    "cumulative_damage": model_info.get("cumulative_damage", "未计算 / 证据不足"),
                    "safety_factor": model_info.get("safety_factor", "未计算 / 证据不足"),
                }

        resolved_solver = solver_info or {
            "solver_type": model_info.get("solver_type", "Abaqus/Standard"),
            "version": model_info.get("solver_version", "未指定 / 运行时检测"),
            "analysis_type": model_info.get("analysis_type", "未指定"),
        }
        resolved_mesh = mesh_info or {
            "total_elements": model_info.get("total_elements", "未统计"),
            "total_nodes": model_info.get("total_nodes", "未统计"),
            "element_type": model_info.get("element_type", "未指定"),
        }

        report_data = EngineeringReportData(
            title=title,
            objective=objective_text,
            model=model_info,
            solver=resolved_solver,
            materials=tuple(materials_info),
            boundary_conditions=tuple(bcs_info),
            loads=tuple(loads_info),
            mesh=resolved_mesh,
            results=tuple(results_info),
            figures=tuple(figures),
            acceptance=acceptance_info,
            contact_diagnostics=contact_diag,
            fatigue=fatigue_diag,
            assumptions=tuple(assumptions),
            limitations=tuple(limitations),
            metadata=meta,
        )

        return report_data
