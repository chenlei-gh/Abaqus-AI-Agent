"""Deterministic comparison between two AnalysisRun instances."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .state_diff import diff_snapshots
from .contracts.model_snapshot import ModelSnapshot


@dataclass(frozen=True)
class MetricDelta:
    name: str
    baseline_value: Optional[float]
    candidate_value: Optional[float]
    delta: Optional[float]
    relative_change: Optional[float]
    unit: str = ""


@dataclass(frozen=True)
class AnalysisRunDiff:
    baseline_id: str
    candidate_id: str
    solver_changed: bool
    solver_diff: Dict[str, Any]
    intent_changed: bool
    intent_diff: Dict[str, Any]
    assumptions_added: Tuple[str, ...]
    assumptions_removed: Tuple[str, ...]
    snapshot_diff: Optional[Dict[str, Any]]
    metrics_diff: Dict[str, MetricDelta]
    acceptance_changed: bool
    acceptance_diff: Dict[str, Any]
    artifacts_added: Tuple[str, ...]
    artifacts_removed: Tuple[str, ...]
    provenance_diff: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "candidate_id": self.candidate_id,
            "solver_changed": self.solver_changed,
            "solver_diff": self.solver_diff,
            "intent_changed": self.intent_changed,
            "intent_diff": self.intent_diff,
            "assumptions_added": list(self.assumptions_added),
            "assumptions_removed": list(self.assumptions_removed),
            "snapshot_diff": self.snapshot_diff,
            "metrics_diff": {
                k: {
                    "name": v.name,
                    "baseline_value": v.baseline_value,
                    "candidate_value": v.candidate_value,
                    "delta": v.delta,
                    "relative_change": v.relative_change,
                    "unit": v.unit,
                }
                for k, v in self.metrics_diff.items()
            },
            "acceptance_changed": self.acceptance_changed,
            "acceptance_diff": self.acceptance_diff,
            "artifacts_added": list(self.artifacts_added),
            "artifacts_removed": list(self.artifacts_removed),
            "provenance_diff": self.provenance_diff,
            "metadata": dict(self.metadata),
        }


def diff_analysis_runs(baseline, candidate) -> AnalysisRunDiff:
    """Compute a deterministic, inspectable diff between two AnalysisRuns."""
    base_id = getattr(baseline, "id", "") or "baseline"
    cand_id = getattr(candidate, "id", "") or "candidate"

    # 1. Solver
    base_solver = getattr(baseline, "solver", None)
    cand_solver = getattr(candidate, "solver", None)
    solver_changed = base_solver != cand_solver
    solver_diff = {"baseline": str(base_solver), "candidate": str(cand_solver)} if solver_changed else {}

    # 2. Intent
    base_intent = getattr(baseline, "intent", None)
    cand_intent = getattr(candidate, "intent", None)
    intent_changed = False
    intent_diff = {}
    if base_intent != cand_intent:
        intent_changed = True
        intent_diff = {
            "baseline": base_intent.to_dict() if hasattr(base_intent, "to_dict") else str(base_intent),
            "candidate": cand_intent.to_dict() if hasattr(cand_intent, "to_dict") else str(cand_intent),
        }

    # 3. Assumptions
    base_assumptions = set(getattr(baseline, "assumptions", ()) or ())
    cand_assumptions = set(getattr(candidate, "assumptions", ()) or ())
    assumptions_added = tuple(sorted(cand_assumptions - base_assumptions))
    assumptions_removed = tuple(sorted(base_assumptions - cand_assumptions))

    # 4. Model Snapshot
    base_snap = getattr(baseline, "model_snapshot", None)
    cand_snap = getattr(candidate, "model_snapshot", None)
    snapshot_diff_dict = None
    if isinstance(base_snap, ModelSnapshot) and isinstance(cand_snap, ModelSnapshot):
        delta = diff_snapshots(base_snap, cand_snap)
        snapshot_diff_dict = {
            "added": delta.added,
            "removed": delta.removed,
            "changed_metadata": delta.changed_metadata,
        }

    # 5. Metrics
    base_metrics = {getattr(m, "name", str(m)): m for m in getattr(baseline, "metrics", ()) or ()}
    cand_metrics = {getattr(m, "name", str(m)): m for m in getattr(candidate, "metrics", ()) or ()}
    all_metric_names = sorted(set(base_metrics.keys()) | set(cand_metrics.keys()))
    metrics_diff = {}
    for name in all_metric_names:
        bm = base_metrics.get(name)
        cm = cand_metrics.get(name)
        bv = getattr(bm, "value", None) if bm is not None else None
        cv = getattr(cm, "value", None) if cm is not None else None
        unit = getattr(cm or bm, "unit", "")

        delta = None
        rel_change = None
        if bv is not None and cv is not None:
            delta = float(cv - bv)
            if abs(bv) > 1e-30:
                rel_change = float(delta / abs(bv))
        metrics_diff[name] = MetricDelta(
            name=name,
            baseline_value=bv,
            candidate_value=cv,
            delta=delta,
            relative_change=rel_change,
            unit=unit,
        )

    # 6. Acceptance
    base_acc_passed = getattr(baseline, "acceptance_passed", None)
    cand_acc_passed = getattr(candidate, "acceptance_passed", None)
    base_status = getattr(baseline, "engineering_status", "")
    cand_status = getattr(candidate, "engineering_status", "")
    acceptance_changed = (base_acc_passed != cand_acc_passed) or (base_status != cand_status)
    acceptance_diff = {
        "baseline": {"passed": base_acc_passed, "status": base_status},
        "candidate": {"passed": cand_acc_passed, "status": cand_status},
    }

    # 7. Artifacts
    base_art = set(getattr(baseline, "artifacts", ()) or ())
    cand_art = set(getattr(candidate, "artifacts", ()) or ())
    artifacts_added = tuple(sorted(cand_art - base_art))
    artifacts_removed = tuple(sorted(base_art - cand_art))

    # 8. Provenance
    base_prov = getattr(baseline, "provenance", None)
    cand_prov = getattr(candidate, "provenance", None)
    prov_diff = {}
    if base_prov and cand_prov:
        for field_name in ("model_hash", "input_hash", "output_hash", "action_plan_hash", "intent_hash"):
            bv = getattr(base_prov, field_name, None)
            cv = getattr(cand_prov, field_name, None)
            if bv != cv:
                prov_diff[field_name] = {"baseline": bv, "candidate": cv}

    return AnalysisRunDiff(
        baseline_id=base_id,
        candidate_id=cand_id,
        solver_changed=solver_changed,
        solver_diff=solver_diff,
        intent_changed=intent_changed,
        intent_diff=intent_diff,
        assumptions_added=assumptions_added,
        assumptions_removed=assumptions_removed,
        snapshot_diff=snapshot_diff_dict,
        metrics_diff=metrics_diff,
        acceptance_changed=acceptance_changed,
        acceptance_diff=acceptance_diff,
        artifacts_added=artifacts_added,
        artifacts_removed=artifacts_removed,
        provenance_diff=prov_diff,
    )
