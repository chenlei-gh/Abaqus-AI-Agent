"""Unit tests for Phase 3.3 bulkDataBlocks numerical equivalence contract."""

from types import SimpleNamespace
import pytest

from abaqus_ai_agent.execution.bulk_data_contract import (
    BulkDataEquivalenceError,
    BulkDataEquivalenceStatus,
    CONTRACT_TOLERANCE_UPPER_BOUND,
    DEFAULT_FLOAT_TOLERANCE,
    extract_scalar_from_blocks,
    is_close_scalar,
    verify_extraction_equivalence,
)


def test_is_close_scalar():
    """Verify absolute and relative tolerance checks with strict inequality."""
    # Zero drift (exact match) always passes
    assert is_close_scalar(100.0, 100.0) is True
    assert is_close_scalar(0.0, 0.0) is True

    # Drift strictly inside 1e-6 relative tolerance:
    # On scale 100.0, diff 5e-5 is 5e-7 relative -> passes
    assert is_close_scalar(100.0, 100.0 + 5e-5) is True

    # When scale == 1.0 (e.g. values <= 1.0), diff exactly 1e-6 equals tol * scale.
    # Under strict inequality (< tol * scale), diff == tol * scale must be False:
    assert is_close_scalar(0.5, 0.5 + 1e-6) is False
    assert is_close_scalar(0.5, 0.5 + 9.99e-7) is True

    # Drift exceeding 1e-6:
    assert is_close_scalar(1.0, 1.0 + 1.0001e-6) is False
    assert is_close_scalar(100.0, 100.0 + 1e-3) is False

    # Rejects non-finite floats
    assert is_close_scalar(float("nan"), 100.0) is False
    assert is_close_scalar(100.0, float("nan")) is False
    assert is_close_scalar(float("inf"), float("inf")) is False
    assert is_close_scalar(float("-inf"), float("-inf")) is False

    # Rejects tolerance outside contract upper bound (1e-6) or non-positive
    assert is_close_scalar(1.0, 1.0 + 1e-4, tol=1e-3) is False
    assert is_close_scalar(1.0, 1.0, tol=0.0) is False
    assert is_close_scalar(1.0, 1.0, tol=-1e-6) is False
    assert is_close_scalar(1.0, 1.0, tol=float("nan")) is False

    # Rejects boolean and non-numeric inputs without raising exceptions
    assert is_close_scalar(True, 1.0) is False
    assert is_close_scalar(1.0, False) is False
    assert is_close_scalar(True, True) is False
    assert is_close_scalar("1.0", 1.0) is False
    assert is_close_scalar(1.0, [1.0]) is False
    assert is_close_scalar(1.0, 1.0, tol=True) is False
    assert is_close_scalar(1.0, 1.0, tol="1e-6") is False


def test_verify_extraction_equivalence_pass_exact_and_within_tolerance():
    """Exact and within-tolerance matches pass equivalence check with proper status."""
    # Exact match
    can_exact = {"success": True, "value": 245.5, "locator": {"node_label": 101, "instance": "Part-1"}}
    blk_exact = {"success": True, "value": 245.5, "locator": {"node_label": 101, "instance": "Part-1"}}
    assert verify_extraction_equivalence(can_exact, blk_exact) == BulkDataEquivalenceStatus.EXACT_MATCH

    # Within tolerance (< 1e-6 relative)
    can_drift = {"success": True, "value": 1000.0, "locator": {"node_label": 101, "instance": "Part-1"}}
    blk_drift = {"success": True, "value": 1000.0005, "locator": {"node_label": 101, "instance": "Part-1"}}
    # relative diff = 0.0005 / 1000 = 5e-7 < 1e-6
    assert verify_extraction_equivalence(can_drift, blk_drift) == BulkDataEquivalenceStatus.EQUIVALENT


def test_verify_extraction_equivalence_rejects_broadening_tolerance():
    """Callers cannot loosen tolerance beyond contract upper bound 1e-6."""
    can = {"success": True, "value": 100.0}
    blk = {"success": True, "value": 100.01}

    # Custom tol > 1e-6 must be strictly rejected
    with pytest.raises(BulkDataEquivalenceError, match="Tolerance cannot exceed contract upper bound"):
        verify_extraction_equivalence(can, blk, tol=1e-3)

    with pytest.raises(BulkDataEquivalenceError, match="Tolerance cannot exceed contract upper bound"):
        verify_extraction_equivalence(can, blk, tol=0.0)

    with pytest.raises(BulkDataEquivalenceError, match="Tolerance must be a finite float"):
        verify_extraction_equivalence(can, blk, tol=float("nan"))

    with pytest.raises(BulkDataEquivalenceError, match="Tolerance must be a finite float"):
        verify_extraction_equivalence(can, blk, tol=True)


def test_verify_extraction_equivalence_drift_rejected():
    """Numerical drift exceeding tolerance raises BulkDataEquivalenceError."""
    can = {"success": True, "value": 100.0, "locator": {"node_label": 1}}
    blk = {"success": True, "value": 100.005, "locator": {"node_label": 1}}
    with pytest.raises(BulkDataEquivalenceError, match="Numerical drift exceeded tolerance"):
        verify_extraction_equivalence(can, blk, tol=DEFAULT_FLOAT_TOLERANCE)


def test_verify_extraction_equivalence_locator_checks():
    """Spatial locators must match on instance, node_label, and element_label."""
    # Instance mismatch
    can_inst = {"success": True, "value": 50.0, "locator": {"node_label": 12, "instance": "PartA"}}
    blk_inst = {"success": True, "value": 50.0, "locator": {"node_label": 12, "instance": "PartB"}}
    assert verify_extraction_equivalence(can_inst, blk_inst) == BulkDataEquivalenceStatus.LOCATOR_MISMATCH

    # Node label mismatch
    can_node = {"success": True, "value": 50.0, "locator": {"node_label": 12, "instance": "PartA"}}
    blk_node = {"success": True, "value": 50.0, "locator": {"node_label": 34, "instance": "PartA"}}
    assert verify_extraction_equivalence(can_node, blk_node) == BulkDataEquivalenceStatus.LOCATOR_MISMATCH

    # Element label mismatch
    can_elem = {"success": True, "value": 50.0, "locator": {"element_label": 101, "instance": "PartA"}}
    blk_elem = {"success": True, "value": 50.0, "locator": {"element_label": 202, "instance": "PartA"}}
    assert verify_extraction_equivalence(can_elem, blk_elem) == BulkDataEquivalenceStatus.LOCATOR_MISMATCH

    # Locator presence asymmetry (one has locator dict, other has None)
    can_with_loc = {"success": True, "value": 50.0, "locator": {"node_label": 12, "instance": "PartA"}}
    blk_no_loc = {"success": True, "value": 50.0}
    with pytest.raises(BulkDataEquivalenceError, match="Required locator metadata is missing"):
        verify_extraction_equivalence(can_with_loc, blk_no_loc)

    # Locator key asymmetry (e.g. one has node_label=12 while other has node_label=None or missing, with element_label present on both)
    can_key_asym = {"success": True, "value": 50.0, "locator": {"node_label": 12, "element_label": 100, "instance": "PartA"}}
    blk_key_asym = {"success": True, "value": 50.0, "locator": {"element_label": 100, "instance": "PartA"}}
    with pytest.raises(BulkDataEquivalenceError, match="Asymmetric locator metadata for key 'node_label'"):
        verify_extraction_equivalence(can_key_asym, blk_key_asym)

    # Invalid locator types (boolean label, negative label, non-string instance)
    with pytest.raises(BulkDataEquivalenceError, match="Invalid canonical node_label"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"node_label": True, "instance": "PartA"}},
            {"success": True, "value": 50.0, "locator": {"node_label": 1, "instance": "PartA"}},
        )

    with pytest.raises(BulkDataEquivalenceError, match="Invalid bulk node_label"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"node_label": 10, "instance": "PartA"}},
            {"success": True, "value": 50.0, "locator": {"node_label": -5, "instance": "PartA"}},
        )

    with pytest.raises(BulkDataEquivalenceError, match="Instance names in locator must be strings"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"node_label": 10, "instance": 123}},
            {"success": True, "value": 50.0, "locator": {"node_label": 10, "instance": "PartA"}},
        )


def test_verify_extraction_equivalence_rejects_missing_locators_for_peak():
    """Peak and extreme extractions must fail-closed if locator metadata is missing or incomplete."""
    base_can = {"success": True, "value": 50.0}
    base_blk = {"success": True, "value": 50.0}

    # 1. Both completely missing locator key
    with pytest.raises(BulkDataEquivalenceError, match=r"Required locator metadata is missing for (peak|max)"):
        verify_extraction_equivalence(base_can, base_blk)

    # 2. Both locator are None
    with pytest.raises(BulkDataEquivalenceError, match=r"Required locator metadata is missing for (peak|max)"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": None},
            {"success": True, "value": 50.0, "locator": None},
        )

    # 3. Both locator are empty dicts
    with pytest.raises(BulkDataEquivalenceError, match=r"Empty locator dictionary is forbidden for (peak|max)"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {}},
            {"success": True, "value": 50.0, "locator": {}},
        )

    # 4. One locator is empty dict, other has full locator
    with pytest.raises(BulkDataEquivalenceError, match=r"Empty locator dictionary is forbidden for (peak|max)"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {}},
            {"success": True, "value": 50.0, "locator": {"instance": "PartA", "node_label": 10}},
        )

    # 5. Missing instance (only node_label provided)
    with pytest.raises(BulkDataEquivalenceError, match=r"Locator must contain non-empty 'instance'"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"node_label": 10}},
            {"success": True, "value": 50.0, "locator": {"node_label": 10}},
        )

    # 6. Instance is empty string
    with pytest.raises(BulkDataEquivalenceError, match=r"Locator must contain non-empty 'instance'"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"instance": "", "node_label": 10}},
            {"success": True, "value": 50.0, "locator": {"instance": "", "node_label": 10}},
        )

    # 7. Neither node_label nor element_label provided (only instance)
    with pytest.raises(BulkDataEquivalenceError, match=r"Locator must specify at least 'node_label' or 'element_label'"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"instance": "PartA"}},
            {"success": True, "value": 50.0, "locator": {"instance": "PartA"}},
        )

    # 8. Average metric rejects localized node_label / element_label
    with pytest.raises(BulkDataEquivalenceError, match="Average extraction cannot bind to specific point locator"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {"node_label": 10}, "aggregation": "average"},
            {"success": True, "value": 50.0, "locator": {}, "aggregation": "average"},
        )

    with pytest.raises(BulkDataEquivalenceError, match="Average extraction cannot bind to specific point locator"):
        verify_extraction_equivalence(
            {"success": True, "value": 50.0, "locator": {}, "aggregation": "average"},
            {"success": True, "value": 50.0, "locator": {"element_label": 20}, "aggregation": "average"},
        )

    # 9. Average metric passes with empty locator or instance-only locator
    avg_can = {"success": True, "value": 50.0, "locator": {}, "aggregation": "average"}
    avg_blk = {"success": True, "value": 50.0, "locator": {}, "aggregation": "average"}
    assert verify_extraction_equivalence(avg_can, avg_blk) == BulkDataEquivalenceStatus.EXACT_MATCH

    avg_inst_can = {"success": True, "value": 50.0, "locator": {"instance": "PartA"}, "aggregation": "average"}
    avg_inst_blk = {"success": True, "value": 50.0, "locator": {"instance": "PartA"}, "aggregation": "average"}
    assert verify_extraction_equivalence(avg_inst_can, avg_inst_blk) == BulkDataEquivalenceStatus.EXACT_MATCH

    # 10. Average metric locator instance mismatch returns LOCATOR_MISMATCH
    avg_diff_inst = {"success": True, "value": 50.0, "locator": {"instance": "PartB"}, "aggregation": "average"}
    assert verify_extraction_equivalence(avg_inst_can, avg_diff_inst) == BulkDataEquivalenceStatus.LOCATOR_MISMATCH


def test_verify_extraction_equivalence_unsupported_or_failure():
    """Both failing marks NOT_SUPPORTED, whereas one-sided failure raises error."""
    can_fail = {"success": False, "error": "Field not available"}
    blk_fail = {"success": False, "error": "Blocks not available"}
    assert verify_extraction_equivalence(can_fail, blk_fail) == BulkDataEquivalenceStatus.NOT_SUPPORTED

    with pytest.raises(BulkDataEquivalenceError, match="Success mismatch"):
        verify_extraction_equivalence({"success": True, "value": 1.0}, blk_fail)

    with pytest.raises(BulkDataEquivalenceError, match="Non-numeric or non-finite"):
        verify_extraction_equivalence({"success": True, "value": float("nan")}, {"success": True, "value": 1.0})

    with pytest.raises(BulkDataEquivalenceError, match="Non-numeric or non-finite"):
        verify_extraction_equivalence({"success": True, "value": True}, {"success": True, "value": 1.0})


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


def test_extract_scalar_from_blocks_fail_closed_on_invalid_data():
    """Any malformed row, boolean, NaN, Inf, or missing data field raises BulkDataEquivalenceError."""
    inst = SimpleNamespace(name="PART_1")

    # None blocks input
    with pytest.raises(BulkDataEquivalenceError, match="Blocks sequence cannot be None"):
        extract_scalar_from_blocks(None)

    # Empty blocks sequence returns None
    assert extract_scalar_from_blocks([]) is None

    # Empty rows across blocks returns None
    assert extract_scalar_from_blocks([SimpleNamespace(data=[], instance=inst)]) is None

    # Missing data attribute
    with pytest.raises(BulkDataEquivalenceError, match="lacks required 'data' field"):
        extract_scalar_from_blocks([SimpleNamespace(nodeLabels=[1])])

    # Boolean data row (direct and in sequence)
    with pytest.raises(BulkDataEquivalenceError, match="Boolean row invalid"):
        extract_scalar_from_blocks([SimpleNamespace(data=[True], instance=inst)])

    with pytest.raises(BulkDataEquivalenceError, match="Non-numeric row element"):
        extract_scalar_from_blocks([SimpleNamespace(data=[[True]], instance=inst)])

    # Non-finite float (NaN)
    with pytest.raises(BulkDataEquivalenceError, match="Non-finite float"):
        extract_scalar_from_blocks([SimpleNamespace(data=[[float("nan")]], instance=inst)])

    # Non-finite float (Inf)
    with pytest.raises(BulkDataEquivalenceError, match="Non-finite float"):
        extract_scalar_from_blocks([SimpleNamespace(data=[[float("inf")]], instance=inst)])

    # Empty row
    with pytest.raises(BulkDataEquivalenceError, match="Empty row data"):
        extract_scalar_from_blocks([SimpleNamespace(data=[[]], instance=inst)])

    # Non-numeric item in sequence
    with pytest.raises(BulkDataEquivalenceError, match="Non-numeric row element"):
        extract_scalar_from_blocks([SimpleNamespace(data=[["bad_str"]], instance=inst)])

    # Label array length mismatch (data has 2 rows, nodeLabels has 1)
    with pytest.raises(BulkDataEquivalenceError, match="nodeLabels length .* != data length"):
        extract_scalar_from_blocks([
            SimpleNamespace(data=[[1.0], [2.0]], nodeLabels=[10], instance=inst)
        ])

    # Element label array length mismatch
    with pytest.raises(BulkDataEquivalenceError, match="elementLabels length .* != data length"):
        extract_scalar_from_blocks([
            SimpleNamespace(data=[[1.0], [2.0]], elementLabels=[101, 102, 103], instance=inst)
        ])

    # Invalid label element (boolean or non-positive)
    with pytest.raises(BulkDataEquivalenceError, match="invalid integer label"):
        extract_scalar_from_blocks([
            SimpleNamespace(data=[[1.0]], nodeLabels=[True], instance=inst)
        ])

    with pytest.raises(BulkDataEquivalenceError, match="non-positive or invalid integer label"):
        extract_scalar_from_blocks([
            SimpleNamespace(data=[[1.0]], nodeLabels=[0], instance=inst)
        ])


def test_differential_equivalence_against_canonical_loop():
    """Verify that canonical values loop and bulkDataBlocks yield identical results across max, min, avg."""
    # Synthetic dataset
    raw_points = [
        {"val": 12.4, "node": 10, "elem": 101, "inst": "PartA"},
        {"val": 89.2, "node": 11, "elem": 102, "inst": "PartA"},
        {"val": -4.5, "node": 12, "elem": 103, "inst": "PartA"},
        {"val": 56.1, "node": 20, "elem": 201, "inst": "PartB"},
        {"val": 78.0, "node": 21, "elem": 202, "inst": "PartB"},
    ]

    # Canonical values loop result for MAX
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

    # Canonical values loop result for MIN
    min_pt = min(raw_points, key=lambda p: p["val"])
    canonical_min = {
        "success": True,
        "value": float(min_pt["val"]),
        "locator": {
            "node_label": min_pt["node"],
            "element_label": min_pt["elem"],
            "instance": min_pt["inst"],
        },
    }

    # Canonical values loop result for AVERAGE
    canonical_avg = {
        "success": True,
        "value": sum(p["val"] for p in raw_points) / float(len(raw_points)),
        "locator": {},
        "aggregation": "average",
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

    # 1. MAX Equivalence
    bulk_max = extract_scalar_from_blocks([b1, b2], aggregation="max")
    assert bulk_max is not None
    bulk_max_dict = {"success": True, "value": bulk_max.value, "locator": bulk_max.locator}
    assert verify_extraction_equivalence(canonical_max, bulk_max_dict) == BulkDataEquivalenceStatus.EXACT_MATCH

    # 2. MIN Equivalence
    bulk_min = extract_scalar_from_blocks([b1, b2], aggregation="min")
    assert bulk_min is not None
    bulk_min_dict = {"success": True, "value": bulk_min.value, "locator": bulk_min.locator}
    assert verify_extraction_equivalence(canonical_min, bulk_min_dict) == BulkDataEquivalenceStatus.EXACT_MATCH

    # 3. AVERAGE Equivalence
    bulk_avg = extract_scalar_from_blocks([b1, b2], aggregation="average")
    assert bulk_avg is not None
    bulk_avg_dict = {
        "success": True,
        "value": bulk_avg.value,
        "locator": bulk_avg.locator,
        "aggregation": bulk_avg.aggregation,
    }
    assert verify_extraction_equivalence(canonical_avg, bulk_avg_dict) == BulkDataEquivalenceStatus.EXACT_MATCH

    # 4. Injected drift Fail-Closed rejection
    drifted_bulk = dict(bulk_max_dict)
    drifted_bulk["value"] += 1e-4
    with pytest.raises(BulkDataEquivalenceError, match="Numerical drift exceeded tolerance"):
        verify_extraction_equivalence(canonical_max, drifted_bulk)


def test_verify_extraction_equivalence_rejects_conflicting_metric_types():
    """Extracting different metrics (e.g. average vs peak, or max vs min) must be rejected even if values match."""
    # Same value (50.0), but one is average and other is peak/max
    can_avg = {
        "success": True,
        "value": 50.0,
        "locator": {},
        "aggregation": "average",
    }
    blk_peak = {
        "success": True,
        "value": 50.0,
        "locator": {"instance": "PartA", "node_label": 10},
        "aggregation": "max",
    }
    with pytest.raises(BulkDataEquivalenceError, match="Conflicting metric types between canonical .* and bulk"):
        verify_extraction_equivalence(can_avg, blk_peak)

    # Max vs min conflict
    can_max = {
        "success": True,
        "value": 50.0,
        "locator": {"instance": "PartA", "node_label": 10},
        "aggregation": "max",
    }
    blk_min = {
        "success": True,
        "value": 50.0,
        "locator": {"instance": "PartA", "node_label": 10},
        "aggregation": "min",
    }
    with pytest.raises(BulkDataEquivalenceError, match="Conflicting metric types"):
        verify_extraction_equivalence(can_max, blk_min)

    # Explicit metric_type argument conflicts with dictionary declaration
    with pytest.raises(BulkDataEquivalenceError, match="Explicit metric_type .* conflicts with canonical"):
        verify_extraction_equivalence(can_avg, can_avg, metric_type="max")

    can_no_metric = {
        "success": True,
        "value": 50.0,
        "locator": {"instance": "PartA", "node_label": 10},
    }
    with pytest.raises(BulkDataEquivalenceError, match="Explicit metric_type .* conflicts with bulk"):
        verify_extraction_equivalence(can_no_metric, can_max, metric_type="average")

    # Non-string metric type rejected
    with pytest.raises(BulkDataEquivalenceError, match="metric_type/aggregation must be string"):
        verify_extraction_equivalence(can_max, can_max, metric_type=123)

    # Synonyms / compatible aliases pass without conflict
    # "peak" and "max" are compatible
    blk_synonym_peak = {
        "success": True,
        "value": 50.0,
        "locator": {"instance": "PartA", "node_label": 10},
        "metric_type": "peak",
    }
    assert verify_extraction_equivalence(can_max, blk_synonym_peak) == BulkDataEquivalenceStatus.EXACT_MATCH

    # "average" and "mean" are compatible
    blk_synonym_mean = {
        "success": True,
        "value": 50.0,
        "locator": {},
        "metric_type": "mean",
    }
    assert verify_extraction_equivalence(can_avg, blk_synonym_mean) == BulkDataEquivalenceStatus.EXACT_MATCH
