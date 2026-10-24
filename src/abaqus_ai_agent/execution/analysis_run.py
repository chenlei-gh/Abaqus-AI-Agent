import os
import time
from pathlib import Path
import uuid
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .jobs import JobController, JobState, JobStatus
from ..contracts.solver_selection import SolverSelectionBlocked
from ..engineering_status import EngineeringStatus
from ..evidence.result import summarize_odb
from ..evidence.model import Evidence, EvidenceBundle
from ..contracts.provenance import AnalysisProvenance, attach_delivery_stamp, provenance_from_mapping
from ..provenance import stable_hash
from ..acceptance import evaluate_production_acceptance, evaluate_result_acceptance


class AnalysisRunState(str, Enum):
    CREATED = "created"
    PREFLIGHTED = "preflighted"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    ODB_VALIDATED = "odb_validated"
    RESULTS_EXTRACTED = "results_extracted"
    ACCEPTED = "accepted"
    FAILED = "failed"


@dataclass(frozen=True)
class AnalysisRun:
    id: str
    model_name: str
    job_name: str
    state: AnalysisRunState = AnalysisRunState.CREATED
    job_status: Optional[JobStatus] = None
    odb_path: Optional[str] = None
    engineering_status: Optional[str] = None
    acceptance_passed: Optional[bool] = None
    provenance: Optional[AnalysisProvenance] = None
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    diagnostics: Tuple[Dict[str, Any], ...] = ()
    artifacts: Tuple[Any, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)
    metrics: Tuple[Any, ...] = ()
    intent: Optional[Any] = None
    assumptions: Tuple[str, ...] = ()
    solver_selection: Optional[Any] = None
    postprocess_profile: Optional[Any] = None
    action_plan: Tuple[Any, ...] = ()
    model_snapshot: Optional[Any] = None
    runtime: Optional[Dict[str, Any]] = None

    @property
    def work_dir(self) -> Optional[str]:
        """Convenience property for resolving execution workdir."""
        return self.metadata.get("workdir")
    solver: str = "standard"
    inputs: Tuple[Any, ...] = ()
    outputs: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    acceptance: Optional[Any] = None
    report_reference: Optional[str] = None
    extractions: Tuple[Any, ...] = ()

    def with_state(self, state, **changes):
        values = dict(
            id=self.id, model_name=self.model_name, job_name=self.job_name,
            state=state, job_status=self.job_status, odb_path=self.odb_path,
            engineering_status=self.engineering_status,
            acceptance_passed=self.acceptance_passed, provenance=self.provenance,
            evidence=self.evidence,
            diagnostics=self.diagnostics, artifacts=self.artifacts,
            metadata=dict(self.metadata), metrics=self.metrics,
            intent=self.intent, assumptions=self.assumptions,
            solver_selection=self.solver_selection,
            postprocess_profile=self.postprocess_profile,
            action_plan=self.action_plan, model_snapshot=self.model_snapshot,
            runtime=self.runtime, solver=self.solver, inputs=self.inputs,
            outputs=self.outputs, verification=self.verification,
            acceptance=self.acceptance, report_reference=self.report_reference,
            extractions=self.extractions,
        )
        values.update(changes)
        return AnalysisRun(**values)

    @property
    def solver_completed(self):
        return self.job_status is not None and self.job_status.state == JobState.COMPLETED

    def get_metric(self, name: str) -> Optional[Any]:
        """Look up a metric value by name from extracted metrics."""
        for m in self.metrics:
            if getattr(m, "name", None) == name or getattr(m, "value_key", None) == name:
                return getattr(m, "value", None)
            if isinstance(m, dict) and (m.get("name") == name or m.get("value_key") == name):
                return m.get("value")
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Canonical dictionary representation answering all engineering run questions."""
        return {
            "id": self.id,
            "model_name": self.model_name,
            "job_name": self.job_name,
            "state": self.state.value if hasattr(self.state, "value") else str(self.state),
            "solver": self.solver,
            "solver_completed": self.solver_completed,
            "job_status": str(getattr(self.job_status, "state", self.job_status)) if self.job_status else None,
            "odb_path": self.odb_path,
            "engineering_status": self.engineering_status,
            "acceptance_passed": self.acceptance_passed,
            "intent": getattr(self.intent, "to_dict", lambda: str(self.intent))() if self.intent is not None else None,
            "assumptions": list(self.assumptions),
            "solver_selection": str(self.solver_selection) if self.solver_selection else None,
            "postprocess_profile": str(self.postprocess_profile) if self.postprocess_profile else None,
            "action_plan_count": len(self.action_plan),
            "runtime": dict(self.runtime or {}),
            "inputs": [getattr(i, "to_dict", lambda: str(i))() if hasattr(i, "to_dict") else i for i in self.inputs],
            "outputs": dict(self.outputs) if self.outputs is not None else None,
            "metrics": [getattr(m, "to_dict", lambda: str(m))() if hasattr(m, "to_dict") else m for m in self.metrics],
            "verification": self.verification,
            "acceptance": getattr(self.acceptance, "to_dict", lambda: str(self.acceptance))() if self.acceptance else None,
            "diagnostics": list(self.diagnostics),
            "artifacts_count": len(self.artifacts),
            "artifacts": [getattr(a, "to_dict", lambda: str(a))() if hasattr(a, "to_dict") else str(a) for a in self.artifacts],
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else (self.provenance.__dict__ if self.provenance else None),
            "report_reference": self.report_reference,
            "metadata": dict(self.metadata),
        }

    def to_evidence_package(self) -> Dict[str, Any]:
        """Produce a unified evidence view for audit and acceptance."""
        return {
            "run_id": self.id,
            "job_name": self.job_name,
            "solver": self.solver,
            "solver_status": "completed" if self.solver_completed else "failed",
            "odb_status": "available" if self.odb_path else "missing",
            "engineering_status": self.engineering_status,
            "acceptance_passed": self.acceptance_passed,
            "metrics": [getattr(m, "to_dict", lambda: str(m))() if hasattr(m, "to_dict") else m for m in self.metrics],
            "artifacts": [getattr(a, "to_dict", lambda: str(a))() if hasattr(a, "to_dict") else str(a) for a in self.artifacts],
            "inputs": [getattr(i, "to_dict", lambda: str(i))() if hasattr(i, "to_dict") else i for i in self.inputs],
            "outputs": dict(self.outputs) if self.outputs is not None else None,
            "verification": self.verification or {},
            "acceptance": getattr(self.acceptance, "to_dict", lambda: str(self.acceptance))() if self.acceptance else None,
            "diagnostics": list(self.diagnostics),
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else None,
            "report_reference": self.report_reference,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisRun":
        """Reconstruct an AnalysisRun instance from its serialized dictionary representation."""
        st_val = data.get("state", "created")
        try:
            state = AnalysisRunState(st_val)
        except (ValueError, TypeError):
            state = AnalysisRunState.CREATED

        raw_metrics = data.get("metrics", [])
        parsed_metrics = []
        for m in raw_metrics:
            if isinstance(m, dict):
                from ..contracts.metrics import EngineeringMetric
                parsed_metrics.append(EngineeringMetric(
                    name=m.get("name", "unknown"),
                    value=m.get("value", 0.0),
                    unit=m.get("unit", ""),
                    source=m.get("source", "odb"),
                    quantity=m.get("quantity", ""),
                    metadata=dict(m.get("metadata", {})),
                ))
            else:
                parsed_metrics.append(m)

        raw_prov = data.get("provenance")
        prov = None
        if isinstance(raw_prov, dict):
            prov = provenance_from_mapping(raw_prov)
            if prov is not None and not prov.run_id:
                prov = prov.replace(
                    run_id=str(data.get("id") or ""),
                    model_name=prov.model_name or str(data.get("model_name") or ""),
                    job_name=prov.job_name or str(data.get("job_name") or ""),
                )

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            model_name=data.get("model_name", "Model-1"),
            job_name=data.get("job_name", "Job-1"),
            state=state,
            solver=data.get("solver", "standard"),
            odb_path=data.get("odb_path"),
            engineering_status=data.get("engineering_status"),
            acceptance_passed=data.get("acceptance_passed"),
            intent=data.get("intent"),
            assumptions=tuple(data.get("assumptions", ())),
            solver_selection=data.get("solver_selection"),
            postprocess_profile=data.get("postprocess_profile"),
            runtime=dict(data.get("runtime", {})),
            inputs=tuple(data.get("inputs", ())),
            outputs=data.get("outputs"),
            artifacts=tuple(data.get("artifacts", ())),
            metrics=tuple(parsed_metrics),
            verification=data.get("verification"),
            acceptance=data.get("acceptance"),
            provenance=prov,
            diagnostics=tuple(data.get("diagnostics", ())),
            metadata=dict(data.get("metadata", {})),
            report_reference=data.get("report_reference"),
        )


def discover_odb(executor, job_name, workdir=None):
    if workdir:
        candidate = os.path.join(workdir, job_name + ".odb")
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    raw = executor.execute(
        "import os; print(os.path.abspath(%r + '.odb') if os.path.exists(%r + '.odb') else '')"
        % (job_name, job_name))
    if isinstance(raw, dict):
        for key in ("path", "odb_path"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("stdout", "output"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value.strip().splitlines()[-1].strip()
                if candidate:
                    return candidate
    if isinstance(raw, str) and raw.strip():
        return raw.strip().splitlines()[-1].strip()
    return None


class AnalysisRunner:
    """Complete lifecycle: job -> artifacts -> ODB -> result extraction -> acceptance."""

    def __init__(self, executor):
        self.executor = executor

    def _attach_inp_contract_diagnostics(self, run, workdir, job_name):
        """Best-effort inp model-contract diagnosis appended to run.diagnostics.

        Advisory only (WARNING level). Never raises and never blocks execution:
        a missing/unreadable inp simply yields no diagnostics. Returns the run
        unchanged when no inp is found or no issues are detected.
        """
        try:
            from ..diagnostics.solver_patterns import diagnose_inp_contract
        except Exception:
            return run
        inp_path = None
        try:
            if workdir and job_name:
                candidate = os.path.join(str(workdir), f"{job_name}.inp")
                if os.path.isfile(candidate):
                    inp_path = candidate
        except Exception:
            inp_path = None
        if not inp_path:
            return run
        try:
            inp_text = Path(inp_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return run
        try:
            issues = diagnose_inp_contract(inp_text, source=inp_path)
        except Exception:
            return run
        if not issues:
            return run
        new_diags = tuple(
            {
                "kind": "model_contract",
                "diagnosis_id": iss.diagnosis_id,
                "severity": iss.severity,
                "likely_cause": iss.likely_cause,
                "suggested_remediation": iss.suggested_remediation,
                "supporting_evidence": list(iss.supporting_evidence),
                "file_source": iss.file_source,
            }
            for iss in issues
        )
        return run.with_state(run.state, diagnostics=tuple(run.diagnostics) + new_diags)

    def _load_job_inp_text(self, workdir, job_name):
        from ..diagnostics.solver_patterns import read_job_inp_text
        return read_job_inp_text(workdir=workdir, job_name=job_name)

    def _resolve_yield_strength(self, engineering_intent):
        """Finite yield from the intent material, or None. Never invents one."""
        if engineering_intent is None:
            return None
        mats = []
        if getattr(engineering_intent, "materials", None):
            mats.extend(engineering_intent.materials)
        if getattr(engineering_intent, "material", None):
            mats.append(engineering_intent.material)
        try:
            from ..reasoning.material_catalog import resolve_material_to_definition
        except Exception:
            resolve_material_to_definition = None
        for mat in mats:
            if resolve_material_to_definition is not None:
                try:
                    mat_def = resolve_material_to_definition(mat, fail_closed=False)
                except Exception:
                    mat_def = None
                if mat_def is not None:
                    plastic = getattr(mat_def, "plastic", None)
                    ys = getattr(plastic, "yield_stress", None) if plastic is not None else None
                    if ys:
                        return float(ys)
                    meta = getattr(mat_def, "metadata", None) or {}
                    if meta.get("yield_strength_mpa"):
                        return float(meta["yield_strength_mpa"])
            props = mat.get("properties") if isinstance(mat, dict) else getattr(mat, "properties", None)
            props = props or (mat if isinstance(mat, dict) else {})
            for key in ("yield_strength", "yield_strength_mpa", "yield"):
                raw = props.get(key) if isinstance(props, dict) else None
                if isinstance(raw, bool) or raw is None:
                    continue
                try:
                    number = float(raw)
                except (TypeError, ValueError):
                    continue
                if number == number and number not in (float("inf"), float("-inf")):
                    return number
        return None

    def _resolve_stabilization_threshold(self, engineering_intent):
        """Explicit static stabilization-energy threshold, or (None, source).

        The 5% figure that appears in the remediation text is a candidate policy
        for one configuration, not a universal rule, so this method never invents
        a default. Without an explicit value the acceptance gate stays BLOCKED
        instead of quietly enforcing an unstated engineering assumption.
        """
        if engineering_intent is None:
            return None, None
        metadata = getattr(engineering_intent, "metadata", None) or {}
        if not isinstance(metadata, dict):
            return None, None
        for key, source in (
            ("stabilization_energy_threshold", "intent.metadata"),
            ("max_stabilization_energy_ratio", "intent.metadata"),
        ):
            raw = metadata.get(key)
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value == value and value not in (float("inf"), float("-inf")) and value >= 0.0:
                return value, "%s.%s" % (source, key)
        return None, None

    def _resolve_energy_history_region(self, raw_odb):
        """History region carrying the global energy outputs, or None.

        Abaqus writes total-model energies to the assembly-level history region.
        The name is taken from the ODB inspection rather than assumed.
        """
        if not isinstance(raw_odb, dict):
            return None
        regions = raw_odb.get("history_regions") or raw_odb.get("historyRegions")
        if isinstance(regions, dict):
            candidates = list(regions.keys())
        elif isinstance(regions, (list, tuple)):
            candidates = [str(name) for name in regions]
        else:
            candidates = []
        for name in candidates:
            if "ASSEMBLY" in str(name).upper():
                return str(name)
        return None

    def _evaluate_stabilization_gate(self, deck_text, odb_summary, raw_odb,
                                     odb_path, engineering_intent,
                                     cached_energy=None):
        """Return ``(stabilization_enabled, verdict_or_None)`` for the P0-a gate.

        The gate is demanded only when the deck actually enables stabilization.
        It is evaluated on the ODB history of the step that requested it -- not on
        whichever step happens to be last -- because energy from an unrelated step
        says nothing about the artificial damping that was introduced. When the
        target step cannot be identified uniquely the verdict is BLOCKED instead
        of silently borrowing another step's energies.
        """
        from ..contracts.stabilization_energy import (
            SELECTION_NOT_ENABLED,
            SELECTION_RESOLVED,
            STATUS_BLOCKED,
            StabilizationEnergyVerdict,
            detect_stabilization_in_deck,
            evaluate_static_stabilization_energy,
            resolve_stabilized_step,
        )

        deck_marks = detect_stabilization_in_deck(deck_text or "")
        enabled = bool(
            deck_marks.get("step_stabilization")
            or deck_marks.get("contact_stabilization")
        )
        odb_step_names = [
            str(name) for name in ((odb_summary or {}).get("steps") or ())
            if str(name).strip().lower() != "initial"
        ]
        selection = resolve_stabilized_step(deck_marks, odb_step_names)
        if selection.status == SELECTION_NOT_ENABLED:
            return False, None

        threshold, threshold_source = self._resolve_stabilization_threshold(
            engineering_intent
        )

        if selection.status != SELECTION_RESOLVED:
            # Ambiguous (several stabilized steps), unattributed (keyword outside
            # any step block) or missing from the ODB. All three mean no single
            # step is authoritative for this repair.
            return enabled, StabilizationEnergyVerdict(
                status=STATUS_BLOCKED,
                threshold=threshold,
                threshold_source=threshold_source,
                reason=selection.reason or "stabilization_step_unresolved",
                details=dict(selection.to_dict()),
            )

        history_region = self._resolve_energy_history_region(raw_odb) or "Assembly ASSEMBLY"
        energy = None
        if isinstance(cached_energy, dict) and cached_energy.get("status") == "available":
            if cached_energy.get("step") == selection.step_name:
                energy = cached_energy

        if energy is None:
            try:
                from .odb import extract_energy_evidence
                energy = extract_energy_evidence(
                    self.executor, odb_path, selection.step_name, history_region
                )
            except Exception as exc:
                return enabled, StabilizationEnergyVerdict(
                    status=STATUS_BLOCKED,
                    threshold=threshold,
                    threshold_source=threshold_source,
                    reason="stabilization_energy_extraction_failed",
                    details={
                        "error": "stabilization_energy_extraction_failed:%s" % exc,
                        "target_step": selection.step_name,
                    },
                )

        return enabled, evaluate_static_stabilization_energy(
            energy,
            threshold,
            stabilization_enabled=True,
            threshold_source=threshold_source,
        )

    _DYNAMIC_STRATEGIES = (
        "DYNAMIC_IMPLICIT",
        "DYNAMIC_EXPLICIT",
        "QUASI_STATIC_EXPLICIT",
    )

    @staticmethod
    def _solver_product_for_strategy(strategy):
        """Map a solver strategy to the contract's declared solver product."""
        if str(strategy or "").upper().startswith("DYNAMIC_EXPLICIT") or str(
            strategy or ""
        ).upper() == "QUASI_STATIC_EXPLICIT":
            return "explicit"
        return "standard"

    def _resolve_dynamic_energy_settings(self, engineering_intent):
        """Caller-declared dynamic energy policy, or Nones.

        The contract ships no universal drift threshold because implicit and
        explicit integration do not dissipate energy the same way. An undeclared
        threshold therefore blocks the gate; it is never filled with a default.
        Turning the gate on is likewise an explicit caller decision, so a dynamic
        run that has not asked for it is not blocked by a rule it never opted into.
        """
        if engineering_intent is None:
            return None, None, False
        metadata = getattr(engineering_intent, "metadata", None) or {}
        if not isinstance(metadata, dict):
            return None, None, False

        threshold = None
        threshold_source = None
        for key in (
            "dynamic_energy_threshold",
            "max_dynamic_energy_drift",
            "dynamic_energy_balance_threshold",
        ):
            raw = metadata.get(key)
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value == value and value not in (float("inf"), float("-inf")) and value >= 0.0:
                threshold = value
                threshold_source = "intent.metadata.%s" % key
                break

        enabled_raw = metadata.get("dynamic_energy_gate")
        if enabled_raw is None:
            enabled_raw = metadata.get("dynamic_energy_balance_gate")
        enabled = enabled_raw is True
        return threshold, threshold_source, enabled

    def _resolve_dynamic_target_step(self, odb_summary, deck_text):
        """Return ``(target_step_or_None, reason)`` for the dynamic gate.

        A dynamic model may hold several steps and only one of them is the event
        of interest. The last step is not assumed to be that event: the caller may
        name it in the intent, otherwise a single non-initial step is unambiguous.
        """
        steps = [
            str(name) for name in ((odb_summary or {}).get("steps") or ())
            if str(name).strip().lower() != "initial"
        ]
        if not steps:
            return None, "dynamic_step_missing_in_odb"
        if len(steps) == 1:
            return steps[0], ""
        return None, "dynamic_step_ambiguous"

    def _evaluate_dynamic_energy_gate(self, deck_text, odb_summary, raw_odb,
                                      odb_path, engineering_intent, selection=None,
                                      cached_energy=None):
        """Return ``(gate_enabled, verdict_or_None)`` for the dynamic gate.

        Only an explicitly requested gate is evaluated. When it is requested, the
        evidence must come from one identifiable dynamic step: borrowing the last
        step of a multi-step model would attribute one event's balance to another.
        """
        from ..contracts.dynamic_energy import (
            STATUS_BLOCKED,
            DynamicEnergyVerdict,
            evaluate_dynamic_energy_balance,
        )

        threshold, threshold_source, enabled = self._resolve_dynamic_energy_settings(
            engineering_intent
        )
        if not enabled:
            return False, None

        metadata = getattr(engineering_intent, "metadata", None) or {}
        declared_step = None
        if isinstance(metadata, dict):
            declared_step = metadata.get("dynamic_energy_step") or metadata.get(
                "dynamic_step"
            )

        target_step, reason = self._resolve_dynamic_target_step(odb_summary, deck_text)
        if isinstance(declared_step, str) and declared_step.strip():
            available = [
                str(name) for name in ((odb_summary or {}).get("steps") or ())
                if str(name).strip().lower() != "initial"
            ]
            exact = [name for name in available if name == declared_step]
            folded = [name for name in available if name.lower() == declared_step.lower()]
            if len(exact) == 1:
                target_step, reason = exact[0], ""
            elif len(folded) == 1:
                target_step, reason = folded[0], ""
            else:
                target_step, reason = None, "dynamic_step_missing_in_odb"

        product = self._solver_product_for_strategy(getattr(selection, "strategy", None))

        if target_step is None:
            return True, DynamicEnergyVerdict(
                status=STATUS_BLOCKED,
                threshold=threshold,
                threshold_source=threshold_source,
                solver_product=product,
                reason=reason or "dynamic_step_unresolved",
                details={"declared_step": declared_step},
            )

        history_region = self._resolve_energy_history_region(raw_odb) or "Assembly ASSEMBLY"
        energy = None
        if isinstance(cached_energy, dict) and cached_energy.get("status") == "available":
            if cached_energy.get("step") == target_step:
                energy = cached_energy

        if energy is None:
            try:
                from .odb import extract_energy_evidence
                energy = extract_energy_evidence(
                    self.executor, odb_path, target_step, history_region
                )
            except Exception as exc:
                return True, DynamicEnergyVerdict(
                    status=STATUS_BLOCKED,
                    threshold=threshold,
                    threshold_source=threshold_source,
                    solver_product=product,
                    reason="dynamic_energy_extraction_failed",
                    details={
                        "error": "dynamic_energy_extraction_failed:%s" % exc,
                        "target_step": target_step,
                    },
                )

        return True, evaluate_dynamic_energy_balance(
            energy,
            threshold,
            solver_product=product,
            analysis_is_dynamic=True,
            threshold_source=threshold_source,
        )

    def run(self, model_name, job_name, odb_path=None, criteria=(),
            result_values=None, numerical_verification=None, engineering_checks=None,
            mesh_quality=None, mesh_convergence=None, fatigue=None, contact_diagnostics=None,
            connector_kinematics=None, fmbd_dynamics=None, sensitivity=None, uncertainty=None,
            timeout=3600, action_plan=(), environment=None, engineering_intent=None,
            phase_profiler=None, license_wait_seconds=None,
            postprocess_profile=None, workdir=None, physics_domain=None, require_evidence=None,
            require_production=None, project_context=None, elastic_validity=None,
            inp_text=None, job_options=None):
        if require_production is None:
            # Explicit test flag via environment or executor attribute takes precedence
            is_explicit_test = (
                os.environ.get("ABAQUS_AGENT_TEST_MODE", "").lower() in ("1", "true", "yes")
                or getattr(self.executor, "is_test_mode", False)
                or getattr(self.executor, "_is_mock", False)
            )
            # Safe Default: Production mode is ALWAYS enforced unless explicitly in test mode.
            # Never rely on Mock/Dummy class name heuristics in safety-critical production pipelines.
            require_production = not is_explicit_test

        if require_production and project_context is None:
            raise RuntimeError(
                "[Production Guard] Execution in production mode requires a valid ExternalProjectContext. "
                "Silent fallback to repository-internal runs/ is strictly prohibited."
            )
        if require_production and project_context is not None:
            from ..paths import assert_path_outside_repo
            required_subdirs = ("project_root", "input_dir", "working_dir", "solver_dir", "evidence_dir", "delivery_dir")
            for attr in required_subdirs:
                if not hasattr(project_context, attr):
                    raise TypeError(f"[Production Guard] project_context must be a valid ExternalProjectContext: missing '{attr}'.")
                val = getattr(project_context, attr)
                if not isinstance(val, Path):
                    raise TypeError(f"[Production Guard] project_context.{attr} must be a Path, got {type(val)}.")
                assert_path_outside_repo(val)
                if attr != "project_root":
                    resolved_val = val.resolve()
                    resolved_root = project_context.project_root.resolve()
                    if not resolved_val.is_relative_to(resolved_root):
                        raise PermissionError(
                            f"[Production Guard] Subdirectory boundary escape (REQ-ISO-002): {attr} '{resolved_val}' escapes project_root."
                        )

        run_id = str(uuid.uuid4())
        orig_executor_workdir = getattr(self.executor, "workdir", None)
        run_evidence_dir = None
        if project_context is not None:
            if workdir:
                cand_path = Path(workdir).resolve()
                project_context.assert_within_subdir(cand_path, project_context.solver_dir)
                workdir = str(cand_path)
            else:
                workdir = str(project_context.create_run_solver_dir(run_id))
            run_evidence_dir = project_context.create_run_evidence_dir(run_id)
        elif require_production:
            raise RuntimeError(
                "[Production Guard] Production execution has no customer solver directory. "
                "Refusing to create a solver copy in the core workspace, the launch directory, or a machine-local scratch directory."
            )
        elif not workdir:
            from ..paths import get_core_workspace_root, resolve_runs_root
            core_root = get_core_workspace_root().resolve()
            launch_dir = Path.cwd().resolve()
            if orig_executor_workdir:
                cand = Path(orig_executor_workdir).resolve()
                inside_core = cand == core_root or cand.is_relative_to(core_root)
                if inside_core or cand == launch_dir:
                    workdir = os.path.join(str(resolve_runs_root()), run_id)
                else:
                    workdir = str(cand)
            else:
                workdir = os.path.join(str(resolve_runs_root()), run_id)
        os.makedirs(workdir, exist_ok=True)
        workdir = os.path.abspath(workdir)
        resolved_workdir = Path(workdir).resolve()
        from ..paths import assert_path_outside_core_workspace
        try:
            assert_path_outside_core_workspace(resolved_workdir)
        except PermissionError as exc:
            raise PermissionError(
                f"Execution workdir '{workdir}' is inside the core workspace. "
                "Solver copies must stay in the customer project directory."
            ) from exc

        if hasattr(self.executor, "workdir"):
            self.executor.workdir = workdir
        runtime = _runtime_provenance(self.executor)
        initial_snapshot = None
        try:
            if hasattr(self.executor, "snapshot"):
                initial_snapshot = self.executor.snapshot()
        except Exception:
            # Snapshot is provenance enrichment, never an execution prerequisite.
            initial_snapshot = None
        runtime_environment = dict(getattr(runtime, "metadata", {}) or {}) if runtime else {}
        if environment:
            runtime_environment.update(dict(environment))
        if project_context is not None:
            runtime_environment["project_root"] = str(project_context.project_root)
            runtime_environment["project_name"] = str(project_context.project_name)
            if run_evidence_dir is not None:
                runtime_environment["evidence_dir"] = str(run_evidence_dir)
        normalized_action_plan = _normalize_action_plan(action_plan)
        provenance = AnalysisProvenance(
            run_id=run_id,
            model_name=model_name,
            job_name=job_name,
            model_hash=None,
            input_hash=None,
            output_hash=None,
            abaqus_version=getattr(runtime, "version", None) if runtime else None,
            python_version=getattr(runtime, "python_version", None) if runtime else None,
            executor=self.executor.__class__.__name__,
            action_plan=normalized_action_plan,
            environment=runtime_environment,
            metadata={
                # A formal signature cannot cite a missing snapshot as if it were
                # captured. "unavailable" is an explicit fingerprint of that fact;
                # None would let the stamp exist without a verifiable scope.
                "model_snapshot_hash": stable_hash(initial_snapshot)
                if initial_snapshot is not None else "unavailable",
                "content_hash_scope": "not_captured",
                "action_plan_scope": "caller" if normalized_action_plan else "none",
                "agent_issued": True,
                "issued_by": "abaqus-ai-agent",
                "agent_entry": (environment or {}).get("agent_entry") or "analysis_runner",
                "jev_routed": bool((environment or {}).get("jev_routed")),
                "jev_mode": (environment or {}).get("jev_mode"),
                "requirement_kind": (environment or {}).get("requirement_kind") or "unspecified",
            },
        )
        run = AnalysisRun(
            run_id, model_name, job_name, AnalysisRunState.PREFLIGHTED,
            provenance=provenance,
            metadata={"workdir": workdir},
        )

        # Preflight Plan Hard Gate (P1-1): Verify plan before job creation/submission
        if action_plan:
            from ..validation.preflight import preflight_plan
            from ..contracts.action import AbaqusAction
            actions_to_preflight = []
            for act in action_plan:
                if isinstance(act, dict):
                    actions_to_preflight.append(AbaqusAction(
                        action_type=act.get("action_type", ""),
                        model_name=act.get("model_name", model_name),
                        target=act.get("target"),
                        parameters=act.get("parameters", {}),
                    ))
                else:
                    actions_to_preflight.append(act)
            preflight_res = preflight_plan(actions_to_preflight, snapshot=initial_snapshot)
            if not preflight_res.passed:
                return run.with_state(
                    AnalysisRunState.FAILED,
                    engineering_status=EngineeringStatus.EXECUTION_FAILED.value,
                    diagnostics=tuple({"preflight_blocker": b} for b in preflight_res.blockers),
                )

        jobs = JobController(self.executor)

        # Life-cycle ledger (Contract A): record enough state that a later session
        # can find this run again, without ever deciding the outcome from the file
        # alone. Writes are best-effort: a read-only or locked workspace must not
        # turn a healthy solve into a failure, and resumption re-verifies reality
        # through the physical probes in `reconciliation.reconcile_run_state`.
        _ledger_api = None
        try:
            from .reconciliation import RunSnapshot, get_current_git_status, write_snapshot
            _ledger_api = (RunSnapshot, write_snapshot, get_current_git_status)
        except Exception:
            _ledger_api = None

        git_head, git_dirty = None, False
        if _ledger_api is not None:
            try:
                git_head, git_dirty = _ledger_api[2]()
            except Exception:
                git_head, git_dirty = None, False

        def _persist_ledger(phase: str, run_obj, *, pid=None) -> None:
            if _ledger_api is None:
                return
            try:
                snapshot_cls, write_snapshot_fn, _ = _ledger_api
                write_snapshot_fn(
                    snapshot_cls(
                        task_id=provenance.run_id,
                        run_id=provenance.run_id,
                        phase=phase,
                        job_name=job_name,
                        sandbox_dir=workdir,
                        git_head_commit=git_head,
                        git_is_dirty=git_dirty,
                        pid=pid,
                        odb_path=getattr(run_obj, "odb_path", None),
                        metadata={"model_name": model_name},
                    )
                )
            except Exception:
                # Snapshotting is an index, never a gate on execution.
                pass

        _persist_ledger("PREFLIGHTED", run)
        try:
            snapshot = initial_snapshot
            if snapshot is not None and job_name not in getattr(snapshot, "jobs", ()):
                from .solver_config import resolve_job_kwargs
                is_adaptive = bool(job_options and job_options.get("adaptive", False))

                # 1. Resolve solver_type from self, intent, or postprocess_profile
                effective_solver_type = getattr(self, "solver_type", None)
                if not effective_solver_type and engineering_intent is not None:
                    try:
                        from ..contracts.solver_selection import select_solver
                        selection = select_solver(engineering_intent)
                        slv = getattr(selection, "solver", "") or getattr(selection, "product", "")
                        if "EXPLICIT" in str(slv).upper():
                            effective_solver_type = "EXPLICIT"
                        elif "STANDARD" in str(slv).upper():
                            effective_solver_type = "STANDARD"
                    except Exception:
                        pass
                    if not effective_solver_type:
                        atype = str(getattr(engineering_intent, "analysis_type", "")).upper()
                        if "EXPLICIT" in atype:
                            effective_solver_type = "EXPLICIT"
                if not effective_solver_type:
                    effective_solver_type = "STANDARD"

                # 2. Extract element_count from available signals
                resolved_elements = None
                if job_options:
                    resolved_elements = job_options.get("element_count") or (job_options.get("context") or {}).get("element_count")
                if resolved_elements is None and mesh_quality:
                    if isinstance(mesh_quality, dict):
                        resolved_elements = mesh_quality.get("element_count") or mesh_quality.get("num_elements") or mesh_quality.get("total_elements")
                    else:
                        resolved_elements = getattr(mesh_quality, "element_count", None) or getattr(mesh_quality, "num_elements", None)
                if resolved_elements is None and mesh_convergence:
                    if isinstance(mesh_convergence, dict):
                        resolved_elements = mesh_convergence.get("element_count") or mesh_convergence.get("num_elements")
                    else:
                        resolved_elements = getattr(mesh_convergence, "element_count", None)
                if resolved_elements is None and engineering_intent is not None:
                    intent_meta = getattr(engineering_intent, "metadata", {}) or {}
                    if isinstance(intent_meta, dict):
                        resolved_elements = intent_meta.get("mesh_elements") or intent_meta.get("element_count")
                if resolved_elements is None:
                    candidate_inp = inp_text
                    if not candidate_inp and workdir and job_name:
                        try:
                            fpath = os.path.join(str(workdir), f"{job_name}.inp")
                            if os.path.isfile(fpath):
                                candidate_inp = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                        except Exception:
                            candidate_inp = None
                    if candidate_inp:
                        try:
                            elem_lines = 0
                            in_elem = False
                            for line in candidate_inp.splitlines():
                                s = line.strip()
                                if s.startswith("*"):
                                    in_elem = s.upper().startswith("*ELEMENT")
                                elif in_elem and s and not s.startswith("**"):
                                    elem_lines += 1
                            if elem_lines > 0:
                                resolved_elements = elem_lines
                        except Exception:
                            pass

                # 3. Extract available_tokens from job_options, environment, or os env
                resolved_tokens = None
                if job_options:
                    resolved_tokens = job_options.get("available_tokens") or (job_options.get("context") or {}).get("available_tokens")
                if resolved_tokens is None and environment:
                    resolved_tokens = environment.get("available_tokens")
                if resolved_tokens is None:
                    env_tok = os.environ.get("ABAQUS_AVAILABLE_TOKENS")
                    if env_tok:
                        try:
                            tok_val = int(env_tok.strip())
                            if tok_val >= 0:
                                resolved_tokens = tok_val
                        except (ValueError, TypeError):
                            pass

                # 4. Extract hardware context
                resolved_hardware = None
                if job_options:
                    resolved_hardware = job_options.get("host_hardware") or (job_options.get("context") or {}).get("host_hardware")
                if resolved_hardware is None and environment:
                    resolved_hardware = environment.get("host_hardware")

                # 5. Physics non-linear flags
                is_large_strain = False
                has_contact = False
                if engineering_intent is not None:
                    intent_meta = getattr(engineering_intent, "metadata", {}) or {}
                    if not isinstance(intent_meta, dict):
                        intent_meta = {}
                    is_large_strain = bool(
                        intent_meta.get("large_deformation")
                        or intent_meta.get("large_deflection")
                        or intent_meta.get("nlgeom")
                    )
                    has_contact = bool(
                        getattr(engineering_intent, "contacts", ())
                        or intent_meta.get("has_contact")
                        or intent_meta.get("contact_pairs")
                    )

                solver_ctx = {
                    "model_name": model_name,
                    "job_name": job_name,
                    "solver_type": effective_solver_type,
                    "element_count": resolved_elements,
                    "available_tokens": resolved_tokens,
                    "host_hardware": resolved_hardware,
                    "large_deformation": is_large_strain,
                    "has_contact": has_contact,
                }
                job_kwargs, job_decisions = resolve_job_kwargs(
                    job_options, adaptive=is_adaptive, context=solver_ctx
                )
                metadata = dict(run.metadata)
                metadata["solver_parameter_decisions"] = job_decisions
                run = run.with_state(run.state, metadata=metadata)
                jobs.create(job_name, model_name, **job_kwargs)

            from ..planning.output import plan_outputs, actions_from_output_plan, criteria_from_postprocess_profile
            # Two lists, because they answer different questions.
            #
            # `effective_criteria` describes what to EXTRACT from the ODB.
            # `acceptance_criteria` describes what counts as a PASS and therefore
            # always carries an operator and a limit. A profile requirement such as
            # `reaction_force` says "this number must exist", not "it must be below
            # X"; feeding it to the criteria evaluator used to surface as
            # `unsupported operator: None` and turned a valid run into a failure.
            acceptance_criteria = tuple(criteria or ())
            effective_criteria = acceptance_criteria

            # The domain profile is what the acceptance gate will hold this run to.
            # Planning extraction from a different profile let a gate require a
            # metric that no ODB request ever asked for, which blocks a valid run
            # for a bookkeeping mismatch instead of a missing result.
            domain_profile = None
            if physics_domain:
                from ..contracts.results import get_physics_result_profile
                domain_profile = get_physics_result_profile(physics_domain)

            for source_profile in (postprocess_profile, domain_profile):
                if source_profile is None:
                    continue
                profile_criteria = criteria_from_postprocess_profile(source_profile)
                existing_keys = {item.get("value_key") for item in effective_criteria if isinstance(item, dict)}
                effective_criteria = effective_criteria + tuple(
                    item for item in profile_criteria
                    if item.get("value_key") not in existing_keys
                )
            if engineering_intent is not None:
                from ..contracts.solver_selection import select_solver
                from ..contracts.postprocess import profile_for_solver_selection
                selection = select_solver(engineering_intent)
                # T-P1 / frozen contract D2: a hard-blocked selection is a
                # pre-submission refusal, never a warning to continue past.
                if getattr(selection, "blocked", False):
                    raise SolverSelectionBlocked(selection)
                postprocess_profile = postprocess_profile or profile_for_solver_selection(selection)
                metadata = dict(run.metadata)
                metadata["solver_selection"] = selection
                metadata["postprocess_profile"] = postprocess_profile
                run = run.with_state(run.state, metadata=metadata)
            output_plan = plan_outputs(effective_criteria, postprocess_profile=None)
            output_actions = actions_from_output_plan(model_name, output_plan)
            if not action_plan and output_actions:
                run = run.with_state(
                    run.state,
                    provenance=run.provenance.replace(
                        action_plan=_action_records(output_actions),
                        metadata=dict(run.provenance.metadata, action_plan_scope="output_plan"),
                    ),
                )
            try:
                if hasattr(self.executor, "execute"):
                    self.executor.execute(f"import os; os.chdir({workdir!r})")
            except Exception:
                pass

            for output_action in output_actions:
                from ..validation.actions import validate_action
                from ..actions.runner import execute
                validate_action(output_action)
                execute(self.executor, output_action)

            # P0.2 Pre-submission Assembly Contract Audit (CAE Model Entrypoint)
            active_scope = None
            cp = locals().get("compiled_plan")
            if cp and getattr(cp, "intent_summary", None):
                geo_info = cp.intent_summary.get("geometry") or {}
                active_scope = geo_info.get("assembly_scope")
            if active_scope is None and engineering_intent is not None:
                active_scope = getattr(engineering_intent, "assembly_scope", None)

            if active_scope is not None:
                from ..validation.assembly_guard import audit_inp_assembly_contract, AssemblyContractViolation

                # 0. Executor validation: ensure executor reliably supports writeInput execution
                if not hasattr(self.executor, "execute") or not callable(self.executor.execute):
                    raise AssemblyContractViolation(
                        f"Pre-submission audit blocked: executor {type(self.executor).__name__} does not support "
                        f"'execute' method to run writeInput for job '{job_name}'."
                    )

                # 1. Freshness guarantee: purge pre-existing stale deck before writeInput to guarantee provenance
                candidate_inp = os.path.join(workdir, f"{job_name}.inp")
                if os.path.exists(candidate_inp):
                    try:
                        os.remove(candidate_inp)
                    except OSError as exc:
                        raise AssemblyContractViolation(
                            f"Pre-submission audit blocked: unable to clean up pre-existing stale deck '{candidate_inp}': {exc}"
                        ) from exc

                # 2. Trigger writeInput on current CAE model to generate the authoritative, deterministic deck
                try:
                    self.executor.execute(f"mdb.jobs[{job_name!r}].writeInput(consistencyChecking=ON)")
                except Exception as exc:
                    raise AssemblyContractViolation(
                        f"Pre-submission writeInput failed consistency checking for job '{job_name}': {exc}"
                    ) from exc

                if not os.path.isfile(candidate_inp):
                    raise AssemblyContractViolation(
                        f"Pre-submission audit blocked: expected solver deck '{candidate_inp}' was not generated by writeInput."
                    )

                # 3. Read raw disk binary bytes and compute authoritative cryptographic SHA-256 binding
                with open(candidate_inp, "rb") as f_raw:
                    raw_bytes = f_raw.read()
                audited_inp_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                try:
                    generated_deck = raw_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise AssemblyContractViolation(
                        f"Pre-submission audit blocked: generated solver deck '{candidate_inp}' "
                        f"is not valid UTF-8 ({exc}); refusing to audit replacement-decoded content."
                    ) from exc

                # 4. Perform fail-closed assembly contract audit
                audit_res = audit_inp_assembly_contract(
                    generated_deck,
                    assembly_scope=active_scope,
                    base_dir=workdir,
                )
                if not audit_res.passed:
                    raise AssemblyContractViolation(
                        f"Pre-submission CAE model audit blocked solver launch: {audit_res.reason}"
                    )

                # 5. Cryptographic binding: bind audited solver deck raw hash and include dependencies to run provenance
                include_hashes: Dict[str, str] = dict(audit_res.diagnostics.get("audited_include_hashes") or {})
                if not include_hashes:
                    resolved_includes = audit_res.diagnostics.get("resolved_include_files", [])
                    for inc_p_str in resolved_includes:
                        try:
                            inc_p = Path(inc_p_str)
                            if inc_p.is_file():
                                include_hashes[inc_p_str] = hashlib.sha256(inc_p.read_bytes()).hexdigest()
                        except Exception:
                            pass

                run = run.with_state(
                    run.state,
                    provenance=run.provenance.replace(
                        input_hash=audited_inp_sha256,
                        metadata=dict(
                            run.provenance.metadata,
                            audited_inp_sha256=audited_inp_sha256,
                            audited_inp_path=candidate_inp,
                            audited_include_hashes=include_hashes,
                        ),
                    ),
                )

                # 6. Pre-submit consistency check: verify solver deck raw binary bytes have not been modified
                with open(candidate_inp, "rb") as f_check:
                    post_audit_bytes = f_check.read()
                current_inp_sha256 = hashlib.sha256(post_audit_bytes).hexdigest()
                if current_inp_sha256 != audited_inp_sha256:
                    raise AssemblyContractViolation(
                        f"Pre-submission consistency mismatch: solver deck '{candidate_inp}' changed after audit."
                    )

                # Verify all included dependencies also have not been modified
                for inc_p_str, expected_hash in include_hashes.items():
                    inc_p = Path(inc_p_str)
                    if not inc_p.is_file() or hashlib.sha256(inc_p.read_bytes()).hexdigest() != expected_hash:
                        raise AssemblyContractViolation(
                            f"Pre-submission consistency mismatch: included deck dependency '{inc_p_str}' changed after audit."
                        )

            # T3: If a license wait duration was measured upstream (e.g. queue dispatch),
            # attach it to the profiler with source="queue_dispatch" and derivation="none".
            # If wait duration was not measured (None), attach_license_timing explicitly records NOT_RUN.
            if phase_profiler is not None:
                from .license import attach_license_timing
                attach_license_timing(
                    phase_profiler,
                    license_wait_seconds,
                    source="queue_dispatch",
                )

            # T4a: wall clock around the existing submit. This is "submitted until
            # the wait returned", which includes solver startup, license queueing and
            # the solve itself -- it is not solver runtime. T4b (solver runtime) is
            # read from the job log afterwards and kept under a different key, so the
            # two can never be substituted for each other.
            #
            # The timing block must not change what this method returns. A failure
            # while recording is noted and swallowed; the job status and the run state
            # machine below are untouched. ``phase_profiler is None`` (the default)
            # skips all of this, so existing callers see no behaviour change.
            status, _t4a_wait_s = _submit_and_time(jobs, job_name, timeout, phase_profiler)
            artifacts = _collect_artifacts(self.executor, job_name, workdir=workdir)
            if phase_profiler is not None:
                _record_solver_timing(phase_profiler, _t4a_wait_s, job_name, workdir)
            run = run.with_state(
                run.state,
                provenance=_provenance_with_artifacts(run.provenance, artifacts),
            )
            _persist_ledger("SOLVING", run)
            if status.state != JobState.COMPLETED:
                solver_diagnostics = _collect_diagnostics(self.executor, job_name, workdir=workdir)
                sta_tail = solver_diagnostics.get(".sta", {}).get("tail", "")
                log_tail = solver_diagnostics.get(".log", {}).get("tail", "")
                if "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta_tail and "COMPLETED" in log_tail:
                    status = JobStatus(job_name, JobState.COMPLETED, status.raw)
                else:
                    engineering = (
                        EngineeringStatus.SOLVER_FAILED
                        if status.state in (JobState.ABORTED, JobState.TERMINATED,
                                             JobState.ERROR, JobState.TIMEOUT)
                        else EngineeringStatus.EXECUTION_FAILED)
                    failed_run = run.with_state(
                        AnalysisRunState.FAILED,
                        job_status=status,
                        engineering_status=engineering.value,
                        artifacts=artifacts,
                        diagnostics=({"reason": "job_not_completed",
                                      "state": status.state.value,
                                      "solver_artifacts": solver_diagnostics},))
                    _persist_ledger("FAILED", failed_run)
                    return failed_run

            run = run.with_state(
                AnalysisRunState.COMPLETED,
                job_status=status,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
                artifacts=artifacts)
            _persist_ledger("COMPLETED", run)

            path = odb_path or discover_odb(self.executor, job_name, workdir=workdir)
            if not path:
                missing_run = run.with_state(
                    AnalysisRunState.FAILED,
                    engineering_status=EngineeringStatus.ODB_MISSING.value,
                    diagnostics=({"reason": "odb_missing"},),
                    artifacts=artifacts)
                _persist_ledger("FAILED", missing_run)
                return missing_run

            raw_odb = None
            if hasattr(self.executor, "inspect_odb"):
                from .odb import inspect_odb
                raw_odb = inspect_odb(self.executor, path)
            odb = summarize_odb(raw_odb) if raw_odb is not None else {"status": "unavailable"}
            if odb.get("status") != "available" or not odb.get("steps"):
                invalid_run = run.with_state(
                    AnalysisRunState.FAILED,
                    odb_path=path,
                    engineering_status=EngineeringStatus.RESULT_INVALID.value,
                    diagnostics=({"reason": "odb_invalid", "odb": odb},),
                    evidence=EvidenceBundle((Evidence(kind="odb_summary", source="odb", locator=path, value=odb),)), artifacts=artifacts)
                _persist_ledger("FAILED", invalid_run)
                return invalid_run

            run = run.with_state(
                AnalysisRunState.ODB_VALIDATED,
                odb_path=path,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
                evidence=EvidenceBundle((Evidence(kind="odb_summary", source="odb", locator=path, value=odb),)), artifacts=artifacts)

            # Model-contract diagnosis (MS13L lesson): surface C3D4-only bending,
            # pin tie+fix overconstraint, oversized fixed sets, and elastic-only
            # decks that claim plasticity. Warnings stay advisory. The deck text
            # itself is kept so acceptance and the report cannot skip it.
            deck_text = inp_text
            deck_source = None
            if not deck_text:
                deck_text, deck_source = self._load_job_inp_text(workdir, job_name)
            if deck_text:
                run = run.with_state(
                    run.state,
                    metadata=dict(run.metadata, inp_text=deck_text, inp_source=deck_source),
                )
            run = self._attach_inp_contract_diagnostics(run, workdir, job_name)

            from ..contracts.fatigue import IntentFatigueSpec, FatigueResult
            fatigue_spec = getattr(engineering_intent, "fatigue", None) or (
                fatigue if isinstance(fatigue, IntentFatigueSpec) else None
            )

            if not effective_criteria and numerical_verification is None and engineering_checks is None and mesh_quality is None and mesh_convergence is None and fatigue is None and fatigue_spec is None and contact_diagnostics is None and connector_kinematics is None and fmbd_dynamics is None and not getattr(engineering_intent, "connectors", None) and not getattr(engineering_intent, "fmbd", None) and sensitivity is None and uncertainty is None:
                return run.with_state(AnalysisRunState.ODB_VALIDATED)

            extractions = ()
            art_dir = workdir or (os.path.dirname(os.path.abspath(path)) if path else ".")
            run_metrics = ()
            extracted_energy_evidence = None

            if result_values is None:
                from .solver import (
                    is_authentic_binary_odb,
                    verify_authentic_odb_structure,
                    has_native_odb_access,
                    find_abaqus_executable,
                )
                if require_production:
                    if not path or not os.path.isfile(path) or not is_authentic_binary_odb(path):
                        return run.with_state(
                            AnalysisRunState.FAILED,
                            odb_path=path,
                            engineering_status=EngineeringStatus.RESULT_INVALID.value,
                            diagnostics=({"reason": "odb_not_authentic_binary", "path": path},),
                            artifacts=artifacts,
                        )
                    can_native = has_native_odb_access()
                    configured_launcher = getattr(self.executor, "launcher", None)
                    if can_native:
                        eff_launcher = configured_launcher
                    else:
                        eff_launcher = configured_launcher or os.environ.get("ABAQUS_BAT_PATH") or find_abaqus_executable()

                    req_fields = []
                    for c in effective_criteria:
                        fld = c.get("field") if isinstance(c, dict) else getattr(c, "field", None)
                        if fld:
                            req_fields.append(str(fld).upper())

                    # In genuine production mode, either in-process native odbAccess must be available,
                    # or launcher MUST be present and native verification MUST succeed.
                    # Offline state, missing launcher, or verification errors strictly block delivery.
                    if not can_native and not eff_launcher:
                        return run.with_state(
                            AnalysisRunState.FAILED,
                            odb_path=path,
                            engineering_status=EngineeringStatus.RESULT_INVALID.value,
                            diagnostics=({"reason": "production_launcher_missing", "detail": "Native Abaqus launcher or in-process odbAccess required in production mode"},),
                            artifacts=artifacts,
                        )
                    odb_check = verify_authentic_odb_structure(
                        path=path,
                        launcher_cmd=eff_launcher,
                        required_fields=tuple(set(req_fields)) if req_fields else None,
                    )
                    if not odb_check.get("verified", False):
                        reason = "odb_native_structure_unverified" if odb_check.get("offline", False) else "odb_native_structure_invalid"
                        return run.with_state(
                            AnalysisRunState.FAILED,
                            odb_path=path,
                            engineering_status=EngineeringStatus.RESULT_INVALID.value,
                            diagnostics=({"reason": reason, "detail": odb_check.get("error", "Native ODB verification failed or launcher is offline")},),
                            artifacts=artifacts,
                        )

                    from .odb_extractor import extract_odb_results
                    eff_inp_hash = (run.provenance.input_hash if run.provenance else None) or ""

                    # 2A pre-injection: If dynamic energy gate is enabled and a target step is declared,
                    # pass energy_spec to extract_odb_results so energy history is extracted in the
                    # batched run, eliminating redundant cold-start runs.
                    pre_energy_spec = None
                    _, _, dyn_enabled = self._resolve_dynamic_energy_settings(engineering_intent)
                    if dyn_enabled and engineering_intent is not None:
                        meta = getattr(engineering_intent, "metadata", None) or {}
                        if isinstance(meta, dict):
                            dec_step = meta.get("dynamic_energy_step") or meta.get("dynamic_step")
                            if dec_step:
                                pre_energy_spec = {"step": str(dec_step).strip()}

                    try:
                        report = extract_odb_results(
                            odb_path=path,
                            requirements_or_criteria=effective_criteria,
                            run_id=run_id,
                            input_hash=eff_inp_hash,
                            workdir=workdir,
                            launcher_cmd=eff_launcher,
                            custom_runner=getattr(self.executor, "execute", None) if eff_launcher else None,
                            energy_spec=pre_energy_spec,
                        )
                    except Exception as exc:
                        return run.with_state(
                            AnalysisRunState.FAILED,
                            odb_path=path,
                            engineering_status=EngineeringStatus.RESULT_INVALID.value,
                            diagnostics=({"reason": "odb_extraction_failed", "detail": str(exc)},),
                            artifacts=artifacts,
                        )
                    extractions = report.extractions
                    result_evidence = report.evidence
                    result_values = report.metrics
                    extracted_energy_evidence = getattr(report, "energy_evidence", None)
                    from ..contracts.metrics import metrics_from_extractions
                    run_metrics = metrics_from_extractions(extractions)
                    result_source = "odb"
                else:
                    from .results import extract_requirements
                    extractions, result_evidence = extract_requirements(
                        self.executor, path, effective_criteria)
                    result_values = {item.requirement.value_key: item.value for item in extractions}
                    from ..contracts.metrics import metrics_from_extractions
                    run_metrics = metrics_from_extractions(extractions)
                    result_source = "odb"
            else:
                result_evidence = (Evidence(
                    kind="injected_result",
                    source="external_input",
                    value=dict(result_values),
                    metadata={
                        "odb_backed": False,
                        "engineering_validity": "not_established",
                    },
                ),)
                result_source = "external_input"

            if fatigue_spec is not None and result_source == "odb":
                from ..fatigue import run_fatigue_postprocess
                computed_fatigue_res = None
                fatigue_metrics = {}
                try:
                    target_odb = raw_odb if (raw_odb is not None and hasattr(raw_odb, "steps")) else path
                    computed_fatigue_res, fatigue_metrics = run_fatigue_postprocess(target_odb, fatigue_spec)
                except Exception:
                    out_json_path = None
                    try:
                        import tempfile
                        import json
                        from ..fatigue import build_odb_fatigue_postprocess_script
                        with tempfile.NamedTemporaryFile(suffix=".json", dir=workdir, delete=False) as tf:
                            out_json_path = tf.name
                        post_script = build_odb_fatigue_postprocess_script(
                            odb_path=path,
                            output_json=out_json_path,
                            material_curve=fatigue_spec.material_curve,
                            ultimate_strength=fatigue_spec.ultimate_strength,
                            mean_stress_correction=fatigue_spec.mean_stress_correction,
                            measure=fatigue_spec.measure,
                            step_name=fatigue_spec.step_name,
                            element_label=fatigue_spec.element_label,
                        )
                        self.executor.execute(post_script)
                        if os.path.exists(out_json_path):
                            with open(out_json_path, "r", encoding="utf-8") as f:
                                fatigue_data = json.load(f)
                            c_sum = fatigue_data.get("cycle_summary", {})
                            damage_val = c_sum.get("cumulative_damage", 0.0)
                            total_cnt = max(c_sum.get("total_cycles_count", 1.0), 1.0)
                            life_val = c_sum.get("life_blocks", 0.0) * total_cnt
                            status_val = fatigue_data.get("status", "fail")
                            computed_fatigue_res = FatigueResult(
                                status=status_val,
                                life_cycles=life_val,
                                damage=damage_val,
                                evidence=tuple(fatigue_data.get("evidence", ("fatigue_postprocess_script",))),
                            )
                            fatigue_metrics = {
                                "fatigue_life": life_val,
                                "damage": damage_val,
                                "max_stress_range": c_sum.get("max_stress_range", 0.0),
                                "mean_stress_average": c_sum.get("mean_stress_average", 0.0),
                                "total_cycles_count": c_sum.get("total_cycles_count", 0.0),
                                "hotspot_element": fatigue_data.get("hotspot", {}).get("element_label"),
                            }
                    except Exception:
                        pass
                    finally:
                        if out_json_path and os.path.exists(out_json_path):
                            try:
                                os.remove(out_json_path)
                            except Exception:
                                pass

                if computed_fatigue_res is not None:
                    fatigue = computed_fatigue_res
                    if fatigue_metrics:
                        result_values.update(fatigue_metrics)
                        from ..contracts.metrics import EngineeringMetric
                        f_metrics = [
                            EngineeringMetric(
                                name=k,
                                value=v,
                                unit="cycles" if "life" in k or "cycles" in k else ("MPa" if "stress" in k else ""),
                                source="odb",
                                quantity="fatigue",
                            )
                            for k, v in fatigue_metrics.items() if isinstance(v, (int, float))
                        ]
                        run_metrics = tuple(locals().get("run_metrics", ())) + tuple(f_metrics)

                existing_keys = {c.get("value_key") for c in effective_criteria if isinstance(c, dict)}
                added_crit = []
                if "fatigue_life" not in existing_keys:
                    added_crit.append({
                        "name": "fatigue_life_gate",
                        "value_key": "fatigue_life",
                        "operator": ">=",
                        "limit": float(fatigue_spec.target_cycles),
                        "unit": "cycles",
                        "required": True,
                    })
                if "damage" not in existing_keys:
                    added_crit.append({
                        "name": "fatigue_damage_gate",
                        "value_key": "damage",
                        "operator": "<=",
                        "limit": float(fatigue_spec.allowable_damage),
                        "unit": "",
                        "required": True,
                    })
                if added_crit:
                    effective_criteria = tuple(effective_criteria) + tuple(added_crit)
                    acceptance_criteria = tuple(acceptance_criteria) + tuple(added_crit)

            run_manifest = None
            if result_source == "odb":
                try:
                    from ..contracts.evidence import build_evidence_manifest_v2
                    art_dir = workdir or (os.path.dirname(os.path.abspath(path)) if path else ".")
                    fnames = [os.path.basename(a.path) for a in artifacts if getattr(a, "exists", False) and getattr(a, "path", None)]
                    if fnames:
                        run_manifest = build_evidence_manifest_v2(
                            run_id=run_id,
                            case_id=job_name,
                            artifacts_dir=art_dir,
                            artifact_filenames=fnames,
                            intent_summary={"model_name": model_name, "job_name": job_name},
                            required_results={"criteria": [c if isinstance(c, dict) else str(c) for c in effective_criteria]},
                            environment=runtime_environment,
                        )
                except Exception:
                    run_manifest = None

            if physics_domain is not None:
                domain_to_eval = physics_domain
            elif fatigue_spec is not None:
                domain_to_eval = "fatigue"
            elif getattr(engineering_intent, "fmbd", None) or fmbd_dynamics is not None:
                domain_to_eval = "fmbd"
            elif getattr(engineering_intent, "connectors", None) or connector_kinematics is not None:
                domain_to_eval = "connector"
            else:
                domain_to_eval = None

            effective_require_evidence = require_evidence if require_evidence is not None else (True if result_source == "odb" else False)
            from ..acceptance import build_elastic_validity
            deck_for_gate = (run.metadata or {}).get("inp_text") or inp_text
            auto_elastic = build_elastic_validity(
                inp_text=deck_for_gate,
                yield_strength=self._resolve_yield_strength(engineering_intent),
                values=result_values if isinstance(result_values, dict) else None,
            )
            effective_elastic = elastic_validity if elastic_validity is not None else auto_elastic

            # Static stabilization acceptance (P0-a). The gate is only demanded
            # when the deck actually enables stabilization; otherwise it stays
            # SKIPPED so its absence is auditable. Evidence is extracted from the
            # live ODB history, never inferred from the deck keywords alone.
            auto_stabilization_enabled = False
            stabilization_verdict_for_evidence = None
            threshold = None
            threshold_source = None
            if result_source == "odb" and path:
                auto_stabilization_enabled, stabilization_verdict_for_evidence = (
                    self._evaluate_stabilization_gate(
                        deck_for_gate, odb, raw_odb, path, engineering_intent,
                        cached_energy=extracted_energy_evidence,
                    )
                )
                if stabilization_verdict_for_evidence is not None:
                    threshold = stabilization_verdict_for_evidence.threshold
                    threshold_source = (
                        stabilization_verdict_for_evidence.threshold_source
                    )
                elif auto_stabilization_enabled:
                    threshold, threshold_source = self._resolve_stabilization_threshold(
                        engineering_intent
                    )

            # Dynamic energy balance (Gate 11c). Opt-in by contract design: the
            # caller must declare the gate and the solver-specific threshold, so an
            # unrequested gate is SKIPPED rather than an unstated enforcement.
            auto_dynamic_energy_enabled = False
            dynamic_energy_verdict_for_evidence = None
            dynamic_energy_threshold = None
            dynamic_energy_threshold_source = None
            dynamic_energy_solver_product = None
            if result_source == "odb" and path:
                (
                    auto_dynamic_energy_enabled,
                    dynamic_energy_verdict_for_evidence,
                ) = self._evaluate_dynamic_energy_gate(
                    deck_for_gate, odb, raw_odb, path, engineering_intent,
                    selection=locals().get("selection"),
                    cached_energy=extracted_energy_evidence,
                )
                if dynamic_energy_verdict_for_evidence is not None:
                    dynamic_energy_threshold = (
                        dynamic_energy_verdict_for_evidence.threshold
                    )
                    dynamic_energy_threshold_source = (
                        dynamic_energy_verdict_for_evidence.threshold_source
                    )
                    dynamic_energy_solver_product = (
                        dynamic_energy_verdict_for_evidence.solver_product
                    )

            if require_production:
                run_snapshot_for_acc = run.with_state(
                    run.state,
                    extractions=tuple(extractions if result_source == "odb" else ()),
                    artifacts=artifacts,
                    job_status=status,
                    odb_path=path,
                )
                accepted = evaluate_production_acceptance(
                    analysis_run=run_snapshot_for_acc,
                    result_status=status.state.value.lower(),
                    numerical=numerical_verification,
                    engineering=engineering_checks,
                    mesh_quality=mesh_quality,
                    convergence=mesh_convergence,
                    fatigue=fatigue,
                    contact_diagnostics=contact_diagnostics,
                    connector_kinematics=connector_kinematics,
                    fmbd_dynamics=fmbd_dynamics,
                    values=result_values,
                    criteria=acceptance_criteria,
                    evidence_manifest=run_manifest,
                    expected_run_id=run_id,
                    base_dir=art_dir if result_source == "odb" else None,
                    physics_domain=domain_to_eval,
                    result_extractions=extractions if result_source == "odb" else None,
                    elastic_validity=effective_elastic,
                    stabilization_energy=stabilization_verdict_for_evidence,
                    stabilization_threshold=threshold,
                    stabilization_threshold_source=threshold_source,
                    stabilization_enabled=auto_stabilization_enabled,
                    dynamic_energy=dynamic_energy_verdict_for_evidence,
                    dynamic_energy_threshold=dynamic_energy_threshold,
                    dynamic_energy_threshold_source=dynamic_energy_threshold_source,
                    dynamic_energy_solver_product=dynamic_energy_solver_product,
                    dynamic_energy_enabled=auto_dynamic_energy_enabled,
                )
            else:
                accepted = evaluate_result_acceptance(
                    result_status=status.state.value.lower(),
                    numerical=numerical_verification,
                    engineering=engineering_checks,
                    mesh_quality=mesh_quality,
                    convergence=mesh_convergence,
                    fatigue=fatigue,
                    contact_diagnostics=contact_diagnostics,
                    connector_kinematics=connector_kinematics,
                    fmbd_dynamics=fmbd_dynamics,
                    values=result_values,
                    criteria=acceptance_criteria,
                    evidence=result_evidence,
                    evidence_manifest=run_manifest,
                    base_dir=art_dir if result_source == "odb" else None,
                    expected_run_id=run_id if result_source == "odb" else None,
                    require_evidence=effective_require_evidence,
                    physics_domain=domain_to_eval,
                    elastic_validity=effective_elastic,
                    stabilization_energy=stabilization_verdict_for_evidence,
                    stabilization_threshold=threshold,
                    stabilization_threshold_source=threshold_source,
                    stabilization_enabled=auto_stabilization_enabled,
                    dynamic_energy=dynamic_energy_verdict_for_evidence,
                    dynamic_energy_threshold=dynamic_energy_threshold,
                    dynamic_energy_threshold_source=dynamic_energy_threshold_source,
                    dynamic_energy_solver_product=dynamic_energy_solver_product,
                    dynamic_energy_enabled=auto_dynamic_energy_enabled,
                )
            verification_evidence = []
            if numerical_verification is not None:
                verification_evidence.append(Evidence(
                    kind="numerical_verification", source="verification",
                    locator=job_name, value=numerical_verification,
                ))
            if engineering_checks is not None:
                verification_evidence.append(Evidence(
                    kind="engineering_checks", source="verification",
                    locator=job_name, value=engineering_checks,
                ))
            if mesh_quality is not None:
                verification_evidence.append(Evidence(
                    kind="mesh_quality", source="verification",
                    locator=job_name, value=mesh_quality,
                ))
            if mesh_convergence is not None:
                verification_evidence.append(Evidence(
                    kind="mesh_convergence", source="verification",
                    locator=job_name, value=mesh_convergence,
                ))
            if fatigue is not None:
                verification_evidence.append(Evidence(
                    kind="fatigue", source="verification",
                    locator=job_name, value=fatigue,
                ))
            if contact_diagnostics is not None:
                verification_evidence.append(Evidence(
                    kind="contact_diagnostics", source="verification",
                    locator=job_name, value=contact_diagnostics,
                ))
            if connector_kinematics is not None:
                verification_evidence.append(Evidence(
                    kind="connector_kinematics", source="verification",
                    locator=job_name, value=connector_kinematics,
                ))
            if fmbd_dynamics is not None:
                verification_evidence.append(Evidence(
                    kind="fmbd_dynamics", source="verification",
                    locator=job_name, value=fmbd_dynamics,
                ))
            if stabilization_verdict_for_evidence is not None:
                verification_evidence.append(Evidence(
                    kind="stabilization_energy", source="odb",
                    locator=job_name, value=stabilization_verdict_for_evidence.to_dict(),
                ))
            if dynamic_energy_verdict_for_evidence is not None:
                verification_evidence.append(Evidence(
                    kind="dynamic_energy", source="odb",
                    locator=job_name, value=dynamic_energy_verdict_for_evidence.to_dict(),
                ))
            if sensitivity is not None:
                verification_evidence.append(Evidence(
                    kind="sensitivity", source="analysis",
                    locator=job_name, value=sensitivity,
                ))
            if uncertainty is not None:
                verification_evidence.append(Evidence(
                    kind="uncertainty", source="analysis",
                    locator=job_name, value=uncertainty,
                ))
            if run_manifest is not None:
                verification_evidence.append(Evidence(
                    kind="evidence_manifest_v2", source="manifest",
                    locator=job_name, value=run_manifest,
                ))
            evidence = EvidenceBundle((Evidence(
                kind="odb_summary", source="odb", locator=path, value=odb
            ), Evidence(
                kind="acceptance", source="acceptance", locator=job_name,
                value=accepted
            ))).extend(tuple(verification_evidence)).extend(result_evidence)
            verification_map = {}
            if numerical_verification is not None:
                verification_map["numerical"] = getattr(numerical_verification, "to_dict", lambda: str(numerical_verification))()
            if engineering_checks is not None:
                verification_map["engineering_checks"] = getattr(engineering_checks, "to_dict", lambda: str(engineering_checks))()
            if mesh_quality is not None:
                # A dict must not fall through to str(dict): the consumer reads
                # structured keys, and a repr string silently loses them.
                verification_map["mesh_quality"] = _structured_result_payload(mesh_quality)
            if locals().get("odb_check") and isinstance(odb_check, dict) and odb_check.get("mesh_metrics"):
                verification_map["mesh_metrics"] = odb_check["mesh_metrics"]
            if mesh_convergence is not None:
                verification_map["mesh_convergence"] = getattr(mesh_convergence, "to_dict", lambda: str(mesh_convergence))()
            if fatigue is not None:
                verification_map["fatigue"] = getattr(fatigue, "to_dict", lambda: str(fatigue))()
            if contact_diagnostics is not None:
                verification_map["contact_diagnostics"] = getattr(contact_diagnostics, "to_dict", lambda: str(contact_diagnostics))()

            if result_source == "external_input":
                final_state = AnalysisRunState.RESULTS_EXTRACTED
                status_value = EngineeringStatus.RESULT_SUSPICIOUS.value
                acceptance_passed = False
            elif accepted.passed and result_source == "odb":
                if require_production and not getattr(accepted, "deliverable", False):
                    final_state = AnalysisRunState.RESULTS_EXTRACTED
                    status_value = EngineeringStatus.RESULT_INVALID.value
                    acceptance_passed = False
                else:
                    final_state = AnalysisRunState.ACCEPTED
                    status_value = EngineeringStatus.RESULT_VALID.value
                    acceptance_passed = True
            else:
                final_state = AnalysisRunState.RESULTS_EXTRACTED
                status_value = EngineeringStatus.RESULT_INVALID.value
                acceptance_passed = False

            return run.with_state(
                final_state,
                engineering_status=status_value,
                acceptance_passed=acceptance_passed,
                acceptance=accepted,
                intent=engineering_intent,
                solver_selection=locals().get("selection"),
                postprocess_profile=postprocess_profile,
                action_plan=tuple(normalized_action_plan),
                verification=verification_map,
                evidence=evidence, artifacts=artifacts, metrics=run_metrics,
                metadata=dict(run.metadata, evidence_manifest=run_manifest) if run_manifest is not None else dict(run.metadata),
                extractions=tuple(extractions if result_source == "odb" else ()))
        except SolverSelectionBlocked as exc:
            artifacts = _collect_artifacts(self.executor, job_name, workdir=workdir)
            diagnostics = _collect_diagnostics(self.executor, job_name, workdir=workdir)
            blocked_selection = exc.selection
            failed_run = run.with_state(
                AnalysisRunState.FAILED,
                engineering_status=EngineeringStatus.SUBMISSION_BLOCKED.value,
                artifacts=artifacts,
                diagnostics=({
                    "error": str(exc),
                    "solver_selection_blocked": True,
                    "blocking_reasons": list(getattr(blocked_selection, "blocking_reasons", ()) or ()),
                    "solver": getattr(blocked_selection, "solver", ""),
                    "strategy": getattr(blocked_selection, "strategy", ""),
                    "solver_artifacts": diagnostics,
                },))
            _persist_ledger("FAILED", failed_run)
            return failed_run
        except Exception as exc:
            artifacts = _collect_artifacts(self.executor, job_name, workdir=workdir)
            diagnostics = _collect_diagnostics(self.executor, job_name, workdir=workdir)
            failed_run = run.with_state(
                AnalysisRunState.FAILED,
                engineering_status=EngineeringStatus.EXECUTION_FAILED.value,
                artifacts=artifacts,
                diagnostics=({"error": str(exc), "solver_artifacts": diagnostics},))
            _persist_ledger("FAILED", failed_run)
            return failed_run
        finally:
            if hasattr(self.executor, "workdir"):
                self.executor.workdir = orig_executor_workdir
            if orig_executor_workdir:
                try:
                    if hasattr(self.executor, "execute"):
                        self.executor.execute(f"import os; os.chdir({orig_executor_workdir!r})")
                except Exception:
                    pass


def _provenance_with_artifacts(provenance, artifacts):
    if provenance is None:
        return None
    manifest = tuple((getattr(a, "suffix", ""), getattr(a, "path", ""),
                      bool(getattr(a, "exists", False)), getattr(a, "size", None),
                      getattr(a, "modified_time", None)) for a in artifacts or ())
    inp_hash = provenance.input_hash
    output_hash = provenance.output_hash
    if not inp_hash or not output_hash:
        import hashlib
        for a in artifacts or ():
            suffix = getattr(a, "suffix", "")
            if suffix not in (".inp", ".odb") or not getattr(a, "exists", False):
                continue
            if suffix == ".inp" and inp_hash:
                continue
            if suffix == ".odb" and output_hash:
                continue
            p = getattr(a, "path", None)
            if not p or not os.path.isfile(p):
                continue
            try:
                with open(p, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                continue
            if suffix == ".inp" and not inp_hash:
                inp_hash = digest
            elif suffix == ".odb" and not output_hash:
                output_hash = digest
    updated = provenance.replace(
        input_hash=inp_hash,
        output_hash=output_hash,
        artifact_manifest_hash=stable_hash(manifest),
        metadata=dict(provenance.metadata),
    )
    if updated.metadata.get("agent_issued"):
        updated = attach_delivery_stamp(updated)
    return updated

def _submit_and_time(jobs, job_name, timeout, profiler):
    """Submit once and, if a profiler is attached, return how long the wait took.

    ``jobs.submit`` is called exactly once either way. The clock is read only when
    a profiler was supplied, so the default path does not even observe the time.
    A clock failure degrades to "wait not measured" rather than failing the job:
    the status is what the caller acts on, the duration is bookkeeping.
    """
    if profiler is None:
        return jobs.submit(job_name, wait=True, timeout=timeout), None
    started = time.monotonic()
    status = jobs.submit(job_name, wait=True, timeout=timeout)
    try:
        elapsed = time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 - clock failure is not a job failure
        note = getattr(profiler, "internal_errors", None)
        if isinstance(note, list):
            note.append(f"could not read clock after submit: {exc!r}")
        return status, None
    if elapsed < 0:
        # A backwards step would be rejected downstream and look like a bug in the
        # job. Report it as unmeasured instead.
        note = getattr(profiler, "internal_errors", None)
        if isinstance(note, list):
            note.append(f"clock moved backwards by {-elapsed:.6f}s during submit")
        return status, None
    return status, elapsed


def _record_solver_timing(profiler, wait_seconds, job_name, workdir):
    """Attach T4a/T4b to ``profiler``. Never raises into the run.

    Observation must not become a new way for a completed job to fail. Any error
    here -- a missing log, a profiler contract violation, a clock glitch -- is
    recorded on the profiler and otherwise ignored. The job outcome was already
    decided by ``jobs.submit`` before this is called.
    """
    try:
        from .solver_timing import attach_solver_timing, read_solver_timing

        log_path = os.path.join(workdir, f"{job_name}.log") if workdir else ""
        timing = read_solver_timing(log_path) if log_path else None
        if timing is None:
            # No workdir means there is no log to read. Say so explicitly rather
            # than letting a missing path look like a measured zero.
            from .solver_timing import SolverTiming, SolverTimingStatus
            timing = SolverTiming(
                status=SolverTimingStatus.FILE_MISSING,
                notes=("no workdir; job log path unknown",),
            )
        attach_solver_timing(profiler, wait_seconds, timing)
    except Exception as exc:  # noqa: BLE001 - profiling must not fail the run
        note = getattr(profiler, "internal_errors", None)
        if isinstance(note, list):
            note.append(f"solver timing not recorded: {exc!r}")


def _collect_diagnostics(executor, job_name, workdir=None):
    try:
        from .artifacts import inspect_job_diagnostics
        return inspect_job_diagnostics(executor, job_name, workdir=workdir)
    except Exception:
        return {}

def _structured_result_payload(item):
    """Return a verification payload that is always a mapping.

    `verification` is consumed by key, so a repr string is worse than useless:
    it looks like evidence and parses as none. Dicts and dataclasses both keep
    their fields; anything else is recorded as a typed, clearly unusable value.
    """
    import dataclasses as _dc

    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "to_dict"):
        try:
            payload = item.to_dict()
        except Exception as exc:
            return {"status": "not_run", "execution_error": "to_dict_failed:%s" % exc}
        if isinstance(payload, dict):
            return payload
    if _dc.is_dataclass(item):
        return _dc.asdict(item)
    return {"status": "not_run", "execution_error": "unsupported_result_type:%s" % type(item).__name__}


def _collect_artifacts(executor, job_name, workdir=None):
    try:
        from .artifacts import inspect_job_artifacts
        items = inspect_job_artifacts(executor, job_name, workdir=workdir).items
        if items and any(getattr(x, "exists", False) for x in items):
            return items
    except Exception:
        pass
    if workdir and os.path.isdir(workdir):
        from .artifacts import JobArtifact, DEFAULT_ARTIFACT_SUFFIXES
        local_items = []
        for sfx in DEFAULT_ARTIFACT_SUFFIXES:
            p = os.path.join(workdir, job_name + sfx)
            if os.path.exists(p):
                st = os.stat(p)
                local_items.append(JobArtifact(
                    job_name=job_name,
                    suffix=sfx,
                    path=p,
                    exists=True,
                    size=st.st_size,
                    modified_time=st.st_mtime,
                ))
        if local_items:
            return tuple(local_items)
    return ()


def _normalize_action_plan(action_plan):
    items = tuple(action_plan or ())
    if not items:
        return ()
    if all(isinstance(item, dict) for item in items):
        return items
    return _action_records(items)


def _runtime_provenance(executor):
    """Best-effort runtime metadata; absence never masquerades as verification."""
    try:
        if hasattr(executor, "runtime_info"):
            return executor.runtime_info()
    except Exception:
        return None
    return None


def _action_records(actions):
    records = []
    for action in actions or ():
        records.append({
            "action_type": getattr(action, "action_type", None),
            "model_name": getattr(action, "model_name", None),
            "target": getattr(action, "target", None),
            "parameters": dict(getattr(action, "parameters", {}) or {}),
        })
    return tuple(records)
