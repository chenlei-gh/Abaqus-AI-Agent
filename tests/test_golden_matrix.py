"""Tests for the Golden Validation Matrix Catalog, Evidence Schema, and Runner.

All tests in this suite are offline, deterministic, and CI-compatible
(requiring 0 live Abaqus licenses or external processes).
"""

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.actions.builders import (
    connector_section,
    reference_point,
    rigid_body,
    wire_connector,
)
from abaqus_ai_agent.golden_evidence import (
    CASE_NAME_TO_ID,
    REQUIRED_ENVELOPE_KEYS,
    GoldenEvidenceEnvelope,
    load_and_normalize_evidence_file,
    normalize_golden_evidence,
    resolve_case_id,
    validate_golden_evidence_dict,
)
from abaqus_ai_agent.golden_registry import (
    GoldenCaseDefinition,
    GoldenMatrixCatalog,
    standard_golden_catalog,
)
from abaqus_ai_agent.validation.preflight import preflight_action
import tools.run_golden_matrix as runner


EXPECTED_TEN_CASES = (
    "smoke",
    "static_cantilever",
    "mesh_convergence",
    "tie_contact",
    "implicit_dynamic",
    "steady_thermal",
    "general_contact",
    "mbd1_rigid_pendulum",
    "mbd2_double_pendulum",
    "fmbd4_rigid_flexible",
)


def test_golden_registry_contains_all_ten_cases():
    catalog = standard_golden_catalog
    assert catalog.count() == 10
    registered_ids = catalog.case_ids()
    for case_id in EXPECTED_TEN_CASES:
        assert case_id in registered_ids
        case = catalog.get_case(case_id)
        assert case is not None
        assert case.title
        assert case.category in ("P0", "P1", "MBD", "FMBD")
        assert case.solver in ("standard", "explicit")
        assert case.physics_type
        assert case.job_name
        assert case.tool_script.startswith("tools/")
        assert case.analytical_reference
        assert len(case.criteria) > 0


def test_golden_registry_category_filtering():
    catalog = standard_golden_catalog
    p0_cases = catalog.cases_by_category("P0")
    p1_cases = catalog.cases_by_category("P1")
    mbd_cases = catalog.cases_by_category("MBD")

    assert len(p0_cases) == 3
    assert {c.case_id for c in p0_cases} == {"smoke", "static_cantilever", "mesh_convergence"}

    assert len(p1_cases) == 4
    assert {c.case_id for c in p1_cases} == {"tie_contact", "implicit_dynamic", "steady_thermal", "general_contact"}

    assert len(mbd_cases) == 2
    assert {c.case_id for c in mbd_cases} == {"mbd1_rigid_pendulum", "mbd2_double_pendulum"}


def test_golden_registry_require_case_raises_on_unknown():
    catalog = standard_golden_catalog
    with pytest.raises(KeyError, match="Unknown golden case_id: 'nonexistent'"):
        catalog.require_case("nonexistent")


def test_golden_registry_negative_gates_registered():
    catalog = standard_golden_catalog
    # Cases with formal strict negative gate test criteria
    strict_case_ids = ("mesh_convergence", "implicit_dynamic", "steady_thermal", "mbd1_rigid_pendulum", "mbd2_double_pendulum")
    for cid in strict_case_ids:
        case = catalog.require_case(cid)
        assert len(case.strict_criteria) > 0, f"Case {cid} must have strict_criteria registered for negative gating"


def test_evidence_envelope_required_keys_and_validation():
    envelope = GoldenEvidenceEnvelope(
        case_id="static_cantilever",
        release="Abaqus 2025",
        runtime={"launcher": "abaqus", "return_code": 0, "process_succeeded": True},
        solver="standard",
        job="StaticGoldenJob",
        odb={"path": "job.odb", "exists": True},
        solver_status="completed",
        result_evidence={"tip_displacement": 2.068},
        verification={"theory_deflection": 1.905},
        acceptance={"passed": True, "criteria": []},
        artifacts=[{"path": "job.odb", "kind": "odb"}],
        provenance={"version": "1.0"},
    )
    d = envelope.to_dict()
    for key in REQUIRED_ENVELOPE_KEYS:
        assert key in d
    assert envelope.passed is True

    # Validate valid dict
    errors = validate_golden_evidence_dict(d)
    assert errors == []

    # Validate missing key
    corrupted = dict(d)
    del corrupted["solver_status"]
    errs = validate_golden_evidence_dict(corrupted)
    assert any("solver_status" in e for e in errs)

    # Validate wrong type
    corrupted2 = dict(d)
    corrupted2["runtime"] = "not_a_dict"
    errs2 = validate_golden_evidence_dict(corrupted2)
    assert any("runtime must be a dictionary" in e for e in errs2)


def test_resolve_case_id_mappings():
    assert resolve_case_id({"case_id": "smoke"}) == "smoke"
    assert resolve_case_id({"case": "3d_cantilever_static"}) == "static_cantilever"
    assert resolve_case_id({"case": "two_body_frictional_contact_sliding"}) == "general_contact"
    assert resolve_case_id({"job": "MBD2GoldenJob"}) == "mbd2_double_pendulum"
    assert resolve_case_id({"script": "machine_validation/thermal_golden_e2e_script.py"}) == "steady_thermal"
    assert resolve_case_id({}, default="fallback") == "fallback"
    with pytest.raises(ValueError, match="Cannot resolve case_id"):
        resolve_case_id({})


def test_normalize_golden_evidence_from_mock_cases():
    # 1. Smoke format
    smoke_raw = {
        "status": "pass",
        "launcher": "C:\\SIMULIA\\Commands\\abaqus.bat",
        "workdir": "D:\\test",
        "script": "smoke_script.py",
        "process_succeeded": True,
        "return_code": 0,
        "harness": {
            "passed": True,
            "job_completed": True,
            "odb_exists": True,
            "required_outputs_present": True,
        },
    }
    env_smoke = normalize_golden_evidence(smoke_raw, case_id="smoke")
    assert env_smoke.case_id == "smoke"
    assert env_smoke.passed is True
    assert env_smoke.solver_status == "completed"
    assert validate_golden_evidence_dict(env_smoke.to_dict()) == []

    # 2. Golden Case format (report style)
    static_raw = {
        "case": "3d_cantilever_static",
        "status": "pass",
        "process_succeeded": True,
        "return_code": 0,
        "launcher": "abaqus",
        "report": {
            "job_name": "StaticGoldenJob",
            "acceptance": {"passed": True, "criteria": []},
            "workflow": {"solver_completed": True},
            "solver": {"odb_path": "StaticGoldenJob.odb", "artifacts": []},
            "results": {"metrics": {"tip_displacement": 2.068}},
            "engineering_checks": {"reaction_balance": {"RF2": 1000.0}},
            "provenance": {"tool": "static_golden"},
        },
    }
    env_static = normalize_golden_evidence(static_raw)
    assert env_static.case_id == "static_cantilever"
    assert env_static.job == "StaticGoldenJob"
    assert env_static.passed is True
    assert validate_golden_evidence_dict(env_static.to_dict()) == []

    # 3. MBD2 format
    mbd2_raw = {
        "status": "pass",
        "simulation_results": {"max_joint_drift_mm": 9.78e-6, "period_error_percent": 0.54},
        "workflow": {"solver_completed": True, "odb_path": "MBD2GoldenJob.odb"},
        "verification": {"joint_report_passed": True},
        "acceptance": {
            "passed": True,
            "criteria": [
                {"name": "revolute_joint_drift_bound", "passed": True},
            ],
            "failures": [],
        },
        "strict_acceptance": {"passed": False},
    }
    env_mbd2 = normalize_golden_evidence(mbd2_raw, case_id="mbd2_double_pendulum")
    assert env_mbd2.case_id == "mbd2_double_pendulum"
    assert env_mbd2.passed is True
    assert env_mbd2.result_evidence["max_joint_drift_mm"] == 9.78e-6
    assert validate_golden_evidence_dict(env_mbd2.to_dict()) == []


def test_existing_disk_evidence_files_normalize_cleanly():
    """Verify that all existing JSON evidence files in machine_validation parse and pass."""
    catalog = standard_golden_catalog
    mv_dir = Path(__file__).resolve().parent.parent / "machine_validation"
    if not mv_dir.is_dir():
        pytest.skip("machine_validation directory not present")

    for case in catalog.all_cases():
        json_path = mv_dir / Path(case.default_evidence_json).name
        if json_path.is_file():
            env = load_and_normalize_evidence_file(json_path)
            assert env.case_id == case.case_id
            errs = validate_golden_evidence_dict(env.to_dict())
            assert errs == [], f"Validation errors for {case.case_id}: {errs}"
            assert env.passed is True, f"Case {case.case_id} marked failed in existing evidence"


def test_runner_cli_list(capsys):
    rc = runner.main(["--list"])
    assert rc == 0
    captured = capsys.readouterr().out
    for case_id in EXPECTED_TEN_CASES:
        assert case_id in captured
    assert "Total: 10" in captured


def test_runner_cli_validate_evidence(capsys):
    rc = runner.main(["--validate-evidence", "all"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Validation Result: ALL TARGET EVIDENCE FILES ARE VALID & PASSED" in captured


def test_runner_cli_manifest_output(tmp_path):
    out_file = tmp_path / "test_manifest.json"
    rc = runner.main(["--manifest-out", str(out_file)])
    assert rc == 0
    assert out_file.is_file()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["manifest_version"] == "1.0"
    assert data["catalog_case_count"] == 10
    assert data["summary"]["PASS"] == 10
    assert data["summary"]["FAIL"] == 0
    assert len(data["cases"]) == 10


def test_preflight_closure_mbd_and_connector_actions():
    """Contract closure audit: preflight checks for MBD and connector actions."""
    # 1. reference_point valid & invalid
    act_rp_ok = reference_point(model="M", name="RP-1", coordinates=(0.0, 0.0, 0.0))
    res = preflight_action(act_rp_ok)
    assert res.passed is True

    act_rp_bad = reference_point(model="M", name="", coordinates=(0.0,))
    res_bad = preflight_action(act_rp_bad)
    assert res_bad.passed is False
    assert any(b["name"] == "name" for b in res_bad.blockers)
    assert any(b["name"] == "coordinates" for b in res_bad.blockers)

    # 2. rigid_body valid & invalid
    act_rb_ok = rigid_body(model="M", name="RB-1", ref_point_expression="r.referencePoints[1]", body_region_expression="p.cells")
    res = preflight_action(act_rb_ok)
    assert res.passed is True

    act_rb_bad = rigid_body(model="M", name="", ref_point_expression="")
    res_bad = preflight_action(act_rb_bad)
    assert res_bad.passed is False
    assert any(b["name"] == "name" for b in res_bad.blockers)
    assert any(b["name"] == "ref_point_expression" for b in res_bad.blockers)

    # 3. connector_section valid & invalid
    act_cs_ok = connector_section(model="M", name="HingeSec", assembled_type="HINGE")
    res = preflight_action(act_cs_ok)
    assert res.passed is True

    act_cs_bad = connector_section(model="M", name="", assembled_type="")
    res_bad = preflight_action(act_cs_bad)
    assert res_bad.passed is False
    assert any(b["name"] == "name" for b in res_bad.blockers)
    assert any(b["name"] == "section_type" for b in res_bad.blockers)

    # 4. wire_connector valid & invalid
    act_wc_ok = wire_connector(model="M", name="Conn-1", section_name="HingeSec", point1_name="P1", point2_name="P2")
    res = preflight_action(act_wc_ok)
    assert res.passed is True

    act_wc_bad = wire_connector(model="M", name="", section_name="", point1_name="", point2_name="")
    res_bad = preflight_action(act_wc_bad)
    assert res_bad.passed is False
    assert any(b["name"] == "name" for b in res_bad.blockers)
    assert any(b["name"] == "section_name" for b in res_bad.blockers)
    assert any(b["name"] == "endpoints" for b in res_bad.blockers)

    # 5. connector_section semantic type validation in preflight
    act_cs_invalid_type = connector_section(model="M", name="BadSec", assembled_type="NONEXISTENT_TYPE")
    res_inv = preflight_action(act_cs_invalid_type)
    assert res_inv.passed is False
    assert any(b["name"] == "assembled_type_valid" for b in res_inv.blockers)


def test_anti_evidence_invention_strictness():
    """Verify normalizer never fabricates solver completion or acceptance from status string alone."""
    # 1. Bare status: pass without acceptance or workflow
    bare_raw = {
        "case_id": "static_cantilever",
        "status": "pass",
    }
    env_bare = normalize_golden_evidence(bare_raw)
    assert env_bare.passed is False, "Must not invent acceptance.passed=True from status=pass"
    assert env_bare.solver_status == "unknown", "Must not invent solver_status=completed from status=pass"

    # 2. Nested standard acceptance where standard.passed is False
    nested_failed = {
        "case_id": "mesh_convergence",
        "status": "pass",  # misleading outer status
        "acceptance": {
            "standard": {
                "passed": False,
                "failures": ["criterion_failed"],
                "criteria": [{"name": "gci", "passed": False}],
            },
            "strict": {"passed": False},
        },
    }
    env_nested = normalize_golden_evidence(nested_failed)
    assert env_nested.passed is False, "Must extract passed=False from nested standard acceptance"
    assert "criterion_failed" in env_nested.acceptance["failures"]


def test_anti_evidence_invention_rejects_inconsistent_positive_envelope(tmp_path):
    """A positive acceptance cannot stand alone without explicit successful execution."""
    evidence = {
        "case_id": "static_cantilever",
        "release": "Abaqus 2025",
        "runtime": {"launcher": "abaqus", "return_code": 1, "process_succeeded": False},
        "solver": "standard",
        "job": "StaticGoldenJob",
        "odb": {"path": "StaticGoldenJob.odb", "exists": False},
        "solver_status": "unknown",
        "result_evidence": {},
        "verification": {},
        "acceptance": {"passed": True, "criteria": []},
        "artifacts": [],
        "provenance": {},
    }
    path = tmp_path / "static_cantilever.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    status, _, err = runner.inspect_case_evidence_status(
        standard_golden_catalog.require_case("static_cantilever"), tmp_path
    )
    assert status == "INVALID_SCHEMA"
    assert "solver_status" in err


def test_workdir_isolation_does_not_leak_repo_evidence(tmp_path):
    """An empty or custom workdir must report NO_EVIDENCE, not leak existing repository files."""
    empty_dir = tmp_path / "isolated_dir"
    empty_dir.mkdir()
    case = standard_golden_catalog.require_case("static_cantilever")
    status, path, err = runner.inspect_case_evidence_status(case, empty_dir)
    assert status == "NO_EVIDENCE"
    assert path is None


def test_runner_cli_dry_run(capsys):
    """Verify --dry-run simulates execution without spawning solver processes."""
    rc = runner.main(["--run", "all", "--dry-run"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "[DRY RUN]" in captured
    assert "Dry run completed: 0 Abaqus solver jobs were started." in captured
