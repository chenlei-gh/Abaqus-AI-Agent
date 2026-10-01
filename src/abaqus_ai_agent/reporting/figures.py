from dataclasses import asdict

from ..contracts.report import ReportFigure


def figure_specs_for_profile(profile):
    """Return deterministic figure slots without fabricating image evidence."""
    return tuple(
        {"kind": kind, "caption": kind.replace("_", " ").title(), "source": "planned"}
        for kind in getattr(profile, "plots", ())
    )


def capture_viewport_report_figure(executor, path, caption="Model Overview", source="viewport"):
    """Capture a real Abaqus viewport and return a report figure record."""
    from ..execution.viewport import capture_viewport
    result = capture_viewport(executor, path)
    return ReportFigure(kind="viewport", path=path, caption=caption, source=source,
                        metadata={"capture_result": result})
