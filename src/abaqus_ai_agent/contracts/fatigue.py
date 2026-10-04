from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class IntentFatigueSpec:
    """Declarative fatigue specification associated with an EngineeringIntent."""
    target_cycles: float = 1.0e6
    allowable_damage: float = 1.0
    material_curve: Tuple[Tuple[float, float], ...] = ()
    ultimate_strength: Optional[float] = None
    mean_stress_correction: Optional[str] = "GOODMAN"
    measure: str = "signed_mises"
    step_name: Optional[str] = None
    element_label: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isfinite(self.target_cycles) or self.target_cycles <= 0:
            raise ValueError("target_cycles must be a positive finite number")
        if not isfinite(self.allowable_damage) or self.allowable_damage <= 0:
            raise ValueError("allowable_damage must be a positive finite number")
        if len(self.material_curve) < 2:
            raise ValueError("material_curve must contain at least two (stress, cycles) points")
        for pt in self.material_curve:
            if len(pt) != 2:
                raise ValueError("each material_curve entry must be a (stress, cycles) pair")
            s, n = pt
            if not isfinite(s) or s <= 0 or not isfinite(n) or n <= 0:
                raise ValueError("material_curve stress and cycle values must be positive and finite")
        if self.ultimate_strength is not None:
            if not isfinite(self.ultimate_strength) or self.ultimate_strength <= 0:
                raise ValueError("ultimate_strength must be a positive finite number")
        valid_measures = (
            "signed_mises", "von_mises", "mises", "max_principal", "tresca",
            "s11", "s22", "s33", "s12", "s13", "s23",
        )
        if str(self.measure).lower() not in valid_measures:
            raise ValueError(f"unsupported stress measure: {self.measure}")
        if self.mean_stress_correction is not None:
            valid_corrections = ("goodman", "none", "soderberg", "gerber")
            if str(self.mean_stress_correction).lower() not in valid_corrections:
                raise ValueError(f"unsupported mean stress correction: {self.mean_stress_correction}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_cycles": self.target_cycles,
            "allowable_damage": self.allowable_damage,
            "material_curve": [list(pt) for pt in self.material_curve],
            "ultimate_strength": self.ultimate_strength,
            "mean_stress_correction": self.mean_stress_correction,
            "measure": self.measure,
            "step_name": self.step_name,
            "element_label": self.element_label,
            "metadata": dict(self.metadata),
        }


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
