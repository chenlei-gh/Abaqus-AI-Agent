from dataclasses import dataclass, field
from math import isfinite
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
class FatigueResult:
    """Evidence-backed fatigue result; it is not inferred from workflow intent."""
    status: str
    life_cycles: Optional[float] = None
    damage: Optional[float] = None
    warnings: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ("not_verified", "pass", "warning", "fail"):
            raise ValueError("invalid fatigue status")
        if self.life_cycles is not None and (not isfinite(self.life_cycles) or self.life_cycles <= 0):
            raise ValueError("life_cycles must be a positive finite value")
        if self.damage is not None and (not isfinite(self.damage) or self.damage < 0):
            raise ValueError("damage must be a finite non-negative value")

    @property
    def passed(self):
        return self.status == "pass"


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
