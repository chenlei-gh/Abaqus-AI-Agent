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
from .geometry import RegionReference, resolve_region
from .material import (
    MaterialDefinition,
    ElasticProperties,
    PlasticProperties,
    ThermalProperties,
)
from .material_record import (
    MaterialIdentity,
    MaterialSource,
    MaterialCondition,
    MaterialProperty,
    MaterialCurve,
    MaterialRecord,
)
from .material_resolver import (
    MaterialResolver,
    MaterialResolutionResult,
)
from .step import AnalysisStep
from .capability import CapabilityStatus, CapabilityResult
