"""Solver selection: bilingual physics-event cues drive the compiled procedure,
and CPU counts are evidence-derived rather than invented.

Chinese literals are written as unicode escapes so the file is ASCII-safe.
"""

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.solver_selection import select_solver
from abaqus_ai_agent.execution.solver_config import calculate_adaptive_cpus
from abaqus_ai_agent.planning.compiler import compile_engineering_intent

# M1FA knob slip-out analysis
SLIPOUT_DESC = "M1FA \u65cb\u94ae\u8131\u51fa\u5206\u6790"
# snap-fit insert/pull force analysis
SNAPFIT_DESC = "\u5361\u6263\u63d2\u62d4\u529b\u5206\u6790"
# knob slip-out large-deformation analysis
SLIPOUT_LD_DESC = "\u65cb\u94ae\u8131\u51fa\u5927\u53d8\u5f62\u5206\u6790"


def _intent(description, kind="linear_static"):
    return EngineeringIntent(
        id="INTENT-SOLVER-SEL",
        kind=kind,
        description=description,
        material={
            "name": "Steel_Q235",
            "elastic_modulus": 210000.0,
            "poisson_ratio": 0.3,
            "unit": "MPa",
        },
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        mesh_requirements={
            "global_size": 2.5,
            "primary_wall_thickness": 2.5,
            "primary_wall_thickness_source": "USER_SPECIFIED",
        },
        metadata={"dimensions": {"shape": "cantilever_box", "length": 150.0, "width": 15.0, "height": 10.0}},
    )


def test_chinese_slipout_cue_selects_explicit_quasi_static():
    """Slip-out (\u8131\u51fa) is the canonical Explicit quasi-static event; the
    Chinese term must reach the same decision as the English 'pull-out'."""
    selection = select_solver(_intent(SLIPOUT_DESC))
    assert selection.solver == "EXPLICIT"
    assert selection.strategy == "QUASI_STATIC_EXPLICIT"
    assert selection.requires_user_confirmation is True


def test_english_pullout_cue_matches_chinese():
    zh = select_solver(_intent(SNAPFIT_DESC))
    en = select_solver(_intent("snap-fit pull-out force analysis"))
    assert zh.solver == en.solver == "EXPLICIT"
    assert zh.strategy == en.strategy == "QUASI_STATIC_EXPLICIT"


def test_plain_static_still_selects_standard():
    selection = select_solver(_intent("Cantilever beam under vertical tip load"))
    assert selection.solver == "STANDARD"
    assert selection.strategy == "STATIC_GENERAL"


def test_compiled_step_follows_selection_for_slipout():
    """The compiled procedure must follow the selection; the old code compiled
    StaticStep regardless of what the selector decided."""
    plan = compile_engineering_intent(_intent(SLIPOUT_LD_DESC))
    assert "ExplicitDynamicsStep" in plan.cae_script
    sel = plan.intent_summary["solver_selection"]
    assert sel["strategy"] == "QUASI_STATIC_EXPLICIT"
    assert sel["solver"] == "EXPLICIT"
    assert sel["requires_user_confirmation"] is True
    assert plan.intent_summary["step_types"] == ["explicit_dynamic"]


def test_compiled_step_stays_static_without_event_cues():
    plan = compile_engineering_intent(_intent("Cantilever beam under vertical tip load"))
    assert "StaticStep" in plan.cae_script
    sel = plan.intent_summary["solver_selection"]
    assert sel["strategy"] == "STATIC_GENERAL"


def test_explicit_large_model_may_use_extended_cpu_tiers():
    host = {"logical_cpu_count": 24, "physical_cpu_count": None}
    cpus, evidence, reason = calculate_adaptive_cpus(
        host_hardware=host, solver_type="EXPLICIT", element_count=200000,
    )
    # 200k elements / 12k per domain = 16, capped by headroom 12 -> tier 12
    assert cpus == 12
    assert "explicit domain parallelism" in reason


def test_standard_never_exceeds_eight_cores():
    host = {"logical_cpu_count": 24, "physical_cpu_count": None}
    cpus, _, _ = calculate_adaptive_cpus(
        host_hardware=host, solver_type="STANDARD", element_count=200000,
    )
    assert cpus == 8


def test_m1fa_scale_explicit_model_selects_eight_cores():
    host = {"logical_cpu_count": 24, "physical_cpu_count": None}
    cpus, _, reason = calculate_adaptive_cpus(
        host_hardware=host, solver_type="EXPLICIT", element_count=98557,
    )
    assert cpus == 8
    assert "98557 elements" in reason
