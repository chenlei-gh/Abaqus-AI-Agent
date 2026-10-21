"""BulkDataBlocks numerical equivalence contract and differential audit tools.

Governs Phase 3.3 runtime optimization: evaluates bulkDataBlocks vector extraction
against the canonical fo.values object traversal under strict numerical equivalence (tol < 1e-6).

Resolves Decision Blocker C2S:
1. Scope is strictly bounded to full-field scalar scans and peak value extractions.
2. Local node/element sets, history outputs, and tensor invariant reductions with
   spatial filtering remain on the canonical fo.values path.
3. Numerical equivalence threshold is strictly enforced at 1e-6 relative/absolute tolerance.
4. Main production execution remains on canonical fo.values until empirical proof of zero
   drift and positive runtime gain on authentic engineering scale ODBs is established.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

DEFAULT_FLOAT_TOLERANCE: float = 1e-6
CONTRACT_TOLERANCE_UPPER_BOUND: float = 1e-6


class BulkDataEquivalenceStatus(str, Enum):
    """Evaluation verdict for bulkDataBlocks vs canonical values extraction."""

    EXACT_MATCH = "EXACT_MATCH"
    EQUIVALENT = "EQUIVALENT"
    NUMERICAL_DRIFT = "NUMERICAL_DRIFT"
    LOCATOR_MISMATCH = "LOCATOR_MISMATCH"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNVERIFIED_REAL_ODB = "UNVERIFIED_REAL_ODB"


class BulkDataEquivalenceError(ValueError):
    """Raised when bulk extraction violates the numerical equivalence contract."""


def is_close_scalar(val_a: float, val_b: float, tol: float = DEFAULT_FLOAT_TOLERANCE) -> bool:
    """Evaluate if two scalar floats are within absolute/relative tolerance.

    Strictly enforces:
    1. Rejects boolean inputs (bool is a subclass of int in Python).
    2. Rejects non-numeric types and non-finite values (NaN, Inf).
    3. Rejects tolerances exceeding the contract upper bound (1e-6) or non-positive.
    4. Exact equality (zero drift) always passes.
    5. Non-zero drift must be strictly less than tol * scale (strictly < 1e-6).
    """
    if isinstance(val_a, bool) or not isinstance(val_a, (int, float)):
        return False
    if isinstance(val_b, bool) or not isinstance(val_b, (int, float)):
        return False
    if isinstance(tol, bool) or not isinstance(tol, (int, float)):
        return False

    val_a_f = float(val_a)
    val_b_f = float(val_b)
    tol_f = float(tol)

    if not (math.isfinite(val_a_f) and math.isfinite(val_b_f) and math.isfinite(tol_f)):
        return False
    if tol_f <= 0.0 or tol_f > CONTRACT_TOLERANCE_UPPER_BOUND:
        return False

    diff = abs(val_a_f - val_b_f)
    if diff == 0.0:
        return True

    scale = max(1.0, abs(val_a_f), abs(val_b_f))
    return diff < (tol_f * scale)


@dataclass(frozen=True)
class ScalarExtractionResult:
    """Extracted scalar metric with spatial locator."""

    value: float
    locator: Dict[str, Any] = field(default_factory=dict)
    method: str = "canonical_values"
    aggregation: str = "max"

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise BulkDataEquivalenceError(f"Extraction value must be finite, got: {self.value}")


def verify_extraction_equivalence(
    canonical: Dict[str, Any],
    bulk: Dict[str, Any],
    tol: float = DEFAULT_FLOAT_TOLERANCE,
    metric_type: Optional[str] = None,
) -> BulkDataEquivalenceStatus:
    """Verify that canonical values and bulkDataBlocks results are numerically equivalent.

    Raises BulkDataEquivalenceError if:
    1. Input types are malformed.
    2. Tolerance exceeds the contract upper bound of 1e-6 or is non-positive.
    3. Execution success flags do not match.
    4. Numerical drift exceeds tolerance (< 1e-6 relative drift).
    5. Required locator metadata is missing (both missing, empty dict, or missing instance/label for peak extractions).
    """
    if not isinstance(canonical, dict) or not isinstance(bulk, dict):
        raise BulkDataEquivalenceError("Both canonical and bulk results must be dictionaries.")

    if not isinstance(tol, (int, float)) or isinstance(tol, bool) or not math.isfinite(tol):
        raise BulkDataEquivalenceError(f"Tolerance must be a finite float, got: {tol!r}")
    if tol <= 0.0 or tol > CONTRACT_TOLERANCE_UPPER_BOUND:
        raise BulkDataEquivalenceError(
            f"Tolerance cannot exceed contract upper bound {CONTRACT_TOLERANCE_UPPER_BOUND} "
            f"or be non-positive, got: {tol}"
        )

    can_succ = canonical.get("success", False)
    blk_succ = bulk.get("success", False)

    if not can_succ or not blk_succ:
        if can_succ != blk_succ:
            raise BulkDataEquivalenceError(
                f"Success mismatch: canonical={can_succ}, bulk={blk_succ}"
            )
        return BulkDataEquivalenceStatus.NOT_SUPPORTED

    val_can = canonical.get("value")
    val_blk = bulk.get("value")

    if not isinstance(val_can, (int, float)) or isinstance(val_can, bool) or not math.isfinite(float(val_can)):
        raise BulkDataEquivalenceError(f"Non-numeric or non-finite canonical value: {val_can!r}")
    if not isinstance(val_blk, (int, float)) or isinstance(val_blk, bool) or not math.isfinite(float(val_blk)):
        raise BulkDataEquivalenceError(f"Non-numeric or non-finite bulk value: {val_blk!r}")

    val_can_f = float(val_can)
    val_blk_f = float(val_blk)

    diff = abs(val_can_f - val_blk_f)
    if not is_close_scalar(val_can_f, val_blk_f, tol=tol):
        scale = max(1.0, abs(val_can_f), abs(val_blk_f))
        rel_diff = diff / scale
        raise BulkDataEquivalenceError(
            f"Numerical drift exceeded tolerance ({tol}): canonical={val_can_f}, "
            f"bulk={val_blk_f}, relative_diff={rel_diff:.3e}"
        )

    # Determine extraction metric type
    m_type = (
        metric_type
        or canonical.get("metric_type")
        or canonical.get("aggregation")
        or bulk.get("metric_type")
        or bulk.get("aggregation")
        or "peak"
    )
    if not isinstance(m_type, str):
        raise BulkDataEquivalenceError(f"metric_type must be a string, got: {type(m_type)}")
    m_type = m_type.lower().strip()

    loc_can = canonical.get("locator")
    loc_blk = bulk.get("locator")

    if m_type in {"peak", "max", "min", "extreme"}:
        # Peak / extreme scalar extractions REQUIRE spatial locator metadata
        if loc_can is None or loc_blk is None:
            raise BulkDataEquivalenceError(
                f"Required locator metadata is missing for {m_type} extraction: "
                f"canonical has={loc_can is not None}, bulk has={loc_blk is not None}"
            )
        if not isinstance(loc_can, dict) or not isinstance(loc_blk, dict):
            raise BulkDataEquivalenceError("Locators must be dictionary objects.")
        if len(loc_can) == 0 or len(loc_blk) == 0:
            raise BulkDataEquivalenceError(
                f"Empty locator dictionary is forbidden for {m_type} extraction."
            )

        # Instance name is strictly required
        inst_can = loc_can.get("instance")
        inst_blk = loc_blk.get("instance")
        if not inst_can or not inst_blk:
            raise BulkDataEquivalenceError(
                f"Locator must contain non-empty 'instance' string for {m_type} extraction: "
                f"canonical={inst_can!r}, bulk={inst_blk!r}"
            )
        if not isinstance(inst_can, str) or not isinstance(inst_blk, str):
            raise BulkDataEquivalenceError("Instance names in locator must be strings.")
        if inst_can != inst_blk:
            return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

        # At least one spatial label (node_label or element_label) is strictly required
        has_label_can = loc_can.get("node_label") is not None or loc_can.get("element_label") is not None
        has_label_blk = loc_blk.get("node_label") is not None or loc_blk.get("element_label") is not None
        if not has_label_can or not has_label_blk:
            raise BulkDataEquivalenceError(
                f"Locator must specify at least 'node_label' or 'element_label' for {m_type} extraction."
            )

        # Symmetry check for all locator keys
        for k in ("instance", "node_label", "element_label"):
            has_can = loc_can.get(k) is not None
            has_blk = loc_blk.get(k) is not None
            if has_can != has_blk:
                raise BulkDataEquivalenceError(
                    f"Asymmetric locator metadata for key '{k}': canonical={loc_can.get(k)!r}, bulk={loc_blk.get(k)!r}"
                )

        # Node label check
        nl_can = loc_can.get("node_label")
        nl_blk = loc_blk.get("node_label")
        if nl_can is not None and nl_blk is not None:
            if isinstance(nl_can, bool) or not isinstance(nl_can, int) or nl_can <= 0:
                raise BulkDataEquivalenceError(f"Invalid canonical node_label: {nl_can!r}")
            if isinstance(nl_blk, bool) or not isinstance(nl_blk, int) or nl_blk <= 0:
                raise BulkDataEquivalenceError(f"Invalid bulk node_label: {nl_blk!r}")
            if nl_can != nl_blk:
                return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

        # Element label check
        el_can = loc_can.get("element_label")
        el_blk = loc_blk.get("element_label")
        if el_can is not None and el_blk is not None:
            if isinstance(el_can, bool) or not isinstance(el_can, int) or el_can <= 0:
                raise BulkDataEquivalenceError(f"Invalid canonical element_label: {el_can!r}")
            if isinstance(el_blk, bool) or not isinstance(el_blk, int) or el_blk <= 0:
                raise BulkDataEquivalenceError(f"Invalid bulk element_label: {el_blk!r}")
            if el_can != el_blk:
                return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

    elif m_type in {"average", "mean"}:
        # Average / mean metrics have independent locator rules:
        # They cannot bind to a localized point (node or element label).
        for side_name, loc in (("canonical", loc_can), ("bulk", loc_blk)):
            if isinstance(loc, dict):
                if loc.get("node_label") is not None or loc.get("element_label") is not None:
                    raise BulkDataEquivalenceError(
                        f"Average extraction cannot bind to specific point locator in {side_name}: {loc!r}"
                    )
        # Check instance symmetry if specified on either side
        if loc_can is not None or loc_blk is not None:
            if loc_can is None or loc_blk is None:
                raise BulkDataEquivalenceError(
                    f"Locator presence mismatch for {m_type}: canonical has={loc_can is not None}, bulk has={loc_blk is not None}"
                )
            if not isinstance(loc_can, dict) or not isinstance(loc_blk, dict):
                raise BulkDataEquivalenceError("Locators must be dictionary objects.")
            inst_can = loc_can.get("instance")
            inst_blk = loc_blk.get("instance")
            if (inst_can is not None) != (inst_blk is not None):
                raise BulkDataEquivalenceError(
                    f"Asymmetric instance metadata for {m_type}: canonical={inst_can!r}, bulk={inst_blk!r}"
                )
            if inst_can is not None and inst_blk is not None and inst_can != inst_blk:
                return BulkDataEquivalenceStatus.LOCATOR_MISMATCH
    else:
        raise BulkDataEquivalenceError(f"Unsupported metric_type: {m_type!r}")

    if diff == 0.0:
        return BulkDataEquivalenceStatus.EXACT_MATCH
    return BulkDataEquivalenceStatus.EQUIVALENT


def extract_scalar_from_blocks(
    blocks: Optional[Sequence[Any]],
    aggregation: str = "max",
) -> Optional[ScalarExtractionResult]:
    """Pure-Python offline reference algorithm for extracting scalar metrics from bulkDataBlocks.

    Each block is expected to offer:
    - `data`: iterable of rows, where row is float or sequence with float as first element
    - `nodeLabels`: optional sequence of int node labels (must match data length if provided)
    - `elementLabels`: optional sequence of int element labels (must match data length if provided)
    - `instance`: optional object with name attribute
    """
    if blocks is None:
        raise BulkDataEquivalenceError("Blocks sequence cannot be None.")
    if len(blocks) == 0:
        return None

    best_val: Optional[float] = None
    best_loc: Dict[str, Any] = {}
    sum_val: float = 0.0
    count: int = 0

    agg = aggregation.lower().strip()
    if agg not in {"max", "min", "average"}:
        raise BulkDataEquivalenceError(f"Unsupported aggregation: {aggregation!r}")

    for b_idx, b in enumerate(blocks):
        data = getattr(b, "data", None)
        if data is None:
            raise BulkDataEquivalenceError(f"Block at index {b_idx} lacks required 'data' field.")
        
        node_labels = getattr(b, "nodeLabels", None)
        elem_labels = getattr(b, "elementLabels", None)
        inst = getattr(b, "instance", None)
        inst_name = getattr(inst, "name", str(inst)) if inst else None

        len_data = len(data) if hasattr(data, "__len__") else None

        # Validate label array lengths and types if provided
        if node_labels is not None:
            if isinstance(node_labels, bool) or not hasattr(node_labels, "__len__"):
                raise BulkDataEquivalenceError(f"Block at index {b_idx} has invalid nodeLabels format.")
            if len_data is not None and len(node_labels) != len_data:
                raise BulkDataEquivalenceError(
                    f"Block at index {b_idx} nodeLabels length ({len(node_labels)}) != data length ({len_data})"
                )
            for nl_idx, nl in enumerate(node_labels):
                if isinstance(nl, bool) or not isinstance(nl, int) or nl <= 0:
                    raise BulkDataEquivalenceError(
                        f"Block at index {b_idx} nodeLabels[{nl_idx}] has non-positive or invalid integer label: {nl!r}"
                    )

        if elem_labels is not None:
            if isinstance(elem_labels, bool) or not hasattr(elem_labels, "__len__"):
                raise BulkDataEquivalenceError(f"Block at index {b_idx} has invalid elementLabels format.")
            if len_data is not None and len(elem_labels) != len_data:
                raise BulkDataEquivalenceError(
                    f"Block at index {b_idx} elementLabels length ({len(elem_labels)}) != data length ({len_data})"
                )
            for el_idx, el in enumerate(elem_labels):
                if isinstance(el, bool) or not isinstance(el, int) or el <= 0:
                    raise BulkDataEquivalenceError(
                        f"Block at index {b_idx} elementLabels[{el_idx}] has non-positive or invalid integer label: {el!r}"
                    )

        for idx, row in enumerate(data):
            if isinstance(row, bool):
                raise BulkDataEquivalenceError(
                    f"Boolean row invalid at block {b_idx}, row {idx}"
                )
            if isinstance(row, (int, float)):
                v = float(row)
            elif hasattr(row, "__iter__"):
                row_list = list(row)
                if not row_list:
                    raise BulkDataEquivalenceError(
                        f"Empty row data at block {b_idx}, row {idx}"
                    )
                first_item = row_list[0]
                if not isinstance(first_item, (int, float)) or isinstance(first_item, bool):
                    raise BulkDataEquivalenceError(
                        f"Non-numeric row element at block {b_idx}, row {idx}: {first_item!r}"
                    )
                v = float(first_item)
            else:
                raise BulkDataEquivalenceError(
                    f"Malformed row data type at block {b_idx}, row {idx}: {type(row)}"
                )

            if not math.isfinite(v):
                raise BulkDataEquivalenceError(
                    f"Non-finite float at block {b_idx}, row {idx}: {v}"
                )

            count += 1
            sum_val += v

            update = False
            if best_val is None:
                update = True
            elif agg == "max" and v > best_val:
                update = True
            elif agg == "min" and v < best_val:
                update = True

            if update and agg in {"max", "min"}:
                best_val = v
                best_loc = {
                    "instance": inst_name,
                    "node_label": node_labels[idx] if node_labels is not None else None,
                    "element_label": elem_labels[idx] if elem_labels is not None else None,
                }

    if count == 0:
        return None

    if agg == "average":
        return ScalarExtractionResult(
            value=sum_val / float(count),
            locator={},
            method="bulk_data_blocks",
            aggregation="average",
        )

    assert best_val is not None
    return ScalarExtractionResult(
        value=best_val,
        locator=best_loc,
        method="bulk_data_blocks",
        aggregation=agg,
    )
