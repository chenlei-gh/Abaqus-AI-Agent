"""Generator script for P1.1 Drawing Benchmark Assets (Tier 1, Tier 2, Tier 3).

Produces:
1. Tier 1: Vector PDF with native text operators and vector lines.
2. Tier 2: Scanned PDF simulated via high-res rasterization and simulated scan contrast.
3. Tier 3: Screenshot PNG representing CAD viewport export.
4. Ground truth JSON contracts for each tier.
"""

from __future__ import annotations

import io
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.contracts.drawing_benchmark import (
    DrawingBoundaryTruth,
    DrawingDimensionTruth,
    DrawingGroundTruth,
    DrawingLoadTruth,
    DrawingMaterialTruth,
    DrawingVerificationTarget,
)


def create_vector_pdf(target_path: Path) -> None:
    """Generates an ISO/GB-compliant vector PDF drawing for an L-Bracket."""
    # PDF Page 612 x 792 pt (Letter)
    # Origin is bottom-left
    # L-Bracket: Base arm 100mm, Vertical arm 100mm, thickness 10mm, width 20mm
    # Drawing drawn with scale factor in center

    stream_content = b"""
% Drawing Border
0.5 w
20 20 572 752 re S

% Title Block
20 20 572 60 re S
BT
/F1 14 Tf
1 0 0 1 35 55 Tm
(TITLE: L-BRACKET ENGINEERING BLUEPRINT) Tj
/F1 10 Tf
1 0 0 1 35 35 Tm
(PART: L-BRACKET-01 | SPEC: GB/T 700-Q235 | UNITS: mm, N, MPa) Tj
ET

% Drawing View: L-Shape Profile
1.5 w
150 250 m
350 250 l
350 290 l
190 290 l
190 550 l
150 550 l
h S

% Dimensions and Text
BT
/F1 10 Tf
% Material Note
1 0 0 1 40 730 Tm
(Material: Steel Q235, E = 210000 MPa, nu = 0.3) Tj

% Dimensions
1 0 0 1 230 230 Tm
(L = 100.0 mm) Tj
1 0 0 1 100 400 Tm
(H = 100.0 mm) Tj
1 0 0 1 200 305 Tm
(T = 10.0 mm) Tj
1 0 0 1 360 270 Tm
(W = 20.0 mm) Tj

% Boundary Condition Callout
1 0 0 1 200 190 Tm
(Encastre fixed support at Base Face) Tj

% Load Callout
1 0 0 1 120 580 Tm
(Downward concentrated force F = 1000 N at Tip Face) Tj
ET

% Arrows & Leader Lines
0.8 w
% Fixed support hatching at base
150 250 m 140 240 l S
170 250 m 160 240 l S
190 250 m 180 240 l S
210 250 m 200 240 l S
230 250 m 220 240 l S
250 250 m 240 240 l S

% Downward Load Arrow at top tip (170, 550)
170 610 m 170 555 l S
166 565 m 170 555 l 174 565 l S
"""
    length = len(stream_content)
    pdf_bytes = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {length} >>
stream{stream_content.decode('latin1')}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
{200 + length}
%%EOF
""".encode("latin1")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(pdf_bytes)


def create_rendered_image(width: int = 1600, height: int = 1200) -> Image.Image:
    """Renders a clean CAD blueprint image using PIL."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rectangle([40, 40, width - 40, height - 40], outline=(0, 0, 0), width=3)
    # Title box
    draw.rectangle([40, height - 140, width - 40, height - 40], outline=(0, 0, 0), width=2)
    draw.text((60, height - 120), "TITLE: L-BRACKET ENGINEERING BLUEPRINT", fill=(0, 0, 0))
    draw.text((60, height - 80), "PART: L-BRACKET-01 | SPEC: GB/T 700-Q235 | UNITS: mm, N, MPa", fill=(50, 50, 50))

    # Notes
    draw.text((60, 60), "Material: Steel Q235, E = 210000 MPa, nu = 0.3", fill=(0, 0, 0))

    # L-bracket polygon
    # Base: (400, 800) to (900, 800) to (900, 700) to (500, 700) to (500, 200) to (400, 200)
    poly = [
        (400, 800),
        (900, 800),
        (900, 700),
        (500, 700),
        (500, 250),
        (400, 250),
    ]
    draw.polygon(poly, outline=(0, 0, 0), fill=(245, 245, 250))

    # Hatching at fixed base (Y=800)
    for x in range(400, 900, 25):
        draw.line([(x, 800), (x - 20, 830)], fill=(100, 100, 100), width=2)

    # Annotations
    draw.text((600, 840), "Encastre fixed support at Base Face", fill=(0, 0, 180))
    draw.text((600, 870), "L = 100.0 mm", fill=(0, 0, 0))

    draw.text((280, 500), "H = 100.0 mm", fill=(0, 0, 0))
    draw.text((550, 660), "T = 10.0 mm", fill=(0, 0, 0))

    # Downward force arrow at top tip (450, 250)
    draw.line([(450, 150), (450, 245)], fill=(200, 0, 0), width=4)
    draw.polygon([(440, 220), (450, 245), (460, 220)], fill=(200, 0, 0))
    draw.text((320, 120), "Downward concentrated force F = 1000 N at Tip Face", fill=(200, 0, 0))

    return img


def create_scanned_pdf(target_path: Path) -> None:
    """Generates simulated scanned PDF by rendering image and applying slight contrast/noise."""
    img = create_rendered_image(1200, 900)
    # Convert to grayscale to simulate scan
    scanned = img.convert("L").convert("RGB")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    scanned.save(target_path, "PDF", resolution=150.0)


def create_screenshot_png(target_path: Path) -> None:
    """Generates PNG screenshot asset."""
    img = create_rendered_image(1600, 1200)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(target_path, "PNG")


def build_l_bracket_ground_truth(tier: str, relative_file_path: str) -> DrawingGroundTruth:
    """Constructs canonical Ground Truth for L-Bracket benchmarks."""
    mat = DrawingMaterialTruth(
        material_name="Q235",
        elastic_modulus=210000.0,
        poisson_ratio=0.3,
        yield_strength=235.0,
        density=7.85e-9,
    )

    dims = (
        DrawingDimensionTruth(
            dimension_id="dim_length",
            nominal_value=100.0,
            unit="mm",
            tolerance_upper=0.1,
            tolerance_lower=-0.1,
            text="L = 100.0 mm",
            feature_name="BaseArmLength",
        ),
        DrawingDimensionTruth(
            dimension_id="dim_height",
            nominal_value=100.0,
            unit="mm",
            tolerance_upper=0.1,
            tolerance_lower=-0.1,
            text="H = 100.0 mm",
            feature_name="VerticalArmHeight",
        ),
        DrawingDimensionTruth(
            dimension_id="dim_thickness",
            nominal_value=10.0,
            unit="mm",
            tolerance_upper=0.05,
            tolerance_lower=-0.05,
            text="T = 10.0 mm",
            feature_name="ArmThickness",
        ),
        DrawingDimensionTruth(
            dimension_id="dim_width",
            nominal_value=20.0,
            unit="mm",
            tolerance_upper=0.1,
            tolerance_lower=-0.1,
            text="W = 20.0 mm",
            feature_name="BracketWidth",
        ),
    )

    bcs = (
        DrawingBoundaryTruth(
            boundary_id="bc_base_fix",
            bc_type="FIXED_SUPPORT",
            target_region="BaseFace",
            location=(0.40, 0.75),
            text="Encastre fixed support at Base Face",
        ),
    )

    loads = (
        DrawingLoadTruth(
            load_id="load_tip_down",
            load_type="CONCENTRATED_FORCE",
            magnitude=1000.0,
            unit="N",
            direction_vector=(0.0, -1.0),
            target_region="TipFace",
            location=(0.28, 0.20),
            text="Downward concentrated force F = 1000 N at Tip Face",
        ),
    )

    verif = DrawingVerificationTarget(
        expected_reaction_y=1000.0,
        reaction_tolerance_ratio=0.001,  # 0.1% equilibrium balance
        max_mises_min_mpa=5.0,
        max_mises_max_mpa=150.0,
        max_deflection_mm=0.5,
    )

    return DrawingGroundTruth(
        drawing_id=f"L_BRACKET_{tier.upper()}",
        tier=tier,
        file_path=relative_file_path,
        title="L-Bracket Structural Blueprint",
        unit_system="SI_MM",
        material=mat,
        dimensions=dims,
        boundary_conditions=bcs,
        loads=loads,
        verification=verif,
        notes=("Benchmark case for P1.1 Multimodal Drawing Ingestion", "L-Bracket linear static analysis"),
    )


def main():
    assets_dir = ROOT / "test_assets" / "drawings"

    # Tier 1: Vector PDF
    t1_file = assets_dir / "tier1_vector_pdf" / "l_bracket_blueprint.pdf"
    t1_gt = assets_dir / "tier1_vector_pdf" / "l_bracket_ground_truth.json"
    print(f"Generating Tier 1 Vector PDF: {t1_file}")
    create_vector_pdf(t1_file)
    gt1 = build_l_bracket_ground_truth("tier1_vector_pdf", "tier1_vector_pdf/l_bracket_blueprint.pdf")
    gt1.save_json(t1_gt)

    # Tier 2: Scanned PDF
    t2_file = assets_dir / "tier2_scan_pdf" / "l_bracket_scanned.pdf"
    t2_gt = assets_dir / "tier2_scan_pdf" / "l_bracket_ground_truth.json"
    print(f"Generating Tier 2 Scanned PDF: {t2_file}")
    create_scanned_pdf(t2_file)
    gt2 = build_l_bracket_ground_truth("tier2_scan_pdf", "tier2_scan_pdf/l_bracket_scanned.pdf")
    gt2.save_json(t2_gt)

    # Tier 3: Screenshot PNG
    t3_file = assets_dir / "tier3_screenshot" / "l_bracket_screenshot.png"
    t3_gt = assets_dir / "tier3_screenshot" / "l_bracket_ground_truth.json"
    print(f"Generating Tier 3 Screenshot: {t3_file}")
    create_screenshot_png(t3_file)
    gt3 = build_l_bracket_ground_truth("tier3_screenshot", "tier3_screenshot/l_bracket_screenshot.png")
    gt3.save_json(t3_gt)

    print("All Phase 1 benchmark drawing assets generated successfully!")


if __name__ == "__main__":
    main()
