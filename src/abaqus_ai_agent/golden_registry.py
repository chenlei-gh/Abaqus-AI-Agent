"""Unified Golden Case Registry and Catalog.

Defines the strongly typed registry of all real-machine engineering Golden Cases
(P0 Baseline, P1 Physics & Verification, MBD Rigid-Body and Multi-Body Dynamics).
Each definition captures analytical references, solvers, expected artifacts,
and nominal acceptance criteria alongside negative strict gates.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class GoldenCriterion:
    """Formal criterion for result acceptance in a Golden Case."""
    name: str
    value_key: str
    operator: str
    limit: Any
    unit: str = ""
    description: str = ""


@dataclass(frozen=True)
class GoldenCaseDefinition:
    """Strongly-typed declarative specification of an engineering Golden Case."""
    case_id: str
    title: str
    category: str  # "P0", "P1", "MBD"
    solver: str    # "standard", "explicit"
    physics_type: str
    tool_script: str
    default_evidence_json: str
    job_name: str
    analytical_reference: str
    summary: str
    criteria: Tuple[GoldenCriterion, ...] = ()
    strict_criteria: Tuple[GoldenCriterion, ...] = ()
    supported_releases: Tuple[str, ...] = ("Abaqus 2025",)
    verified_releases: Tuple[str, ...] = ("Abaqus 2025",)
    pending_releases: Tuple[str, ...] = ("Abaqus V5 R2018 / B28",)
    tags: Tuple[str, ...] = ()


def _build_standard_catalog() -> Tuple[GoldenCaseDefinition, ...]:
    return (
        GoldenCaseDefinition(
            case_id="smoke",
            title="Abaqus Runtime & Solver Artifact Smoke",
            category="P0",
            solver="standard",
            physics_type="linear_static",
            tool_script="tools/b28_smoke.py",
            default_evidence_json="machine_validation/b28_smoke.json",
            job_name="AIAgent_B28Smoke",
            analytical_reference="Baseline solver execution, .sta/.log closure, ODB creation and field output inspection",
            summary="Validates live Abaqus launcher invocation, batch script execution, solver process completion, and ODB field readability.",
            criteria=(
                GoldenCriterion("process_succeeded", "process_succeeded", "==", True, "", "Launcher return code 0 and successful process run"),
                GoldenCriterion("solver_completed", "solver_completed", "==", True, "", "Abaqus solver completed via .sta/.log evidence"),
                GoldenCriterion("odb_readable", "odb_readable", "==", True, "", "ODB generated and target step/frames opened"),
                GoldenCriterion("required_outputs_present", "required_outputs_present", "==", True, "", "Required primary field outputs (U, RF) present"),
            ),
            tags=("smoke", "runtime", "baseline"),
        ),
        GoldenCaseDefinition(
            case_id="static_cantilever",
            title="3D Cantilever Beam Linear Static Golden E2E",
            category="P0",
            solver="standard",
            physics_type="linear_static",
            tool_script="tools/static_golden_e2e.py",
            default_evidence_json="machine_validation/static_golden_e2e.json",
            job_name="StaticGoldenJob",
            analytical_reference="Euler-Bernoulli cantilever tip deflection PL^3/(3EI) = 1.9048 mm, root bending stress 600 MPa, reaction balance = 1000 N",
            summary="Full E2E cantilever beam under transverse tip load with reaction balance, tip deflection, and root stress sanity checks.",
            criteria=(
                GoldenCriterion("tip_displacement_lower", "tip_displacement", ">=", 1.6, "mm", "Tip deflection lower bound vs Euler-Bernoulli"),
                GoldenCriterion("tip_displacement_upper", "tip_displacement", "<=", 2.2, "mm", "Tip deflection upper bound vs Euler-Bernoulli"),
                GoldenCriterion("reaction_balance_RF2", "reaction_balance_y_rel_error", "<=", 0.01, "", "Global vertical reaction balance error <= 1%"),
                GoldenCriterion("root_mises_sanity", "root_mises", "<=", 1200.0, "MPa", "Root element Mises stress sanity bound"),
            ),
            tags=("static", "beam", "elasticity", "acceptance"),
        ),
        GoldenCaseDefinition(
            case_id="mesh_convergence",
            title="3D Cantilever 3-Level Mesh Convergence & GCI E2E",
            category="P0",
            solver="standard",
            physics_type="linear_static",
            tool_script="tools/mesh_convergence_e2e.py",
            default_evidence_json="machine_validation/mesh_convergence_e2e.json",
            job_name="MeshConv_Fine",
            analytical_reference="Richardson extrapolation & Roache Grid Convergence Index (GCI)",
            summary="Three-level mesh refinement (Coarse 80 -> Medium 640 -> Fine 5120 elements) with formal GCI evaluation and negative strict gate.",
            criteria=(
                GoldenCriterion("gci_acceptable", "gci", "<=", 0.05, "", "Roache Grid Convergence Index <= 5% (observed ~1.03%)"),
                GoldenCriterion("tip_displacement_sanity", "tip_displacement", ">=", 1.0, "mm", "Displacement sanity on fine mesh"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_gci_limit", "gci", "<=", 0.005, "", "Strict negative gate limit <= 0.5% designed to fail"),
            ),
            tags=("mesh", "convergence", "gci", "numerical_verification"),
        ),
        GoldenCaseDefinition(
            case_id="tie_contact",
            title="Two-Block Tied Cantilever Kinematic Continuity E2E",
            category="P1",
            solver="standard",
            physics_type="contact_tie",
            tool_script="tools/tie_contact_e2e.py",
            default_evidence_json="machine_validation/tie_contact_e2e.json",
            job_name="TieContactJob",
            analytical_reference="Kinematic continuity across tied interface (ΔU = 0), reaction balance = 1000 N",
            summary="Two segmented cantilever blocks bonded via Tie interaction verifying zero interface displacement jump and full load transfer.",
            criteria=(
                GoldenCriterion("max_interface_relative_disp", "max_interface_relative_disp", "<=", 1e-4, "mm", "Interface relative displacement jump <= 1e-4 mm (observed 0.0)"),
                GoldenCriterion("global_load_balance_RF2", "reaction_balance_y_rel_error", "<=", 0.01, "", "Global reaction balance error <= 1%"),
                GoldenCriterion("tip_displacement_lower", "tip_displacement", ">=", 1.6, "mm", "Tip deflection sanity lower bound"),
            ),
            tags=("contact", "tie", "assembly", "kinematics"),
        ),
        GoldenCaseDefinition(
            case_id="implicit_dynamic",
            title="Implicit Dynamic Transient Cantilever Beam E2E",
            category="P1",
            solver="standard",
            physics_type="implicit_dynamic",
            tool_script="tools/dynamic_golden_e2e.py",
            default_evidence_json="machine_validation/dynamic_golden_e2e.json",
            job_name="DynamicGoldenJob",
            analytical_reference="Dynamic load factor (DLF) for ramp loading, energy conservation (ALLKE, ALLSE, ALLWK, ALLIE)",
            summary="Multi-frame transient dynamic step under ramped tip loading with dynamic amplification factor and energy ratio auditing.",
            criteria=(
                GoldenCriterion("frame_count_minimum", "frame_count", ">=", 20, "", "Minimum number of transient time frames in ODB"),
                GoldenCriterion("dynamic_amplification_lower", "dynamic_amplification_factor", ">=", 1.0, "", "Dynamic load factor lower bound"),
                GoldenCriterion("dynamic_amplification_upper", "dynamic_amplification_factor", "<=", 1.5, "", "Dynamic load factor upper bound (observed 1.13)"),
                GoldenCriterion("max_kinetic_energy_ratio", "max_kinetic_energy_ratio", "<=", 0.01, "", "Kinetic energy to internal energy ratio bound"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_max_kinetic_energy_ratio", "max_kinetic_energy_ratio", "<=", 1e-6, "", "Strict negative gate limit <= 1e-6"),
            ),
            tags=("dynamic", "transient", "amplitude", "energy"),
        ),
        GoldenCaseDefinition(
            case_id="steady_thermal",
            title="1D Steady-State Heat Conduction Bar E2E",
            category="P1",
            solver="standard",
            physics_type="steady_thermal",
            tool_script="tools/thermal_golden_e2e.py",
            default_evidence_json="machine_validation/thermal_golden_e2e.json",
            job_name="ThermalGoldenJob",
            analytical_reference="Fourier 1D conduction T(x) = T_hot - (T_hot - T_cold)*(x/L), flux balance Q_in + Q_out = 0",
            summary="Pure heat transfer step on DC3D8 mesh with temperature BCs verifying exact linear gradient and reaction heat flux balance.",
            criteria=(
                GoldenCriterion("midpoint_temperature", "midpoint_temperature", "==", 50.0, "C", "Midpoint temperature exact theoretical value (observed error < 1e-14)"),
                GoldenCriterion("net_flux_balance_rel_error", "net_flux_balance_rel_error", "<=", 0.01, "", "Reaction heat flux conservation relative error <= 1%"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_temperature_tolerance", "midpoint_temperature_abs_error", "<=", 1e-16, "C", "Strict negative gate limit <= 1e-16 C"),
            ),
            tags=("thermal", "heat_transfer", "flux", "analytical"),
        ),
        GoldenCaseDefinition(
            case_id="general_contact",
            title="Two-Body General Frictional Sliding Contact E2E",
            category="P1",
            solver="standard",
            physics_type="general_contact_friction",
            tool_script="tools/general_contact_e2e.py",
            default_evidence_json="machine_validation/general_contact_e2e.json",
            job_name="GeneralContactJob",
            analytical_reference="Coulomb friction law F_f = μ F_N (μ=0.25), normal & tangential equilibrium",
            summary="Two-body contact interaction under compression and tangential slide verifying Coulomb friction law and contact pressure/opening.",
            criteria=(
                GoldenCriterion("min_cpress", "min_cpress", ">=", 1.0, "MPa", "Positive contact pressure across interface"),
                GoldenCriterion("max_copen", "max_copen", "<=", 0.01, "mm", "Zero contact opening / separation during active contact"),
                GoldenCriterion("effective_friction_mu_lower", "effective_friction_mu", ">=", 0.20, "", "Effective friction coefficient lower bound"),
                GoldenCriterion("effective_friction_mu_upper", "effective_friction_mu", "<=", 0.30, "", "Effective friction coefficient upper bound (nominal 0.25, error 0.08%)"),
                GoldenCriterion("normal_equilibrium_rel_error", "normal_equilibrium_rel_error", "<=", 0.01, "", "Normal equilibrium error <= 1%"),
                GoldenCriterion("tangential_equilibrium_rel_error", "tangential_equilibrium_rel_error", "<=", 0.01, "", "Tangential equilibrium error <= 1%"),
            ),
            tags=("contact", "friction", "coulomb", "diagnostics"),
        ),
        GoldenCaseDefinition(
            case_id="mbd1_rigid_pendulum",
            title="MBD-1 Rigid-Body Physical Pendulum Dynamics E2E",
            category="MBD",
            solver="standard",
            physics_type="rigid_body_dynamics",
            tool_script="tools/mbd_golden_e2e.py",
            default_evidence_json="machine_validation/mbd_golden_e2e.json",
            job_name="MBDGoldenJob",
            analytical_reference="Physical pendulum finite-amplitude period T = 1.2713 s (L=600 mm, θ_0=10 deg), energy conservation",
            summary="Single rigid-body pendulum constrained to reference point hinge under gravity verifying large-angle period and mechanical energy.",
            criteria=(
                GoldenCriterion("period_rel_error", "period_rel_error", "<=", 0.02, "", "Pendulum period relative error <= 2% (observed 0.08%)"),
                GoldenCriterion("angular_velocity_rel_error", "angular_velocity_rel_error", "<=", 0.02, "", "Max angular velocity relative error <= 2% (observed 0.27%)"),
                GoldenCriterion("energy_loss_ratio", "energy_loss_ratio", "<=", 0.05, "", "Mechanical energy loss ratio <= 5% (observed 2.41%)"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_period_error", "period_rel_error", "<=", 0.0001, "", "Strict negative gate limit <= 0.01%"),
            ),
            tags=("mbd", "rigid_body", "pendulum", "dynamics"),
        ),
        GoldenCaseDefinition(
            case_id="mbd2_double_pendulum",
            title="MBD-2 Dual Rigid-Body Revolute Connector (CONN3D2 Hinge) E2E",
            category="MBD",
            solver="standard",
            physics_type="multibody_revolute_connector",
            tool_script="tools/mbd2_revolute_golden_e2e.py",
            default_evidence_json="machine_validation/mbd2_revolute_golden_e2e.json",
            job_name="MBD2GoldenJob",
            analytical_reference="Dual rigid pendulum linear mode period T_1 = 1.2843 s, kinematic joint drift limit <= 1e-3 mm",
            summary="Two rigid bodies linked via native CONN3D2 Hinge connector with local orientation verifying joint drift, articulation, and energy.",
            criteria=(
                GoldenCriterion("max_joint_drift", "max_joint_drift", "<=", 1e-3, "mm", "Revolute joint translational drift <= 1e-3 mm (observed 9.78e-6 mm)"),
                GoldenCriterion("max_relative_rotation", "max_relative_rotation_deg", ">=", 2.0, "deg", "Significant relative hinge articulation >= 2 deg (observed 6.96 deg)"),
                GoldenCriterion("period_rel_error", "period_rel_error", "<=", 0.03, "", "Fundamental period relative error <= 3% (observed 0.54%)"),
                GoldenCriterion("energy_loss_ratio", "energy_loss_ratio", "<=", 0.03, "", "Mechanical energy loss ratio <= 3% (observed 2.13%)"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_joint_drift", "max_joint_drift", "<=", 1e-8, "mm", "Strict negative gate drift <= 1e-8 mm"),
            ),
            tags=("mbd", "connector", "revolute", "conn3d2", "hinge"),
        ),
    )


class GoldenMatrixCatalog:
    """Registry catalog for managing, inspecting, and filtering Golden Cases."""

    def __init__(self, cases: Optional[Sequence[GoldenCaseDefinition]] = None):
        self._cases: Tuple[GoldenCaseDefinition, ...] = tuple(cases) if cases is not None else _build_standard_catalog()
        self._by_id: Dict[str, GoldenCaseDefinition] = {c.case_id: c for c in self._cases}

    def all_cases(self) -> Tuple[GoldenCaseDefinition, ...]:
        return self._cases

    def case_ids(self) -> Tuple[str, ...]:
        return tuple(self._cases[i].case_id for i in range(len(self._cases)))

    def get_case(self, case_id: str) -> Optional[GoldenCaseDefinition]:
        return self._by_id.get(case_id)

    def require_case(self, case_id: str) -> GoldenCaseDefinition:
        case = self.get_case(case_id)
        if case is None:
            available = ", ".join(self.case_ids())
            raise KeyError(f"Unknown golden case_id: '{case_id}'. Available: {available}")
        return case

    def cases_by_category(self, category: str) -> Tuple[GoldenCaseDefinition, ...]:
        cat_upper = category.upper()
        return tuple(c for c in self._cases if c.category.upper() == cat_upper)

    def cases_by_solver(self, solver: str) -> Tuple[GoldenCaseDefinition, ...]:
        solv_lower = solver.lower()
        return tuple(c for c in self._cases if c.solver.lower() == solv_lower)

    def count(self) -> int:
        return len(self._cases)


# Global singleton instance for convenient access
standard_golden_catalog = GoldenMatrixCatalog()
