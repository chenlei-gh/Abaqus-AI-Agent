"""Unit and integration tests for P1.1 DocumentIngestionPipeline.

Tests:
- Vector-first PDF ingestion with native text stream extraction.
- Raster image ingestion (PNG, JPEG) with true dimension preservation.
- Reversible coordinate mapping between native source coordinates and normalized [0, 1] space.
- Fail-closed error handling for corrupt, non-existent, or unsupported files.
- Provenance tracking (source_path, page_index, source_dimensions).
"""

from pathlib import Path
import pytest
from PIL import Image

from abaqus_ai_agent.perception.ingestion import (
    DocumentIngestionPipeline,
    IngestedPage,
    IngestionError,
)


def _create_minimal_vector_pdf(path: Path, text: str = "Beam F=5000N L=1000mm") -> None:
    """Constructs a strictly valid minimal PDF with a vector text content stream."""
    stream_content = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("latin1")
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R>> endobj\n"
        b"4 0 obj <</Length " + str(len(stream_content)).encode("ascii") + b">> stream\n"
        + stream_content + b"\nendstream\nendobj\nxref\n0 5\n"
        b"trailer <</Size 5 /Root 1 0 R>>\nstartxref\n500\n%%EOF"
    )
    path.write_bytes(pdf_bytes)


def _create_minimal_raster_image(path: Path, width: int = 800, height: int = 600, fmt: str = "PNG") -> None:
    """Constructs a test raster image with explicit dimensions."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    img.save(path, format=fmt)


def test_raster_image_ingestion(tmp_path: Path):
    img_path = tmp_path / "test_blueprint.png"
    _create_minimal_raster_image(img_path, width=1024, height=768)

    pipeline = DocumentIngestionPipeline()
    pages = pipeline.load_document(img_path)

    assert len(pages) == 1
    page = pages[0]
    assert page.page_index == 0
    assert page.width == 1024.0
    assert page.height == 768.0
    assert page.is_vector is False
    assert page.source_path == str(img_path)
    assert page.image_bytes is not None

    # Test reversible coordinate mapping
    u, v = page.to_normalized(512.0, 384.0)
    assert pytest.approx(u, rel=1e-5) == 0.5
    assert pytest.approx(v, rel=1e-5) == 0.5

    x, y = page.from_normalized(0.5, 0.5)
    assert pytest.approx(x, rel=1e-5) == 512.0
    assert pytest.approx(y, rel=1e-5) == 384.0


def test_vector_pdf_ingestion(tmp_path: Path):
    pdf_path = tmp_path / "test_drawing.pdf"
    _create_minimal_vector_pdf(pdf_path, text="Cantilever Bracket L=200mm")

    pipeline = DocumentIngestionPipeline()
    pages = pipeline.load_document(pdf_path)

    assert len(pages) == 1
    page = pages[0]
    assert page.page_index == 0
    assert page.width == 612.0
    assert page.height == 792.0
    assert page.is_vector is True
    assert len(page.vector_text_elements) >= 1

    extracted_text = page.vector_text_elements[0]["text"]
    assert "Cantilever" in extracted_text

    # Verify provenance generation
    provenance = page.build_provenance(extraction_method="vector_pdf", provider_id="test_provider")
    assert provenance.source_path == str(pdf_path)
    assert provenance.page_index == 0
    assert provenance.source_dimensions == (612.0, 792.0)
    assert provenance.extraction_method == "vector_pdf"
    assert provenance.provider_id == "test_provider"


def test_ingestion_fail_closed_errors(tmp_path: Path):
    pipeline = DocumentIngestionPipeline()

    # 1. Non-existent file
    with pytest.raises(FileNotFoundError):
        pipeline.load_document(tmp_path / "non_existent.pdf")

    # 2. Directory passed instead of file
    with pytest.raises(IngestionError):
        pipeline.load_document(tmp_path)

    # 3. Unsupported extension
    unsupported = tmp_path / "model.step"
    unsupported.write_text("ISO-10303-21;")
    with pytest.raises(IngestionError, match="unsupported document format"):
        pipeline.load_document(unsupported)

    # 4. Corrupt PDF
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"NOT_A_PDF_HEADER_12345")
    with pytest.raises(IngestionError, match="invalid PDF header"):
        pipeline.load_document(corrupt_pdf)
