"""Unit tests for Phase 3.3 bulkDataBlocks numerical equivalence contract."""

from types import SimpleNamespace
import pytest

from abaqus_ai_agent.execution.bulk_data_contract import (
    BulkDataEquivalenceError,
    BulkDataEquivalenceStatus,
    DEFAULT_FLOAT_TOLERANCE,
    extract_scalar_from_blocks,
    is_close_scalar,
    verify_extraction_equivalence,
)


def test_is_close_scalar():
    """Verify absolute and relative tolerance checks."""
    assert is_close_scalar(100.0, 100.0)
    # Drift 1e-5 on 100.0 (relative 1e-7) is within 1e-6 tolerance
    assert is_close_scalar(100.0, 100.0 + 1e-5) is True
    # Drift 1e-3 on 100.0 (relative 1e-5) exceeds 1e-6 tolerance
    assert is_close_scalar(100.0, 100.0 + 1e-3) is False
    # Drift 1e-5 on 1.0 (relative 1e-5) exceeds 1e-6 tolerance
    assert is_close_scalar(1.0, 1.0 + 1e-5) is False
    # Drift 5e-7 on 1.0 (relative 5e-7) is within 1e-6 tolerance
    assert is_close_scalar(1.0, 1.0 + 5e-7) is True

    # Rejects non-finite floats
    assert is_close_scalar(float("nan"), 100.0) is False
    assert is_close_scalar(float("inf"), float("inf")) is False


def test_verify_extraction_equivalence_pass():
    """Exact and within-tolerance matches pass equivalence check."""
    can = {"success": True, "value": 245.500000, "locator": {"node_label": 101, "instance": "Part-1"}}
    blk = {"success": True, "value": 245.500050, "locator": {"node_label": 101, "instance": "Part-1"}}
    assert verify_extraction_equivalence(can, blk, tol=1e-5) == BulkDataEquivalenceStatus.EQUIVALENT


def test_verify_extraction_equivalence_drift_rejected():
    """Numerical drift exceeding tolerance raises BulkDataEquivalenceError."""
    can = {"success": True, "value": 100.0, "locator": {"node_label": 1}}
    blk = {"success": True, "value": 100.005, "locator": {"node_label": 1}}
    with pytest.raises(BulkDataEquivalenceError, match="Numerical drift exceeded tolerance"):
        verify_extraction_equivalence(can, blk, tol=DEFAULT_FLOAT_TOLERANCE)


def test_verify_extraction_equivalence_locator_mismatch():
    """Symmetric/identical peak values with divergent locators are categorized as LOCATOR_MISMATCH."""
    can = {"success": True, "value": 50.0, "locator": {"node_label": 12, "instance": "I1"}}
    blk = {"success": True, "value": 50.0, "locator": {"node_label": 34, "instance": "I1"}}
    assert verify_extraction_equivalence(can, blk) == BulkDataEquivalenceStatus.LOCATOR_MISMATCH


def test_verify_extraction_equivalence_unsupported_or_failure():
    """Both failing marks NOT_SUPPORTED, whereas one-sided failure raises error."""
    can_fail = {"success": False, "error": "Field not available"}
    blk_fail = {"success": False, "error": "Blocks not available"}
    assert verify_extraction_equivalence(can_fail, blk_fail) == BulkDataEquivalenceStatus.NOT_SUPPORTED

    with pytest.raises(BulkDataEquivalenceError, match="Success mismatch"):
        verify_extraction_equivalence({"success": True, "value": 1.0}, blk_fail)


def test_extract_scalar_from_blocks_basic():
    """Mock blocks extract max, min, and average with accurate locators."""
    inst = SimpleNamespace(name="BUMPER_INST")
    block1 = SimpleNamespace(
        data=[[10.5], [25.0], [5.0]],
        nodeLabels=[1, 2, 3],
        elementLabels=None,
        instance=inst,
    )
    block2 = SimpleNamespace(
        data=[[35.2], [18.0]],
        nodeLabels=[4, 5],
        elementLabels=None,
        instance=inst,
    )

    # Max extraction
    res_max = extract_scalar_from_blocks([block1, block2], aggregation="max")
    assert res_max is not None
    assert res_max.value == 35.2
    assert res_max.locator["node_label"] == 4
    assert res_max.locator["instance"] == "BUMPER_INST"

    # Min extraction
    res_min = extract_scalar_from_blocks([block1, block2], aggregation="min")
    assert res_min is not None
    assert res_min.value == 5.0
    assert res_min.locator["node_label"] == 3

    # Average extraction
    res_avg = extract_scalar_from_blocks([block1, block2], aggregation="average")
    assert res_avg is not None
    assert res_avg.value == pytest.approx((10.5 + 25.0 + 5.0 + 35.2 + 18.0) / 5.0)


def test_extract_scalar_from_blocks_empty_and_error():
    """Empty blocks return None, invalid aggregations raise error."""
    assert extract_scalar_from_blocks([]) is None
    with pytest.raises(BulkDataEquivalenceError, match="Unsupported aggregation"):
        extract_scalar_from_blocks([SimpleNamespace(data=[[1.0]])], aggregation="invalid_agg")


def test_differential_equivalence_against_canonical_loop():
    """Verify that canonical values loop and bulkDataBlocks yield identical results."""
    # Synthetic dataset
    raw_points = [
        {"val": 12.4, "node": 10, "elem": 101, "inst": "PartA"},
        {"val": 89.2, "node": 11, "elem": 102, "inst": "PartA"},
        {"val": -4.5, "node": 12, "elem": 103, "inst": "PartA"},
        {"val": 56.1, "node": 20, "elem": 201, "inst": "PartB"},
        {"val": 78.0, "node": 21, "elem": 202, "inst": "PartB"},
    ]

    # Canonical values loop result
    max_pt = max(raw_points, key=lambda p: p["val"])
    canonical_max = {
        "success": True,
        "value": float(max_pt["val"]),
        "locator": {
            "node_label": max_pt["node"],
            "element_label": max_pt["elem"],
            "instance": max_pt["inst"],
        },
    }

    # Bulk blocks representation
    b1 = SimpleNamespace(
        data=[[p["val"]] for p in raw_points[:3]],
        nodeLabels=[p["node"] for p in raw_points[:3]],
        elementLabels=[p["elem"] for p in raw_points[:3]],
        instance=SimpleNamespace(name="PartA"),
    )
    b2 = SimpleNamespace(
        data=[[p["val"]] for p in raw_points[3:]],
        nodeLabels=[p["node"] for p in raw_points[3:]],
        elementLabels=[p["elem"] for p in raw_points[3:]],
        instance=SimpleNamespace(name="PartB"),
    )

    bulk_res = extract_scalar_from_blocks([b1, b2], aggregation="max")
    assert bulk_res is not None

    bulk_dict = {
        "success": True,
        "value": bulk_res.value,
        "locator": bulk_res.locator,
    }

    # Equivalence passes under strict 1e-6 tolerance
    status = verify_extraction_equivalence(canonical_max, bulk_dict, tol=1e-6)
    assert status == BulkDataEquivalenceStatus.EQUIVALENT

    # Injecting artificial drift of 1e-4 causes Fail-Closed rejection
    drifted_bulk = dict(bulk_dict)
    drifted_bulk["value"] += 1e-4
    with pytest.raises(BulkDataEquivalenceError, match="Numerical drift exceeded tolerance"):
        verify_extraction_equivalence(canonical_max, drifted_bulk, tol=1e-6)
