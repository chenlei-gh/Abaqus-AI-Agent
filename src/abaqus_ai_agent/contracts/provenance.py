import dataclasses
import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

AGENT_ISSUER = "abaqus-ai-agent"
DELIVERY_STAMP_SCHEMA = "agent_run_stamp_v1"


@dataclass(frozen=True)
class AnalysisProvenance:
    """Reproducibility metadata for one analysis run."""
    run_id: str
    model_name: str
    job_name: str
    model_hash: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    artifact_manifest_hash: Optional[str] = None
    intent_hash: Optional[str] = None
    action_plan_hash: Optional[str] = None
    abaqus_version: Optional[str] = None
    python_version: Optional[str] = None
    executor: Optional[str] = None
    action_plan: Tuple[Dict[str, Any], ...] = ()
    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_name": self.model_name,
            "job_name": self.job_name,
            "model_hash": self.model_hash,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "intent_hash": self.intent_hash,
            "action_plan_hash": self.action_plan_hash,
            "abaqus_version": self.abaqus_version,
            "python_version": self.python_version,
            "executor": self.executor,
            "action_plan": list(self.action_plan),
            "environment": dict(self.environment),
            "metadata": dict(self.metadata),
        }

    def replace(self, **changes) -> "AnalysisProvenance":
        """Return a copy, preserving fields that callers do not override."""
        return replace(self, **changes)


def _stamp_payload(provenance: AnalysisProvenance, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Canonical payload for an Agent issuance record.

    This is a content digest of the run record, not a keyed signature.
    An attacker who can rewrite the file can also recompute the digest.
    The product gate is: a formal report may only cite a record the Agent issued.
    """
    meta = dict(provenance.metadata if metadata is None else metadata)
    return {
        "schema": DELIVERY_STAMP_SCHEMA,
        "issued_by": AGENT_ISSUER,
        "run_id": provenance.run_id,
        "model_name": provenance.model_name,
        "job_name": provenance.job_name,
        "executor": provenance.executor,
        "input_hash": provenance.input_hash,
        "output_hash": provenance.output_hash,
        "entry": meta.get("agent_entry") or "analysis_runner",
        "jev_routed": bool(meta.get("jev_routed")),
        "jev_mode": meta.get("jev_mode"),
        "requirement_kind": meta.get("requirement_kind") or "unspecified",
        "model_snapshot_hash": meta.get("model_snapshot_hash"),
        "content_hash_scope": meta.get("content_hash_scope"),
        "action_plan_scope": meta.get("action_plan_scope"),
    }


def compute_delivery_stamp(provenance: AnalysisProvenance, metadata: Optional[Dict[str, Any]] = None) -> str:
    payload = json.dumps(_stamp_payload(provenance, metadata), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def attach_delivery_stamp(provenance: Optional[AnalysisProvenance]) -> Optional[AnalysisProvenance]:
    """Mark a run as issued by the Agent runtime and bind the current hashes."""
    if provenance is None:
        return None
    meta = dict(provenance.metadata)
    meta["agent_issued"] = True
    meta["issued_by"] = AGENT_ISSUER
    meta.pop("delivery_stamp", None)
    stamped = provenance.replace(metadata=meta)
    digest = compute_delivery_stamp(stamped)
    meta["delivery_stamp"] = digest
    meta["delivery_stamp_schema"] = DELIVERY_STAMP_SCHEMA
    return stamped.replace(metadata=meta)


def issue_agent_run_record(
    *,
    run_id: str,
    model_name: str,
    job_name: str,
    input_hash: Optional[str] = None,
    output_hash: Optional[str] = None,
    executor: str = "qualification_script",
    jev_routed: bool = False,
    requirement_kind: str = "engineering_intent",
    agent_entry: str = "qualification_script",
    jev_mode: Optional[str] = None,
    model_snapshot_hash: Optional[str] = None,
    content_hash_scope: Optional[str] = None,
    action_plan_scope: Optional[str] = None,
) -> AnalysisProvenance:
    """Issue a programmatic Agent run record bound to the current hashes.

    This is not a keyed signature. ``jev_routed`` records that a natural-language
    request passed the product router. It does not certify the parse, the model,
    the solve, or engineering acceptance. A qualification script may file an
    engineering-intent record, but must not be captioned as JEV-routed.
    """
    provenance = AnalysisProvenance(
        run_id=str(run_id),
        model_name=str(model_name),
        job_name=str(job_name),
        input_hash=input_hash,
        output_hash=output_hash,
        executor=executor,
        metadata={
            "agent_issued": True,
            "issued_by": AGENT_ISSUER,
            "agent_entry": agent_entry,
            "jev_routed": bool(jev_routed),
            "jev_mode": jev_mode,
            "requirement_kind": requirement_kind,
            "model_snapshot_hash": model_snapshot_hash,
            "content_hash_scope": content_hash_scope,
            "action_plan_scope": action_plan_scope,
        },
    )
    return attach_delivery_stamp(provenance)


def _execution_fingerprint_gaps(metadata: Dict[str, Any]) -> Tuple[str, ...]:
    """Return the fingerprints a formal attribution must carry.

    ``agent_issued`` is a claim. These three values are what makes that claim
    point at one model snapshot, one hashed content scope, and one action-plan
    scope. A missing value cannot be filled in by the gate.
    """
    required = {
        "model_snapshot_hash": "missing_model_snapshot_hash",
        "content_hash_scope": "missing_content_hash_scope",
        "action_plan_scope": "missing_action_plan_scope",
    }
    gaps = []
    for key, code in required.items():
        value = str(metadata.get(key) or "").strip()
        if not value or value.lower() in {"none", "null"}:
            gaps.append(code)
    return tuple(gaps)


def provenance_from_mapping(raw: Any) -> Optional[AnalysisProvenance]:
    """Rebuild provenance from a dict without dropping issuance fields."""
    if isinstance(raw, AnalysisProvenance):
        return raw
    if not isinstance(raw, dict):
        return None
    return AnalysisProvenance(
        run_id=str(raw.get("run_id") or ""),
        model_name=str(raw.get("model_name") or ""),
        job_name=str(raw.get("job_name") or ""),
        model_hash=raw.get("model_hash"),
        input_hash=raw.get("input_hash"),
        output_hash=raw.get("output_hash"),
        artifact_manifest_hash=raw.get("artifact_manifest_hash"),
        intent_hash=raw.get("intent_hash"),
        action_plan_hash=raw.get("action_plan_hash"),
        abaqus_version=raw.get("abaqus_version"),
        python_version=raw.get("python_version"),
        executor=raw.get("executor"),
        action_plan=tuple(raw.get("action_plan") or ()),
        environment=dict(raw.get("environment") or {}),
        metadata=dict(raw.get("metadata") or {}),
    )


def build_delivery_record(
    *,
    provenance: Any = None,
    results: Any = None,
    odb_path: Any = None,
    odb_sha256: Optional[str] = None,
    acceptance: Any = None,
    condition_fidelity: Any = None,
    figures: Any = None,
    require_preprocessing_figures: Any = False,
    model_contract_mismatch: Any = None,
) -> Dict[str, Any]:
    """Build the single authorization input shared by every delivery path.

    CLI, the deterministic pipeline, and the file-write gate must all call this
    function. Keeping one constructor is what makes "the same evidence" mean the
    same thing on every path; building the dict ad hoc is how the fidelity
    blocker was silently dropped before.
    """
    issued = provenance_from_mapping(provenance)
    record: Dict[str, Any] = {
        "provenance": issued.to_dict() if issued is not None else None,
        "results": list(results or ()),
        "odb_path": str(odb_path) if odb_path else None,
        "odb_sha256": odb_sha256,
    }
    if acceptance is not None:
        record["acceptance"] = _acceptance_payload(acceptance)
    if condition_fidelity is not None:
        record["condition_fidelity"] = _fidelity_payload(condition_fidelity)
    if figures is not None:
        record["figures"] = [_figure_payload(item) for item in figures if item is not None]
    if require_preprocessing_figures:
        record["require_preprocessing_figures"] = True
        if isinstance(require_preprocessing_figures, (list, tuple)):
            record["required_preprocessing_figures"] = [
                str(kind) for kind in require_preprocessing_figures
            ]
    if model_contract_mismatch:
        record["model_contract_mismatch"] = model_contract_mismatch
    return record


def _acceptance_payload(acceptance: Any) -> Any:
    if isinstance(acceptance, dict):
        return dict(acceptance)
    if hasattr(acceptance, "to_dict"):
        return acceptance.to_dict()
    payload = {}
    for key in ("status", "acceptance_status", "deliverable", "passed", "result_validity"):
        if hasattr(acceptance, key):
            payload[key] = getattr(acceptance, key)
    return payload or None


def _figure_payload(figure: Any) -> Dict[str, Any]:
    if isinstance(figure, dict):
        return dict(figure)
    if hasattr(figure, "to_dict"):
        payload = figure.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    if dataclasses.is_dataclass(figure):
        return dataclasses.asdict(figure)
    return {
        key: getattr(figure, key)
        for key in ("kind", "visualization_type", "path", "caption", "source", "metadata")
        if hasattr(figure, key)
    }


def _fidelity_payload(fidelity: Any) -> Any:
    if isinstance(fidelity, dict):
        return dict(fidelity)
    if hasattr(fidelity, "to_dict"):
        return fidelity.to_dict()
    return fidelity


def verify_deliverable(record: Any, *, require_decision_inputs: bool = False) -> Dict[str, Any]:
    """Decide whether a JSON record may be written as an Agent engineering report.

    BLOCKED means the product must not write a deliverable and must not claim
    "Abaqus-AI-Agent \u7f16\u5236". A matching digest is tamper-evidence for an
    unsynced edit, not proof that a privileged signer produced the file.

    require_decision_inputs makes a missing engineering verdict fatal: a report
    with no acceptance verdict and no fidelity verdict cannot be authorized by
    defaulting those to "fine". Callers on the formal-delivery path pass True.
    """
    payload = record if isinstance(record, dict) else {}
    provenance = provenance_from_mapping(payload.get("provenance") if isinstance(payload, dict) else None)
    if provenance is None and isinstance(payload.get("report"), dict):
        provenance = provenance_from_mapping(payload["report"].get("provenance"))
    reasons = []
    if provenance is None:
        reasons.append("missing_agent_run_record")
    else:
        meta = dict(provenance.metadata or {})
        stamp = meta.get("delivery_stamp")
        if not meta.get("agent_issued") or not stamp:
            reasons.append("missing_agent_run_stamp")
        elif meta.get("issued_by") != AGENT_ISSUER:
            reasons.append("issuer_is_not_agent")
        else:
            expected = compute_delivery_stamp(provenance)
            if stamp != expected:
                reasons.append("run_stamp_mismatch")
            if require_decision_inputs:
                reasons.extend(_execution_fingerprint_gaps(meta))
        results = payload.get("results") or payload.get("metrics") or []
        # A path string is not a binding. Results may be filed only when the
        # Agent record itself carries the ODB content hash.
        if results and not provenance.output_hash:
            reasons.append("results_not_bound_to_odb")
        recorded_odb = payload.get("odb_sha256") or payload.get("output_hash")
        if recorded_odb and provenance.output_hash and str(recorded_odb) != str(provenance.output_hash):
            reasons.append("odb_hash_mismatch")

    meta = dict(provenance.metadata) if provenance is not None else {}
    jev_routed = bool(meta.get("jev_routed"))
    requirement_kind = meta.get("requirement_kind") or "unspecified"
    allow_file = not reasons
    # A natural-language file must show that it passed the product router.
    # jev_routed is path evidence only: it does not approve the parse, the
    # constraints, the solve, or the engineering acceptance. A programmatic
    # EngineeringIntent may be filed, but must not be captioned as JEV-routed.
    allow_agent_attribution = allow_file and jev_routed
    if allow_file and requirement_kind == "natural_language" and not jev_routed:
        reasons.append("natural_language_requirement_not_jev_routed")
        allow_file = False
        allow_agent_attribution = False
    fidelity = payload.get("condition_fidelity") if isinstance(payload, dict) else None
    if isinstance(fidelity, dict) and fidelity.get("blockers"):
        reasons.extend("condition_fidelity:" + str(item) for item in fidelity.get("blockers") or ())
        allow_file = False
        allow_agent_attribution = False
    elif isinstance(payload, dict) and payload.get("formal_report_allowed") is False:
        reasons.append("condition_fidelity_blocks_formal_report")
        allow_file = False
        allow_agent_attribution = False
    missing_figures = payload.get("missing_preprocessing_figures") if isinstance(payload, dict) else None
    if missing_figures:
        reasons.append("formal_report_missing_preprocessing_figures:" + ",".join(str(item) for item in missing_figures))
        allow_file = False
        allow_agent_attribution = False
    elif isinstance(payload, dict) and payload.get("require_preprocessing_figures"):
        from ..validation.condition_fidelity import required_formal_figure_kinds
        declared = payload.get("required_preprocessing_figures")
        # A caller that names the figures it claims is checked against exactly
        # those. The full preprocessing set applies only when the record says
        # "preprocessing figures are required" without naming any.
        required_kinds = tuple(str(kind) for kind in declared) if declared else required_formal_figure_kinds()
        present = {
            str(item.get("kind") or item.get("visualization_type") or "").strip().lower()
            for item in (payload.get("figures") or ())
            if isinstance(item, dict) and (item.get("path") or item.get("embedded"))
        }
        absent = [kind for kind in required_kinds if kind not in present]
        if absent:
            reasons.append("formal_report_missing_preprocessing_figures:" + ",".join(absent))
            allow_file = False
            allow_agent_attribution = False

    acceptance = payload.get("acceptance") if isinstance(payload, dict) else None
    if isinstance(acceptance, dict) and acceptance.get("deliverable") is not True:
        reasons.append("acceptance_not_granted")
        allow_file = False
        allow_agent_attribution = False
    elif isinstance(payload, dict) and payload.get("model_contract_mismatch"):
        reasons.append("model_contract_mismatch")
        allow_file = False
        allow_agent_attribution = False

    if require_decision_inputs:
        # Absent evidence is not passing evidence. These two verdicts decide the
        # engineering question; without them the run is only a diagnostic draft.
        if not isinstance(acceptance, dict) or not acceptance:
            reasons.append("missing_acceptance_verdict")
            allow_file = False
            allow_agent_attribution = False
        if not isinstance(fidelity, dict) or not fidelity:
            reasons.append("missing_condition_fidelity")
            allow_file = False
            allow_agent_attribution = False

    status = "PASS" if allow_file else "BLOCKED"
    return {
        "status": status,
        "deliverable_file_allowed": allow_file,
        "allow_agent_attribution": allow_agent_attribution,
        "jev_routed": jev_routed,
        "requirement_kind": requirement_kind,
        "reasons": reasons,
        "guarantee": "agent_run_record",
        "not_a_keyed_signature": True,
    }
