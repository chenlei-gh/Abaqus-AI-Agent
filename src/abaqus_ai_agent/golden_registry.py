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
    pending_releases: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()


def _build_standard_catalog() -> Tuple[GoldenCaseDefinition, ...]:
    return (
        GoldenCaseDefinition(
            case_id="smoke",
            title="Abaqus Live Runtime & Solver Artifact Smoke",
            category="P0",
            solver="standard",
            physics_type="linear_static",
            tool_script="tools/runtime_smoke.py",
            default_evidence_json="machine_validation/runtime_smoke.json",
            job_name="AIAgent_RuntimeSmoke",
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
        GoldenCaseDefinition(
            case_id="fmbd4_rigid_flexible",
            title="FMBD-4 Coupled Rigid-Flexible Mechanism Dynamics E2E",
            category="FMBD",
            solver="standard",
            physics_type="flexible_multibody_dynamics",
            tool_script="tools/fmbd4_rigid_flexible_golden_e2e.py",
            default_evidence_json="machine_validation/fmbd4_rigid_flexible_golden_e2e.json",
            job_name="FMBD4GoldenJob",
            analytical_reference="Coupled rigid crank and C3D8R flexible link under gravity, CONN3D2 Hinge drift <= 1e-3 mm, active elastic strain energy participation ALLSE/ALLIE >= 1%, dynamic stress sanity 0.01 <= Mises <= 100 MPa",
            summary="Coupled rigid-flexible mechanism linked by native CONN3D2 Hinge and Kinematic Coupling constraint verifying joint drift, flexible body stress, and dynamic energy conservation.",
            criteria=(
                GoldenCriterion("joint_drift", "max_joint_drift_mm", "<=", 1e-3, "mm", "CONN3D2 Hinge translational drift <= 1e-3 mm"),
                GoldenCriterion("max_mises_stress_lower", "max_mises_stress_mpa", ">=", 0.01, "MPa", "Dynamic stress sanity lower bound"),
                GoldenCriterion("max_mises_stress_upper", "max_mises_stress_mpa", "<=", 100.0, "MPa", "Dynamic stress sanity upper bound"),
                GoldenCriterion("strain_energy_active", "strain_energy_ratio", ">=", 0.01, "", "Flexible body dynamic strain energy participation"),
                GoldenCriterion("energy_dissipation", "energy_dissipation_ratio", "<=", 0.05, "", "Mechanical energy conservation <= 5% dissipation"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_joint_drift", "max_joint_drift_mm", "<=", 1e-15, "mm", "Strict negative gate limit <= 1e-15 mm"),
            ),
            tags=("fmbd", "flexible", "rigid_flexible", "coupling", "connector", "dynamics"),
        ),
        GoldenCaseDefinition(
            case_id="fmbd5_crank_slider",
            title="FMBD-5 Closed-Loop Rigid-Flexible Crank-Slider Mechanism Dynamics E2E",
            category="FMBD",
            solver="standard",
            physics_type="flexible_multibody_dynamics",
            tool_script="tools/fmbd5_crank_slider_golden_e2e.py",
            default_evidence_json="machine_validation/fmbd5_crank_slider_golden_e2e.json",
            job_name="FMBD5GoldenJob",
            analytical_reference="Closed-loop rigid crank, C3D8R flexible rod, and rigid slider mechanism compiled purely from MechanismGraph; kinematic loop closure <= 0.05, joint drift <= 1e-3 mm, slider transverse drift <= 1e-2 mm, dynamic stress sanity 0.01 <= Mises <= 150 MPa, internal energy composition ALLSE/ALLIE >= 0.5%, algorithmic numerical dissipation -ETOTAL_min/max(ALLWK, ALLKE) <= 50%",
            summary="Full-cycle closed-loop crank-slider mechanism consisting of ground pivot, rotating rigid crank, C3D8R elastic rod with dual kinematic couplings, Revolute/Hinge connectors, and horizontal Translator slider guide under gravity, compiled 100% via MechanismGraph under MODERATE_DISSIPATION.",
            criteria=(
                GoldenCriterion("joint_drift", "max_joint_drift_mm", "<=", 1e-3, "mm", "Hinge translational joint drift <= 1e-3 mm"),
                GoldenCriterion("slider_transverse_drift", "max_slider_y_drift_mm", "<=", 1e-2, "mm", "Slider transverse drift bound <= 1e-2 mm"),
                GoldenCriterion("loop_closure_error", "max_loop_closure_error", "<=", 0.05, "", "Kinematic loop closure error <= 5%"),
                GoldenCriterion("max_mises_stress_lower", "max_mises_stress_mpa", ">=", 0.01, "MPa", "Dynamic stress sanity lower bound"),
                GoldenCriterion("max_mises_stress_upper", "max_mises_stress_mpa", "<=", 150.0, "MPa", "Dynamic stress sanity upper bound"),
                GoldenCriterion("strain_energy_active", "strain_energy_ratio", ">=", 0.005, "", "Internal energy composition: elastic strain energy ratio ALLSE/ALLIE >= 0.5%"),
                GoldenCriterion("energy_dissipation", "energy_dissipation_ratio", "<=", 0.50, "", "Algorithmic numerical damping dissipation bounded <= 50% under MODERATE_DISSIPATION"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_joint_drift", "max_joint_drift_mm", "<=", 1e-15, "mm", "Strict negative gate limit <= 1e-15 mm"),
            ),
            tags=("fmbd", "closed_loop", "crank_slider", "coupling", "connector", "translator", "mechanism_graph"),
        ),
        GoldenCaseDefinition(
            case_id="explicit_dynamic",
            title="3D Cantilever Beam Explicit Transient Dynamic Golden E2E",
            category="P1",
            solver="explicit",
            physics_type="explicit_dynamic",
            tool_script="tools/explicit_golden_e2e.py",
            default_evidence_json="machine_validation/explicit_golden_e2e.json",
            job_name="ExplicitGoldenJob",
            analytical_reference="Abaqus/Explicit dynamic wave propagation, stable time increment dt <= Le/cd, total energy conservation (|ETOTAL|/E_ref <= 2%), and C3D8R hourglass energy control (ALLAE/ALLIE <= 5%)",
            summary="Abaqus/Explicit transient dynamic analysis of a 3D cantilever beam under ramped step load, verifying *DYNAMIC, EXPLICIT, stable time increment, multi-frame ODB history, total energy balance (ALLKE, ALLIE, ALLWK, ALLSE, ALLAE, ETOTAL), and hourglass control.",
            criteria=(
                GoldenCriterion("stable_increment_upper_bound", "stable_increment_s", "<=", 2.0e-6, "s", "Explicit stable time increment bounded by CFL condition dt <= Le/cd"),
                GoldenCriterion("stable_increment_lower_bound", "stable_increment_s", ">=", 1.0e-8, "s", "Stable time increment positive and reasonable"),
                GoldenCriterion("energy_drift_ratio", "energy_drift_ratio", "<=", 0.02, "", "Explicit total energy drift |ETOTAL| / max(ALLWK, ALLKE) <= 2.0%"),
                GoldenCriterion("hourglass_energy_ratio", "hourglass_to_internal_energy_ratio", "<=", 0.05, "", "C3D8R artificial hourglass energy ratio ALLAE / ALLIE <= 5.0%"),
                GoldenCriterion("peak_displacement_bound", "peak_displacement_mm", "<=", 5.0, "mm", "Dynamic tip displacement bounded under step load"),
                GoldenCriterion("peak_displacement_positive", "peak_displacement_mm", ">=", 0.5, "mm", "Dynamic tip displacement positive"),
            ),
            strict_criteria=(
                GoldenCriterion("hourglass_unphysical_strict", "hourglass_to_internal_energy_ratio", "<=", 1.0e-10, "", "Unphysical strict limit on hourglass ratio to verify deterministic rejection"),
            ),
            tags=("explicit", "dynamic", "cfl", "energy_balance", "hourglass"),
        ),
        GoldenCaseDefinition(
            case_id="fatigue_real_odb",
            title="Real ODB Stress History Fatigue Damage & Rainflow E2E",
            category="P2",
            solver="postprocess",
            physics_type="fatigue_postprocess",
            tool_script="tools/fatigue_odb_golden_e2e.py",
            default_evidence_json="machine_validation/fatigue_odb_golden_e2e.json",
            job_name="DynamicGoldenJob",
            analytical_reference="ASTM E1049-85 Rainflow cycle counting, Goodman mean-stress correction, log-log S-N interpolation, and Palmgren-Miner linear cumulative damage",
            summary="Real Abaqus ODB post-processing establishing automatic hotspot identification, multi-frame stress tensor time history extraction, Signed von Mises reduction, rainflow cycle counting, Goodman mean-stress correction, and Palmgren-Miner cumulative fatigue damage.",
            criteria=(
                GoldenCriterion("has_stress_history", "frame_count", ">=", 2, "", "Stress history contains at least 2 time frames"),
                GoldenCriterion("rainflow_cycles_counted", "total_cycles_count", ">=", 1.0, "", "At least one rainflow cycle event detected"),
                GoldenCriterion("cumulative_damage_positive", "cumulative_damage", ">=", 0.0, "", "Cumulative Miner damage is non-negative"),
                GoldenCriterion("cumulative_damage_allowable", "cumulative_damage", "<=", 1.0, "", "Cumulative Miner damage within fatigue allowable D <= 1.0"),
            ),
            strict_criteria=(
                GoldenCriterion("strict_damage_threshold", "cumulative_damage", "<=", 1.0e-15, "", "Strict negative gate limit D <= 1.0e-15"),
            ),
            tags=("fatigue", "odb", "rainflow", "goodman", "miner", "postprocess"),
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
