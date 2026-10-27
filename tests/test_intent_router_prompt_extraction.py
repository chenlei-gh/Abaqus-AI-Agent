"""Regression tests for prompt quantity extraction in the intent router.

Root cause of the 2026-10-27 pilot-2 phase-B physics failure: the router
extracted "E=210000MPa" and "yield=235MPa" as concentrated loads (material
properties misread as forces), and the BC clause splitter did not treat ASCII
periods as sentence boundaries, so "fixed ... . Load: ... tip" merged into one
clause and the encastre BC was stolen onto TipFace (the loaded end). The solved
model then had the load applied directly at the constrained face: S=0, U=0,
reaction = sum of all spurious loads.
"""

from abaqus_ai_agent.typesafe_intent import (
    JevIntentRouter,
    _extract_prompt_boundary_conditions,
    _extract_prompt_load_region,
    _split_prompt_clauses,
)

PILOT2_STYLE_PROMPT = (
    "Cantilever beam 100mm x 10mm x 10mm, structural steel Q235 "
    "(E=210000MPa, nu=0.3, yield=235MPa). "
    "Boundary condition: the root end face fully fixed (encastre). "
    "Load: 200N downward concentrated force at the free end tip. "
    "Verify that the max von Mises stress does not exceed 1500 MPa. "
    "Compute von Mises stress and displacement, and deliver the "
    "engineering report."
)


def test_material_properties_are_never_extracted_as_loads():
    """E / yield / nu values must not become concentrated forces."""
    router = JevIntentRouter(mode="offline")
    res = router.route(PILOT2_STYLE_PROMPT)
    assert res.status == "ROUTED"
    loads = list(res.intent.loads)
    assert len(loads) == 1
    assert loads[0]["magnitude"] == 200.0
    assert loads[0]["unit"] == "N"


def test_ascii_period_separates_bc_clause_from_load_clause():
    """Sentence-final ASCII periods are clause boundaries; decimals are not."""
    clauses = _split_prompt_clauses("fixed at root (encastre). load: 200n at tip.")
    assert clauses == ["fixed at root (encastre)", "load: 200n at tip"]
    # decimal numbers are preserved
    clauses = _split_prompt_clauses("deflection 2.5mm, fixed root.")
    assert clauses[0] == "deflection 2.5mm"


def test_boundary_condition_lands_on_root_face_not_tip():
    bcs = _extract_prompt_boundary_conditions(PILOT2_STYLE_PROMPT)
    assert len(bcs) == 1
    assert bcs[0]["type"] == "encastre"
    assert bcs[0]["region"] == "RootFace"


def test_load_region_still_resolves_to_tip():
    assert _extract_prompt_load_region(PILOT2_STYLE_PROMPT, "concentrated_force") == "TipFace"


def test_routed_intent_has_correct_bc_loads_and_criteria():
    router = JevIntentRouter(mode="offline")
    res = router.route(PILOT2_STYLE_PROMPT)
    assert res.status == "ROUTED"
    assert res.intent.boundary_conditions[0]["region"] == "RootFace"
    assert res.intent.loads[0]["region"] == "TipFace"
    criteria = list(res.intent.acceptance_criteria)
    assert any(c["value_key"] == "max_mises" and c["limit"] == 1500.0 for c in criteria)


def test_mpa_value_without_pressure_context_is_not_a_load():
    """An MPa figure outside any pressure clause must not become a load."""
    router = JevIntentRouter(mode="offline")
    prompt = (
        "Cantilever beam 100mm x 10mm x 10mm, structural steel "
        "(E=210000MPa). Boundary condition: the root end face fully fixed (encastre). "
        "Load: 500N downward concentrated force at the free end tip."
    )
    res = router.route(prompt)
    assert res.status == "ROUTED"
    loads = list(res.intent.loads)
    assert len(loads) == 1
    assert loads[0]["magnitude"] == 500.0


def test_mpa_pressure_with_pressure_context_remains_a_load():
    """A genuine pressure load stated with MPa keeps working."""
    router = JevIntentRouter(mode="offline")
    prompt = (
        "Steel plate 100mm x 100mm x 10mm, structural steel "
        "(E=210000MPa). Boundary condition: the root end face fully fixed (encastre). "
        "Apply 2.5MPa pressure load uniformly on the top face."
    )
    res = router.route(prompt)
    assert res.status == "ROUTED"
    loads = list(res.intent.loads)
    assert any(ld.get("type") == "pressure" and ld["magnitude"] == 2.5 for ld in loads)
