"""Abaqus AI Agent core package."""

from .agent import AbaqusAIAgent, RunResult
from .execution import AbaqusExecutor, BridgeExecutor, InProcessExecutor
from .contracts.units import UnitSystem
from .contracts.model_snapshot import ModelSnapshot, SnapshotDelta
from .contracts.version import AbaqusRuntimeInfo
from .contracts.viewport import ViewportState
from .contracts.session import SessionHealth
from .contracts.results import ResultRequirement, ResultExtraction
from .contracts.metrics import EngineeringMetric
from .contracts.solver_selection import SolverSelection, select_solver
from .contracts.report import EngineeringReportData, ReportFigure
from .contracts.postprocess import PostProcessingProfile, profile_for_solver_selection
from .reporting.figures import figure_specs_for_profile, capture_viewport_report_figure
from .contracts.fatigue import FatigueAnalysisIntent, FatigueWorkflow, FatigueResult
from .contracts.convergence import MeshConvergencePoint, MeshConvergencePolicy, MeshConvergenceResult, evaluate_mesh_convergence
from .contracts.mesh_quality import MeshSummary, MeshQualityPolicy, MeshQualityResult
from .contracts.engineering_checks import EngineeringCheck, EngineeringCheckReport
from .contracts.provenance import AnalysisProvenance
from .contracts.sensitivity import SensitivityCase, SensitivityResult, SensitivityReport
from .contracts.uncertainty import UncertaintyParameter, UncertaintyScenario, UncertaintyReport
from .contracts.correction import RepairCandidate, CorrectionAttempt, CorrectionPolicy
from .contracts.benchmarks import BenchmarkCase, BenchmarkResult
from .contracts.contact import ContactDiagnostic, ContactDiagnosticReport
from .contracts.numerical import NumericalVerificationResult
from .execution.analysis_run import AnalysisRun, AnalysisRunState, AnalysisRunner
from .execution.artifacts import JobArtifact, JobArtifacts
from .execution.batch import BatchExecutor, BatchResult
from .workflow import AnalysisWorkflow

__version__ = "0.2.2"

from .benchmark_catalog import standard_benchmarks

from .engineering_evidence import reaction_balance_from_field_evidence, energy_ratio_from_history_evidence

from .contracts.mesh_strategy import MeshRefinementRequest, GeometryMeshPlan
from .planning.mesh_strategy import plan_geometry_mesh
from .planning.mesh_strategy import local_seeds_from_geometry_plan, mesh_specification_from_geometry_plan
from .contracts.geometry_features import GeometryFeature, GeometryFeatureEvidence, characterize_geometry
