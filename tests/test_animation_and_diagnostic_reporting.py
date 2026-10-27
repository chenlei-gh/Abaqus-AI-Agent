"""Animation auto-inclusion and diagnostic-draft figure embedding."""

import base64
from pathlib import Path

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.contracts.report import ReportFigure
from abaqus_ai_agent.reporting.figure_selector import select_engineering_figures

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _probe(frames):
    return {
        "verified": True,
        "offline": False,
        "steps": {"Step-1": {"frames": frames, "fields": ["S", "U"]}},
    }


def test_animation_auto_included_when_odb_has_multiple_frames(tmp_path, monkeypatch):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"\x00" * 64)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: _probe(12),
    )
    result = select_engineering_figures(
        physics_domain="static",
        run_id="RUN-ANIM-AUTO",
        odb_path=odb,
        include_animation=False,
    )
    kinds = [s.visualization_type for s in result.specs]
    assert "deformation_animation" in kinds


def test_animation_still_skipped_for_single_frame_odb(tmp_path, monkeypatch):
    odb = tmp_path / "job.odb"
    odb.write_bytes(b"\x00" * 64)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.verify_authentic_odb_structure",
        lambda **kwargs: _probe(1),
    )
    result = select_engineering_figures(
        physics_domain="static",
        run_id="RUN-ANIM-SKIP",
        odb_path=odb,
        include_animation=False,
    )
    kinds = [s.visualization_type for s in result.specs]
    assert "deformation_animation" not in kinds


def test_animation_explicit_request_still_works_without_probe(tmp_path):
    result = select_engineering_figures(
        physics_domain="static",
        run_id="RUN-ANIM-EXPLICIT",
        include_animation=True,
    )
    kinds = [s.visualization_type for s in result.specs]
    assert "deformation_animation" in kinds


def test_diagnostic_html_embeds_verified_figures(tmp_path):
    img = tmp_path / "mises.png"
    img.write_bytes(_MINIMAL_PNG)
    gif = tmp_path / "deformation_animation.gif"
    gif.write_bytes(b"GIF89a" + b"\x00" * 32)
    figures = (
        ReportFigure(kind="stress_hotspot", path=str(img), caption="Mises"),
        ReportFigure(kind="deformation_animation", path=str(gif), caption="Animation"),
        ReportFigure(kind="ghost", path=str(tmp_path / "missing.png"), caption="Ghost"),
    )
    html = AbaqusAIAgent._render_diagnostic_html(None, "Draft", ["line1"], figures=figures)
    assert "data:image/png;base64," in html
    assert "data:image/gif;base64," in html
    assert "Mises" in html
    assert "DIAGNOSTIC NON-DELIVERABLE DRAFT" in html
    # Missing files are skipped, not embedded and not fatal.
    assert "Ghost" not in html
