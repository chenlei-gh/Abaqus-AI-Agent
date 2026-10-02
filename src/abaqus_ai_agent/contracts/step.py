"""Unified Analysis Step semantic contract."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .action import AbaqusAction


@dataclass(frozen=True)
class AnalysisStep:
    """Unified semantic contract for an Abaqus analysis step."""
    name: str = "Step-1"
    procedure: str = "static"  # static, implicit_dynamic, explicit_dynamic, heat_transfer, frequency
    previous: str = "Initial"
    time_period: float = 1.0
    nlgeom: bool = False
    initial_inc: Optional[float] = None
    min_inc: Optional[float] = None
    max_inc: Optional[float] = None
    max_num_inc: int = 100
    stabilization_method: str = "NONE"
    stabilization_magnitude: Optional[float] = None
    amplitude: str = "RAMP"
    solution_technique: str = "FULL_NEWTON"
    application: Optional[str] = None
    nohaf: Optional[bool] = None
    half_inc_scale_factor: Optional[float] = None
    num_eigenvalues: Optional[int] = None
    steady_state: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            raise ValueError("step name is required")
        if self.procedure not in (
            "static", "implicit_dynamic", "explicit_dynamic", "heat_transfer", "frequency",
            "coupled_temp_displacement", "coupled_temperature_displacement"
        ):
            raise ValueError("unsupported step procedure: %s" % self.procedure)
        if self.time_period <= 0 and self.procedure != "frequency":
            raise ValueError("time_period must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "procedure": self.procedure,
            "previous": self.previous,
            "time_period": self.time_period,
            "nlgeom": self.nlgeom,
            "initial_inc": self.initial_inc,
            "min_inc": self.min_inc,
            "max_inc": self.max_inc,
            "max_num_inc": self.max_num_inc,
            "stabilization_method": self.stabilization_method,
            "stabilization_magnitude": self.stabilization_magnitude,
            "amplitude": self.amplitude,
            "solution_technique": self.solution_technique,
            "application": self.application,
            "nohaf": self.nohaf,
            "half_inc_scale_factor": self.half_inc_scale_factor,
            "num_eigenvalues": self.num_eigenvalues,
            "steady_state": self.steady_state,
            "metadata": dict(self.metadata),
        }

    def to_action(self, model_name: str) -> AbaqusAction:
        """Materialize AnalysisStep into native Abaqus step action."""
        from ..actions.builders import (
            static_step,
            implicit_dynamic_step,
            explicit_dynamic_step,
            heat_transfer_step,
            coupled_temp_displacement_step,
            frequency_step,
        )

        res_action: AbaqusAction
        if self.procedure == "static":
            res_action = static_step(
                model=model_name,
                name=self.name,
                previous=self.previous,
                nlgeom=self.nlgeom,
                time_period=self.time_period,
                stabilization_method=self.stabilization_method,
                stabilization_magnitude=self.stabilization_magnitude,
                max_num_inc=self.max_num_inc,
                initial_inc=self.initial_inc,
                min_inc=self.min_inc,
                max_inc=self.max_inc,
                amplitude=self.amplitude,
            )
        elif self.procedure == "implicit_dynamic":
            res_action = implicit_dynamic_step(
                model=model_name,
                name=self.name,
                previous=self.previous,
                time_period=self.time_period,
                nlgeom=self.nlgeom,
                max_num_inc=self.max_num_inc,
                initial_inc=self.initial_inc,
                min_inc=self.min_inc,
                max_inc=self.max_inc,
                solution_technique=self.solution_technique,
                amplitude=self.amplitude,
                application=self.application,
                nohaf=self.nohaf,
                half_inc_scale_factor=self.half_inc_scale_factor,
            )
        elif self.procedure == "explicit_dynamic":
            res_action = explicit_dynamic_step(
                model=model_name,
                name=self.name,
                previous=self.previous,
                time_period=self.time_period,
                nlgeom=self.nlgeom,
                max_increment=self.max_inc,
            )
        elif self.procedure == "heat_transfer":
            res_action = heat_transfer_step(
                model=model_name,
                name=self.name,
                previous=self.previous,
                response="STEADY_STATE" if self.steady_state else "TRANSIENT",
                time_period=self.time_period,
                initial_inc=self.initial_inc,
                min_inc=self.min_inc,
                max_inc=self.max_inc,
                max_num_inc=self.max_num_inc,
                amplitude=self.amplitude,
            )
        elif self.procedure in ("coupled_temp_displacement", "coupled_temperature_displacement"):
            res_action = coupled_temp_displacement_step(
                model=model_name,
                name=self.name,
                previous=self.previous,
                response="STEADY_STATE" if self.steady_state else "TRANSIENT",
                time_period=self.time_period,
                nlgeom=self.nlgeom,
                max_num_inc=self.max_num_inc,
                initial_inc=self.initial_inc,
                min_inc=self.min_inc,
                max_inc=self.max_inc,
                amplitude=self.amplitude,
            )
        elif self.procedure == "frequency":
            res_action = frequency_step(
                model=model_name,
                name=self.name,
                previous=self.previous,
                num_eigen=self.num_eigenvalues or 10,
            )
        else:
            raise ValueError("unsupported procedure for action materialization: %s" % self.procedure)

        if self.metadata:
            res_action.parameters.setdefault("metadata", dict(self.metadata))
        return res_action
