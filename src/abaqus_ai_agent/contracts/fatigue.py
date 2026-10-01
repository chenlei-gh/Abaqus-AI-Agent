from dataclasses import dataclass, field
from typing import Optional, Tuple


_STRESS_VARIABLES = {
    "S11", "S22", "S33", "S12", "S13", "S23",
    "MISES", "MAX_PRINCIPAL", "MIN_PRINCIPAL",
}


@dataclass(frozen=True)
class FatigueAnalysisIntent:
    """Deterministic fatigue post-processing over an existing scalar stress history."""
    name: str
    method: str = "S_N"
    cycles: Optional[float] = None
    mean_stress_correction: Optional[str] = None
    stress_variable: str = "S11"
    history_step: Optional[str] = None
    history_region: Optional[str] = None
    material_curve: Tuple[Tuple[float, float], ...] = ()
    damage_model: str = "PALMGREN_MINER"
    stress_semantics: str = "scalar_component"
    stress_unit: str = ""
    endurance_unit: str = "cycles"

    def __post_init__(self):
        if self.method.upper() != "S_N":
            raise ValueError("only S_N fatigue is currently implemented")
        if self.cycles is not None and self.cycles <= 0:
            raise ValueError("cycles must be positive")
        variable = self.stress_variable.upper()
        if variable not in _STRESS_VARIABLES:
            raise ValueError("unsupported stress_variable: %s" % self.stress_variable)
        if self.stress_semantics not in ("scalar_component", "scalar_invariant", "scalar_principal"):
            raise ValueError("unsupported stress_semantics")
        if variable in {"S11", "S22", "S33", "S12", "S13", "S23"} and self.stress_semantics != "scalar_component":
            raise ValueError("tensor components require scalar_component semantics")
        if variable == "MISES" and self.stress_semantics != "scalar_invariant":
            raise ValueError("MISES requires scalar_invariant semantics")
        if variable in {"MAX_PRINCIPAL", "MIN_PRINCIPAL"} and self.stress_semantics != "scalar_principal":
            raise ValueError("principal stress requires scalar_principal semantics")
        if self.damage_model.upper() != "PALMGREN_MINER":
            raise ValueError("unsupported damage_model")
        if self.mean_stress_correction is not None:
            correction = self.mean_stress_correction.upper()
            if correction not in ("GOODMAN", "NONE"):
                raise ValueError("only Goodman or NONE mean-stress correction is supported")
        curve = tuple((float(x), float(y)) for x, y in self.material_curve)
        if any(x <= 0 or y <= 0 for x, y in curve):
            raise ValueError("S-N points must contain positive stress and cycle values")
        if curve and len(curve) < 2:
            raise ValueError("material_curve requires at least two points")


@dataclass(frozen=True)
class FatigueCycle:
    index: int
    weight: float
    minimum: float
    maximum: float
    mean: float
    range: float
    amplitude: float
    corrected_amplitude: float
    source_variable: str


@dataclass(frozen=True)
class FatigueResult:
    cycles: Tuple[FatigueCycle, ...]
    damage: float
    life: Optional[float]
    stress_variable: str
    stress_semantics: str
    correction: str
    damage_model: str = "PALMGREN_MINER"
    evidence: Tuple[dict, ...] = ()
    passed: bool = True


@dataclass(frozen=True)
class FatigueWorkflow:
    intent: FatigueAnalysisIntent
    steps: Tuple[str, ...] = field(default_factory=lambda: (
        "inspect_model",
        "verify_stress_output",
        "verify_stress_history",
        "stress_semantics",
        "turning_points",
        "cycle_counting",
        "stress_range_amplitude_mean",
        "mean_stress_correction",
        "sn_life",
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
