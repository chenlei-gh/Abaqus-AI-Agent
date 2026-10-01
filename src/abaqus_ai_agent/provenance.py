import hashlib
import json


def stable_hash(value):
    """Return a deterministic SHA-256 hash for JSON-compatible values."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def build_reproducibility_manifest(provenance, artifacts=()):
    """Build a deterministic manifest from available run metadata.

    This intentionally hashes metadata rather than pretending that model,
    input or ODB bytes were captured when they were not.
    """
    if provenance is None:
        raise ValueError("provenance is required")
    artifact_items = tuple(
        {
            "suffix": getattr(a, "suffix", ""),
            "path": getattr(a, "path", ""),
            "exists": bool(getattr(a, "exists", False)),
            "size": getattr(a, "size", None),
            "modified_time": getattr(a, "modified_time", None),
        }
        for a in artifacts or ()
    )
    manifest = {
        "run_id": provenance.run_id,
        "model_name": provenance.model_name,
        "job_name": provenance.job_name,
        "model_hash": provenance.model_hash,
        "input_hash": provenance.input_hash,
        "output_hash": provenance.output_hash,
        "abaqus_version": provenance.abaqus_version,
        "python_version": provenance.python_version,
        "executor": provenance.executor,
        "action_plan": tuple(provenance.action_plan),
        "environment": dict(provenance.environment),
        "metadata": dict(provenance.metadata),
        "artifacts": artifact_items,
    }
    return {
        "manifest": manifest,
        "manifest_hash": stable_hash(manifest),
        "content_hashes_available": bool(
            provenance.model_hash or provenance.input_hash or provenance.output_hash
        ),
    }
