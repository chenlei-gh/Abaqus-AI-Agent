import pytest

from abaqus_ai_agent.contracts.element_strategy import ElementStrategy, resolve_element_code
from abaqus_ai_agent.actions import element_strategy
from abaqus_ai_agent.actions.runner import preview
from abaqus_ai_agent.validation.actions import validate_action


def test_common_3d_hex_strategy_resolves():
    strategy = ElementStrategy("continuum", "3d", "hex", "linear", "reduced")
    assert resolve_element_code(strategy) == "C3D8R"


def test_common_2d_plane_stress_quad_strategy_resolves():
    strategy = ElementStrategy("continuum", "2d_plane_stress", "quad", "quadratic", "full")
    assert resolve_element_code(strategy) == "CPS8"


def test_common_2d_plane_strain_quad_strategy_resolves():
    strategy = ElementStrategy("continuum", "2d_plane_strain", "quad", "linear", "reduced")
    assert resolve_element_code(strategy) == "CPE4R"


def test_unsupported_combination_fails_closed():
    strategy = ElementStrategy("beam", "3d", "line", "linear", "reduced")
    with pytest.raises(ValueError):
        resolve_element_code(strategy)


def test_inconsistent_integration_fails_closed():
    with pytest.raises(ValueError, match="reduced formulation"):
        ElementStrategy("continuum", "3d", "hex", "linear", "reduced", "full")


def test_standard_formulation_is_not_silently_mapped():
    with pytest.raises(ValueError, match="STANDARD formulation"):
        ElementStrategy("continuum", "3d", "hex", "linear", "standard")


def test_action_exposes_semantic_intent_and_native_code():
    action = element_strategy(
        "M", "P", "p.cells",
        family="continuum", dimension="3d", shape="hex",
        order="linear", formulation="reduced",
    )
    assert action.parameters["elem_code"] == "C3D8R"
    assert action.parameters["family"] == "CONTINUUM"
    assert "C3D8R" in preview(action)


def test_validation_rejects_semantic_native_code_mismatch():
    action = element_strategy(
        "M", "P", "p.cells",
        family="continuum", dimension="3d", shape="hex",
        order="linear", formulation="reduced",
    )
    action.parameters["elem_code"] = "C3D8"
    with pytest.raises(ValueError, match="does not match semantic element strategy"):
        validate_action(action)
