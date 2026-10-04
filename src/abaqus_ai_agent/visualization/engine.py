"""P1.3 Visualization & Graphical Engineering Deliverable Engine.

Pure Python vector SVG generation for:
1. Time-history and parametric XY response curves (energy, force, displacement).
2. Spatial hotspot Top-K ranking and continuum stress distribution summaries.
3. Automated figure artifact generation, SHA-256 calculation, and ReportFigure packaging.

Requires zero external heavy dependencies (no mandatory matplotlib or reportlab),
ensuring robust, deterministic offline execution across all CI and production platforms.
"""

from __future__ import annotations

import hashlib
import html
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.report import ReportFigure
from ..contracts.result_intelligence import SpatialHotspot, XYCurveData, XYPoint


def render_xy_curve_svg(
    curve: XYCurveData,
    width: int = 720,
    height: int = 420,
    stroke_color: str = "#2563eb",
    fill_color: str = "rgba(37, 99, 235, 0.08)",
) -> str:
    """Render a publication-quality SVG chart for an engineering XY response curve."""
    pts = curve.points
    padding_left = 80
    padding_right = 40
    padding_top = 50
    padding_bottom = 60

    plot_w = width - padding_left - padding_right
    plot_h = height - padding_top - padding_bottom

    if not pts:
        return _render_empty_svg(
            width, height, f"No curve data available for {curve.curve_name}"
        )

    xs = [p.x for p in pts]
    ys = [p.y for p in pts]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Add 5% headroom to Y range for visual clarity
    y_span = max_y - min_y
    if abs(y_span) < 1e-12:
        y_span = abs(min_y) if abs(min_y) > 1e-6 else 1.0
    padded_min_y = min_y - 0.05 * y_span
    padded_max_y = max_y + 0.05 * y_span

    x_span = max_x - min_x
    if abs(x_span) < 1e-12:
        x_span = 1.0

    def to_screen(x: float, y: float) -> Tuple[float, float]:
        sx = padding_left + ((x - min_x) / x_span) * plot_w
        sy = padding_top + (1.0 - (y - padded_min_y) / (padded_max_y - padded_min_y)) * plot_h
        return (sx, sy)

    svg_parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" style="background-color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">',
        "  <defs>",
        f'    <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">',
        f'      <stop offset="0%" stop-color="{stroke_color}" stop-opacity="0.2"/>',
        f'      <stop offset="100%" stop-color="{stroke_color}" stop-opacity="0.0"/>',
        "    </linearGradient>",
        "  </defs>",
    ]

    # Title
    title_text = html.escape(curve.curve_name)
    svg_parts.append(
        f'  <text x="{width // 2}" y="28" text-anchor="middle" font-size="16" font-weight="600" fill="#1e293b">{title_text}</text>'
    )

    # Grid lines and Y ticks (5 intervals)
    y_ticks = 5
    for i in range(y_ticks + 1):
        ratio = i / float(y_ticks)
        val = padded_min_y + ratio * (padded_max_y - padded_min_y)
        sy = padding_top + (1.0 - ratio) * plot_h
        svg_parts.append(
            f'  <line x1="{padding_left}" y1="{sy:.1f}" x2="{width - padding_right}" y2="{sy:.1f}" stroke="#e2e8f0" stroke-width="1"/>'
        )
        val_str = f"{val:.4g}" if abs(val) < 10000 else f"{val:.2e}"
        svg_parts.append(
            f'  <text x="{padding_left - 10}" y="{sy + 4:.1f}" text-anchor="end" font-size="11" fill="#64748b">{val_str}</text>'
        )

    # X ticks (5 intervals)
    x_ticks = 5
    for i in range(x_ticks + 1):
        ratio = i / float(x_ticks)
        val = min_x + ratio * x_span
        sx = padding_left + ratio * plot_w
        svg_parts.append(
            f'  <line x1="{sx:.1f}" y1="{padding_top}" x2="{sx:.1f}" y2="{padding_top + plot_h}" stroke="#e2e8f0" stroke-width="1"/>'
        )
        val_str = f"{val:.4g}"
        svg_parts.append(
            f'  <text x="{sx:.1f}" y="{padding_top + plot_h + 20}" text-anchor="middle" font-size="11" fill="#64748b">{val_str}</text>'
        )

    # Plot border
    svg_parts.append(
        f'  <rect x="{padding_left}" y="{padding_top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#94a3b8" stroke-width="1.2"/>'
    )

    # Curve points & path
    screen_pts = [to_screen(p.x, p.y) for p in pts]
    path_d = f"M {screen_pts[0][0]:.2f} {screen_pts[0][1]:.2f}"
    for sp in screen_pts[1:]:
        path_d += f" L {sp[0]:.2f} {sp[1]:.2f}"

    # Shaded area under curve (clamped to bottom of plot)
    bottom_y = padding_top + plot_h
    area_d = (
        f"{path_d} L {screen_pts[-1][0]:.2f} {bottom_y:.2f} "
        f"L {screen_pts[0][0]:.2f} {bottom_y:.2f} Z"
    )
    svg_parts.append(f'  <path d="{area_d}" fill="url(#areaGrad)"/>')
    svg_parts.append(
        f'  <path d="{path_d}" fill="none" stroke="{stroke_color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # Peak Point Annotation
    peak_idx = 0
    max_abs_y = -1.0
    for idx, p in enumerate(pts):
        if abs(p.y) > max_abs_y:
            max_abs_y = abs(p.y)
            peak_idx = idx

    peak_sp = screen_pts[peak_idx]
    peak_pt = pts[peak_idx]
    svg_parts.append(
        f'  <circle cx="{peak_sp[0]:.2f}" cy="{peak_sp[1]:.2f}" r="4.5" fill="#ef4444" stroke="#ffffff" stroke-width="1.5"/>'
    )
    y_unit_str = f" {curve.y_unit}" if curve.y_unit else ""
    peak_label = f"Peak: {peak_pt.y:.4g}{y_unit_str}"
    svg_parts.append(
        f'  <text x="{peak_sp[0] + 8:.2f}" y="{peak_sp[1] - 8:.2f}" font-size="11" font-weight="600" fill="#b91c1c">{html.escape(peak_label)}</text>'
    )

    # Axis Labels
    x_axis_label = f"{curve.x_label}" + (f" [{curve.x_unit}]" if curve.x_unit else "")
    y_axis_label = f"{curve.y_label}" + (f" [{curve.y_unit}]" if curve.y_unit else "")

    svg_parts.append(
        f'  <text x="{padding_left + plot_w // 2}" y="{height - 15}" text-anchor="middle" font-size="12" font-weight="500" fill="#334155">{html.escape(x_axis_label)}</text>'
    )
    svg_parts.append(
        f'  <text x="24" y="{padding_top + plot_h // 2}" text-anchor="middle" font-size="12" font-weight="500" fill="#334155" transform="rotate(-90 24 {padding_top + plot_h // 2})">{html.escape(y_axis_label)}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def render_hotspots_svg(
    hotspots: Sequence[SpatialHotspot],
    width: int = 720,
    height: int = 400,
) -> str:
    """Render a publication-quality SVG visual summary for Top-K localized hotspots."""
    if not hotspots:
        return _render_empty_svg(width, height, "No spatial hotspots identified")

    padding_top = 50
    padding_bottom = 30
    padding_left = 60
    padding_right = 60

    max_val = max(h.value for h in hotspots)
    if abs(max_val) < 1e-12:
        max_val = 1.0

    svg_parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" style="background-color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">',
        f'  <text x="{width // 2}" y="28" text-anchor="middle" font-size="16" font-weight="600" fill="#1e293b">Top-{len(hotspots)} Localized Stress / Field Concentrations</text>',
    ]

    card_h = (height - padding_top - padding_bottom - (len(hotspots) - 1) * 12) / len(hotspots)
    card_h = max(card_h, 48.0)

    for idx, h in enumerate(hotspots):
        card_y = padding_top + idx * (card_h + 12)
        ratio = max(0.0, min(1.0, h.value / max_val))
        bar_w = (width - padding_left - padding_right - 220) * ratio

        # Determine color gradient by rank
        bar_color = "#ef4444" if h.rank == 1 else ("#f97316" if h.rank == 2 else "#3b82f6")

        # Background card
        svg_parts.append(
            f'  <rect x="{padding_left}" y="{card_y:.1f}" width="{width - padding_left - padding_right}" height="{card_h:.1f}" rx="6" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1"/>'
        )

        # Rank badge
        svg_parts.append(
            f'  <rect x="{padding_left + 12}" y="{card_y + card_h/2 - 12:.1f}" width="32" height="24" rx="4" fill="{bar_color}"/>'
        )
        svg_parts.append(
            f'  <text x="{padding_left + 28}" y="{card_y + card_h/2 + 4:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="#ffffff">#{h.rank}</text>'
        )

        # Field value & unit
        val_str = f"{h.value:.3f} {h.unit}"
        svg_parts.append(
            f'  <text x="{padding_left + 54}" y="{card_y + 20:.1f}" font-size="13" font-weight="600" fill="#0f172a">{html.escape(val_str)}</text>'
        )

        # Element / node details
        elem_node_info = f"Element {h.element_label or 'N/A'} | Node {h.node_label or 'N/A'}"
        coords_str = f"Coord: ({h.coordinates[0]:.1f}, {h.coordinates[1]:.1f}, {h.coordinates[2]:.1f})"
        svg_parts.append(
            f'  <text x="{padding_left + 54}" y="{card_y + card_h - 10:.1f}" font-size="11" fill="#64748b">{html.escape(elem_node_info)} &bull; {html.escape(coords_str)}</text>'
        )

        # Value bar
        bar_x = width - padding_right - 180
        svg_parts.append(
            f'  <rect x="{bar_x}" y="{card_y + card_h/2 - 6:.1f}" width="160" height="12" rx="3" fill="#e2e8f0"/>'
        )
        if bar_w > 0:
            svg_parts.append(
                f'  <rect x="{bar_x}" y="{card_y + card_h/2 - 6:.1f}" width="{bar_w * 160 / (width - padding_left - padding_right - 220):.1f}" height="12" rx="3" fill="{bar_color}"/>'
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def save_chart_figure(
    svg_content: str,
    output_path: str,
    caption: str = "",
    kind: str = "xy_curve",
    metadata: Optional[Dict[str, Any]] = None,
) -> ReportFigure:
    """Save vector SVG chart artifact to disk and compute cryptographic SHA-256 provenance."""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    hasher = hashlib.sha256()
    hasher.update(svg_content.encode("utf-8"))
    sha256_hash = hasher.hexdigest()

    meta = dict(metadata or {})
    meta["sha256"] = sha256_hash
    meta["size_bytes"] = os.path.getsize(output_path)
    meta["format"] = "svg"

    return ReportFigure(
        kind=kind,
        path=output_path,
        caption=caption or f"Graphical Deliverable: {os.path.basename(output_path)}",
        source="p1_3_visualization_engine",
        metadata=meta,
    )


def _render_empty_svg(width: int, height: int, message: str) -> str:
    escaped_msg = html.escape(message)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" style="background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">\n'
        f'  <rect x="20" y="20" width="{width - 40}" height="{height - 40}" rx="8" fill="none" stroke="#cbd5e1" stroke-dasharray="6,6"/>\n'
        f'  <text x="{width // 2}" y="{height // 2}" text-anchor="middle" font-size="14" fill="#94a3b8">{escaped_msg}</text>\n'
        f'</svg>'
    )
