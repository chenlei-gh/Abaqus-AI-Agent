from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    required: bool = True
    confirmation: bool = False


@dataclass(frozen=True)
class AnalysisWorkflow:
    """Recipe layer for complete engineering analyses; actions remain explicit."""
    analysis_type: str
    steps: Tuple[WorkflowStep, ...]

    @classmethod
    def _build(cls, analysis_type, names):
        return cls(analysis_type, tuple(WorkflowStep(name) for name in names))

    @classmethod
    def standard_static(cls):
        return cls._build("static", (
            "inspect_model", "ground_geometry", "inspect_geometry", "material",
            "section", "step", "boundary_conditions", "loads", "contact",
            "mesh", "mesh_quality", "output", "job", "artifacts", "odb",
            "results", "acceptance", "evidence"))

    @classmethod
    def modal(cls):
        return cls._build("modal", (
            "inspect_model", "ground_geometry", "inspect_geometry", "material",
            "section", "step", "boundary_conditions", "mesh", "mesh_quality",
            "output", "job", "artifacts", "odb", "results", "acceptance", "evidence"))

    @classmethod
    def dynamic(cls):
        return cls._build("dynamic", (
            "inspect_model", "ground_geometry", "inspect_geometry", "material",
            "section", "step", "boundary_conditions", "loads", "contact",
            "mesh", "mesh_quality", "output", "job", "artifacts", "odb",
            "results", "acceptance", "evidence"))

    @classmethod
    def thermal(cls):
        return cls._build("thermal", (
            "inspect_model", "ground_geometry", "inspect_geometry", "material",
            "section", "step", "boundary_conditions", "loads", "mesh",
            "mesh_quality", "output", "job", "artifacts", "odb",
            "results", "acceptance", "evidence"))

    @classmethod
    def coupled(cls):
        return cls._build("coupled", (
            "inspect_model", "ground_geometry", "inspect_geometry", "material",
            "section", "step", "boundary_conditions", "loads", "contact",
            "mesh", "mesh_quality", "output", "job", "artifacts", "odb",
            "results", "acceptance", "evidence"))

    @classmethod
    def for_type(cls, analysis_type):
        value = str(analysis_type or "static").lower().replace("_", "-")
        mapping = {
            "static": cls.standard_static,
            "static-general": cls.standard_static,
            "linear-static": cls.standard_static,
            "modal": cls.modal,
            "frequency": cls.modal,
            "dynamic": cls.dynamic,
            "explicit": cls.dynamic,
            "dynamic-explicit": cls.dynamic,
            "thermal": cls.thermal,
            "heat-transfer": cls.thermal,
            "coupled": cls.coupled,
            "coupled-thermal-stress": cls.coupled,
        }
        factory = mapping.get(value)
        if factory:
            return factory()
        return cls._build(value, (
            "inspect_model", "ground_geometry", "inspect_geometry", "material",
            "section", "step", "boundary_conditions", "loads", "contact",
            "mesh", "mesh_quality", "output", "job", "artifacts", "odb",
            "results", "acceptance", "evidence"))


from .static import StaticAnalysisPlan, build_static_plan
