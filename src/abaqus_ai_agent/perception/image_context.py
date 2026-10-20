"""Layered image verification for model context (Governance Plan 阶段 2 第 3 项).

Rule under implementation:

    script machine verification -> metadata alignment -> controlled local crop

The point is that a high-resolution original never enters the model context. The
model may only see a bounded, provenance-carrying slice, and only after the bytes
have been machine-verified.

Design decisions worth stating explicitly:

- No new image-format rules are invented. PNG/GIF structural verification is
  delegated to ``execution.odb_rendering.verify_png_image_integrity`` /
  ``verify_gif_image_integrity``, which already validate magic bytes, chunk CRCs,
  IEND termination and full raster decoding. This module adds a bounded JPEG
  header check, because that verifier does not exist yet and JPEG is a supported
  engineering input.
- Metadata is read with Pillow on a header-only path (``Image.open`` does not
  decode pixels until ``load()``), so dimension checks stay cheap on large files.
- Cropping is fail-closed: an unsupported format, a zero-area region, or an
  unverified source raises instead of silently degrading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import io
from typing import Any, Dict, Optional, Tuple, Union

#: Default budget for a single slice handed to a model.
DEFAULT_MAX_SLICE_BYTES = 200_000
#: Above this pixel count the full image is never a legitimate context payload.
HIGH_RESOLUTION_PIXEL_THRESHOLD = 4_000_000


class ImageVerificationError(RuntimeError):
    """Raised when image bytes cannot be machine-verified."""


class ImageContextBlockedError(ImageVerificationError):
    """Raised when a caller attempts to push a full high-resolution image into context."""


@dataclass(frozen=True)
class ImageMetadata:
    """Header-level facts about an image, obtained without full decoding."""
    width: int
    height: int
    format: str
    mode: str
    size_bytes: int
    path: Optional[str] = None

    @property
    def pixel_count(self) -> int:
        return int(self.width) * int(self.height)

    @property
    def is_high_resolution(self) -> bool:
        return self.pixel_count >= HIGH_RESOLUTION_PIXEL_THRESHOLD

    @property
    def aspect_ratio(self) -> float:
        return (self.width / self.height) if self.height else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "pixel_count": self.pixel_count,
            "is_high_resolution": self.is_high_resolution,
            "path": self.path,
        }


@dataclass(frozen=True)
class ImageSlice:
    """A verified, bounded image slice suitable for model context."""
    path: Optional[str]
    format: str
    width: int
    height: int
    source_width: int
    source_height: int
    box: Tuple[int, int, int, int]
    data: bytes = field(repr=False, default=b"")
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    def to_llm_card(self) -> Dict[str, Any]:
        """Metadata-only card: pixel bytes never travel in the summary itself."""
        return {
            "slice": {
                "source": self.path,
                "format": self.format,
                "box": list(self.box),
                "width": self.width,
                "height": self.height,
                "source_width": self.source_width,
                "source_height": self.source_height,
                "bytes": self.size_bytes,
            },
            **self.metadata,
        }


# ---------------------------------------------------------------------------
# Layer 1: script machine verification
# ---------------------------------------------------------------------------

def verify_image_bytes(data: bytes) -> ImageMetadata:
    """Structurally verify image bytes and return header metadata.

    Fail-closed: any unverifiable input raises ``ImageVerificationError``.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ImageVerificationError(f"Expected image bytes, got {type(data)!r}")
    raw = bytes(data)
    if not raw:
        raise ImageVerificationError("Empty image payload")

    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        from ..execution.odb_rendering import verify_png_image_integrity

        try:
            width, height = verify_png_image_integrity(raw)
        except (ValueError, RuntimeError) as exc:
            raise ImageVerificationError(f"PNG verification failed: {exc}") from exc
        fmt = "PNG"
    elif raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
        from ..execution.odb_rendering import verify_gif_image_integrity

        try:
            width, height = verify_gif_image_integrity(raw)
        except (ValueError, RuntimeError) as exc:
            raise ImageVerificationError(f"GIF verification failed: {exc}") from exc
        fmt = "GIF"
    elif raw.startswith(b"\xff\xd8\xff"):
        width, height = _verify_jpeg_header(raw)
        fmt = "JPEG"
    else:
        raise ImageVerificationError(
            f"Unsupported or unrecognized image signature: {raw[:8]!r}"
        )

    mode = _read_mode(raw, fmt)
    return ImageMetadata(
        width=int(width),
        height=int(height),
        format=fmt,
        mode=mode,
        size_bytes=len(raw),
    )


def _verify_jpeg_header(data: bytes) -> Tuple[int, int]:
    """Walk JPEG marker segments to SOFn and read dimensions.

    Deliberately header-only: entropy-coded scan data is not parsed here, and this
    function does not claim pixel-level integrity. It only proves the container is
    a well-formed JPEG with declared positive dimensions.
    """
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise ImageVerificationError("Missing JPEG SOI marker")
    if not data.rstrip(b"\x00").endswith(b"\xff\xd9") and b"\xff\xd9" not in data[-64:]:
        raise ImageVerificationError("JPEG lacks EOI terminator; file is likely truncated")

    i = 2
    n = len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2 or i + 2 + seg_len > n:
            break
        # SOF0..SOF15 except DHT(C4), JPG(C8), DAC(CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                break
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            if width <= 0 or height <= 0:
                raise ImageVerificationError(
                    f"Invalid JPEG dimensions: {width}x{height}"
                )
            return width, height
        i += 2 + seg_len
    raise ImageVerificationError("JPEG has no valid SOF frame header")


def _read_mode(data: bytes, fmt: str) -> str:
    try:
        from PIL import Image as _Image

        with _Image.open(io.BytesIO(data)) as im:
            return im.mode
    except Exception:
        return "unknown"


def verify_image_file(path: Union[str, Path]) -> ImageMetadata:
    p = Path(path)
    if not p.is_file():
        raise ImageVerificationError(f"Image file does not exist: {p}")
    meta = verify_image_bytes(p.read_bytes())
    return ImageMetadata(
        width=meta.width,
        height=meta.height,
        format=meta.format,
        mode=meta.mode,
        size_bytes=meta.size_bytes,
        path=str(p),
    )


# ---------------------------------------------------------------------------
# Layer 2: metadata alignment
# ---------------------------------------------------------------------------

def align_metadata(
    metadata: ImageMetadata,
    *,
    expected_width: Optional[float] = None,
    expected_height: Optional[float] = None,
    tolerance_px: float = 0.5,
) -> Tuple[bool, Tuple[str, ...]]:
    """Compare declared dimensions against the verified header.

    Returns ``(aligned, problems)``. A caller with no expectation is trivially aligned.
    """
    problems = []
    if expected_width is not None and abs(float(expected_width) - metadata.width) > tolerance_px:
        problems.append(
            f"width mismatch: declared {expected_width}, verified {metadata.width}"
        )
    if expected_height is not None and abs(float(expected_height) - metadata.height) > tolerance_px:
        problems.append(
            f"height mismatch: declared {expected_height}, verified {metadata.height}"
        )
    return (not problems, tuple(problems))


def is_full_image_blocked(metadata: ImageMetadata, max_full_image_bytes: int = DEFAULT_MAX_SLICE_BYTES) -> bool:
    """Whether the full image must be refused as a context payload."""
    return metadata.is_high_resolution or metadata.size_bytes > max_full_image_bytes


# ---------------------------------------------------------------------------
# Layer 3: controlled local slice
# ---------------------------------------------------------------------------

def crop_region_normalized(
    metadata: ImageMetadata,
    center: Tuple[float, float],
    width: float,
    height: float,
) -> Tuple[int, int, int, int]:
    """Map a normalized region (origin top-left) to integer pixel bounds.

    The box is clamped to the image so a marginally out-of-range annotation yields
    a valid slice rather than an exception; a region that falls entirely outside
    still raises.
    """
    for name, val in (("center.x", center[0]), ("center.y", center[1])):
        if not 0.0 <= float(val) <= 1.0:
            raise ImageVerificationError(f"{name} must be in [0, 1], got {val}")
    if not 0.0 < width <= 1.0 or not 0.0 < height <= 1.0:
        raise ImageVerificationError(
            f"slice width/height must be in (0, 1], got {width}x{height}"
        )

    cx = float(center[0]) * metadata.width
    cy = float(center[1]) * metadata.height
    half_w = float(width) * metadata.width / 2.0
    half_h = float(height) * metadata.height / 2.0

    left = max(0, int(round(cx - half_w)))
    upper = max(0, int(round(cy - half_h)))
    right = min(metadata.width, int(round(cx + half_w)))
    lower = min(metadata.height, int(round(cy + half_h)))

    if right <= left or lower <= upper:
        raise ImageVerificationError(
            f"Slice region collapses to zero area: box=({left}, {upper}, {right}, {lower})"
        )
    return (left, upper, right, lower)


def extract_verified_slice(
    source: Union[str, Path, bytes],
    *,
    center: Tuple[float, float],
    width: float,
    height: float,
    max_slice_bytes: int = DEFAULT_MAX_SLICE_BYTES,
    expected_dimensions: Optional[Tuple[float, float]] = None,
) -> ImageSlice:
    """Run all three layers and return a bounded, verified slice.

    Raises ``ImageContextBlockedError`` if the produced slice cannot be bounded
    within the byte budget, and ``ImageVerificationError`` for any integrity or
    alignment failure.
    """
    source_path: Optional[str] = None
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.is_file():
            raise ImageVerificationError(f"Image file does not exist: {p}")
        raw = p.read_bytes()
        source_path = str(p)
    else:
        raw = bytes(source)

    # Layer 1
    meta = verify_image_bytes(raw)
    if source_path:
        meta = ImageMetadata(
            width=meta.width,
            height=meta.height,
            format=meta.format,
            mode=meta.mode,
            size_bytes=meta.size_bytes,
            path=source_path,
        )

    # Layer 2
    if expected_dimensions is not None:
        aligned, problems = align_metadata(
            meta,
            expected_width=expected_dimensions[0],
            expected_height=expected_dimensions[1],
        )
        if not aligned:
            raise ImageVerificationError(
                "Image metadata does not align with declared dimensions: " + "; ".join(problems)
            )

    # Layer 3
    box = crop_region_normalized(meta, center, width, height)
    slice_bytes = _render_slice(raw, box, meta.format)
    if len(slice_bytes) > max_slice_bytes:
        raise ImageContextBlockedError(
            f"Slice is {len(slice_bytes)} bytes, exceeding the {max_slice_bytes}-byte "
            "context budget. Reduce the requested region instead of shrinking quality silently."
        )

    return ImageSlice(
        path=source_path,
        format=meta.format,
        width=box[2] - box[0],
        height=box[3] - box[1],
        source_width=meta.width,
        source_height=meta.height,
        box=box,
        data=slice_bytes,
        metadata={
            "source_verified": True,
            "source_pixel_count": meta.pixel_count,
            "full_image_sent": False,
        },
    )


def _render_slice(raw: bytes, box: Tuple[int, int, int, int], fmt: str) -> bytes:
    try:
        from PIL import Image as _Image
    except Exception as exc:  # pragma: no cover - Pillow is a hard dependency
        raise ImageVerificationError(f"Pillow is required for slicing: {exc}") from exc

    try:
        with _Image.open(io.BytesIO(raw)) as im:
            target_fmt = "PNG" if fmt not in ("PNG", "JPEG", "GIF") else fmt
            cropped = im.crop(box)
            buffer = io.BytesIO()
            save_kwargs: Dict[str, Any] = {}
            if target_fmt == "JPEG" and cropped.mode not in ("RGB", "L"):
                cropped = cropped.convert("RGB")
            cropped.save(buffer, format=target_fmt, **save_kwargs)
            return buffer.getvalue()
    except ImageVerificationError:
        raise
    except Exception as exc:
        raise ImageVerificationError(f"Failed to render verified slice: {exc}") from exc


def enforce_image_context_policy(
    metadata: ImageMetadata,
    requested_full_image: bool,
    max_full_image_bytes: int = DEFAULT_MAX_SLICE_BYTES,
) -> None:
    """Refuse a full high-resolution image before it can enter model context."""
    if not requested_full_image:
        return
    if is_full_image_blocked(metadata, max_full_image_bytes=max_full_image_bytes):
        raise ImageContextBlockedError(
            f"Full image context blocked: {metadata.width}x{metadata.height} "
            f"({metadata.pixel_count} px, {metadata.size_bytes} bytes). "
            "Use a verified local slice instead."
        )
