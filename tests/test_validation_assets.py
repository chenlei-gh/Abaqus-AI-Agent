"""Unit tests verifying the canonical validation assets registry and structure."""

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.paths import get_repo_root, resolve_validation_assets_root


def test_validation_assets_root_resolves():
    val_root = resolve_validation_assets_root()
    assert val_root.is_dir()


def test_registry_json_integrity():
    repo = get_repo_root()
    registry_file = repo / "validation_assets" / "registry.json"
    assert registry_file.is_file(), "registry.json must exist in validation_assets/"

    with open(registry_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    assert "cases" in data
    cases = data["cases"]
    assert len(cases) == 10, "Must register Case 01 to Case 10"

    # Verify qualified cases (01 to 06)
    qualified = [c for c in cases if c.get("qualification_status") == "QUALIFIED"]
    assert len(qualified) == 6

    for c in qualified:
        case_id = c["case_id"]
        # Check input assets exist
        for inp in c["input_assets"]:
            inp_path = repo / inp
            assert inp_path.is_file(), f"Input asset {inp} for {case_id} must exist"

        # Check evidence manifest exists
        manifest_path = repo / c["evidence_manifest"]
        assert manifest_path.is_file(), f"Manifest {c['evidence_manifest']} for {case_id} must exist"

        # Check case dir exists
        case_dir = repo / c["case_dir"]
        assert case_dir.is_dir(), f"Case dir {c['case_dir']} for {case_id} must exist"

        # Check individual case_manifest.json exists inside case_dir
        manifest_inside = case_dir / "case_manifest.json"
        assert manifest_inside.is_file()
        with open(manifest_inside, "r", encoding="utf-8") as m_fh:
            inner_data = json.load(m_fh)
        assert inner_data["case_id"] == case_id


def test_official_references_catalog():
    repo = get_repo_root()
    ref_file = repo / "validation_assets" / "references" / "official_examples.json"
    assert ref_file.is_file()

    with open(ref_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    assert "references" in data
    assert len(data["references"]) >= 6

    # Verify all references point to recognized physics domains
    for ref in data["references"]:
        assert "ref_id" in ref
        assert "physics_domain" in ref
        assert "associated_cases" in ref
        assert len(ref["associated_cases"]) >= 1


def test_cli_assets_subcommand(capsys):
    from abaqus_ai_agent.cli import main

    # Test list
    rc = main(["assets", "--list"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "CASE_01_BOLTED_PIPE_FLANGE" in captured.out
    assert "CASE_10_RESERVED" in captured.out

    # Test single case query
    rc = main(["assets", "--case", "case_02"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Nuclear Reactor Pressure Vessel" in captured.out
    assert "REF_ABQ_RPV_CLOSURE" in captured.out

    # Test json query
    rc = main(["assets", "--case", "case_03", "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    c3_data = json.loads(captured.out)
    assert c3_data["case_id"] == "CASE_03_EXHAUST_MANIFOLD_THERMO_MECHANICAL"


def test_registry_boundary_and_authority_division():
    """Verify distinct namespace boundaries between runtime golden_registry and canonical assets registry."""
    from abaqus_ai_agent.golden_registry import standard_golden_catalog
    repo = get_repo_root()
    with open(repo / "validation_assets" / "registry.json", "r", encoding="utf-8") as fh:
        assets_data = json.load(fh)

    golden_ids = {case.case_id for case in standard_golden_catalog.all_cases()}
    asset_ids = {case["case_id"] for case in assets_data["cases"]}

    # Ensure no namespace collision: golden cases use snake_case runtime IDs (e.g. static_cantilever),
    # while engineering asset cases use uppercase prefix CASE_NN_*.
    collision = golden_ids.intersection(asset_ids)
    assert not collision, f"Namespace collision detected between golden_registry and registry.json: {collision}"


def test_cross_registry_references_provenance():
    """Ensure all qualified cases in registry.json map bidirectionally to official_examples.json."""
    repo = get_repo_root()
    with open(repo / "validation_assets" / "registry.json", "r", encoding="utf-8") as fh:
        assets_data = json.load(fh)
    with open(repo / "validation_assets" / "references" / "official_examples.json", "r", encoding="utf-8") as fh:
        ref_data = json.load(fh)

    ref_map = {r["ref_id"]: r for r in ref_data["references"]}

    qualified_cases = [c for c in assets_data["cases"] if c.get("qualification_status") == "QUALIFIED"]
    for case in qualified_cases:
        ref_id = case["reference_source"]
        assert ref_id in ref_map, f"Case {case['case_id']} references unknown benchmark {ref_id}"
        # Bidirectional check: the official reference must list this case in associated_cases
        assert case["case_id"] in ref_map[ref_id]["associated_cases"], (
            f"Official reference {ref_id} does not associate {case['case_id']}"
        )


def test_case_manifests_single_source_of_truth():
    """Ensure individual case_manifest.json metrics and registry.json criteria keys are identical."""
    repo = get_repo_root()
    with open(repo / "validation_assets" / "registry.json", "r", encoding="utf-8") as fh:
        assets_data = json.load(fh)

    qualified_cases = [c for c in assets_data["cases"] if c.get("qualification_status") == "QUALIFIED"]
    for case in qualified_cases:
        manifest_file = repo / case["case_dir"] / "case_manifest.json"
        assert manifest_file.is_file()
        with open(manifest_file, "r", encoding="utf-8") as fh:
            m_data = json.load(fh)

        # Verified metrics keys must match exactly between canonical registry criteria and case manifest
        assert set(m_data["verified_metrics"].keys()) == set(case["acceptance_criteria"].keys()), (
            f"Criteria divergence detected for {case['case_id']}"
        )
