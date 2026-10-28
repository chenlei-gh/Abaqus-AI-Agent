"""Best-effort records of correction cost.

This module observes syntax failures, preflight failures, diagnosis, healing
attempts and solver outcomes. It never decides whether a run may proceed, and
a write or classification failure must not change solver, approval or BLOCKED
state. A record is not evidence that correction time has gone down.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CATEGORIES = (
    "syntax",
    "abaqus_api",
    "region_invalid",
    "unit_or_direction",
    "convergence",
    "preflight",
    "license",
    "other",
)


def classify_correction_category(message: str = "", category: Optional[str] = None) -> str:
    """Map a failure into the REQ-4.7 category set. Never raises."""
    try:
        if category in CATEGORIES:
            return category
        low = str(message or "").lower()
        rules = (
            ("syntax", "syntax"),
            ("invalid syntax", "syntax"),
            ("attributeerror", "abaqus_api"),
            ("abaqus_api", "abaqus_api"),
            ("has no attribute", "abaqus_api"),
            ("region", "region_invalid"),
            ("set not found", "region_invalid"),
            ("empty region", "region_invalid"),
            ("unit", "unit_or_direction"),
            ("direction", "unit_or_direction"),
            ("load direction", "unit_or_direction"),
            ("too many attempts", "convergence"),
            ("convergence", "convergence"),
            ("cutback", "convergence"),
            ("preflight", "preflight"),
            ("license", "license"),
        )
        for marker, name in rules:
            if marker in low:
                return name
        return "other"
    except Exception:
        logger.debug("correction category classification failed", exc_info=True)
        return "other"


@dataclass
class CorrectionRecord:
    """One observed correction event. Times are seconds, never a gate input."""

    category: str
    stage: str
    first_pass: bool
    retry_count: int = 0
    diagnosis_s: Optional[float] = None
    repair_s: Optional[float] = None
    extra_solve_s: Optional[float] = None
    message: str = ""
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=lambda: datetime.datetime.now(
        datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "stage": self.stage,
            "first_pass": self.first_pass,
            "retry_count": self.retry_count,
            "diagnosis_s": self.diagnosis_s,
            "repair_s": self.repair_s,
            "extra_solve_s": self.extra_solve_s,
            "message": self.message,
            "source": self.source,
            "metadata": dict(self.metadata),
            "recorded_at": self.recorded_at,
            "clock": "monotonic",
        }


class CorrectionRecorder:
    """Append-only JSONL recorder. Construction and writes never raise."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self.records = []

    def record(self, record: CorrectionRecord) -> Optional[Dict[str, Any]]:
        try:
            payload = record.to_dict()
            self.records.append(payload)
            if self.path:
                directory = os.path.dirname(os.path.abspath(self.path))
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            return payload
        except Exception:
            logger.debug("correction telemetry write failed", exc_info=True)
            return None


def record_correction_event(
    category: str,
    stage: str,
    *,
    message: str = "",
    source: str = "",
    first_pass: bool = False,
    retry_count: int = 0,
    diagnosis_s: Optional[float] = None,
    repair_s: Optional[float] = None,
    extra_solve_s: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
    path: Optional[str] = None,
    workdir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Record one event. Returns the payload, or None if recording failed."""
    try:
        target = path
        if target is None and workdir:
            target = os.path.join(str(workdir), "correction_telemetry.jsonl")
        recorder = CorrectionRecorder(target)
        return recorder.record(CorrectionRecord(
            category=classify_correction_category(message, category),
            stage=stage,
            first_pass=bool(first_pass),
            retry_count=int(retry_count),
            diagnosis_s=diagnosis_s,
            repair_s=repair_s,
            extra_solve_s=extra_solve_s,
            message=str(message or "")[:500],
            source=str(source or ""),
            metadata=dict(metadata or {}),
        ))
    except Exception:
        logger.debug("correction telemetry record failed", exc_info=True)
        return None


class CorrectionTimer:
    """Monotonic span timer. A missing start yields None, never an exception."""

    def __init__(self) -> None:
        self._start: Optional[float] = None

    def start(self) -> None:
        try:
            self._start = time.monotonic()
        except Exception:
            logger.debug("correction timer start failed", exc_info=True)
            self._start = None

    def elapsed(self) -> Optional[float]:
        try:
            if self._start is None:
                return None
            return time.monotonic() - self._start
        except Exception:
            logger.debug("correction timer elapsed failed", exc_info=True)
            return None
