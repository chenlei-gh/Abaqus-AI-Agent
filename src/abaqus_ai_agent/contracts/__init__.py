"""Stable contracts between planning, grounding, execution and evidence."""

from .engineering_checks import EngineeringCheck, EngineeringCheckReport
from .provenance import AnalysisProvenance
from .sensitivity import SensitivityCase, SensitivityResult, SensitivityReport
from .uncertainty import UncertaintyParameter, UncertaintyScenario, UncertaintyReport
from .correction import RepairCandidate, CorrectionAttempt, CorrectionPolicy
from .benchmarks import BenchmarkCase, BenchmarkResult
from .contact import (
    ContactDiagnostic,
    ContactDiagnosticReport,
    ExpectedContactBehavior,
)
from .numerical import NumericalVerificationResult

from .numerical import NumericalRefinementCase, NumericalRefinementReport, NumericalVerificationResult

from .convergence import MeshConvergencePoint, MeshConvergencePolicy, MeshConvergenceResult, evaluate_mesh_convergence

from .element_strategy import ElementStrategy, resolve_element_code, element_strategy_metadata
