"""Case Memory and Run Index over AnalysisRun instances."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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

    def export_manifest(self, manifest_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """Export a lightweight summary manifest of all indexed runs."""
        manifest = {
            "total_runs": len(self.runs),
            "runs": [
                {
                    "id": getattr(r, "id", ""),
                    "model_name": getattr(r, "model_name", ""),
                    "job_name": getattr(r, "job_name", ""),
                    "solver": getattr(r, "solver", "standard"),
                    "state": getattr(getattr(r, "state", None), "value", str(getattr(r, "state", ""))),
                    "engineering_status": getattr(r, "engineering_status", None),
                    "acceptance_passed": getattr(r, "acceptance_passed", None),
                    "metrics_count": len(getattr(r, "metrics", ()) or ()),
                    "report_reference": getattr(r, "report_reference", None),
                }
                for r in sorted(self.runs.values(), key=lambda x: str(getattr(x, "id", "")))
            ],
        }
        if manifest_path:
            p = Path(manifest_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        return manifest

    def save_to_directory(self, dir_path: Union[str, Path], save_manifest: bool = True) -> int:
        """Persist all indexed runs as individual JSON records in dir_path."""
        p = Path(dir_path)
        p.mkdir(parents=True, exist_ok=True)
        count = 0
        for run_id, run in self.runs.items():
            run_data = run.to_dict() if hasattr(run, "to_dict") else dict(run)
            safe_id = "".join(c if (c.isalnum() or c in ("-", "_", ".")) else "_" for c in str(run_id))
            file_path = p / f"{safe_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(run_data, f, indent=2, ensure_ascii=False)
            count += 1

        if save_manifest:
            self.export_manifest(p / "manifest.json")
        return count

    def load_from_directory(self, dir_path: Union[str, Path]) -> int:
        """Scan and restore AnalysisRun instances from a directory of JSON records."""
        from .execution.analysis_run import AnalysisRun

        p = Path(dir_path)
        if not p.is_dir():
            return 0

        loaded = 0
        for item in sorted(p.glob("*.json")):
            if item.name == "manifest.json":
                continue
            try:
                with open(item, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "id" in data:
                    run = AnalysisRun.from_dict(data)
                    self.add_run(run)
                    loaded += 1
            except Exception:
                continue
        return loaded
