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
    1. Rejects non-finite values (NaN, Inf).
    2. Rejects tolerances exceeding the contract upper bound (1e-6) or non-positive.
    3. Exact equality (zero drift) always passes.
    4. Non-zero drift must be strictly less than tol * scale (strictly < 1e-6).
    """
    if not (math.isfinite(val_a) and math.isfinite(val_b)):
        return False
    if not math.isfinite(tol) or tol <= 0.0 or tol > CONTRACT_TOLERANCE_UPPER_BOUND:
        return False

    diff = abs(val_a - val_b)
    if diff == 0.0:
        return True

    scale = max(1.0, abs(val_a), abs(val_b))
    return diff < (tol * scale)


@dataclass(frozen=True)
class ScalarExtractionResult:
    """Extracted scalar metric with spatial locator."""

    value: float
    locator: Dict[str, Any] = field(default_factory=dict)
    method: str = "canonical_values"

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise BulkDataEquivalenceError(f"Extraction value must be finite, got: {self.value}")


def verify_extraction_equivalence(
    canonical: Dict[str, Any],
    bulk: Dict[str, Any],
    tol: float = DEFAULT_FLOAT_TOLERANCE,
) -> BulkDataEquivalenceStatus:
    """Verify that canonical values and bulkDataBlocks results are numerically equivalent.

    Raises BulkDataEquivalenceError if:
    1. Input types are malformed.
    2. Tolerance exceeds the contract upper bound of 1e-6 or is non-positive.
    3. Execution success flags do not match.
    4. Numerical drift exceeds tolerance (< 1e-6 relative drift).
    5. Required locator metadata is missing.
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

    # Compare spatial locators: instance, node_label, element_label
    loc_can = canonical.get("locator")
    loc_blk = bulk.get("locator")

    if loc_can is not None or loc_blk is not None:
        if loc_can is None or loc_blk is None:
            # One has locator metadata while the other is missing
            raise BulkDataEquivalenceError(
                f"Locator presence mismatch: canonical has={loc_can is not None}, bulk has={loc_blk is not None}"
            )
        if not isinstance(loc_can, dict) or not isinstance(loc_blk, dict):
            raise BulkDataEquivalenceError("Locators must be dictionary objects.")

        # Instance name check
        inst_can = loc_can.get("instance")
        inst_blk = loc_blk.get("instance")
        if inst_can is not None and inst_blk is not None and inst_can != inst_blk:
            return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

        # Node label check (when present in both)
        nl_can = loc_can.get("node_label")
        nl_blk = loc_blk.get("node_label")
        if nl_can is not None and nl_blk is not None and nl_can != nl_blk:
            return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

        # Element label check (when present in both)
        el_can = loc_can.get("element_label")
        el_blk = loc_blk.get("element_label")
        if el_can is not None and el_blk is not None and el_can != el_blk:
            return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

    if diff == 0.0:
        return BulkDataEquivalenceStatus.EXACT_MATCH
    return BulkDataEquivalenceStatus.EQUIVALENT


def extract_scalar_from_blocks(
    blocks: Sequence[Any],
    aggregation: str = "max",
) -> Optional[ScalarExtractionResult]:
    """Pure-Python offline reference algorithm for extracting scalar metrics from bulkDataBlocks.

    Each block is expected to offer:
    - `data`: iterable of rows, where row is float or sequence with float as first element
    - `nodeLabels`: optional sequence of int node labels
    - `elementLabels`: optional sequence of int element labels
    - `instance`: optional object with name attribute
    """
    if not blocks:
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
                    "node_label": node_labels[idx] if node_labels is not None and idx < len(node_labels) else None,
                    "element_label": elem_labels[idx] if elem_labels is not None and idx < len(elem_labels) else None,
                }

    if count == 0:
        return None

    if agg == "average":
        return ScalarExtractionResult(
            value=sum_val / float(count),
            locator={},
            method="bulk_data_blocks",
        )

    assert best_val is not None
    return ScalarExtractionResult(
        value=best_val,
        locator=best_loc,
        method="bulk_data_blocks",
    )
