from dataclasses import dataclass
from typing import Dict

UNIT_SYSTEMS = {
    "SI": {"length": "m", "force": "N", "stress": "Pa", "mass": "kg", "time": "s"},
    "MM_N_MPA": {"length": "mm", "force": "N", "stress": "MPa", "mass": "tonne", "time": "s"},
    "M_N_PA": {"length": "m", "force": "N", "stress": "Pa", "mass": "kg", "time": "s"},
}

UNIT_DIMENSIONS = {"m":"length", "mm":"length", "N":"force", "Pa":"stress", "MPa":"stress", "kg":"mass", "tonne":"mass", "s":"time", "Hz":"frequency", "K":"temperature", "C":"temperature", "degC":"temperature"}

@dataclass(frozen=True)
class UnitSystem:
    name: str
    units: Dict[str, str]
    @classmethod
    def named(cls, name):
        key = str(name).upper()
        if key not in UNIT_SYSTEMS: raise ValueError("unsupported unit system: %s" % name)
        return cls(key, dict(UNIT_SYSTEMS[key]))
    def unit(self, quantity): return self.units[quantity]
    def validate(self, quantity, unit):
        expected = self.unit(quantity)
        if str(unit) != expected: raise ValueError("unit mismatch for %s: expected %s, got %s" % (quantity, expected, unit))
        return True

def unit_dimension(unit):
    key = str(unit)
    if key not in UNIT_DIMENSIONS: raise ValueError("unsupported unit: %s" % unit)
    return UNIT_DIMENSIONS[key]

def validate_same_dimension(units):
    values = tuple(str(unit) for unit in units if unit not in (None, ""))
    if not values: return None
    dimensions = tuple(unit_dimension(unit) for unit in values)
    if len(set(dimensions)) != 1: raise ValueError("incompatible dimensions: %s" % (", ".join(dimensions)))
    return dimensions[0]
