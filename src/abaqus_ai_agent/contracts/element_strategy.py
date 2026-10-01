"""Semantic element-selection contract with a conservative Abaqus mapping.

The contract describes engineering intent first and resolves only a small,
explicitly supported subset to native Abaqus element codes. Unknown
combinations fail closed rather than guessing an element formulation.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ElementStrategy:
    family: str
    dimension: str
    shape: str
    order: str = "LINEAR"
    formulation: str = "REDUCED"
    integration: str = "DEFAULT"

    def __post_init__(self):
        for name in ("family", "dimension", "shape", "order", "formulation", "integration"):
            value = str(getattr(self, name)).upper()
            object.__setattr__(self, name, value)
        if self.family not in {"CONTINUUM", "SHELL", "BEAM", "TRUSS"}:
            raise ValueError("unsupported element family")
        if self.dimension not in {"3D", "2D_PLANE_STRESS", "2D_PLANE_STRAIN", "AXISYMMETRIC"}:
            raise ValueError("unsupported element dimension")
        if self.shape not in {"HEX", "TET", "WEDGE", "QUAD", "TRI", "LINE"}:
            raise ValueError("unsupported element shape")
        if self.order not in {"LINEAR", "QUADRATIC"}:
            raise ValueError("order must be LINEAR or QUADRATIC")
        if self.formulation not in {"REDUCED", "FULL", "STANDARD"}:
            raise ValueError("formulation must be REDUCED, FULL or STANDARD")
        if self.integration not in {"DEFAULT", "FULL", "REDUCED"}:
            raise ValueError("unsupported integration")
        if self.formulation == "REDUCED" and self.integration == "FULL":
            raise ValueError("reduced formulation cannot request full integration")
        if self.formulation == "FULL" and self.integration == "REDUCED":
            raise ValueError("full formulation cannot request reduced integration")
        if self.formulation == "STANDARD":
            raise ValueError("STANDARD formulation is not mapped by this contract")


# Deliberately small: common structural continuum element choices only.
# Abaqus element code is the authoritative runtime representation.
_ELEMENT_CODES = {
    ("CONTINUUM", "3D", "HEX", "LINEAR", "REDUCED"): "C3D8R",
    ("CONTINUUM", "3D", "HEX", "LINEAR", "FULL"): "C3D8",
    ("CONTINUUM", "3D", "HEX", "QUADRATIC", "REDUCED"): "C3D20R",
    ("CONTINUUM", "3D", "HEX", "QUADRATIC", "FULL"): "C3D20",
    ("CONTINUUM", "3D", "TET", "LINEAR", "REDUCED"): "C3D4",
    ("CONTINUUM", "3D", "TET", "QUADRATIC", "FULL"): "C3D10",
    ("CONTINUUM", "3D", "WEDGE", "LINEAR", "REDUCED"): "C3D6",
    ("CONTINUUM", "3D", "WEDGE", "QUADRATIC", "FULL"): "C3D15",
    ("CONTINUUM", "2D_PLANE_STRESS", "QUAD", "LINEAR", "REDUCED"): "CPS4R",
    ("CONTINUUM", "2D_PLANE_STRESS", "QUAD", "LINEAR", "FULL"): "CPS4",
    ("CONTINUUM", "2D_PLANE_STRESS", "QUAD", "QUADRATIC", "REDUCED"): "CPS8R",
    ("CONTINUUM", "2D_PLANE_STRESS", "QUAD", "QUADRATIC", "FULL"): "CPS8",
    ("CONTINUUM", "2D_PLANE_STRESS", "TRI", "LINEAR", "FULL"): "CPS3",
    ("CONTINUUM", "2D_PLANE_STRESS", "TRI", "QUADRATIC", "FULL"): "CPS6",
    ("CONTINUUM", "2D_PLANE_STRAIN", "QUAD", "LINEAR", "REDUCED"): "CPE4R",
    ("CONTINUUM", "2D_PLANE_STRAIN", "QUAD", "LINEAR", "FULL"): "CPE4",
    ("CONTINUUM", "2D_PLANE_STRAIN", "QUAD", "QUADRATIC", "REDUCED"): "CPE8R",
    ("CONTINUUM", "2D_PLANE_STRAIN", "QUAD", "QUADRATIC", "FULL"): "CPE8",
    ("CONTINUUM", "2D_PLANE_STRAIN", "TRI", "LINEAR", "FULL"): "CPE3",
    ("CONTINUUM", "2D_PLANE_STRAIN", "TRI", "QUADRATIC", "FULL"): "CPE6",
}


def resolve_element_code(strategy: ElementStrategy) -> str:
    key = (
        strategy.family, strategy.dimension, strategy.shape,
        strategy.order, strategy.formulation
    )
    try:
        return _ELEMENT_CODES[key]
    except KeyError:
        raise ValueError(
            "unsupported element strategy combination: %s/%s/%s/%s/%s"
            % key
        )


def element_strategy_metadata(strategy: ElementStrategy) -> Tuple[str, str, str, str, str, str]:
    return (
        strategy.family, strategy.dimension, strategy.shape,
        strategy.order, strategy.formulation, strategy.integration
    )
