"""Abaqus AI Agent core package."""

from .agent import AbaqusAIAgent, RunResult
from .execution import AbaqusExecutor, BridgeExecutor, InProcessExecutor
from .contracts.units import UnitSystem

__version__ = "0.2.1"

from .contracts.model_snapshot import ModelSnapshot, SnapshotDelta
from .contracts.version import AbaqusRuntimeInfo
from .contracts.viewport import ViewportState
from .execution.analysis_run import AnalysisRun, AnalysisRunState, AnalysisRunner
from .workflow import AnalysisWorkflow
