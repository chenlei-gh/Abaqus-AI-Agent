"""Abaqus AI Agent core package."""

from .agent import AbaqusAIAgent, RunResult
from .execution import AbaqusExecutor, BridgeExecutor, InProcessExecutor
from .contracts.units import UnitSystem
from .contracts.model_snapshot import ModelSnapshot, SnapshotDelta
from .contracts.version import AbaqusRuntimeInfo
from .contracts.viewport import ViewportState
from .contracts.session import SessionHealth
from .contracts.results import ResultRequirement, ResultExtraction
from .contracts.fatigue import FatigueAnalysisIntent, FatigueWorkflow
from .contracts.convergence import MeshConvergencePoint, MeshConvergencePolicy, MeshConvergenceResult
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
from .engineering_evidence import (
    reaction_balance_from_field_evidence,
    energy_ratio_from_history_evidence,
    numeric_field_sanity_from_field_evidence,
)
from .uncertainty import execute_uncertainty, aggregate_uncertainty_outputs, build_uncertainty_scenarios
from .numerical_verification import execute_refinement_study
from .correction import execute_authorized_correction

from .contracts.experimental_validation import ExperimentalObservation, ExperimentalValidationReport, ExperimentalValidationResult
from .experimental_validation import validate_observations, validate_result_values
