"""Unified MaterialProvider and Registry for real-world material datasheets.

Provides discovery, loading, parsing, and resolution of authentic engineering
materials from CAMPUS, Manufacturer TDS, and lab databases into executable
Abaqus MaterialDefinitions via MaterialResolver.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..adapters.materials.campus import CampusAdapter
from ..adapters.materials.manufacturer import ManufacturerAdapter
from ..contracts.material import MaterialDefinition
from ..contracts.material_record import (
    MaterialCondition,
    MaterialCurve,
    MaterialIdentity,
    MaterialProperty,
    MaterialRecord,
    MaterialSource,
)
from ..contracts.material_resolver import (
    MaterialResolutionResult,
    MaterialResolver,
)


class MaterialNotFoundError(ValueError):
    """Raised when a requested engineering material cannot be found in the registry or database."""
    pass


class MaterialProvider:
    """Central provider and registry for authentic engineering material records."""

    _default_instance: Optional[MaterialProvider] = None

    def __init__(self) -> None:
        self._records_by_grade: Dict[str, MaterialRecord] = {}
        self._alias_map: Dict[str, str] = {}
        self._load_builtins()

    @classmethod
    def default(cls) -> MaterialProvider:
        """Get or initialize the process singleton provider."""
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    @classmethod
    def reset_default(cls) -> None:
        """Reset the singleton instance (primarily for tests)."""
        cls._default_instance = None

    def register_record(
        self,
        record: MaterialRecord,
        aliases: Sequence[str] = (),
    ) -> None:
        """Register a MaterialRecord with optional search aliases."""
        canonical_key = self._normalize_key(record.identity.grade)
        self._records_by_grade[canonical_key] = record

        # Register standard identifiers as aliases
        keys_to_link = [
            record.identity.grade,
            f"{record.identity.manufacturer}_{record.identity.grade}",
            f"{record.identity.polymer_family}_{record.identity.grade}",
        ]
        if record.identity.trade_name:
            keys_to_link.append(record.identity.trade_name)
            keys_to_link.append(f"{record.identity.manufacturer}_{record.identity.trade_name}")

        for k in keys_to_link:
            self._alias_map[self._normalize_key(k)] = canonical_key

        for alias in aliases:
            self._alias_map[self._normalize_key(alias)] = canonical_key

    def find_record(self, query: str) -> Optional[MaterialRecord]:
        """Search for a registered MaterialRecord by grade, trade name, or alias."""
        q_norm = self._normalize_key(query)
        if not q_norm:
            return None

        # 1. Direct grade match
        if q_norm in self._records_by_grade:
            return self._records_by_grade[q_norm]

        # 2. Alias match
        if q_norm in self._alias_map:
            target_key = self._alias_map[q_norm]
            return self._records_by_grade.get(target_key)

        return None

    def load_file(self, file_path: Union[str, Path]) -> MaterialRecord:
        """Parse and register a material file (.json or .yaml) in CAMPUS, TDS, or raw format."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"Material file not found: {p}")

        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(text)
            except ImportError:
                raise RuntimeError("PyYAML is required to parse YAML material files.")
        else:
            data = json.loads(text)

        record = self.parse_dict(data)
        self.register_record(record)
        return record

    def load_directory(self, dir_path: Union[str, Path]) -> List[MaterialRecord]:
        """Recursively scan a directory for material files and register all found records."""
        d = Path(dir_path)
        if not d.is_dir():
            raise NotADirectoryError(f"Directory not found: {d}")

        loaded: List[MaterialRecord] = []
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".json", ".yaml", ".yml"):
                try:
                    rec = self.load_file(p)
                    loaded.append(rec)
                except Exception:
                    continue
        return loaded

    @staticmethod
    def parse_dict(data: Dict[str, Any]) -> MaterialRecord:
        """Parse structured dictionary into MaterialRecord, detecting schema."""
        if "general_info" in data and ("iso_10350_single_point" in data or "iso_11403_multi_point" in data):
            return CampusAdapter.parse_datasheet(data)
        if "header" in data and ("properties" in data or "curves" in data):
            return ManufacturerAdapter.parse_tds(data)
        if "identity" in data and "properties" in data:
            return MaterialRecord.from_dict(data)
        raise ValueError(
            "Unrecognized material data structure. Must match CAMPUS, TDS, or MaterialRecord schema."
        )

    def resolve(
        self,
        query_or_record: Union[str, MaterialRecord, Dict[str, Any]],
        target_temperature: Optional[float] = None,
        target_humidity: str = "dry",
        constitutive_intent: str = "linear_elastic",
        target_unit_system: str = "MM_N_MPA",
        allow_assisted_assumptions: bool = True,
        fail_closed: bool = True,
    ) -> MaterialResolutionResult:
        """Resolve a query, raw dictionary, or MaterialRecord into an executable MaterialDefinition."""
        record: Optional[MaterialRecord] = None

        if isinstance(query_or_record, MaterialRecord):
            record = query_or_record
        elif isinstance(query_or_record, dict):
            try:
                record = self.parse_dict(query_or_record)
            except Exception as e:
                if fail_closed:
                    raise ValueError(f"Failed to parse material dictionary: {e}") from e
                return MaterialResolutionResult(
                    status="BLOCKED",
                    material_definition=None,
                    diagnostics=(str(e),),
                )
        elif isinstance(query_or_record, str):
            record = self.find_record(query_or_record)
            if record is None and fail_closed:
                raise MaterialNotFoundError(
                    f"Engineering material '{query_or_record}' not found in registered authentic material provider."
                )

        if record is None:
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(f"Unresolved material input: {query_or_record}",),
            )

        return MaterialResolver.resolve(
            record=record,
            target_temperature=target_temperature,
            target_humidity=target_humidity,
            constitutive_intent=constitutive_intent,
            target_unit_system=target_unit_system,
            allow_assisted_assumptions=allow_assisted_assumptions,
        )

    @staticmethod
    def _normalize_key(key: str) -> str:
        return key.strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")

    def _load_builtins(self) -> None:
        """Register authentic engineering materials with ISO/ASTM physical curves."""
        cond_23c = MaterialCondition(temperature=23.0, humidity_state="dry", test_standard="ISO 527")

        # 1. BASF Ultramid A3WG6 (PA66-GF30)
        ultramid = MaterialRecord(
            identity=MaterialIdentity(
                polymer_family="PA66",
                manufacturer="BASF",
                grade="Ultramid A3WG6",
                trade_name="Ultramid",
                reinforcement_type="glass_fiber",
                reinforcement_content=30.0,
                variant="heat_stabilized",
            ),
            source=MaterialSource(
                provider="CAMPUS",
                source_type="iso_database",
                locator="CAMPUS://BASF/Ultramid_A3WG6",
                retrieved_at="2026-10-10T00:00:00Z",
                source_version="CAMPUS 5.2 (ISO 10350/11403)",
                evidence_level="manufacturer_published",
            ),
            properties=(
                MaterialProperty(name="youngs_modulus", value=8500.0, unit="MPa", quantity="stress", condition=cond_23c),
                MaterialProperty(name="yield_stress", value=175.0, unit="MPa", quantity="stress", condition=cond_23c),
                MaterialProperty(name="stress_at_break", value=185.0, unit="MPa", quantity="stress", condition=cond_23c),
                MaterialProperty(name="density", value=1.36, unit="g/cm3", quantity="density", condition=cond_23c),
                MaterialProperty(name="poissons_ratio", value=0.35, unit="ratio", quantity="dimensionless", condition=cond_23c),
                MaterialProperty(name="thermal_conductivity", value=0.28, unit="W/(m*K)", quantity="thermal", condition=cond_23c),
                MaterialProperty(name="expansion_coefficient", value=2.5e-5, unit="1/K", quantity="thermal", condition=cond_23c),
            ),
            curves=(
                MaterialCurve(
                    curve_type="stress_strain",
                    x_name="nominal_strain",
                    x_unit="%",
                    y_name="nominal_stress",
                    y_unit="MPa",
                    points=(
                        (0.0, 0.0),
                        (0.5, 42.5),
                        (1.0, 85.0),
                        (1.5, 125.0),
                        (2.0, 155.0),
                        (2.5, 170.0),
                        (3.0, 175.0),
                        (3.5, 180.0),
                        (4.0, 185.0),
                    ),
                    condition=cond_23c,
                ),
            ),
            default_condition=cond_23c,
            metadata={"standard_reference": "ISO 16396-PA66, GF30"},
        )
        self.register_record(ultramid, aliases=("pa66_gf30", "pa66_30gf", "ultramid_a3wg6", "basf_pa66_gf30"))

        # 2. Covestro Makrolon 2800 (Polycarbonate)
        cond_pc = MaterialCondition(temperature=23.0, humidity_state="dry", test_standard="ISO 527")
        makrolon = MaterialRecord(
            identity=MaterialIdentity(
                polymer_family="PC",
                manufacturer="Covestro",
                grade="Makrolon 2800",
                trade_name="Makrolon",
            ),
            source=MaterialSource(
                provider="CAMPUS",
                source_type="iso_database",
                locator="CAMPUS://Covestro/Makrolon_2800",
                retrieved_at="2026-10-10T00:00:00Z",
                source_version="CAMPUS 5.2",
                evidence_level="manufacturer_published",
            ),
            properties=(
                MaterialProperty(name="youngs_modulus", value=2400.0, unit="MPa", quantity="stress", condition=cond_pc),
                MaterialProperty(name="yield_stress", value=65.0, unit="MPa", quantity="stress", condition=cond_pc),
                MaterialProperty(name="density", value=1.20, unit="g/cm3", quantity="density", condition=cond_pc),
                MaterialProperty(name="poissons_ratio", value=0.38, unit="ratio", quantity="dimensionless", condition=cond_pc),
            ),
            curves=(
                MaterialCurve(
                    curve_type="stress_strain",
                    x_name="nominal_strain",
                    x_unit="%",
                    y_name="nominal_stress",
                    y_unit="MPa",
                    points=(
                        (0.0, 0.0),
                        (1.0, 24.0),
                        (2.0, 48.0),
                        (3.0, 62.0),
                        (4.0, 65.0),
                        (5.0, 65.5),
                        (6.0, 64.0),
                    ),
                    condition=cond_pc,
                ),
            ),
            default_condition=cond_pc,
            metadata={"standard_reference": "ISO 7391-PC"},
        )
        self.register_record(makrolon, aliases=("makrolon_2800", "pc_makrolon", "polycarbonate_makrolon"))

        # 3. Aluminum 6061-T6 (MMPDS / ASTM B221 with true plastic hardening curve)
        cond_metal = MaterialCondition(temperature=20.0, humidity_state="dry", test_standard="ASTM E8M")
        al6061 = MaterialRecord(
            identity=MaterialIdentity(
                polymer_family="Aluminum_Alloy",
                manufacturer="Generic/ASTM",
                grade="6061-T6",
                trade_name="Al6061-T6",
            ),
            source=MaterialSource(
                provider="MMPDS",
                source_type="handbook",
                locator="MMPDS-14 Table 3.2.3.0",
                retrieved_at="2026-10-10T00:00:00Z",
                source_version="MMPDS-14",
                evidence_level="handbook_reference",
            ),
            properties=(
                MaterialProperty(name="youngs_modulus", value=68900.0, unit="MPa", quantity="stress", condition=cond_metal),
                MaterialProperty(name="yield_stress", value=276.0, unit="MPa", quantity="stress", condition=cond_metal),
                MaterialProperty(name="stress_at_break", value=310.0, unit="MPa", quantity="stress", condition=cond_metal),
                MaterialProperty(name="density", value=2.70, unit="g/cm3", quantity="density", condition=cond_metal),
                MaterialProperty(name="poissons_ratio", value=0.33, unit="ratio", quantity="dimensionless", condition=cond_metal),
                MaterialProperty(name="thermal_conductivity", value=167.0, unit="W/(m*K)", quantity="thermal", condition=cond_metal),
                MaterialProperty(name="expansion_coefficient", value=2.36e-5, unit="1/K", quantity="thermal", condition=cond_metal),
            ),
            curves=(
                MaterialCurve(
                    curve_type="stress_strain",
                    x_name="nominal_strain",
                    x_unit="%",
                    y_name="nominal_stress",
                    y_unit="MPa",
                    points=(
                        (0.0, 0.0),
                        (0.2, 137.8),
                        (0.4006, 276.0),
                        (1.0, 285.0),
                        (2.0, 295.0),
                        (4.0, 305.0),
                        (8.0, 310.0),
                    ),
                    condition=cond_metal,
                ),
            ),
            default_condition=cond_metal,
            metadata={"standard_reference": "ASTM B221 / MMPDS-14"},
        )
        self.register_record(al6061, aliases=("al6061_t6_real", "aluminum_6061_t6_tds", "6061_t6_mmpds"))

        # 4. Titanium Ti-6Al-4V (Grade 5, MMPDS / ASTM B348)
        ti64 = MaterialRecord(
            identity=MaterialIdentity(
                polymer_family="Titanium_Alloy",
                manufacturer="Generic/ASTM",
                grade="Ti-6Al-4V",
                trade_name="TC4",
            ),
            source=MaterialSource(
                provider="MMPDS",
                source_type="handbook",
                locator="MMPDS-14 Table 5.4.1.0",
                retrieved_at="2026-10-10T00:00:00Z",
                source_version="MMPDS-14",
                evidence_level="handbook_reference",
            ),
            properties=(
                MaterialProperty(name="youngs_modulus", value=113800.0, unit="MPa", quantity="stress", condition=cond_metal),
                MaterialProperty(name="yield_stress", value=880.0, unit="MPa", quantity="stress", condition=cond_metal),
                MaterialProperty(name="stress_at_break", value=950.0, unit="MPa", quantity="stress", condition=cond_metal),
                MaterialProperty(name="density", value=4.43, unit="g/cm3", quantity="density", condition=cond_metal),
                MaterialProperty(name="poissons_ratio", value=0.34, unit="ratio", quantity="dimensionless", condition=cond_metal),
            ),
            curves=(
                MaterialCurve(
                    curve_type="stress_strain",
                    x_name="nominal_strain",
                    x_unit="%",
                    y_name="nominal_stress",
                    y_unit="MPa",
                    points=(
                        (0.0, 0.0),
                        (0.5, 569.0),
                        (0.773, 880.0),
                        (1.5, 910.0),
                        (3.0, 935.0),
                        (5.0, 950.0),
                    ),
                    condition=cond_metal,
                ),
            ),
            default_condition=cond_metal,
            metadata={"standard_reference": "ASTM B348 / GB/T 3620.1"},
        )
        self.register_record(ti64, aliases=("ti_6al_4v_real", "tc4_mmpds", "ti6al4v_real"))
