"""Comprehensive verification of the end-to-end Material Intelligence integration.

Tests that all materials across the compiler, reasoning catalog, workflows,
agent solving, and report rendering are grounded in physical standards (ISO/GB/ASTM),
verified constants, and fail-closed validation.
"""

from typing import Any, ClassVar
import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import MaterialDefinition
from abaqus_ai_agent.planning.compiler import (
    IntentBoundarySpec,
    IntentGeometrySpec,
    IntentLoadSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)
from abaqus_ai_agent.reasoning.material_catalog import (
    resolve_material_to_definition,
)
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.reporting.renderer import render_html, render_markdown
from abaqus_ai_agent.workflow.contact import build_contact_plan
from abaqus_ai_agent.workflow.static import build_static_plan


# =====================================================================
# 1. Material Catalog Resolution & Normalization Tests
# =====================================================================

def test_resolve_material_string_profiles():
    """Verify common engineering material strings resolve to verified MaterialDefinitions."""
    cases = [
        ("Q235", "Q235", 210000.0, 0.30, 235.0, "GB/T 700-2006"),
        ("q235b", "Q235", 210000.0, 0.30, 235.0, "GB/T 700-2006"),
        ("Steel", "Structural_Steel", 210000.0, 0.30, 250.0, "ISO 630 / ASTM A36"),
        ("45号钢", "Steel_45", 210000.0, 0.29, 355.0, "GB/T 699-2015"),
        ("Aluminum_6061_T6", "Aluminum_6061_T6", 68900.0, 0.33, 276.0, "ASTM B221"),
        ("304不锈钢", "Stainless_Steel_304", 193000.0, 0.29, 205.0, "ASTM A240"),
        ("TC4", "Titanium_TC4", 113800.0, 0.34, 880.0, "GB/T 3620.1"),
        ("PA66", "PA66", 2800.0, 0.38, 80.0, "ISO 16396-PA66"),
    ]
    for query, expected_name, expected_e, expected_nu, expected_sy, ref_keyword in cases:
        mat_def = resolve_material_to_definition(query, fail_closed=True)
        assert mat_def is not None
        assert mat_def.name == expected_name
        assert mat_def.elastic is not None
        assert mat_def.elastic.youngs_modulus == pytest.approx(expected_e)
        assert mat_def.elastic.poisson_ratio == pytest.approx(expected_nu)
        assert mat_def.plastic is not None
        assert mat_def.plastic.yield_stress == pytest.approx(expected_sy)
        assert ref_keyword in mat_def.provenance


def test_resolve_material_incomplete_dict_enriched():
    """Verify incomplete dictionaries (e.g. only name) are enriched with catalog standards."""
    incomplete = {"name": "Q235"}
    mat_def = resolve_material_to_definition(incomplete, fail_closed=True)
    assert mat_def is not None
    assert mat_def.name == "Q235"
    assert mat_def.elastic is not None
    assert mat_def.elastic.youngs_modulus == 210000.0
    assert mat_def.density == pytest.approx(7.85e-9)
    assert mat_def.plastic is not None
    assert mat_def.plastic.yield_stress == 235.0
    assert "GB/T 700-2006" in mat_def.provenance


def test_resolve_material_custom_dict_preserved():
    """Verify custom material properties with non-standard values are faithfully preserved."""
    custom = {
        "name": "Custom_Titanium_Alloy",
        "youngs_modulus": 115000.0,
        "poisson": 0.32,
        "density": 4.5e-9,
        "yield_strength": 920.0,
        "provenance": "Lab Tensile Test Report #2026-X",
    }
    mat_def = resolve_material_to_definition(custom, fail_closed=True)
    assert mat_def is not None
    assert mat_def.name == "Custom_Titanium_Alloy"
    assert mat_def.elastic is not None
    assert mat_def.elastic.youngs_modulus == 115000.0
    assert mat_def.elastic.poisson_ratio == 0.32
    assert mat_def.density == 4.5e-9
    assert mat_def.plastic is not None
    assert mat_def.plastic.yield_stress == 920.0
    assert mat_def.provenance == "Lab Tensile Test Report #2026-X"


def test_resolve_material_fail_closed_on_unrecognized():
    """Verify unknown or unphysical material strings trigger fail-closed exception."""
    with pytest.raises(ValueError, match="Unrecognized engineering material"):
        resolve_material_to_definition("Unobtanium_Vibranium_Mythical_999", fail_closed=True)

    with pytest.raises(ValueError, match="missing material specification"):
        resolve_material_to_definition(None, fail_closed=True)


# =====================================================================
# 2. Compiler Integration Tests
# =====================================================================

def test_compile_engineering_intent_with_string_material():
    """Verify compile_engineering_intent seamlessly resolves material string 'Q235'."""
    intent = EngineeringIntent(
        id="T_MAT_1",
        kind="linear_static",
        analysis_type="linear_static",
        description="Steel cantilever beam",
        material="Q235",
        loads=(IntentLoadSpec(name="P", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(IntentBoundarySpec(name="Fix", bc_type="ENCASTRE", region="RootFace"),),
        metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
    )
    plan = compile_engineering_intent(intent)
    assert plan is not None
    assert plan.material is not None
    assert plan.material.name == "Q235"
    assert plan.material.elastic is not None
    assert plan.material.elastic.youngs_modulus == 210000.0
    assert plan.material.plastic is not None
    assert plan.material.plastic.yield_stress == 235.0
    assert "GB/T 700-2006" in plan.material.provenance

    # Verify CAE script contains generated Abaqus material commands
    assert "model.Material('Q235')" in plan.cae_script
    assert "210000.0" in plan.cae_script
    assert "7.85e-09" in plan.cae_script


def test_compile_intent_to_actions_with_string_and_dict():
    """Verify compile_intent_to_actions accepts string, dict, or MaterialDefinition directly."""
    geom = IntentGeometrySpec(shape="cantilever_box", length=50.0, width=5.0, height=5.0)

    # 1. String
    plan_str = compile_intent_to_actions(
        model_name="M1", part_name="P1", job_name="J1",
        geometry=geom, material="Aluminum_6061_T6",
    )
    assert plan_str.material is not None
    assert plan_str.material.name == "Aluminum_6061_T6"
    assert plan_str.material.elastic is not None
    assert plan_str.material.elastic.youngs_modulus == 68900.0

    # 2. Dict with aliases
    plan_dict = compile_intent_to_actions(
        model_name="M2", part_name="P2", job_name="J2",
        geometry=geom, material={"name": "Steel_45"},
    )
    assert plan_dict.material is not None
    assert plan_dict.material.name == "Steel_45"
    assert plan_dict.material.elastic is not None
    assert plan_dict.material.elastic.youngs_modulus == 210000.0


# =====================================================================
# 3. Workflows Integration Tests
# =====================================================================

def test_static_workflow_accepts_string_and_material_definition():
    """Verify build_static_plan works with string or MaterialDefinition."""
    # With string
    plan1 = build_static_plan(
        model_name="StaticM",
        material="Q235",
        region_map={"section": "AllCells", "fixed": "FixFace", "load": "LoadFace"},
    )
    assert plan1.material is not None
    assert isinstance(plan1.material, MaterialDefinition)
    assert plan1.material.name == "Q235"
    action_types = [a.action_type for a in plan1.actions]
    assert "material_elastic" in action_types
    assert "material_density" in action_types

    # With MaterialDefinition
    mat_def = resolve_material_to_definition("304不锈钢")
    assert mat_def is not None
    plan2 = build_static_plan(
        model_name="StaticM2",
        material=mat_def,
        region_map={"section": "AllCells"},
    )
    assert plan2.material is not None
    assert plan2.material.name == "Stainless_Steel_304"


def test_contact_workflow_accepts_material_string():
    """Verify build_contact_plan normalizes material correctly."""
    plan = build_contact_plan(
        model_name="ContactM",
        material="TC4",
        region_map={"master_surface": "SurfM", "slave_surface": "SurfS"},
    )
    assert plan is not None
    assert any(a.action_type == "material_elastic" and a.parameters["name"] == "Titanium_TC4" for a in plan.actions)


# =====================================================================
# 4. Report Chapter 3 Material Rendering Tests
# =====================================================================

def test_report_pipeline_renders_chapter_3_material_specifications(tmp_path):
    """Verify Chapter 3 ('Material Constitutive Specifications') renders standard metadata and tables."""
    mat_def = resolve_material_to_definition("Q235")
    assert mat_def is not None
    pipeline = DeterministicReportPipeline()

    class MockAcceptance:
        status: str = "PASS"
        passed: bool = True
        deliverable: bool = True
        gate_summary: ClassVar[dict[str, Any]] = {"status": "PASS"}

    _, _, report_data = pipeline.build_and_render(
        output_dir=tmp_path,
        title="Engineering Verification Report",
        case_id="MAT-VERIFY-01",
        run_id="RUN-MAT-01",
        model_info={"name": "BeamModel"},
        results_info=[{"metric": "max_mises", "value": 150.0}],
        acceptance_info=MockAcceptance(),
        materials_info=[mat_def.to_dict()],
        require_deliverable=False,
    )

    # 1. Check report_data contains materials
    assert len(report_data.materials) == 1
    m0 = report_data.materials[0]
    assert m0["name"] == "Q235"
    assert m0["elastic"]["youngs_modulus"] == 210000.0
    assert m0["provenance"] == "GB/T 700-2006"

    # 2. Check rendered Markdown output contains Chapter 3
    md_content = render_markdown(report_data, language="bilingual")
    assert "3. Material" in md_content
    assert "材料本构规范与高温温变物性" in md_content
    assert "Q235" in md_content
    assert "GB/T 700-2006" in md_content
    assert "210,000 MPa" in md_content
    assert "235.0 MPa" in md_content

    # 3. Check rendered HTML output contains Chapter 3
    html_content = render_html(report_data, language="bilingual")
    assert "3. Material" in html_content
    assert "Q235" in html_content
    assert "GB/T 700-2006" in html_content
