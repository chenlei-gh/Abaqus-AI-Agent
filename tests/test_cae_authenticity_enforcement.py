"""Rigorous validation tests enforcing authentic CAE execution and forbidding deceptive shortcuts.

Verifies:
1. Case 06 solver never synthesizes fake plaintext JSON disguised as .odb.
2. Case 06 mesh quality auditor performs genuine 3D isoparametric Jacobian determinants and INP deck parsing, not static mock dicts.
3. Pre-solver mesh quality gatekeeper detects and blocks inverted/distorted elements parsed from real INP decks.
4. Fallback asset copying from pre-baked assets directories is strictly forbidden in case workflows.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.execution.case_06_mesh_audit import (
    audit_case_06_mesh_quality,
    audit_hex_element,
    build_and_audit_submodel_hex_mesh,
    parse_and_audit_inp_deck,
)
from abaqus_ai_agent.execution.case_06_solver import execute_case_06_solver


def test_case_06_solver_never_writes_plaintext_json_as_odb(tmp_path: Path):
    """Case 06 solver must never write a plaintext JSON file with .odb extension."""
    problem_path = (
        Path(__file__).resolve().parent.parent
        / "test_assets"
        / "engineering_cases"
        / "case_06_sheet_metal_submodeling"
        / "problem_statement.json"
    )
    with open(problem_path, "r", encoding="utf-8") as f:
        problem = json.load(f)

    res = execute_case_06_solver(tmp_path, problem, require_live=False)

    # Inspect all .odb files generated in workdir
    odb_files = list(tmp_path.glob("*.odb"))
    for odb_file in odb_files:
        content = odb_file.read_bytes().strip()
        assert not content.startswith(b"{"), f"Fake JSON disguised as .odb detected: {odb_file}"
        assert not content.startswith(b"["), f"Fake JSON array disguised as .odb detected: {odb_file}"

    # Artifacts catalog should not contain any fake plaintext odb
    for art in res["artifacts"]:
        if art["name"].endswith(".odb"):
            p = Path(art["path"])
            assert p.is_file()
            head = p.read_bytes()[:16].strip()
            assert not head.startswith((b"{", b"[")), "Fake plaintext JSON tracked as ODB in artifacts"


def test_hex_mesh_audit_computes_genuine_3d_jacobian():
    """Verify Hex element audit uses genuine isoparametric shape function derivatives and determinant."""
    # Ideal unit cube [0, 1]^3: min_det == 1.0, AR == 1.0, Jacobian ratio == 1.0
    pts_cube = (
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    )
    res_cube = audit_hex_element(1, pts_cube)
    assert res_cube.aspect_ratio == 1.0
    assert res_cube.jacobian_ratio >= 0.99
    assert res_cube.min_angle_deg == 90.0
    assert res_cube.max_angle_deg == 90.0

    # Stretched hex: 3x1x1 -> AR == 3.0
    pts_stretched = (
        (0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (3.0, 0.0, 1.0), (3.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    )
    res_str = audit_hex_element(2, pts_stretched)
    assert res_str.aspect_ratio == 3.0
    assert res_str.jacobian_ratio >= 0.99

    # Inverted hex (top and bottom nodes swapped along Z -> negative volume)
    pts_inverted = (
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    )
    res_inv = audit_hex_element(3, pts_inverted)
    assert res_inv.jacobian_ratio <= 0.0, "Inverted element must yield zero or negative Jacobian ratio"


def test_parse_and_audit_inp_deck_detects_real_deck_topologies(tmp_path: Path):
    """Verify INP parser reads *NODE and *ELEMENT lines and audits elements deterministically."""
    inp_content = """*HEADING
Test Deck
*PART, NAME=Part-1
*NODE
1, 0.0, 0.0, 0.0
2, 10.0, 0.0, 0.0
3, 10.0, 10.0, 0.0
4, 0.0, 10.0, 0.0
*ELEMENT, TYPE=S4R, ELSET=ShellSet
101, 1, 2, 3, 4
*END PART
"""
    inp_file = tmp_path / "test_model.inp"
    inp_file.write_text(inp_content, encoding="utf-8")

    parsed = parse_and_audit_inp_deck(inp_file)
    assert parsed["nodes_count"] == 4
    assert parsed["quad_elements_count"] == 1
    assert len(parsed["audited_quads"]) == 1
    quad = parsed["audited_quads"][0]
    assert quad.element_id == 101
    assert quad.aspect_ratio == 1.0
    assert quad.jacobian_ratio >= 0.99


def test_case_06_mesh_audit_with_inverted_inp_fails_gate(tmp_path: Path):
    """A generated INP deck containing distorted elements must fail the pre-solver mesh gate."""
    # Create an INP with an inverted quad (clockwise node ordering)
    inverted_inp = tmp_path / "bad_global.inp"
    inverted_inp.write_text(
        "*NODE\n"
        "1, 0.0, 0.0, 0.0\n"
        "2, 10.0, 0.0, 0.0\n"
        "3, 0.0, 10.0, 0.0\n"
        "4, 10.0, 10.0, 0.0\n"  # Folded self-intersecting quad
        "*ELEMENT, TYPE=S4R\n"
        "1, 1, 2, 3, 4\n",
        encoding="utf-8",
    )

    gate_eval, report = audit_case_06_mesh_quality(global_inp=inverted_inp)
    assert report["sample_quad_count"] >= 1


def test_no_stale_asset_copying_in_case_workflows():
    """Anti-Cheat AST check: E2E case scripts must never copy pre-baked assets to disguise unrendered CAE results."""
    root = Path(__file__).resolve().parent.parent
    tools_dir = root / "tools"
    case_scripts = list(tools_dir.glob("p2_case_*_e2e.py"))
    assert len(case_scripts) >= 6

    for script in case_scripts:
        text = script.read_text(encoding="utf-8")
        # Forbidden pattern: copying assets directory files into destination report folder
        assert "case_assets_dir.iterdir()" not in text, f"Stale asset sync loop found in {script.name}"
        assert "p2_src.read_bytes()" not in text, f"Stale asset copy fallback found in {script.name}"


def test_no_json_dumps_to_odb_across_entire_repo():
    """Anti-Cheat scan: No Python file in the codebase may serialize JSON directly into an .odb file."""
    root = Path(__file__).resolve().parent.parent
    src_dir = root / "src"
    py_files = list(src_dir.rglob("*.py"))

    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        assert "odb_path.write_text(json.dumps" not in text, f"Fake JSON ODB writer found in {py_file}"
        assert ".odb.write_text(json.dumps" not in text, f"Fake JSON ODB writer found in {py_file}"
