"""Case Memory and Run Index over AnalysisRun instances."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .analysis_run_diff import diff_analysis_runs, AnalysisRunDiff


@dataclass
class RunIndex:
    """Deterministic in-memory and searchable index for AnalysisRun records."""
    runs: Dict[str, Any] = field(default_factory=dict)

    def add_run(self, run: Any) -> None:
        """Index a completed AnalysisRun."""
        run_id = getattr(run, "id", None)
        if not run_id:
            raise ValueError("AnalysisRun must have an id to be indexed")
        self.runs[run_id] = run

    def get_run(self, run_id: str) -> Optional[Any]:
        return self.runs.get(run_id)

    def search_runs(
        self,
        solver: Optional[str] = None,
        engineering_status: Optional[str] = None,
        acceptance_passed: Optional[bool] = None,
        has_metric: Optional[str] = None,
        min_metric_value: Optional[float] = None,
        max_metric_value: Optional[float] = None,
    ) -> List[Any]:
        """Filter indexed runs by engineering criteria."""
        results = []
        for run in self.runs.values():
            if solver is not None and getattr(run, "solver", None) != solver:
                continue
            if engineering_status is not None and getattr(run, "engineering_status", None) != engineering_status:
                continue
            if acceptance_passed is not None and getattr(run, "acceptance_passed", None) != acceptance_passed:
                continue
            if has_metric is not None:
                val = getattr(run, "get_metric", lambda k: None)(has_metric)
                if val is None:
                    continue
                if min_metric_value is not None and val < min_metric_value:
                    continue
                if max_metric_value is not None and val > max_metric_value:
                    continue
            results.append(run)
        return results

    def compare_runs(self, baseline_id: str, candidate_id: str) -> AnalysisRunDiff:
        """Run-level deterministic diff between two indexed runs."""
        base = self.get_run(baseline_id)
        if not base:
            raise KeyError("baseline run '%s' not found in index" % baseline_id)
        cand = self.get_run(candidate_id)
        if not cand:
            raise KeyError("candidate run '%s' not found in index" % candidate_id)
        return diff_analysis_runs(base, cand)

    def browse_evidence(self, run_id: str) -> Dict[str, Any]:
        """Provide a structured, traceable view of a run's engineering evidence."""
        run = self.get_run(run_id)
        if not run:
            raise KeyError("run '%s' not found in index" % run_id)
        return {
            "run_id": run_id,
            "solver": getattr(run, "solver", None),
            "state": getattr(run, "state", None),
            "engineering_status": getattr(run, "engineering_status", None),
            "acceptance_passed": getattr(run, "acceptance_passed", None),
            "artifacts": list(getattr(run, "artifacts", ()) or ()),
            "metrics": [
                getattr(m, "to_dict", lambda: str(m))()
                if hasattr(m, "to_dict") else str(m)
                for m in getattr(run, "metrics", ()) or ()
            ],
            "provenance": getattr(run, "provenance", None).to_dict()
            if hasattr(getattr(run, "provenance", None), "to_dict") else None,
            "evidence_package": getattr(run, "to_evidence_package", lambda: {})(),
        }
