"""Tests for P0-1: ArtifactPointer and ArtifactSummary contracts."""

import hashlib
import json
import pytest
from pathlib import Path

from abaqus_ai_agent.contracts.artifact import (
    ArtifactContractError,
    ArtifactPointer,
    ArtifactSummary,
)


def test_artifact_pointer_valid(tmp_path: Path):
    test_file = tmp_path / "test_chart.svg"
    test_content = b"<svg>test</svg>"
    test_file.write_bytes(test_content)
    expected_sha = hashlib.sha256(test_content).hexdigest()

    pointer = ArtifactPointer.from_file(
        filepath=test_file,
        artifact_id="ART-TEST-001",
        artifact_type="chart",
        media_type="image/svg+xml",
        created_by="test_suite",
        metadata={"case": "test"},
    )

    assert pointer.artifact_id == "ART-TEST-001"
    assert pointer.type == "chart"
    assert pointer.media_type == "image/svg+xml"
    assert pointer.size_bytes == len(test_content)
    assert pointer.checksum_sha256 == expected_sha
    assert pointer.created_by == "test_suite"
    assert pointer.storage_scope == "run"
    assert pointer.access_policy == "llm_pointer_only"
    assert pointer.metadata == {"case": "test"}

    # Serialization roundtrip
    d = pointer.to_dict()
    restored = ArtifactPointer.from_dict(d)
    assert restored == pointer


def test_artifact_pointer_invalid_fields():
    with pytest.raises(ArtifactContractError, match="artifact_id"):
        ArtifactPointer(
            artifact_id="",
            type="chart",
            media_type="image/png",
            location="path/to/file",
            size_bytes=100,
        )

    with pytest.raises(ArtifactContractError, match="size_bytes"):
        ArtifactPointer(
            artifact_id="ART-1",
            type="chart",
            media_type="image/png",
            location="path/to/file",
            size_bytes=-5,
        )

    with pytest.raises(ArtifactContractError, match="checksum_sha256"):
        ArtifactPointer(
            artifact_id="ART-1",
            type="chart",
            media_type="image/png",
            location="path/to/file",
            size_bytes=10,
            checksum_sha256="invalid_hex",
        )


def test_artifact_summary_to_llm_card():
    summary = ArtifactSummary(
        artifact_id="ART-001",
        type="stress_contour",
        headline="Top 5 von Mises stress concentrations located at inner fillet radius.",
        key_metrics={"max_mises_mpa": 315.4, "unit": "MPa", "safety_factor": 1.45},
        status="PASS",
    )

    card = summary.to_llm_card()
    assert card["artifact_id"] == "ART-001"
    assert card["type"] == "stress_contour"
    assert "headline" in card
    assert card["metrics"]["max_mises_mpa"] == 315.4
    assert card["status"] == "PASS"

    # Verify compactness: serialized JSON should be very small (< 200 chars, ~40 tokens)
    card_json = json.dumps(card)
    assert len(card_json) < 250

    # Serialization roundtrip
    restored = ArtifactSummary.from_dict(summary.to_dict())
    assert restored == summary
