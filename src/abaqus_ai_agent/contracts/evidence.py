"""Unified Evidence Manifest V2 Contract and Integrity Verification.

GA-CL.4 Evidence / Provenance V2:
Establishes an unforgeable, tamper-evident cryptographic contract binding:
run_id + case_id + runtime/solver_version + job/model + procedure + required_results +
verification + acceptance + artifacts (.inp/.odb/.sta/.msg/.dat/.log) + provenance + SHA-256 signatures.

Key Capabilities:
1. Unified Evidence Manifest:
   - Unique run_id and case_id.
   - Live environment & solver details.
   - Declarative intent and required results profile.
   - Cryptographic artifact registry mapping file roles to size & SHA-256.
   - Audit signature over canonical manifest contents.
2. Run Identity Binding:
   - Prohibits reusing artifacts from older/different jobs (run_id mismatch -> EVIDENCE_STALE).
3. Artifact Integrity:
   - Live byte verification against recorded SHA-256 checksums (hash mismatch -> EVIDENCE_TAMPERED).
   - Verification of mandatory solver artifacts on disk (missing files -> EVIDENCE_INCOMPLETE).
4. Stale Evidence Protection:
   - Validates run_id alignment and max age limits.
5. Strong Acceptance Binding:
   - If evidence is tampered, incomplete, or stale, acceptance status MUST be BLOCKED
     and result_validity MUST be RESULT_INVALID.
6. Reporting Layer Synchronization:
   - Reports expose evidence integrity status and reject engineering approval if evidence is invalid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


def compute_file_sha256(path: Union[Path, str]) -> Optional[str]:
    """Compute deterministic SHA-256 hash of a file on disk."""
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


DEFAULT_MANDATORY_ROLES: Tuple[str, ...] = ("inp", "odb", "msg", "dat", "sta", "log")


def infer_artifact_role(filename_or_suffix: str) -> str:
    """Infer standardized role for an analysis artifact based on file extension."""
    suffix = filename_or_suffix.lower()
    if "." in suffix:
        suffix = "." + suffix.rsplit(".", 1)[-1]
    role_map = {
        ".inp": "inp",
        ".odb": "odb",
        ".msg": "msg",
        ".dat": "dat",
        ".sta": "sta",
        ".log": "log",
        ".cae": "cae",
        ".sim": "sim",
        ".prt": "prt",
        ".com": "com",
        ".md": "report",
        ".html": "report",
        ".json": "evidence",
        ".png": "figure",
        ".jpg": "figure",
    }
    return role_map.get(suffix, "other")


@dataclass(frozen=True)
class ArtifactRecord:
    """Cryptographic record of an analysis artifact file."""
    name: str
    path: str
    role: str
    exists: bool
    size_bytes: int
    sha256: str
    modified_time: Optional[float] = None
    mandatory: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "role": self.role,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "modified_time": self.modified_time,
            "mandatory": self.mandatory,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArtifactRecord":
        return cls(
            name=str(d.get("name", "")),
            path=str(d.get("path", "")),
            role=str(d.get("role") or infer_artifact_role(d.get("name", ""))),
            exists=bool(d.get("exists", False)),
            size_bytes=int(d.get("size_bytes", 0)),
            sha256=str(d.get("sha256", "")),
            modified_time=d.get("modified_time"),
            mandatory=bool(d.get("mandatory", True)),
        )

    def verify_live(self, base_dir: Optional[Union[Path, str]] = None) -> Tuple[bool, str, Optional[str]]:
        """Verify this record against the physical file on disk.

        Returns:
            (matched, reason, live_sha256)
        """
        p = Path(self.path)
        if not p.is_absolute() and base_dir is not None:
            p = Path(base_dir) / self.path

        if not p.is_file():
            return False, "file_not_found", None

        live_sha = compute_file_sha256(p)
        if live_sha != self.sha256:
            return False, "hash_mismatch", live_sha

        return True, "verified", live_sha


@dataclass
class EvidenceManifestV2:
    """Unified, cryptographic Evidence Manifest V2 contract."""
    schema_version: str = "evidence_manifest_v2"
    run_id: str = ""
    case_id: str = ""
    created_at: str = ""
    environment: Dict[str, Any] = field(default_factory=dict)
    intent_summary: Dict[str, Any] = field(default_factory=dict)
    required_results: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, ArtifactRecord] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    acceptance: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    validity: str = "VALID"  # VALID, TAMPERED, INCOMPLETE, STALE
    audit_signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compute_audit_signature(self) -> str:
        """Compute deterministic SHA-256 over canonical manifest fields."""
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "created_at": self.created_at,
            "environment": self.environment,
            "intent_summary": self.intent_summary,
            "required_results": self.required_results,
            "artifacts": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v)
                for k, v in sorted(self.artifacts.items())
            },
            "verification": self.verification,
            "acceptance": self.acceptance,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }
        canonical_str = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def with_signature(self) -> "EvidenceManifestV2":
        """Attach calculated audit_signature to the manifest."""
        self.audit_signature = self.compute_audit_signature()
        return self

    def verify_signature(self) -> bool:
        """Check whether the stored audit_signature matches the current payload."""
        if not self.audit_signature:
            return False
        return self.audit_signature == self.compute_audit_signature()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "created_at": self.created_at,
            "environment": dict(self.environment),
            "intent_summary": dict(self.intent_summary),
            "required_results": dict(self.required_results),
            "artifacts": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v)
                for k, v in self.artifacts.items()
            },
            "verification": dict(self.verification),
            "acceptance": dict(self.acceptance),
            "provenance": dict(self.provenance),
            "validity": self.validity,
            "audit_signature": self.audit_signature,
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceManifestV2":
        raw_artifacts = d.get("artifacts") or {}
        artifacts = {}
        for k, v in raw_artifacts.items():
            if isinstance(v, ArtifactRecord):
                artifacts[k] = v
            elif isinstance(v, dict):
                artifacts[k] = ArtifactRecord.from_dict(v)
            else:
                artifacts[k] = v
        return cls(
            schema_version=d.get("schema_version", "evidence_manifest_v2"),
            run_id=str(d.get("run_id", "")),
            case_id=str(d.get("case_id", "")),
            created_at=str(d.get("created_at", "")),
            environment=dict(d.get("environment", {})),
            intent_summary=dict(d.get("intent_summary", {})),
            required_results=dict(d.get("required_results", {})),
            artifacts=artifacts,
            verification=dict(d.get("verification", {})),
            acceptance=dict(d.get("acceptance", {})),
            provenance=dict(d.get("provenance", {})),
            validity=str(d.get("validity", "VALID")),
            audit_signature=str(d.get("audit_signature", "")),
            metadata=dict(d.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "EvidenceManifestV2":
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class EvidenceVerificationReport:
    """Comprehensive evaluation report of evidence and artifact integrity."""
    valid: bool
    validity: str  # VALID, TAMPERED, INCOMPLETE, STALE
    run_id: str
    expected_run_id: Optional[str] = None
    run_id_matches: bool = True
    stale: bool = False
    age_seconds: Optional[float] = None
    audit_signature_valid: bool = True
    artifact_checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    missing_artifacts: Tuple[str, ...] = ()
    tampered_artifacts: Tuple[str, ...] = ()
    failures: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "validity": self.validity,
            "run_id": self.run_id,
            "expected_run_id": self.expected_run_id,
            "run_id_matches": self.run_id_matches,
            "stale": self.stale,
            "age_seconds": self.age_seconds,
            "audit_signature_valid": self.audit_signature_valid,
            "artifact_checks": dict(self.artifact_checks),
            "missing_artifacts": list(self.missing_artifacts),
            "tampered_artifacts": list(self.tampered_artifacts),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


def build_evidence_manifest_v2(
    run_id: str,
    case_id: str,
    artifacts_dir: Union[Path, str],
    artifact_filenames: Sequence[str],
    intent_summary: Optional[Dict[str, Any]] = None,
    required_results: Optional[Dict[str, Any]] = None,
    verification: Optional[Dict[str, Any]] = None,
    acceptance: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    environment: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
    sign: bool = True,
) -> EvidenceManifestV2:
    """Build and sign an EvidenceManifestV2 scanning concrete files on disk."""
    base = Path(artifacts_dir)
    artifacts: Dict[str, ArtifactRecord] = {}

    for fname in artifact_filenames:
        fpath = base / fname if not Path(fname).is_absolute() else Path(fname)
        exists = fpath.is_file()
        size_bytes = fpath.stat().st_size if exists else 0
        sha = compute_file_sha256(fpath) if exists else ""
        mtime = fpath.stat().st_mtime if exists else None
        role = infer_artifact_role(fname)
        is_mandatory = role in DEFAULT_MANDATORY_ROLES

        artifacts[fname] = ArtifactRecord(
            name=fname,
            path=str(fname),
            role=role,
            exists=exists,
            size_bytes=size_bytes,
            sha256=sha or "",
            modified_time=mtime,
            mandatory=is_mandatory,
        )

    env = dict(environment or {})
    env.setdefault("os", "windows")
    env.setdefault("solver_version", "Abaqus 2025")
    env.setdefault("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())

    iso_created = created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

    manifest = EvidenceManifestV2(
        schema_version="evidence_manifest_v2",
        run_id=run_id,
        case_id=case_id,
        created_at=iso_created,
        environment=env,
        intent_summary=dict(intent_summary or {}),
        required_results=dict(required_results or {}),
        artifacts=artifacts,
        verification=dict(verification or {}),
        acceptance=dict(acceptance or {}),
        provenance=dict(provenance or {}),
        validity="VALID",
        metadata=dict(metadata or {}),
    )

    if sign:
        manifest = manifest.with_signature()

    return manifest


def verify_evidence_integrity(
    manifest: Union[EvidenceManifestV2, Dict[str, Any]],
    base_dir: Optional[Union[Path, str]] = None,
    expected_run_id: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    mandatory_roles: Optional[Sequence[str]] = DEFAULT_MANDATORY_ROLES,
    check_signature: bool = True,
) -> EvidenceVerificationReport:
    """Deterministically verify the physical and cryptographic integrity of an evidence manifest.

    Validates:
    1. Signature validity (if present and check_signature=True)
    2. Run Identity Binding (rejects run_id mismatch against expected_run_id)
    3. Freshness / Anti-Stale check (validates age against max_age_seconds)
    4. Artifact physical existence on disk
    5. Artifact live SHA-256 hash match against manifest values
    6. Presence of mandatory artifact roles (inp, odb, msg, dat, sta, log)
    """
    if isinstance(manifest, dict):
        manifest_obj = EvidenceManifestV2.from_dict(manifest)
    else:
        manifest_obj = manifest

    failures: List[str] = []
    warnings: List[str] = []
    missing_artifacts: List[str] = []
    tampered_artifacts: List[str] = []
    artifact_checks: Dict[str, Dict[str, Any]] = {}

    current_validity = "VALID"

    # Check for legacy schema or explicit deprecation for RC
    is_legacy = False
    if isinstance(manifest, dict):
        if manifest.get("manifest_version") == "1.0":
            is_legacy = True
        elif manifest.get("schema_version") not in (None, "evidence_manifest_v2"):
            is_legacy = True
        if manifest.get("rc_evidence_eligible") is False:
            is_legacy = True
    else:
        if getattr(manifest, "schema_version", "evidence_manifest_v2") != "evidence_manifest_v2":
            is_legacy = True
        if getattr(manifest, "rc_evidence_eligible", True) is False:
            is_legacy = True

    if is_legacy:
        failures.append("unsupported_legacy_manifest:schema_v1_deprecated_for_rc")
        return EvidenceVerificationReport(
            valid=False,
            validity="INCOMPLETE",
            run_id=getattr(manifest_obj, "run_id", "") or (manifest.get("run_id", "") if isinstance(manifest, dict) else ""),
            failures=tuple(failures),
        )

    # Pre-declared validity check
    if manifest_obj.validity == "TAMPERED":
        failures.append("evidence_tampered:manifest_declared_tampered")
        current_validity = "TAMPERED"
    elif manifest_obj.validity == "INCOMPLETE":
        failures.append("evidence_incomplete:manifest_declared_incomplete")
        current_validity = "INCOMPLETE"
    elif manifest_obj.validity == "STALE":
        failures.append("evidence_stale:manifest_declared_stale")
        current_validity = "STALE"

    # 1. Cryptographic Audit Signature Check
    sig_valid = True
    if check_signature:
        if not manifest_obj.audit_signature:
            sig_valid = False
            failures.append("evidence_unsigned:manifest_audit_signature_missing")
            if current_validity == "VALID":
                current_validity = "INCOMPLETE"
        elif not manifest_obj.verify_signature():
            sig_valid = False
            failures.append("evidence_tampered:manifest_signature_mismatch")
            current_validity = "TAMPERED"

    # 2. Run Identity Binding Check
    run_id_matches = True
    if expected_run_id is not None:
        if manifest_obj.run_id != expected_run_id:
            run_id_matches = False
            failures.append(f"evidence_stale:run_id_mismatch:{manifest_obj.run_id}_expected_{expected_run_id}")
            if current_validity == "VALID":
                current_validity = "STALE"

    # 3. Freshness / Anti-Stale Check
    is_stale = not run_id_matches
    age_seconds: Optional[float] = None
    if max_age_seconds is not None and manifest_obj.created_at:
        try:
            # Handle ISO string with or without Z
            created_str = manifest_obj.created_at.replace("Z", "+00:00")
            created_dt = datetime.datetime.fromisoformat(created_str)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            age_seconds = max(0.0, (now_dt - created_dt).total_seconds())
            if age_seconds > max_age_seconds:
                is_stale = True
                failures.append(f"evidence_stale:timestamp_expired:{age_seconds:.1f}s_exceeds_{max_age_seconds:.1f}s")
                if current_validity == "VALID":
                    current_validity = "STALE"
        except Exception as exc:
            warnings.append(f"timestamp_parse_error:{exc}")

    # 4. Physical Artifact Integrity & Live Hash Check
    for name, art in manifest_obj.artifacts.items():
        p = Path(art.path)
        if not p.is_absolute():
            if base_dir is not None:
                p = Path(base_dir) / art.path
            else:
                p = Path.cwd() / art.path

        if not p.is_file():
            missing_artifacts.append(name)
            is_mandatory = art.mandatory or (mandatory_roles and art.role in mandatory_roles)
            if is_mandatory:
                failures.append(f"evidence_incomplete:missing_artifact:{name}")
                if current_validity == "VALID":
                    current_validity = "INCOMPLETE"
            else:
                warnings.append(f"optional_artifact_missing:{name}")
            artifact_checks[name] = {
                "exists": False,
                "role": art.role,
                "expected_sha256": art.sha256,
                "actual_sha256": None,
                "matched": False,
            }
        else:
            live_sha = compute_file_sha256(p)
            live_size = p.stat().st_size
            matched = (live_sha == art.sha256)
            artifact_checks[name] = {
                "exists": True,
                "size_bytes": live_size,
                "role": art.role,
                "expected_sha256": art.sha256,
                "actual_sha256": live_sha,
                "matched": matched,
            }
            # Layer 1 Probe: ODB artifact quick sanity checks (rejection of obvious corrupt/fake artifacts)
            if art.role == "odb":
                if live_size == 0:
                    failures.append(f"corrupt_artifact:odb_file_empty:{name}")
                    current_validity = "EVIDENCE_CORRUPT"
                else:
                    try:
                        with open(p, "rb") as bf:
                            sample = bf.read(128).strip()
                        if sample.startswith(b"{") or sample.startswith(b"["):
                            failures.append(f"corrupt_artifact:odb_is_plaintext_json:{name}")
                            current_validity = "EVIDENCE_CORRUPT"
                        elif sample.startswith((b"#!", b"import ", b"from ", b"def ", b"print(")):
                            failures.append(f"corrupt_artifact:odb_is_script:{name}")
                            current_validity = "EVIDENCE_CORRUPT"
                    except Exception:
                        pass

            if not matched:
                tampered_artifacts.append(name)
                failures.append(f"evidence_tampered:sha256_mismatch:{name}")
                failures.append(f"evidence_tampered:hash_mismatch:{name}")
                current_validity = "TAMPERED"

    # 5. Mandatory Roles Completeness Check
    if mandatory_roles:
        matching_roles = {
            c["role"] for c in artifact_checks.values()
            if c.get("exists") and c.get("matched")
        }
        for req_role in mandatory_roles:
            if req_role not in matching_roles:
                failures.append(f"evidence_incomplete:missing_mandatory_role:{req_role}")
                if current_validity == "VALID":
                    current_validity = "INCOMPLETE"

    valid = (len(failures) == 0)
    final_validity = "VALID" if valid else current_validity

    return EvidenceVerificationReport(
        valid=valid,
        validity=final_validity,
        run_id=manifest_obj.run_id,
        expected_run_id=expected_run_id,
        run_id_matches=run_id_matches,
        stale=is_stale,
        age_seconds=age_seconds,
        audit_signature_valid=sig_valid,
        artifact_checks=artifact_checks,
        missing_artifacts=tuple(missing_artifacts),
        tampered_artifacts=tuple(tampered_artifacts),
        failures=tuple(failures),
        warnings=tuple(warnings),
    )
