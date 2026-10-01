from dataclasses import dataclass

@dataclass(frozen=True)
class WeibullFit:
    shape: float
    scale: float
    failures: int
    censored: int
    converged: bool
    iterations: int
    log_likelihood: float

@dataclass(frozen=True)
class ReliabilityResult:
    time: float
    reliability: float
    failure_probability: float
    hazard_rate: float
    distribution: str = "WEIBULL_2P"

@dataclass(frozen=True)
class EmpiricalReliabilityPoint:
    time: float
    failures: int
    survivors: int
    reliability: float
