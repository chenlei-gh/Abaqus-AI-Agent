"""Contract B.2 tests: ODB extraction cache, five-condition binding and ``result_ref``.

Contract under test (docs/Abaqus-AI-Agent-Governance-Plan.md 契约 B.2 + TC-TOK-03):
1. Payload is persisted to ``.cache/results/{run_id}_{odb_sha256[:8]}.json``.
2. Reuse requires input_hash, odb_sha256, extraction_spec, extractor_version and units
   to match exactly. Any single mismatch forces a fresh extraction.
3. The model-facing summary is strictly below 1500 characters.
4. The full float array and causal evidence can be restored from disk in < 10 ms.

Layer of evidence: unit/integration against a mocked extraction runner. No real
Abaqus solver or real ODB is involved here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from abaqus_ai_agent.contracts.results import ResultRequirement
from abaqus_ai_agent.execution.odb_extractor import (
    EXTRACTOR_VERSION,
    extract_odb_results,
)
from abaqus_ai_agent.execution.result_cache import (
    MAX_RESULT_REF_CHARS,
    CacheBinding,
    ResultCacheError,
    binding_of_payload,
    cache_entry_path,
    check_cache_binding,
    extraction_spec_digest,
    normalized_units,
    read_result_cache_payload,
    report_from_payload,
    result_ref_from_payload,
)


def _binary_odb(path: Path, size: int = 4096) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * (size - 8))
    return path


def _field_req(value_key: str = "max_mises", unit: str = "MPa") -> ResultRequirement:
    return ResultRequirement(
        name=f"{value_key}_gate",
        value_key=value_key,
        field="S",
        invariant="MISES",
        unit=unit,
        aggregation="max",
    )


def _runner(value: float = 185.5):
    """Extraction runner returning one field value plus a large float payload."""

    def run(code: str):
        if "names=list(odb.steps.keys())" in code:
            return "Step-1"
        # A wide float array keeps the fixture realistic without touching a solver.
        return {
            "meta": {"field": "S", "count": 1},
            "values": [
                {
                    "element_label": 101,
                    "instance": "PART-1-1",
                    "mises": value,
                    "data": tuple(round(value + i * 0.001, 6) for i in range(200)),
                }
            ],
        }

    return run


def _extract(odb: Path, cache_root: Path, value: float = 185.5, **kwargs):
    return extract_odb_results(
        odb_path=odb,
        requirements_or_criteria=kwargs.pop("requirements", [_field_req()]),
        run_id=kwargs.pop("run_id", "run-cache-001"),
        input_hash=kwargs.pop("input_hash", "inp-hash-abc"),
        workdir=odb.parent,
        custom_runner=_runner(value),
        cache_root=cache_root,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Persistence contract
# ---------------------------------------------------------------------------

def test_cache_path_matches_contract_naming(tmp_path: Path):
    report = _extract(_binary_odb(tmp_path / "job.odb"), tmp_path / "cache")
    expected = tmp_path / "cache" / f"run-cache-001_{report.odb_sha256[:8]}.json"

    assert report.result_ref is not None
    assert Path(report.result_ref.cache_path) == expected
    assert expected.is_file()
    assert report.cache_status == "miss"
    assert report.cache_hit is False

    payload = read_result_cache_payload(expected)
    assert payload["schema"] == "odb_result_cache_v1"
    assert payload["report"]["metrics"]["max_mises"] == 185.5


def test_original_odb_is_never_modified(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    before = (odb.stat().st_size, odb.read_bytes())

    _extract(odb, tmp_path / "cache")

    after = (odb.stat().st_size, odb.read_bytes())
    assert before == after


# ---------------------------------------------------------------------------
# Five-condition binding
# ---------------------------------------------------------------------------

def test_identical_binding_hits_cache_without_re_extraction(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"

    first = _extract(odb, cache, value=185.5)
    assert first.cache_hit is False

    calls = {"n": 0}

    def counting_runner(code: str):
        calls["n"] += 1
        return _runner(999.0)(code)

    second = extract_odb_results(
        odb_path=odb,
        requirements_or_criteria=[_field_req()],
        run_id="run-cache-001",
        input_hash="inp-hash-abc",
        workdir=odb.parent,
        custom_runner=counting_runner,
        cache_root=cache,
    )

    assert calls["n"] == 0, "cache hit must not invoke the extractor"
    assert second.cache_hit is True
    assert second.cache_status == "hit"
    assert second.metrics["max_mises"] == 185.5


@pytest.mark.parametrize(
    "changed, expected_key",
    [
        ({"input_hash": "different-inp-hash"}, "max_mises"),
        ({"run_id": "run-cache-002"}, "max_mises"),
        ({"requirements": [_field_req(unit="Pa")]}, "max_mises"),
        ({"requirements": [_field_req(value_key="max_disp")]}, "max_disp"),
    ],
    ids=["input_hash", "odb_path_slot", "units", "extraction_spec"],
)
def test_any_binding_mismatch_forces_fresh_extraction(tmp_path: Path, changed, expected_key):
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"

    _extract(odb, cache, value=185.5)
    refreshed = _extract(odb, cache, value=222.0, **changed)

    assert refreshed.cache_hit is False
    assert refreshed.cache_status == "miss"
    assert refreshed.metrics[expected_key] == 222.0
    assert refreshed.cache_detail.get("cache_mismatch")


def test_odb_content_change_forces_fresh_extraction(tmp_path: Path):
    cache = tmp_path / "cache"
    odb = _binary_odb(tmp_path / "job.odb", size=4096)
    _extract(odb, cache, value=185.5)

    # Rewrite with different bytes; the SHA changes, so the cache key itself changes.
    odb.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 2048 + b"\x01" * 2040)
    refreshed = _extract(odb, cache, value=310.0)

    assert refreshed.cache_hit is False
    assert refreshed.metrics["max_mises"] == 310.0


def test_extractor_version_mismatch_rejects_cache(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"
    report = _extract(odb, cache)

    path = Path(report.result_ref.cache_path)
    payload = read_result_cache_payload(path)
    payload["binding"]["extractor_version"] = "odb_extractor_v0"

    expected = CacheBinding(
        input_hash="inp-hash-abc",
        odb_sha256=report.odb_sha256,
        extraction_spec=extraction_spec_digest([_field_req()]),
        extractor_version=EXTRACTOR_VERSION,
        units=tuple(normalized_units([_field_req()])),
    )
    hit, mismatched = check_cache_binding(payload, expected)

    assert hit is False
    assert mismatched == ("extractor_version",)


def test_binding_digest_is_order_independent(tmp_path: Path):
    a = [_field_req("max_mises"), _field_req("max_disp")]
    b = list(reversed(a))
    assert extraction_spec_digest(a) == extraction_spec_digest(b)

    units_a = normalized_units(a)
    units_b = normalized_units(b)
    assert units_a == units_b
    assert units_a == ["MPa", "MPa"]


# ---------------------------------------------------------------------------
# TC-TOK-03: bounded summary and sub-10ms restoration
# ---------------------------------------------------------------------------

def test_tc_tok_03_summary_is_under_1500_chars(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    many = [_field_req(f"metric_{i:03d}") for i in range(60)]

    report = _extract(odb, tmp_path / "cache", requirements=many)
    summary = report.to_llm_summary()

    assert len(summary) < MAX_RESULT_REF_CHARS == 1500
    card = json.loads(summary)
    assert card["result_ref"] == report.result_ref.ref_id
    assert card["cache_path"] == report.result_ref.cache_path
    # Raw arrays must never appear in the model-facing summary.
    assert "\"values\"" not in summary
    assert "\"data\"" not in summary


def test_tc_tok_03_restores_full_payload_from_disk_under_10ms(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    report = _extract(odb, tmp_path / "cache")
    path = Path(report.result_ref.cache_path)

    start = time.perf_counter()
    payload = read_result_cache_payload(path)
    restored = report_from_payload(payload)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Full float array and causal evidence must survive the round trip.
    restored_ext = restored.get_extraction("max_mises")
    assert restored_ext is not None
    assert restored_ext.value == 185.5
    assert restored_ext.locator["odb_sha256"] == report.odb_sha256
    assert restored_ext.locator["run_id"] == "run-cache-001"
    assert restored.evidence
    assert restored.evidence[0].metadata["odb_sha256"] == report.odb_sha256

    assert elapsed_ms < 10.0, f"restoration took {elapsed_ms:.3f} ms (budget 10 ms)"


def test_tc_tok_03_summary_and_restoration_stay_consistent(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    report = _extract(odb, tmp_path / "cache")
    card = json.loads(report.to_llm_summary())

    restored = report_from_payload(read_result_cache_payload(card["cache_path"]))
    assert restored.metrics == report.metrics
    assert restored.odb_sha256 == card["odb_sha256"]


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------

def test_corrupt_cache_entry_forces_re_extraction(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"
    first = _extract(odb, cache, value=185.5)

    Path(first.result_ref.cache_path).write_text("{not json", encoding="utf-8")
    refreshed = _extract(odb, cache, value=201.0)

    assert refreshed.cache_hit is False
    assert refreshed.metrics["max_mises"] == 201.0
    assert "unreadable_cache" in refreshed.cache_detail.get("cache_mismatch", [])


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p.pop("report"), id="report_block_missing"),
        pytest.param(lambda p: p["report"].pop("extractions"), id="extractions_missing"),
        pytest.param(
            lambda p: p["report"].__setitem__("extractions", "not-a-list"),
            id="extractions_wrong_type",
        ),
        pytest.param(
            lambda p: p["report"]["extractions"][0].pop("requirement"),
            id="requirement_missing",
        ),
        pytest.param(
            lambda p: p["report"]["extractions"][0].__setitem__("value", "NaN-ish"),
            id="value_not_numeric",
        ),
        pytest.param(
            lambda p: p["report"].__setitem__("metrics", [1, 2, 3]),
            id="metrics_wrong_type",
        ),
    ],
)
def test_structurally_invalid_but_parseable_cache_is_not_reused(tmp_path: Path, mutate):
    """Valid JSON with a broken report body must fall back, not abort extraction."""
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"
    first = _extract(odb, cache, value=185.5)

    path = Path(first.result_ref.cache_path)
    payload = read_result_cache_payload(path)
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    refreshed = _extract(odb, cache, value=201.0)

    assert refreshed.cache_hit is False
    assert refreshed.cache_status == "miss"
    assert refreshed.metrics["max_mises"] == 201.0
    assert "unusable_cache" in refreshed.cache_detail.get("cache_mismatch", [])
    # The damaged entry is replaced by a well-formed one.
    assert report_from_payload(read_result_cache_payload(path)).metrics["max_mises"] == 201.0


def test_report_from_payload_normalizes_structural_errors(tmp_path: Path):
    """Every structural defect surfaces as one exception type, never KeyError/TypeError."""
    odb = _binary_odb(tmp_path / "job.odb")
    report = _extract(odb, tmp_path / "cache")
    payload = read_result_cache_payload(report.result_ref.cache_path)

    payload["report"]["extractions"][0]["value"] = None
    with pytest.raises(ResultCacheError, match="malformed report body"):
        report_from_payload(payload)


def test_result_ref_from_payload_normalizes_structural_errors(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    report = _extract(odb, tmp_path / "cache")
    payload = read_result_cache_payload(report.result_ref.cache_path)

    payload["result_ref"]["counts"] = ["not", "a", "mapping"]
    with pytest.raises(ResultCacheError, match="non-object counts field"):
        result_ref_from_payload(payload, report.result_ref.cache_path)


def test_summary_is_strictly_below_the_bound(tmp_path: Path):
    """TC-TOK-03 says < 1500, so a summary of exactly 1500 characters is a violation."""
    odb = _binary_odb(tmp_path / "job.odb")
    report = _extract(
        odb,
        tmp_path / "cache",
        requirements=[_field_req(f"m{i:03d}") for i in range(60)],
    )
    ref = report.result_ref

    assert len(ref.to_llm_json()) < MAX_RESULT_REF_CHARS
    # The trim loop must honour the strict bound, not stop one character late.
    assert len(ref.to_llm_json(max_chars=MAX_RESULT_REF_CHARS + 1)) <= MAX_RESULT_REF_CHARS

    # A bound the payload cannot satisfy must raise rather than return an over-long card.
    with pytest.raises(ResultCacheError, match="cannot fit below"):
        ref.to_llm_json(max_chars=100)

    assert len(report.to_llm_summary()) < MAX_RESULT_REF_CHARS


def test_unknown_cache_schema_is_not_reused(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"
    first = _extract(odb, cache)
    path = Path(first.result_ref.cache_path)

    payload = read_result_cache_payload(path)
    payload["schema"] = "odb_result_cache_v0"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResultCacheError, match="Unsupported result cache schema"):
        binding_of_payload(payload)


def test_cache_disabled_never_writes(tmp_path: Path):
    odb = _binary_odb(tmp_path / "job.odb")
    cache = tmp_path / "cache"

    report = _extract(odb, cache, enable_result_cache=False)

    assert report.cache_status == "disabled"
    assert report.result_ref is None
    assert not cache_entry_path("run-cache-001", report.odb_sha256, cache).exists()
    # Even without a cache, the summary stays bounded.
    assert len(report.to_llm_summary()) < 1500
