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
    time_step_from_history_evidence,
    thermal_mechanical_consistency_from_field_evidence,
)
from .uncertainty import (
    execute_uncertainty, aggregate_uncertainty_outputs, build_uncertainty_scenarios,
    sample_uniform_parameters, summarize_probabilistic_outputs,
    execute_probabilistic_uncertainty,
)
from .numerical_verification import execute_refinement_study
from .correction import execute_authorized_correction

from .contracts.experimental_validation import ExperimentalObservation, ExperimentalValidationReport, ExperimentalValidationResult
from .experimental_validation import validate_observations, validate_result_values

from .fatigue import evaluate_fatigue_history, rainflow_count, stress_cycle_statistics, sn_cycles_to_failure, mean_stress_corrected_amplitude

from .contracts.calibration import CalibrationObservation, ParameterBound, CalibrationResult
from .calibration import identify_parameters
from .contracts.reliability import WeibullFit, ReliabilityResult, EmpiricalReliabilityPoint
from .reliability import empirical_reliability, fit_weibull_2p, weibull_reliability, weibull_b_life
