import pytest

from abaqus_ai_agent.contracts.element_strategy import ElementStrategy, resolve_element_code
from abaqus_ai_agent.actions import element_strategy
from abaqus_ai_agent.actions.runner import preview


def test_common_3d_hex_strategy_resolves():
    strategy = ElementStrategy("continuum", "3d", "hex", "linear", "reduced")
    assert resolve_element_code(strategy) == "C3D8R"


def test_common_2d_quad_strategy_resolves():
    strategy = ElementStrategy("continuum", "2d", "quad", "quadratic", "full")
    assert resolve_element_code(strategy) == "CPS8"


def test_unsupported_combination_fails_closed():
    strategy = ElementStrategy("beam", "3d", "line", "linear", "reduced")
    with pytest.raises(ValueError):
        resolve_element_code(strategy)


def test_action_exposes_semantic_intent_and_native_code():
    action = element_strategy(
        "M", "P", "p.cells",
        family="continuum", dimension="3d", shape="hex",
        order="linear", formulation="reduced",
    )
    assert action.parameters["elem_code"] == "C3D8R"
    assert action.parameters["family"] == "CONTINUUM"
    assert "C3D8R" in preview(action)
