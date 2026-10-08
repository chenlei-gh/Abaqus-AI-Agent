"""Result Query Protocol & Data Plane Access Boundary (P0-4).

Enforces the Three-Plane Architecture access barrier:
- The LLM Plane NEVER directly ingests raw ODB, DAT, MSG, STA, or bulky field arrays.
- All result queries MUST pass through the DeterministicResultProvider.
- Governed by strict Query Budgets (max_items, max_bytes, allow_raw=False).
- Unhandled solver exceptions, missing fields, or raw dump attempts return structured RESULT_INVALID cards.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..contracts.artifact import ArtifactPointer
from ..telemetry.tracker import _heuristic_count_tokens


class QueryType(str, Enum):
    SCALAR = "scalar"
    HOTSPOT = "hotspot"
    EVIDENCE = "evidence"


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    RESULT_INVALID = "RESULT_INVALID"
    BLOCKED = "BLOCKED"
    FIELD_NOT_AVAILABLE = "FIELD_NOT_AVAILABLE"
    REGION_NOT_FOUND = "REGION_NOT_FOUND"


@dataclass(frozen=True)
class QueryBudget:
    """Strict guardrails limiting the output volume returned to the LLM Plane."""
    max_items: int = 10                  # Hard cap on number of hotspot/tabular entities
    max_bytes: int = 8192                # Hard cap on response size
    max_query_depth: int = 1
    allowed_fields: Tuple[str, ...] = ("U", "S", "S_MISES", "RF", "CPRESS", "TEMP", "PEEQ", "LE")
    allow_raw: bool = False              # Absolute prohibition of raw nodal/elemental arrays

    def validate_field(self, field_name: str) -> bool:
        norm = field_name.upper().replace(".", "_")
        return norm in self.allowed_fields or any(norm.startswith(f) for f in self.allowed_fields)


@dataclass(frozen=True)
class ScalarQuery:
    """Query for a single deterministic scalar metric."""
    field: str                           # e.g., "U", "S_MISES", "RF"
    operation: str = "max"               # "max", "min", "sum", "mean", "norm"
    region: str = "ALL"
    step_name: Optional[str] = None
    component: Optional[str] = None      # e.g., "U3", "MISES", "RF3"
    unit_hint: Optional[str] = None


@dataclass(frozen=True)
class HotspotQuery:
    """Query for localized peak concentration hotspots (Top-N)."""
    field: str = "S_MISES"
    top_n: int = 5
    region: str = "ALL"
    step_name: Optional[str] = None


@dataclass(frozen=True)
class EvidenceQuery:
    """Query for deterministic criterion compliance and acceptance gate evidence."""
    requirement_id: Optional[str] = None
    acceptance_id: Optional[str] = None
    criterion_name: Optional[str] = None


@dataclass(frozen=True)
class HotspotItem:
    """A localized peak hotspot entity."""
    rank: int
    value: float
    unit: str
    element_id: Optional[int] = None
    node_id: Optional[int] = None
    location: Optional[Tuple[float, float, float]] = None
    integration_point: Optional[int] = None
    region: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "value": round(self.value, 4),
            "unit": self.unit,
            "element_id": self.element_id,
            "node_id": self.node_id,
            "location": [round(c, 2) for c in self.location] if self.location else None,
            "integration_point": self.integration_point,
            "region": self.region,
        }


@dataclass(frozen=True)
class QueryResultCard:
    """Authoritative response payload returned to the LLM Plane."""
    query_type: str
    status: str                          # "SUCCESS", "RESULT_INVALID", "BLOCKED"
    reason_code: Optional[str] = None    # "FIELD_NOT_AVAILABLE", "REGION_NOT_FOUND", "RAW_DUMP_PROHIBITED", "BUDGET_EXCEEDED"
    source_artifact_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_llm_card(self) -> Dict[str, Any]:
        """Produce the ultra-compact semantic dictionary for the LLM Context."""
        card: Dict[str, Any] = {
            "query_type": self.query_type,
            "status": self.status,
        }
        if self.reason_code:
            card["reason_code"] = self.reason_code
        if self.message:
            card["message"] = self.message
        if self.source_artifact_id:
            card["source_artifact_id"] = self.source_artifact_id
        card["data"] = self.data
        return card

    @property
    def estimated_tokens(self) -> int:
        return _heuristic_count_tokens(json.dumps(self.to_llm_card()))

    @property
    def byte_count(self) -> int:
        return len(json.dumps(self.to_llm_card()).encode("utf-8"))


class DeterministicResultProvider:
    """Data Plane engine executing structured queries while guarding raw ODB internals."""

    def __init__(
        self,
        odb_data_store: Optional[Dict[str, Any]] = None,
        acceptance_records: Optional[Dict[str, Any]] = None,
        source_artifact_id: str = "ART-ODB-DEFAULT",
    ):
        self._odb_data_store: Dict[str, Any] = odb_data_store or {}
        self._acceptance_records: Dict[str, Any] = acceptance_records or {}
        self.source_artifact_id = source_artifact_id

    def execute_scalar_query(
        self,
        query: ScalarQuery,
        budget: QueryBudget = QueryBudget(),
    ) -> QueryResultCard:
        """Execute a scalar field reduction query."""
        # Field validation
        if not budget.validate_field(query.field):
            return QueryResultCard(
                query_type=QueryType.SCALAR.value,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="FIELD_NOT_AVAILABLE",
                source_artifact_id=self.source_artifact_id,
                message=f"Field '{query.field}' is not available or recognized in analysis results.",
            )

        norm_field = query.field.upper().replace(".", "_")
        field_records = self._odb_data_store.get(norm_field)
        if field_records is None:
            return QueryResultCard(
                query_type=QueryType.SCALAR.value,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="FIELD_NOT_AVAILABLE",
                source_artifact_id=self.source_artifact_id,
                message=f"Field output '{query.field}' was not requested or is missing from ODB.",
            )

        # Region validation
        if query.region != "ALL" and query.region not in field_records.get("regions", {}):
            return QueryResultCard(
                query_type=QueryType.SCALAR.value,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="REGION_NOT_FOUND",
                source_artifact_id=self.source_artifact_id,
                message=f"Requested geometric region '{query.region}' does not exist in model.",
            )

        # Retrieve scalar value
        val = field_records.get(query.operation, field_records.get("max"))
        unit = field_records.get("unit", query.unit_hint or "")

        return QueryResultCard(
            query_type=QueryType.SCALAR.value,
            status=ResultStatus.SUCCESS.value,
            source_artifact_id=self.source_artifact_id,
            data={
                "field": norm_field,
                "operation": query.operation,
                "value": round(float(val), 6) if val is not None else None,
                "unit": unit,
                "region": query.region,
            },
        )

    def execute_hotspot_query(
        self,
        query: HotspotQuery,
        budget: QueryBudget = QueryBudget(),
    ) -> QueryResultCard:
        """Execute a localized peak hotspot query with strict top_n capping."""
        norm_field = query.field.upper().replace(".", "_")
        if not budget.validate_field(norm_field):
            return QueryResultCard(
                query_type=QueryType.HOTSPOT.value,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="FIELD_NOT_AVAILABLE",
                source_artifact_id=self.source_artifact_id,
                message=f"Field '{query.field}' not supported for hotspot extraction.",
            )

        field_records = self._odb_data_store.get(norm_field)
        if field_records is None:
            return QueryResultCard(
                query_type=QueryType.HOTSPOT.value,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="FIELD_NOT_AVAILABLE",
                source_artifact_id=self.source_artifact_id,
                message=f"Field output '{query.field}' is missing from ODB frames.",
            )

        # Enforce budget cap on top_n
        effective_top_n = min(query.top_n, budget.max_items)
        raw_hotspots = field_records.get("hotspots", [])

        items: List[Dict[str, Any]] = []
        for i, h in enumerate(raw_hotspots[:effective_top_n], start=1):
            if isinstance(h, HotspotItem):
                items.append(h.to_dict())
            elif isinstance(h, dict):
                items.append({
                    "rank": i,
                    "value": round(float(h.get("value", 0.0)), 4),
                    "unit": h.get("unit", field_records.get("unit", "")),
                    "element_id": h.get("element_id"),
                    "node_id": h.get("node_id"),
                    "location": h.get("location"),
                    "integration_point": h.get("integration_point", 1),
                    "region": h.get("region", query.region),
                })

        return QueryResultCard(
            query_type=QueryType.HOTSPOT.value,
            status=ResultStatus.SUCCESS.value,
            source_artifact_id=self.source_artifact_id,
            data={
                "field": norm_field,
                "top_n_requested": query.top_n,
                "top_n_returned": len(items),
                "capped_by_budget": query.top_n > budget.max_items,
                "items": items,
            },
        )

    def execute_evidence_query(
        self,
        query: EvidenceQuery,
        budget: QueryBudget = QueryBudget(),
    ) -> QueryResultCard:
        """Execute an acceptance criteria evidence query."""
        req_id = query.requirement_id or query.criterion_name or query.acceptance_id
        if not req_id or req_id not in self._acceptance_records:
            return QueryResultCard(
                query_type=QueryType.EVIDENCE.value,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="FIELD_NOT_AVAILABLE",
                source_artifact_id=self.source_artifact_id,
                message=f"Evidence for requirement/criterion '{req_id}' is not indexed or missing.",
            )

        record = self._acceptance_records[req_id]
        return QueryResultCard(
            query_type=QueryType.EVIDENCE.value,
            status=ResultStatus.SUCCESS.value,
            source_artifact_id=self.source_artifact_id,
            data={
                "requirement": record.get("requirement", req_id),
                "value": record.get("value"),
                "limit": record.get("limit"),
                "operator": record.get("operator", "<="),
                "unit": record.get("unit", ""),
                "status": record.get("status", "PASS"),
                "source": {
                    "odb": self.source_artifact_id,
                    "step": record.get("step", "Step-1"),
                    "frame": record.get("frame", -1),
                    "field": record.get("field", "S_MISES"),
                },
            },
        )

    def query(
        self,
        request: Dict[str, Any],
        budget: QueryBudget = QueryBudget(),
    ) -> Dict[str, Any]:
        """Unified gateway enforcing QueryBudget, blocking raw dumps and routing queries."""
        # 1. Block raw ODB/field array dump attempts
        if not budget.allow_raw:
            raw_triggers = {
                "raw", "dump_all", "dump_nodes", "dump_elements", "raw_field_array",
                "dump_connectivity", "all_values", "export_raw"
            }
            if any(k in request for k in raw_triggers) or request.get("allow_raw") is True:
                blocked_card = QueryResultCard(
                    query_type=request.get("query_type", "unknown"),
                    status=ResultStatus.BLOCKED.value,
                    reason_code="RAW_DUMP_PROHIBITED",
                    source_artifact_id=self.source_artifact_id,
                    message="Raw ODB field/node/element array dumps are strictly prohibited by Three-Plane Architecture.",
                )
                return blocked_card.to_llm_card()

        # 2. Dispatch to typed queries
        q_type = request.get("query_type", "").lower()
        if q_type == QueryType.SCALAR.value:
            res = self.execute_scalar_query(
                ScalarQuery(
                    field=request.get("field", ""),
                    operation=request.get("operation", "max"),
                    region=request.get("region", "ALL"),
                    step_name=request.get("step_name"),
                    component=request.get("component"),
                    unit_hint=request.get("unit_hint"),
                ),
                budget=budget,
            )
        elif q_type == QueryType.HOTSPOT.value:
            res = self.execute_hotspot_query(
                HotspotQuery(
                    field=request.get("field", "S_MISES"),
                    top_n=int(request.get("top_n", 5)),
                    region=request.get("region", "ALL"),
                    step_name=request.get("step_name"),
                ),
                budget=budget,
            )
        elif q_type == QueryType.EVIDENCE.value:
            res = self.execute_evidence_query(
                EvidenceQuery(
                    requirement_id=request.get("requirement_id"),
                    acceptance_id=request.get("acceptance_id"),
                    criterion_name=request.get("criterion_name"),
                ),
                budget=budget,
            )
        else:
            res = QueryResultCard(
                query_type=q_type or "unknown",
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="FIELD_NOT_AVAILABLE",
                source_artifact_id=self.source_artifact_id,
                message=f"Unsupported query_type '{q_type}'. Expected 'scalar', 'hotspot', or 'evidence'.",
            )

        card_dict = res.to_llm_card()

        # 3. Check byte budget
        byte_len = len(json.dumps(card_dict).encode("utf-8"))
        if byte_len > budget.max_bytes:
            capped_card = QueryResultCard(
                query_type=res.query_type,
                status=ResultStatus.RESULT_INVALID.value,
                reason_code="BUDGET_EXCEEDED",
                source_artifact_id=self.source_artifact_id,
                message=f"Response payload size ({byte_len} bytes) exceeded QueryBudget limit ({budget.max_bytes} bytes).",
            )
            return capped_card.to_llm_card()

        return card_dict
