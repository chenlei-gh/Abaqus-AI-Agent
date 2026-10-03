"""Manufacturer Technical Data Sheet (TDS) adapter.

Parses structured manufacturer technical bulletins into canonical MaterialRecord representations.
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


class ManufacturerAdapter:
    """Parser and adapter for manufacturer technical bulletins and property tables."""

    @classmethod
    def parse_tds(cls, data: Dict[str, Any]) -> MaterialRecord:
        """Parse structured manufacturer technical datasheet dict into MaterialRecord."""
        header = data.get("header", {})
        identity = MaterialIdentity(
            polymer_family=header.get("polymer_family", "Generic Polymer"),
            manufacturer=header.get("manufacturer", "Manufacturer"),
            grade=header.get("grade", "Standard Grade"),
            trade_name=header.get("trade_name"),
            reinforcement_type=header.get("reinforcement_type"),
            reinforcement_content=float(header["reinforcement_content"]) if header.get("reinforcement_content") is not None else None,
            filler_type=header.get("filler_type"),
            variant=header.get("variant"),
        )

        doc_info = data.get("document", {})
        source = MaterialSource(
            provider=header.get("manufacturer", "Manufacturer"),
            source_type="technical_datasheet",
            locator=doc_info.get("locator") or doc_info.get("document_id") or f"TDS://{identity.manufacturer}/{identity.grade}",
            retrieved_at=doc_info.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
            source_version=doc_info.get("revision", "1.0"),
            evidence_level="manufacturer_published",
            license_note=doc_info.get("disclaimer"),
        )

        properties: List[MaterialProperty] = []
        for prop in data.get("properties", []):
            cond_dict = prop.get("condition", {})
            cond = MaterialCondition(
                temperature=float(cond_dict.get("temperature", 23.0)),
                temperature_unit=cond_dict.get("temperature_unit", "C"),
                humidity_state=cond_dict.get("humidity_state", "dry"),
                relative_humidity=float(cond_dict["relative_humidity"]) if cond_dict.get("relative_humidity") is not None else None,
                test_standard=prop.get("test_standard"),
                strain_rate=float(cond_dict["strain_rate"]) if cond_dict.get("strain_rate") is not None else None,
                test_time=float(cond_dict["test_time"]) if cond_dict.get("test_time") is not None else None,
                frequency=float(cond_dict["frequency"]) if cond_dict.get("frequency") is not None else None,
                stress_level=float(cond_dict["stress_level"]) if cond_dict.get("stress_level") is not None else None,
            )
            properties.append(
                MaterialProperty(
                    name=prop["name"],
                    value=float(prop["value"]),
                    unit=prop["unit"],
                    quantity=prop.get("quantity", "stress"),
                    condition=cond,
                )
            )

        curves: List[MaterialCurve] = []
        for c in data.get("curves", []):
            cond_dict = c.get("condition", {})
            cond = MaterialCondition(
                temperature=float(cond_dict.get("temperature", 23.0)),
                temperature_unit=cond_dict.get("temperature_unit", "C"),
                humidity_state=cond_dict.get("humidity_state", "dry"),
                test_standard=c.get("test_standard"),
                strain_rate=float(cond_dict["strain_rate"]) if cond_dict.get("strain_rate") is not None else None,
                test_time=float(cond_dict["test_time"]) if cond_dict.get("test_time") is not None else None,
                frequency=float(cond_dict["frequency"]) if cond_dict.get("frequency") is not None else None,
                stress_level=float(cond_dict["stress_level"]) if cond_dict.get("stress_level") is not None else None,
            )
            raw_pts = c.get("points", [])
            pts = tuple((float(p[0]), float(p[1])) for p in raw_pts if len(p) >= 2)
            if len(pts) >= 2:
                curves.append(
                    MaterialCurve(
                        curve_type=c.get("curve_type", "stress_strain"),
                        x_name=c.get("x_name", "nominal_strain"),
                        x_unit=c.get("x_unit", "%"),
                        y_name=c.get("y_name", "nominal_stress"),
                        y_unit=c.get("y_unit", "MPa"),
                        points=pts,
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
