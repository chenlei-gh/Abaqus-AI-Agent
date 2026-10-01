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
from .execution.analysis_run import AnalysisRun, AnalysisRunState, AnalysisRunner
from .execution.artifacts import JobArtifact, JobArtifacts
from .execution.batch import BatchExecutor, BatchResult
from .workflow import AnalysisWorkflow

__version__ = "0.2.2"
