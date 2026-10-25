from __future__ import annotations

from abaqus_ai_agent.contracts.deck_material import (
    compare_material_claims,
    deck_material_table,
    parse_deck_materials,
)


DECK = (
    "*MATERIAL, NAME=STEEL\n"
    "*ELASTIC\n"
    "210000., 0.3\n"
    "*SOLID SECTION, ELSET=STRUCTURE, MATERIAL=STEEL\n"
)


def _claim(**overrides):
    claim = dict(deck_material_table(DECK, input_sha256="deck-v1")[0])
    claim.update(overrides)
    return claim


def test_section_assignment_is_material_evidence():
    card = parse_deck_materials(DECK)[0]
    assert card["applicable_regions"] == ("STRUCTURE",)
    assert card["section_assignments"][0]["section_type"] == "SOLID_SECTION"
    assert compare_material_claims([_claim()], parse_deck_materials(DECK)) is None


def test_missing_applicable_region_declaration_fails_closed():
    claim = _claim(applicable_regions=())
    mismatch = compare_material_claims([claim], parse_deck_materials(DECK))
    assert mismatch is not None
    assert "material_applicable_regions_missing" in {
        item["code"] for item in mismatch["mismatches"]
    }


def test_applicable_region_mismatch_fails_closed():
    claim = _claim(applicable_regions=("CAP",))
    mismatch = compare_material_claims([claim], parse_deck_materials(DECK))
    assert mismatch is not None
    region_mismatch = next(
        item for item in mismatch["mismatches"]
        if item["code"] == "material_applicable_regions_mismatch"
    )
    assert region_mismatch["claimed_regions"] == ["CAP"]
    assert region_mismatch["deck_regions"] == ["STRUCTURE"]


def test_material_without_section_assignment_fails_closed():
    unassigned = (
        "*MATERIAL, NAME=STEEL\n"
        "*ELASTIC\n"
        "210000., 0.3\n"
    )
    claim = _claim(applicable_regions=("STRUCTURE",))
    mismatch = compare_material_claims([claim], parse_deck_materials(unassigned))
    assert mismatch is not None
    assert "material_unassigned_in_deck" in {
        item["code"] for item in mismatch["mismatches"]
    }


def test_report_material_table_is_deck_generated_and_shows_regions(tmp_path):
    from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
    from abaqus_ai_agent.reporting.renderer import render_markdown

    class Acceptance:
        status = "PASS"
        passed = True
        deliverable = True

    digest = "deck-v1"
    pipeline = DeterministicReportPipeline()
    _, _, report = pipeline.build_and_render(
        output_dir=tmp_path,
        title="Material Evidence",
        case_id="P14-MATERIAL",
        run_id="P14-RUN",
        model_info={"name": "Model-1"},
        results_info=(),
        acceptance_info=Acceptance(),
        materials_info=[_claim()],
        require_deliverable=False,
        inp_text=DECK,
        input_hash=digest,
    )
    assert report.materials[0]["source"] == "solved_deck"
    assert report.materials[0]["applicable_regions"] == ["STRUCTURE"]
    rendered = render_markdown(report, language="english")
    assert "Applicable Regions" in rendered
    assert "STRUCTURE" in rendered
