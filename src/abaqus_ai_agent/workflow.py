from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    required: bool = True
    confirmation: bool = False


@dataclass(frozen=True)
class AnalysisWorkflow:
    """Small recipe layer for complete engineering analyses; actions remain explicit."""
    analysis_type: str
    steps: Tuple[WorkflowStep, ...]

    @classmethod
    def standard_static(cls):
        return cls("static", tuple(WorkflowStep(name) for name in (
            "inspect_model", "ground_geometry", "inspect_geometry", "material", "section",
            "step", "boundary_conditions", "loads", "contact", "mesh", "mesh_quality",
            "job", "odb", "results", "acceptance", "evidence")))

    @classmethod
    def for_type(cls, analysis_type):
        value=str(analysis_type or "static").lower().replace("_", "-")
        if value in ("static", "static-general", "linear-static"):
            return cls.standard_static()
        return cls(value, tuple(WorkflowStep(name) for name in (
            "inspect_model", "ground_geometry", "inspect_geometry", "material", "section",
            "step", "boundary_conditions", "loads", "contact", "mesh", "job", "odb",
            "results", "acceptance", "evidence")))
