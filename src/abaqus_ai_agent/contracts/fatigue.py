from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class FatigueAnalysisIntent:
    """Contract for fatigue post-processing; no fatigue solver is implied."""
    name: str
    method: str = "S_N"
    cycles: Optional[float] = None
    mean_stress_correction: Optional[str] = None
    stress_variable: str = "S"
    history_step: Optional[str] = None
    history_region: Optional[str] = None
    material_curve: Tuple[Tuple[float, float], ...] = ()
    damage_model: str = "PALMGREN_MINER"

    def __post_init__(self):
        if self.method.upper() not in ("S_N", "EPSILON_N"):
            raise ValueError("method must be S_N or EPSILON_N")
        if self.cycles is not None and self.cycles <= 0:
            raise ValueError("cycles must be positive")
        if not self.stress_variable:
            raise ValueError("stress_variable is required")
        if self.damage_model.upper() not in ("PALMGREN_MINER",):
            raise ValueError("unsupported damage_model")
        if any(len(point) != 2 for point in self.material_curve):
            raise ValueError("material_curve points must be (x, y) pairs")


@dataclass(frozen=True)
class FatigueWorkflow:
    """Minimal workflow contract around existing Abaqus stress history."""
    intent: FatigueAnalysisIntent
    steps: Tuple[str, ...] = field(default_factory=lambda: (
        "inspect_model",
        "verify_stress_output",
        "verify_stress_history",
        "material_fatigue_curve",
        "cycle_counting",
        "damage_accumulation",
        "life_result",
        "acceptance",
        "evidence",
    ))

    @classmethod
    def for_intent(cls, intent):
        if not isinstance(intent, FatigueAnalysisIntent):
            raise TypeError("intent must be FatigueAnalysisIntent")
        return cls(intent)

    @property
    def solver_scope(self):
        return "postprocess_existing_abaqus_results"


@dataclass(frozen=True)
class FatigueResult:
    """Deterministic post-processing result for an existing stress history."""
    name: str
    cycles_evaluated: float
    damage: float
    predicted_life_cycles: Optional[float]
    method: str = "S_N"
    damage_model: str = "PALMGREN_MINER"
    status: str = "completed"
    source: str = ""
    unit: str = ""

    def __post_init__(self):
        if self.cycles_evaluated < 0:
            raise ValueError("cycles_evaluated must be non-negative")
        if self.damage < 0:
            raise ValueError("damage must be non-negative")
        if self.status not in ("completed", "failed"):
            raise ValueError("status must be completed or failed")
