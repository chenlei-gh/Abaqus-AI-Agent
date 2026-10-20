"""Layered image verification tests (Governance Plan 阶段 2 第 3 项).

Covers the three mandated layers:
1. Script machine verification (structure/CRC/magic, fail-closed).
2. Metadata alignment (declared vs verified dimensions).
3. Controlled local slice, plus refusal to push a high-resolution original.

Layer of evidence: unit tests against synthetic images. No real CAD viewport capture
and no real Abaqus rendering path is exercised here.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from abaqus_ai_agent.perception.image_context import (
    DEFAULT_MAX_SLICE_BYTES,
    HIGH_RESOLUTION_PIXEL_THRESHOLD,
    ImageContextBlockedError,
    ImageMetadata,
    ImageVerificationError,
    align_metadata,
    crop_region_normalized,
    enforce_image_context_policy,
    extract_verified_slice,
    is_full_image_blocked,
    verify_image_bytes,
    verify_image_file,
)


def _png_bytes(width: int = 800, height: int = 600, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(width: int = 640, height: int = 480) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Layer 1: machine verification
# ---------------------------------------------------------------------------

def test_verify_png_reports_true_dimensions():
    meta = verify_image_bytes(_png_bytes(1024, 768))
    assert (meta.width, meta.height) == (1024, 768)
    assert meta.format == "PNG"
    assert meta.size_bytes > 0


def test_verify_jpeg_reads_sof_dimensions():
    meta = verify_image_bytes(_jpeg_bytes(640, 480))
    assert (meta.width, meta.height) == (640, 480)
    assert meta.format == "JPEG"


def test_verify_rejects_empty_payload():
    with pytest.raises(ImageVerificationError, match="Empty image payload"):
        verify_image_bytes(b"")


def test_verify_rejects_unknown_signature():
    with pytest.raises(ImageVerificationError, match="Unsupported or unrecognized"):
        verify_image_bytes(b"NOT_AN_IMAGE_AT_ALL" * 20)


def test_verify_rejects_truncated_png():
    data = _png_bytes(300, 200)
    with pytest.raises(ImageVerificationError):
        verify_image_bytes(data[: len(data) // 2])


def test_verify_rejects_truncated_jpeg():
    data = _jpeg_bytes()
    with pytest.raises(ImageVerificationError):
        verify_image_bytes(data[: len(data) // 3])


def test_verify_image_file_requires_existing_path(tmp_path: Path):
    with pytest.raises(ImageVerificationError, match="does not exist"):
        verify_image_file(tmp_path / "missing.png")


def test_verify_image_file_returns_path(tmp_path: Path):
    target = tmp_path / "view.png"
    target.write_bytes(_png_bytes())
    meta = verify_image_file(target)
    assert meta.path == str(target)


# ---------------------------------------------------------------------------
# Layer 2: metadata alignment
# ---------------------------------------------------------------------------

def test_align_metadata_accepts_matching_dimensions():
    meta = verify_image_bytes(_png_bytes(800, 600))
    aligned, problems = align_metadata(meta, expected_width=800, expected_height=600)
    assert aligned is True
    assert problems == ()


def test_align_metadata_flags_mismatch():
    meta = verify_image_bytes(_png_bytes(800, 600))
    aligned, problems = align_metadata(meta, expected_width=1024, expected_height=600)
    assert aligned is False
    assert "width mismatch" in problems[0]


def test_align_metadata_without_expectation_is_aligned():
    meta = verify_image_bytes(_png_bytes())
    aligned, problems = align_metadata(meta)
    assert aligned is True and problems == ()


# ---------------------------------------------------------------------------
# Layer 3: controlled slice and full-image blocking
# ---------------------------------------------------------------------------

def test_crop_region_normalized_maps_to_pixels():
    meta = ImageMetadata(width=1000, height=800, format="PNG", mode="RGB", size_bytes=1)
    box = crop_region_normalized(meta, center=(0.5, 0.5), width=0.2, height=0.25)
    left, upper, right, lower = box
    assert (left, right) == (400, 600)
    assert (upper, lower) == (300, 500)


def test_crop_region_clamps_within_bounds():
    meta = ImageMetadata(width=100, height=100, format="PNG", mode="RGB", size_bytes=1)
    box = crop_region_normalized(meta, center=(0.98, 0.02), width=0.5, height=0.5)
    assert box[0] >= 0 and box[1] >= 0
    assert box[2] <= 100 and box[3] <= 100


def test_crop_region_rejects_zero_area_request():
    meta = ImageMetadata(width=10, height=10, format="PNG", mode="RGB", size_bytes=1)
    with pytest.raises(ImageVerificationError, match="must be in"):
        crop_region_normalized(meta, center=(1.5, 0.5), width=0.1, height=0.1)


def test_full_image_is_blocked_above_pixel_threshold():
    meta = ImageMetadata(
        width=4000,
        height=4000,
        format="PNG",
        mode="RGB",
        size_bytes=500,
    )
    assert meta.pixel_count >= HIGH_RESOLUTION_PIXEL_THRESHOLD
    assert is_full_image_blocked(meta) is True
    with pytest.raises(ImageContextBlockedError, match="Full image context blocked"):
        enforce_image_context_policy(meta, requested_full_image=True)


def test_small_image_full_context_allowed_when_budget_permits():
    meta = verify_image_bytes(_png_bytes(200, 150))
    assert is_full_image_blocked(meta) is False
    enforce_image_context_policy(meta, requested_full_image=True)  # must not raise


def test_extract_slice_returns_bounded_verified_payload():
    data = _png_bytes(1600, 1200)
    slice_ = extract_verified_slice(data, center=(0.5, 0.5), width=0.15, height=0.15)

    assert slice_.metadata["source_verified"] is True
    assert slice_.metadata["full_image_sent"] is False
    assert (slice_.source_width, slice_.source_height) == (1600, 1200)
    assert slice_.width < slice_.source_width
    assert slice_.size_bytes <= DEFAULT_MAX_SLICE_BYTES

    # The slice must itself be a structurally valid image.
    verify_image_bytes(slice_.data)


def test_extract_slice_rejects_metadata_mismatch():
    data = _png_bytes(800, 600)
    with pytest.raises(ImageVerificationError, match="does not align"):
        extract_verified_slice(
            data,
            center=(0.5, 0.5),
            width=0.2,
            height=0.2,
            expected_dimensions=(900, 600),
        )


def test_extract_slice_fails_closed_when_budget_too_small():
    data = _png_bytes(1200, 1200)
    with pytest.raises(ImageContextBlockedError, match="context budget"):
        extract_verified_slice(
            data,
            center=(0.5, 0.5),
            width=0.9,
            height=0.9,
            max_slice_bytes=32,
        )


def test_extract_slice_from_file_records_source_path(tmp_path: Path):
    target = tmp_path / "viewport.png"
    target.write_bytes(_png_bytes(900, 700))
    slice_ = extract_verified_slice(target, center=(0.5, 0.5), width=0.25, height=0.25)

    assert slice_.path == str(target)
    card = slice_.to_llm_card()
    assert card["slice"]["source"] == str(target)
    # The card is metadata only; it carries no pixel payload key.
    assert "data" not in card["slice"]
