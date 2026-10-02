"""Unified Material Definition semantic contract."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .action import AbaqusAction
from .units import UnitSystem


@dataclass(frozen=True)
class ElasticProperties:
    youngs_modulus: float
    poisson_ratio: float
    temperature_dependence: bool = False

    def __post_init__(self):
        if self.youngs_modulus <= 0:
            raise ValueError("Young's modulus must be positive")
        if not (-1.0 < self.poisson_ratio < 0.5):
            raise ValueError("Poisson's ratio must be in (-1, 0.5)")


@dataclass(frozen=True)
class PlasticProperties:
    yield_stress: float
    plastic_strain: float = 0.0
    hardening_table: Tuple[Tuple[float, float], ...] = ()


@dataclass(frozen=True)
class ThermalProperties:
    conductivity: float
    specific_heat: Optional[float] = None
    expansion_coefficient: Optional[float] = None


@dataclass(frozen=True)
class MaterialDefinition:
    """Consolidated semantic representation of an engineering material."""
    name: str
    unit_system: str = "MM_N_MPA"
    elastic: Optional[ElasticProperties] = None
    density: Optional[float] = None
    plastic: Optional[PlasticProperties] = None
    thermal: Optional[ThermalProperties] = None
    provenance: str = ""
    assumptions: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            raise ValueError("material name is required")
        if self.density is not None and self.density <= 0:
            raise ValueError("density must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "unit_system": self.unit_system,
            "elastic": {
                "youngs_modulus": self.elastic.youngs_modulus,
                "poisson_ratio": self.elastic.poisson_ratio,
                "temperature_dependence": self.elastic.temperature_dependence,
            } if self.elastic else None,
            "density": self.density,
            "plastic": {
                "yield_stress": self.plastic.yield_stress,
                "plastic_strain": self.plastic.plastic_strain,
                "hardening_table": list(self.plastic.hardening_table),
            } if self.plastic else None,
            "thermal": {
                "conductivity": self.thermal.conductivity,
                "specific_heat": self.thermal.specific_heat,
                "expansion_coefficient": self.thermal.expansion_coefficient,
            } if self.thermal else None,
            "provenance": self.provenance,
            "assumptions": list(self.assumptions),
            "metadata": dict(self.metadata),
        }

    def to_actions(self, model_name: str) -> Tuple[AbaqusAction, ...]:
        """Materialize MaterialDefinition into native Abaqus material actions."""
        from ..actions.builders import (
            material_elastic,
            material_density,
            material_plastic,
            material_conductivity,
            material_specific_heat,
            material_expansion,
        )

        actions = []
        if self.elastic is not None:
            actions.append(
                material_elastic(
                    model=model_name,
                    name=self.name,
                    youngs_modulus=self.elastic.youngs_modulus,
                    poisson=self.elastic.poisson_ratio,
                )
            )
        if self.density is not None:
            actions.append(
                material_density(
                    model=model_name,
                    name=self.name,
                    density=self.density,
                )
            )
        if self.plastic is not None:
            table = self.plastic.hardening_table or ((self.plastic.yield_stress, self.plastic.plastic_strain),)
            actions.append(
                material_plastic(
                    model=model_name,
                    name=self.name,
                    table=table,
                )
            )
        if self.thermal is not None:
            if self.thermal.conductivity is not None:
                actions.append(
                    material_conductivity(
                        model=model_name,
                        name=self.name,
                        table=((self.thermal.conductivity,),),
                    )
                )
            if self.thermal.specific_heat is not None:
                actions.append(
                    material_specific_heat(
                        model=model_name,
                        name=self.name,
                        table=((self.thermal.specific_heat,),),
                    )
                )
            if self.thermal.expansion_coefficient is not None:
                actions.append(
                    material_expansion(
                        model=model_name,
                        name=self.name,
                        table=((self.thermal.expansion_coefficient,),),
                    )
                )
        return tuple(actions)
