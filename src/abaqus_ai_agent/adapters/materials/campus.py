"""CAMPUS (Computer Aided Material Preselection by Uniform Standards) adapter.

Parses standardized ISO 10350 single-point and ISO 11403 multi-point polymer data
into canonical MaterialRecord representations without embedding proprietary databases.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from ...contracts.material_record import (
    MaterialCondition,
    MaterialCurve,
    MaterialIdentity,
    MaterialProperty,
    MaterialRecord,
    MaterialSource,
)


class CampusAdapter:
    """Parser and adapter for CAMPUS standardized ISO 10350 / 11403 data structures."""

    @classmethod
    def parse_datasheet(cls, data: Dict[str, Any]) -> MaterialRecord:
        """Parse a CAMPUS-compliant JSON/dict export into a canonical MaterialRecord.

        Expected schema supports standard CAMPUS headers:
        - general_info: polymer_family, manufacturer, grade_name, trade_name, etc.
        - iso_10350_single_point: list of property entries with value, unit, test_standard, condition
        - iso_11403_multi_point: list of curve entries with curve_type, points, condition
        """
        gen = data.get("general_info", {})
        identity = MaterialIdentity(
            polymer_family=gen.get("polymer_family", "Generic Polymer"),
            manufacturer=gen.get("manufacturer", "CAMPUS Member"),
            grade=gen.get("grade_name") or gen.get("grade", "Standard Grade"),
            trade_name=gen.get("trade_name"),
            reinforcement_type=gen.get("reinforcement_type"),
            reinforcement_content=float(gen["reinforcement_content"]) if gen.get("reinforcement_content") is not None else None,
            filler_type=gen.get("filler_type"),
            variant=gen.get("variant"),
        )

        src_meta = data.get("source_meta", {})
        source = MaterialSource(
            provider="CAMPUS",
            source_type="iso_database",
            locator=src_meta.get("locator") or f"CAMPUS://{identity.manufacturer}/{identity.grade}",
            retrieved_at=src_meta.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
            source_version=src_meta.get("version", "CAMPUS 5.2+ ISO 10350/11403"),
            evidence_level="manufacturer_published",
            license_note="Structured via CAMPUS public standard format; proprietary bulk distribution restricted.",
        )

        properties: List[MaterialProperty] = []
        for prop_item in data.get("iso_10350_single_point", []):
            cond_data = prop_item.get("condition", {})
            cond = MaterialCondition(
                temperature=float(cond_data.get("temperature", 23.0)),
                temperature_unit=cond_data.get("temperature_unit", "C"),
                humidity_state=cond_data.get("humidity_state", "dry"),
                relative_humidity=float(cond_data["relative_humidity"]) if cond_data.get("relative_humidity") is not None else None,
                test_standard=prop_item.get("test_standard", "ISO 10350"),
                strain_rate=float(cond_data["strain_rate"]) if cond_data.get("strain_rate") is not None else None,
                test_time=float(cond_data["test_time"]) if cond_data.get("test_time") is not None else None,
                frequency=float(cond_data["frequency"]) if cond_data.get("frequency") is not None else None,
                stress_level=float(cond_data["stress_level"]) if cond_data.get("stress_level") is not None else None,
            )
            prop = MaterialProperty(
                name=prop_item["name"],
                value=float(prop_item["value"]),
                unit=prop_item["unit"],
                quantity=prop_item.get("quantity", "stress"),
                condition=cond,
            )
            properties.append(prop)

        curves: List[MaterialCurve] = []
        for curve_item in data.get("iso_11403_multi_point", []):
            cond_data = curve_item.get("condition", {})
            cond = MaterialCondition(
                temperature=float(cond_data.get("temperature", 23.0)),
                temperature_unit=cond_data.get("temperature_unit", "C"),
                humidity_state=cond_data.get("humidity_state", "dry"),
                test_standard=curve_item.get("test_standard", "ISO 11403-1"),
                strain_rate=float(cond_data["strain_rate"]) if cond_data.get("strain_rate") is not None else None,
                test_time=float(cond_data["test_time"]) if cond_data.get("test_time") is not None else None,
                frequency=float(cond_data["frequency"]) if cond_data.get("frequency") is not None else None,
                stress_level=float(cond_data["stress_level"]) if cond_data.get("stress_level") is not None else None,
            )
            raw_pts = curve_item.get("points", [])
            parsed_pts = tuple((float(p[0]), float(p[1])) for p in raw_pts if len(p) >= 2)
            if len(parsed_pts) >= 2:
                curves.append(
                    MaterialCurve(
                        curve_type=curve_item.get("curve_type", "stress_strain"),
                        x_name=curve_item.get("x_name", "nominal_strain"),
                        x_unit=curve_item.get("x_unit", "%"),
                        y_name=curve_item.get("y_name", "nominal_stress"),
                        y_unit=curve_item.get("y_unit", "MPa"),
                        points=parsed_pts,
                        condition=cond,
                    )
                )

        default_cond = MaterialCondition(temperature=23.0, humidity_state="dry")
        return MaterialRecord(
            identity=identity,
            source=source,
            properties=tuple(properties),
            curves=tuple(curves),
            default_condition=default_cond,
            metadata=dict(data.get("metadata", {})),
        )
