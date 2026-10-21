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


class BulkDataEquivalenceStatus(str, Enum):
    """Evaluation verdict for bulkDataBlocks vs canonical values extraction."""

    EQUIVALENT = "EQUIVALENT"
    NUMERICAL_DRIFT = "NUMERICAL_DRIFT"
    LOCATOR_MISMATCH = "LOCATOR_MISMATCH"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNVERIFIED_REAL_ODB = "UNVERIFIED_REAL_ODB"


class BulkDataEquivalenceError(ValueError):
    """Raised when bulk extraction violates the numerical equivalence contract."""


def is_close_scalar(val_a: float, val_b: float, tol: float = DEFAULT_FLOAT_TOLERANCE) -> bool:
    """Evaluate if two scalar floats are within absolute/relative tolerance."""
    if not (math.isfinite(val_a) and math.isfinite(val_b)):
        return False
    scale = max(1.0, abs(val_a), abs(val_b))
    return abs(val_a - val_b) <= tol * scale


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

    Raises BulkDataEquivalenceError if status fails or numerical drift exceeds tol.
    """
    if not isinstance(canonical, dict) or not isinstance(bulk, dict):
        raise BulkDataEquivalenceError("Both canonical and bulk results must be dictionaries.")

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

    if not isinstance(val_can, (int, float)) or not isinstance(val_blk, (int, float)):
        raise BulkDataEquivalenceError(
            f"Non-numeric values returned: canonical={val_can!r}, bulk={val_blk!r}"
        )

    val_can_f = float(val_can)
    val_blk_f = float(val_blk)

    if not is_close_scalar(val_can_f, val_blk_f, tol=tol):
        scale = max(1.0, abs(val_can_f), abs(val_blk_f))
        diff = abs(val_can_f - val_blk_f) / scale
        raise BulkDataEquivalenceError(
            f"Numerical drift exceeded tolerance ({tol}): canonical={val_can_f}, "
            f"bulk={val_blk_f}, relative_diff={diff:.3e}"
        )

    # Compare spatial locators if present
    loc_can = canonical.get("locator") or {}
    loc_blk = bulk.get("locator") or {}

    # Node label check (when present in both)
    nl_can = loc_can.get("node_label")
    nl_blk = loc_blk.get("node_label")
    if nl_can is not None and nl_blk is not None and nl_can != nl_blk:
        # If values are numerically identical (e.g. symmetric max), locator mismatch is noted
        return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

    # Element label check (when present in both)
    el_can = loc_can.get("element_label")
    el_blk = loc_blk.get("element_label")
    if el_can is not None and el_blk is not None and el_can != el_blk:
        return BulkDataEquivalenceStatus.LOCATOR_MISMATCH

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

    for b in blocks:
        data = getattr(b, "data", None)
        if data is None:
            continue
        node_labels = getattr(b, "nodeLabels", None)
        elem_labels = getattr(b, "elementLabels", None)
        inst = getattr(b, "instance", None)
        inst_name = getattr(inst, "name", str(inst)) if inst else None

        for idx, row in enumerate(data):
            if isinstance(row, (int, float)):
                v = float(row)
            elif hasattr(row, "__iter__"):
                row_list = list(row)
                if not row_list or not isinstance(row_list[0], (int, float)):
                    continue
                v = float(row_list[0])
            else:
                continue

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
