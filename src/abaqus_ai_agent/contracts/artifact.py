"""Contracts for Artifact Pointer and LLM Artifact Summary.

Part of the Three-Plane Architecture (Data Plane vs LLM Plane):
- ArtifactPointer represents the authoritative metadata reference in the Data Plane.
- ArtifactSummary represents the ultra-compact, semantic summary card for the LLM Plane.

Strict rule: LLM Plane NEVER holds full Data Plane file content.
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


class ArtifactContractError(ValueError):
    """Raised when an ArtifactPointer or ArtifactSummary fails validation."""
    pass


@dataclass(frozen=True)
class ArtifactPointer:
    """Authoritative Data Plane reference to an on-disk or remote artifact."""

    artifact_id: str
    type: str  # e.g., "image", "chart", "report", "log", "odb", "inp", "json"
    media_type: str  # MIME type: "image/png", "image/svg+xml", "text/plain", etc.
    location: str  # Project-relative or canonical storage path
    size_bytes: int
    created_by: str = "deterministic_process"  # e.g. "renderer", "solver", "odb_extractor"
    storage_scope: str = "run"  # "run", "case", "global", "ephemeral"
    access_policy: str = "llm_pointer_only"  # "llm_pointer_only", "engineering_internal", "human_downloadable", "machine_internal"
    checksum_sha256: Optional[str] = None
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Validate pointer constraints."""
        if not self.artifact_id or not isinstance(self.artifact_id, str):
            raise ArtifactContractError("artifact_id must be a non-empty string")
        if not self.type or not isinstance(self.type, str):
            raise ArtifactContractError("type must be a non-empty string")
        if not self.media_type or not isinstance(self.media_type, str):
            raise ArtifactContractError("media_type must be a non-empty string")
        if not self.location or not isinstance(self.location, str):
            raise ArtifactContractError("location must be a non-empty string")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ArtifactContractError("size_bytes must be a non-negative integer")
        if not self.storage_scope or not isinstance(self.storage_scope, str):
            raise ArtifactContractError("storage_scope must be a non-empty string")
        if not self.access_policy or not isinstance(self.access_policy, str):
            raise ArtifactContractError("access_policy must be a non-empty string")
        if self.checksum_sha256 is not None:
            if not isinstance(self.checksum_sha256, str) or len(self.checksum_sha256) != 64:
                raise ArtifactContractError("checksum_sha256 must be a 64-character hex string if provided")

    @classmethod
    def from_file(
        cls,
        filepath: str | Path,
        artifact_id: str,
        artifact_type: str,
        media_type: str,
        created_by: str = "deterministic_process",
        compute_checksum: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactPointer:
        """Construct an ArtifactPointer by inspecting an actual file on disk."""
        p = Path(filepath)
        if not p.is_file():
            raise ArtifactContractError(f"Target file does not exist: {filepath}")

        size = p.stat().st_size
        checksum = None
        if compute_checksum:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            checksum = h.hexdigest()

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return cls(
            artifact_id=artifact_id,
            type=artifact_type,
            media_type=media_type,
            location=str(filepath).replace("\\", "/"),
            size_bytes=size,
            created_by=created_by,
            storage_scope=metadata.get("storage_scope", "run") if metadata else "run",
            access_policy=metadata.get("access_policy", "llm_pointer_only") if metadata else "llm_pointer_only",
            checksum_sha256=checksum,
            created_at=now,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArtifactPointer:
        return cls(
            artifact_id=data["artifact_id"],
            type=data["type"],
            media_type=data["media_type"],
            location=data["location"],
            size_bytes=int(data["size_bytes"]),
            created_by=data.get("created_by", "deterministic_process"),
            storage_scope=data.get("storage_scope", "run"),
            access_policy=data.get("access_policy", "llm_pointer_only"),
            checksum_sha256=data.get("checksum_sha256"),
            created_at=data.get("created_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ArtifactSummary:
    """Lightweight, semantic summary card designed for LLM Plane context injection.

    Contains zero binary data, zero raw SVG/HTML, strictly limited to high-level
    engineering findings and primary values.
    """

    artifact_id: str
    type: str
    headline: str
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    status: Optional[str] = None  # e.g. "PASS", "FAIL", "READY", "OPTIMAL"

    def __post_init__(self):
        if not self.artifact_id or not isinstance(self.artifact_id, str):
            raise ArtifactContractError("artifact_id must be a non-empty string")
        if not self.type or not isinstance(self.type, str):
            raise ArtifactContractError("type must be a non-empty string")
        if not self.headline or not isinstance(self.headline, str):
            raise ArtifactContractError("headline must be a non-empty string")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_llm_card(self) -> Dict[str, Any]:
        """Produce the minimal dict for injection into LLM prompt."""
        card: Dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "type": self.type,
            "headline": self.headline,
        }
        if self.key_metrics:
            card["metrics"] = self.key_metrics
        if self.status:
            card["status"] = self.status
        return card

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArtifactSummary:
        return cls(
            artifact_id=data["artifact_id"],
            type=data["type"],
            headline=data["headline"],
            key_metrics=data.get("key_metrics") or data.get("metrics") or {},
            status=data.get("status"),
        )
