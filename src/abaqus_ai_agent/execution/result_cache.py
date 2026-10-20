"""ODB extraction result cache and lightweight ``result_ref`` pointer.

Implements Governance Plan 契约 B.2 (ODB 提取缓存与引用契约):

- Extraction results are persisted to ``.cache/results/{run_id}_{odb_sha256[:8]}.json``.
- Reuse requires **all five** bindings to match exactly:
  ``input_hash``, ``odb_sha256``, ``extraction_spec``, ``extractor_version``, ``units``.
  Any mismatch means the cache is not reused; it is never "close enough".
- The cache is a *pointer substrate for the LLM plane*, never a replacement for
  evidence. The original ODB binary and solver logs are never modified or removed.
- What the model receives is a scalar summary below 1500 characters; the full causal
  payload stays on disk behind ``result_ref``.

Design boundary: a cache write failure must not discard a freshly obtained authentic
result. It is recorded on the report, not raised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ..contracts.results import ResultExtraction, ResultRequirement
from ..evidence.model import Evidence

CACHE_SCHEMA_VERSION = "odb_result_cache_v1"

#: Hard ceiling for the summary handed to the model (TC-TOK-03).
MAX_RESULT_REF_CHARS = 1500

ENV_RESULT_CACHE_DIR = "ABAQUS_AGENT_RESULT_CACHE_DIR"


class ResultCacheError(RuntimeError):
    """Raised when a cache entry exists but cannot be trusted or decoded."""


# ---------------------------------------------------------------------------
# Cache location
# ---------------------------------------------------------------------------

def resolve_result_cache_root(override: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the root of the extraction result cache.

    Priority: explicit override -> ``ABAQUS_AGENT_RESULT_CACHE_DIR`` -> a
    user-local directory next to the ephemeral runs root.

    The default never points inside the product checkout: the cache is machine-local
    derived state, not a tracked artifact.
    """
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_RESULT_CACHE_DIR, "").strip()
    if env_val:
        return Path(env_val).resolve()
    from ..paths import resolve_runs_root

    return (resolve_runs_root().parent / ".cache" / "results").resolve()


def cache_entry_path(
    run_id: str,
    odb_sha256: str,
    cache_root: Optional[Union[str, Path]] = None,
) -> Path:
    """Return ``<root>/{run_id}_{odb_sha256[:8]}.json`` for a run/ODB pair."""
    root = resolve_result_cache_root(cache_root)
    return root / f"{run_id}_{odb_sha256[:8]}.json"


# ---------------------------------------------------------------------------
# Binding (5 conditions)
# ---------------------------------------------------------------------------

def normalized_extraction_spec(
    requirements: Sequence[ResultRequirement],
) -> List[Dict[str, Any]]:
    """Canonical, order-independent description of the extraction request."""
    specs = [req.to_dict() for req in requirements]
    return sorted(specs, key=lambda d: (d.get("value_key") or "", d.get("name") or ""))


def extraction_spec_digest(requirements: Sequence[ResultRequirement]) -> str:
    payload = json.dumps(
        normalized_extraction_spec(requirements),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized_units(requirements: Sequence[ResultRequirement]) -> List[str]:
    """Units participating in the binding, aligned with the sorted spec order."""
    return [str(req.unit or "") for req in sorted(
        requirements, key=lambda r: (r.value_key or "", r.name or "")
    )]


@dataclass(frozen=True)
class CacheBinding:
    """The five conditions that must match exactly for a cache hit."""
    input_hash: str
    odb_sha256: str
    extraction_spec: str
    extractor_version: str
    units: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_hash": self.input_hash,
            "odb_sha256": self.odb_sha256,
            "extraction_spec": self.extraction_spec,
            "extractor_version": self.extractor_version,
            "units": list(self.units),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CacheBinding":
        return cls(
            input_hash=str(d.get("input_hash", "")),
            odb_sha256=str(d.get("odb_sha256", "")),
            extraction_spec=str(d.get("extraction_spec", "")),
            extractor_version=str(d.get("extractor_version", "")),
            units=tuple(str(u) for u in (d.get("units") or ())),
        )

    def mismatches(self, other: "CacheBinding") -> Tuple[str, ...]:
        """Return the names of the conditions that do not match."""
        bad: List[str] = []
        if self.input_hash != other.input_hash:
            bad.append("input_hash")
        if self.odb_sha256 != other.odb_sha256:
            bad.append("odb_sha256")
        if self.extraction_spec != other.extraction_spec:
            bad.append("extraction_spec")
        if self.extractor_version != other.extractor_version:
            bad.append("extractor_version")
        if self.units != other.units:
            bad.append("units")
        return tuple(bad)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _requirement_to_dict(req: ResultRequirement) -> Dict[str, Any]:
    return req.to_dict()


def _requirement_from_dict(d: Dict[str, Any]) -> ResultRequirement:
    return ResultRequirement(
        name=str(d["name"]),
        value_key=str(d["value_key"]),
        field=d.get("field"),
        component=d.get("component"),
        invariant=d.get("invariant"),
        aggregation=d.get("aggregation", "max"),
        step=d.get("step"),
        frame=int(d.get("frame", -1)),
        position=d.get("position"),
        region=d.get("region"),
        history_region=d.get("history_region"),
        history_region_expression=d.get("history_region_expression"),
        history_variable=d.get("history_variable"),
        unit=str(d.get("unit", "")),
        output_kind=d.get("output_kind", "field"),
        quantity=d.get("quantity"),
        source=d.get("source", "odb"),
        required=bool(d.get("required", True)),
        reducer=d.get("reducer"),
        metadata=dict(d.get("metadata") or {}),
    )


def _evidence_to_dict(ev: Any) -> Dict[str, Any]:
    if isinstance(ev, Evidence):
        return {
            "kind": ev.kind,
            "source": ev.source,
            "locator": ev.locator,
            "value": ev.value,
            "unit": ev.unit,
            "metadata": dict(ev.metadata),
        }
    if isinstance(ev, dict):
        return dict(ev)
    raise ResultCacheError(f"Unsupported evidence item type in extraction result: {type(ev)!r}")


def _evidence_from_dict(d: Dict[str, Any]) -> Evidence:
    return Evidence(
        kind=str(d.get("kind", "")),
        source=str(d.get("source", "")),
        locator=str(d.get("locator", "")),
        value=d.get("value"),
        unit=str(d.get("unit", "")),
        metadata=dict(d.get("metadata") or {}),
    )


def report_to_payload(report: Any) -> Dict[str, Any]:
    """Serialize an ``OdbExtractionReport`` into a JSON-compatible payload."""
    return {
        "run_id": report.run_id,
        "input_hash": report.input_hash,
        "odb_path": str(report.odb_path),
        "odb_sha256": report.odb_sha256,
        "timestamp": report.timestamp,
        "extractions": [
            {
                "requirement": _requirement_to_dict(ext.requirement),
                "value": float(ext.value),
                "locator": dict(ext.locator or {}),
                "evidence": [_evidence_to_dict(e) for e in (ext.evidence or ())],
            }
            for ext in report.extractions
        ],
        "metrics": {str(k): float(v) for k, v in report.metrics.items()},
        "evidence": [_evidence_to_dict(e) for e in (report.evidence or ())],
        "metadata": dict(report.metadata or {}),
        "energy_evidence": report.energy_evidence,
    }


# ---------------------------------------------------------------------------
# ResultRef: the lightweight pointer handed to the model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultRef:
    """Compact reference describing where the full causal payload lives."""
    cache_path: str
    run_id: str
    input_hash: str
    odb_sha256: str
    extractor_version: str
    extraction_spec: str
    units: Tuple[str, ...]
    metrics: Dict[str, float] = field(default_factory=dict)
    extraction_count: int = 0
    evidence_count: int = 0
    energy_status: Optional[str] = None
    created_at: float = 0.0
    schema: str = CACHE_SCHEMA_VERSION

    @property
    def ref_id(self) -> str:
        return f"{self.run_id}_{self.odb_sha256[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "result_ref": self.ref_id,
            "schema": self.schema,
            "cache_path": self.cache_path,
            "run_id": self.run_id,
            "odb_sha256": self.odb_sha256,
            "input_hash": self.input_hash,
            "extractor_version": self.extractor_version,
            "extraction_spec": self.extraction_spec,
            "units": list(self.units),
            "counts": {"extractions": self.extraction_count, "evidence": self.evidence_count},
            "metrics": dict(self.metrics),
            "energy_status": self.energy_status,
            "created_at": self.created_at,
        }
        return d

    def to_llm_json(self, max_chars: int = MAX_RESULT_REF_CHARS) -> str:
        """Serialize the pointer, deterministically trimming metrics to stay bounded.

        The trim is recorded (``metrics_truncated``) so a reader can tell that the
        summary is partial; the full set is always available behind ``cache_path``.
        """
        payload = self.to_dict()
        ordered = sorted(self.metrics.items(), key=lambda kv: (-abs(kv[1]), kv[0]))
        keep = len(ordered)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        while keep > 0 and len(text) > max_chars:
            keep -= 1
            trimmed = dict(payload)
            trimmed["metrics"] = {k: v for k, v in ordered[:keep]}
            trimmed["metrics_truncated"] = True
            trimmed["metrics_total"] = len(ordered)
            text = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
        if len(text) > max_chars:
            raise ResultCacheError(
                f"result_ref summary cannot fit in {max_chars} characters "
                f"({len(text)} chars after trimming metrics)."
            )
        return text

    def to_llm_card(self, max_chars: int = MAX_RESULT_REF_CHARS) -> Dict[str, Any]:
        return json.loads(self.to_llm_json(max_chars=max_chars))


def build_result_ref(report: Any, cache_path: Union[str, Path], extractor_version: str,
                     binding: CacheBinding) -> ResultRef:
    energy_status = None
    if isinstance(report.energy_evidence, dict):
        energy_status = report.energy_evidence.get("status")
    return ResultRef(
        cache_path=str(cache_path),
        run_id=report.run_id,
        input_hash=report.input_hash,
        odb_sha256=report.odb_sha256,
        extractor_version=extractor_version,
        extraction_spec=binding.extraction_spec,
        units=binding.units,
        metrics=dict(report.metrics),
        extraction_count=len(report.extractions),
        evidence_count=len(report.evidence),
        energy_status=str(energy_status) if energy_status is not None else None,
        created_at=float(report.timestamp),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_result_cache(
    report: Any,
    binding: CacheBinding,
    cache_path: Path,
    result_ref: ResultRef,
) -> Path:
    """Persist the extraction payload next to its pointer. Atomic replace, no deletes."""
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "binding": binding.to_dict(),
        "result_ref": result_ref.to_dict(),
        "report": report_to_payload(report),
    }
    _atomic_write_json(Path(cache_path), payload)
    return Path(cache_path)


def read_result_cache_payload(cache_path: Union[str, Path]) -> Dict[str, Any]:
    path = Path(cache_path)
    if not path.is_file():
        raise ResultCacheError(f"result_ref cache entry does not exist: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ResultCacheError(f"result_ref cache entry is unreadable: {path}: {exc}") from exc


def binding_of_payload(payload: Dict[str, Any]) -> CacheBinding:
    if payload.get("schema") != CACHE_SCHEMA_VERSION:
        raise ResultCacheError(
            f"Unsupported result cache schema {payload.get('schema')!r}; "
            f"expected {CACHE_SCHEMA_VERSION!r}."
        )
    return CacheBinding.from_dict(payload.get("binding") or {})


def check_cache_binding(
    payload: Dict[str, Any],
    expected: CacheBinding,
) -> Tuple[bool, Tuple[str, ...]]:
    """Return ``(hit, mismatched_conditions)``. Any mismatch means no reuse."""
    stored = binding_of_payload(payload)
    bad = stored.mismatches(expected)
    return (not bad, bad)


def report_from_payload(payload: Dict[str, Any]) -> Any:
    """Rebuild an ``OdbExtractionReport`` from a cache payload."""
    from .odb_extractor import OdbExtractionReport

    body = payload.get("report")
    if not isinstance(body, dict):
        raise ResultCacheError("result_ref cache entry has no report body.")

    extractions: List[ResultExtraction] = []
    for item in body.get("extractions") or ():
        req = _requirement_from_dict(item["requirement"])
        extractions.append(
            ResultExtraction(
                requirement=req,
                value=float(item["value"]),
                locator=dict(item.get("locator") or {}),
                evidence=tuple(_evidence_from_dict(e) for e in (item.get("evidence") or ())),
            )
        )

    return OdbExtractionReport(
        run_id=str(body.get("run_id", "")),
        input_hash=str(body.get("input_hash", "")),
        odb_path=Path(body.get("odb_path", "")),
        odb_sha256=str(body.get("odb_sha256", "")),
        extractions=tuple(extractions),
        metrics={str(k): float(v) for k, v in (body.get("metrics") or {}).items()},
        evidence=tuple(_evidence_from_dict(e) for e in (body.get("evidence") or ())),
        metadata=dict(body.get("metadata") or {}),
        energy_evidence=body.get("energy_evidence"),
        timestamp=float(body.get("timestamp", 0.0)),
    )


def result_ref_from_payload(payload: Dict[str, Any], cache_path: Union[str, Path]) -> ResultRef:
    """Read the pointer back from a cache entry (disk is authoritative for its path)."""
    d = payload.get("result_ref")
    if not isinstance(d, dict):
        raise ResultCacheError("result_ref cache entry has no result_ref block.")
    counts = d.get("counts") or {}
    return ResultRef(
        cache_path=str(cache_path),
        run_id=str(d.get("run_id", "")),
        input_hash=str(d.get("input_hash", "")),
        odb_sha256=str(d.get("odb_sha256", "")),
        extractor_version=str(d.get("extractor_version", "")),
        extraction_spec=str(d.get("extraction_spec", "")),
        units=tuple(str(u) for u in (d.get("units") or ())),
        metrics={str(k): float(v) for k, v in (d.get("metrics") or {}).items()},
        extraction_count=int(counts.get("extractions", 0)),
        evidence_count=int(counts.get("evidence", 0)),
        energy_status=d.get("energy_status"),
        created_at=float(d.get("created_at", 0.0)),
        schema=str(d.get("schema", CACHE_SCHEMA_VERSION)),
    )


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
