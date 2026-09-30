from dataclasses import dataclass
from typing import Dict

UNIT_SYSTEMS = {
    "SI": {"length": "m", "force": "N", "stress": "Pa", "mass": "kg", "time": "s"},
    "MM_N_MPA": {"length": "mm", "force": "N", "stress": "MPa", "mass": "tonne", "time": "s"},
    "M_N_PA": {"length": "m", "force": "N", "stress": "Pa", "mass": "kg", "time": "s"},
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
            raise ValueError("unit mismatch for %s: expected %s, got %s" %
                             (quantity, expected, unit))
        return True
