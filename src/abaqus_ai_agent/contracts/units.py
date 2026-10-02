from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

UNIT_SYSTEMS = {
    "SI": {
        "length": "m", "force": "N", "stress": "Pa", "mass": "kg",
        "time": "s", "temperature": "K", "energy": "J", "frequency": "Hz",
    },
    "MM_N_MPA": {
        "length": "mm", "force": "N", "stress": "MPa", "mass": "tonne",
        "time": "s", "temperature": "K", "energy": "N*mm", "frequency": "Hz",
    },
    "M_N_PA": {
        "length": "m", "force": "N", "stress": "Pa", "mass": "kg",
        "time": "s", "temperature": "K", "energy": "J", "frequency": "Hz",
    },
    "SI_MM": {
        "length": "mm", "force": "N", "stress": "MPa", "mass": "tonne",
        "time": "s", "temperature": "K", "energy": "N*mm", "frequency": "Hz",
    },
}

UNIT_DIMENSIONS = {
    "m": "length",
    "mm": "length",
    "N": "force",
    "Pa": "stress",
    "MPa": "stress",
    "kg": "mass",
    "tonne": "mass",
    "s": "time",
    "Hz": "frequency",
    "K": "temperature",
    "C": "temperature",
    "degC": "temperature",
    "J": "energy",
    "N*mm": "energy",
}

QUANTITY_DIMENSIONS = {
    "length": "length",
    "displacement": "length",
    "force": "force",
    "pressure": "stress",
    "stress": "stress",
    "mass": "mass",
    "time": "time",
    "temperature": "temperature",
    "energy": "energy",
    "frequency": "frequency",
}


@dataclass(frozen=True)
class UnitSystem:
    name: str
    units: Dict[str, str]

    @classmethod
    def named(cls, name):
        key = str(name).upper()
        if key not in UNIT_SYSTEMS:
            raise ValueError("unsupported unit system: %s" % name)
        return cls(key, dict(UNIT_SYSTEMS[key]))

    def unit(self, quantity):
        return self.units[quantity]

    def validate(self, quantity, unit):
        expected = self.unit(quantity)
        if str(unit) != expected:
            raise ValueError(
                "unit mismatch for %s: expected %s, got %s"
                % (quantity, expected, unit)
            )
        return True


def unit_dimension(unit):
    key = str(unit)
    if key not in UNIT_DIMENSIONS:
        raise ValueError("unsupported unit: %s" % unit)
    return UNIT_DIMENSIONS[key]


def quantity_dimension(quantity):
    key = str(quantity).lower()
    if key not in QUANTITY_DIMENSIONS:
        raise ValueError("unsupported quantity: %s" % quantity)
    return QUANTITY_DIMENSIONS[key]


def validate_quantity_unit(quantity, unit, unit_system=None):
    """Validate a declared quantity/unit pair without performing conversion.

    Abaqus uses user-selected, self-consistent units rather than a built-in
    unit system. When a unit system is supplied, the unit must match that
    system exactly; otherwise only dimensional compatibility is checked.
    """
    if unit in (None, ""):
        return True
    dimension = quantity_dimension(quantity)
    if unit_system is not None:
        UnitSystem.named(unit_system).validate(
            quantity if quantity in UNIT_SYSTEMS[str(unit_system).upper()] else dimension,
            unit,
        )
        return True
    if unit_dimension(unit) != dimension:
        raise ValueError(
            "unit dimension mismatch for %s: expected dimension %s, got %s"
            % (quantity, dimension, unit_dimension(unit))
        )
    return True


def validate_same_dimension(units):
    values = tuple(str(unit) for unit in units if unit not in (None, ""))
    if not values:
        return None
    dimensions = tuple(unit_dimension(item) for item in values)
    if any(item != dimensions[0] for item in dimensions):
        raise ValueError("inconsistent unit dimensions: %s" % (values,))
    return dimensions[0]


def validate_action_quantities(action_type: str, parameters: dict, unit_system: Optional[str] = None) -> bool:
    """Validate dimensional consistency and non-negativity of quantities within an action."""
    params = parameters or {}
    if action_type == "material_elastic":
        ym = params.get("youngs_modulus")
        if ym is not None and float(ym) <= 0:
            raise ValueError("Young's modulus must be positive in %s" % action_type)
        if "unit" in params:
            validate_quantity_unit("stress", params["unit"], unit_system)
    elif action_type == "material_density":
        rho = params.get("density")
        if rho is not None and float(rho) <= 0:
            raise ValueError("density must be positive in %s" % action_type)
        if "unit" in params:
            validate_quantity_unit("mass", params["unit"], unit_system)
    elif action_type in ("static_step", "implicit_dynamic_step", "explicit_dynamic_step"):
        tp = params.get("time_period")
        if tp is not None and float(tp) <= 0:
            raise ValueError("time_period must be positive in %s" % action_type)
        if "unit" in params:
            validate_quantity_unit("time", params["unit"], unit_system)
    elif action_type in ("concentrated_force", "pressure_load"):
        if "unit" in params:
            q = "force" if action_type == "concentrated_force" else "stress"
            validate_quantity_unit(q, params["unit"], unit_system)
    return True
    dimensions = tuple(unit_dimension(unit) for unit in values)
    if len(set(dimensions)) != 1:
        raise ValueError("incompatible dimensions: %s" % (", ".join(dimensions)))
    return dimensions[0]
