"""Adaptive Mesh Convergence Controller for closed-loop refinement."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..contracts.convergence import (
    MultiLevelConvergenceResult,
    evaluate_multi_level_mesh_convergence,
)
from ..contracts.mesh import LocalSeed
from ..planning.compiler import IntentMeshSpec


@dataclass(frozen=True)
class AdaptiveConvergenceRun:
    """Outcome of an adaptive multi-level mesh refinement loop."""
    status: str                                  # "CONVERGED", "BUDGET_EXHAUSTED", "SINGULARITY_STOPPED", "ERROR"
    levels_executed: int
    final_mesh_spec: IntentMeshSpec
    convergence_result: MultiLevelConvergenceResult
    probes: Tuple[Dict[str, Any], ...]
    final_run: Optional[Any] = None
    diagnostics: Tuple[str, ...] = ()

    @property
    def is_converged(self) -> bool:
        return self.status == "CONVERGED" and self.convergence_result.converged


class AdaptiveMeshConvergenceController:
    """Controller that drives progressive mesh refinement until convergence or budget exhaustion."""

    def __init__(
        self,
        base_mesh_spec: IntentMeshSpec,
        tolerance: float = 0.05,
        max_levels: int = 4,
        refinement_ratio: float = 0.5,
        refinement_target: str = "auto",         # "auto", "local", "global", "both"
        stress_key: str = "peak_s11",
        displacement_key: str = "max_u1",
        theory_peak: Optional[float] = None,
        min_seed_size: float = 0.05,
    ) -> None:
        if not math.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError(f"tolerance must be a positive finite float, got {tolerance}")
        if not isinstance(max_levels, int) or max_levels < 2:
            raise ValueError(f"max_levels must be an integer >= 2, got {max_levels}")
        if not math.isfinite(refinement_ratio) or not (0.0 < refinement_ratio < 1.0):
            raise ValueError(f"refinement_ratio must be a finite float strictly in (0.0, 1.0), got {refinement_ratio}")
        if not math.isfinite(min_seed_size) or min_seed_size <= 0.0:
            raise ValueError(f"min_seed_size must be a positive finite float, got {min_seed_size}")
        if theory_peak is not None and not math.isfinite(theory_peak):
            raise ValueError(f"theory_peak must be a finite float if provided, got {theory_peak}")

        self.base_mesh_spec = base_mesh_spec
        self.tolerance = tolerance
        self.max_levels = max_levels
        self.refinement_ratio = refinement_ratio
        self.refinement_target = refinement_target
        self.stress_key = stress_key
        self.displacement_key = displacement_key
        self.theory_peak = theory_peak
        self.min_seed_size = min_seed_size

    def next_mesh_spec(self, current_spec: IntentMeshSpec) -> IntentMeshSpec:
        """Derive the refined mesh specification for the next convergence iteration."""
        refine_local = (
            self.refinement_target in ("local", "both")
            or (self.refinement_target == "auto" and bool(current_spec.local_seeds))
        )
        refine_global = (
            self.refinement_target in ("global", "both")
            or (self.refinement_target == "auto" and not current_spec.local_seeds)
        )

        new_local_seeds: List[LocalSeed] = []
        if refine_local and current_spec.local_seeds:
            for seed in current_spec.local_seeds:
                if seed.size is not None:
                    next_size = max(self.min_seed_size, round(seed.size * self.refinement_ratio, 4))
                    new_local_seeds.append(
                        LocalSeed(
                            region_expression=seed.region_expression,
                            size=next_size,
                            constraint=seed.constraint,
                        )
                    )
                elif seed.number is not None:
                    next_num = int(round(seed.number / self.refinement_ratio))
                    new_local_seeds.append(
                        LocalSeed(
                            region_expression=seed.region_expression,
                            number=next_num,
                            constraint=seed.constraint,
                        )
                    )
                else:
                    new_local_seeds.append(seed)
        else:
            new_local_seeds = list(current_spec.local_seeds)

        new_global_size = current_spec.global_size
        if refine_global and current_spec.global_size is not None:
            new_global_size = max(self.min_seed_size, round(current_spec.global_size * self.refinement_ratio, 4))

        return IntentMeshSpec(
            element_type=current_spec.element_type,
            global_size=new_global_size,
            local_seeds=tuple(new_local_seeds),
            deviation_factor=current_spec.deviation_factor,
            element_library=current_spec.element_library,
        )

    def execute_loop(
        self,
        step_runner: Callable[[int, IntentMeshSpec], Tuple[Any, Dict[str, Any]]],
    ) -> AdaptiveConvergenceRun:
        """Execute the adaptive refinement loop.

        Args:
            step_runner: Callback function (level_index, mesh_spec) -> (run_object, probe_dict).
        """
        current_spec = self.base_mesh_spec
        probes: List[Dict[str, Any]] = []
        last_run: Optional[Any] = None
        diagnostics: List[str] = []

        conv_result = evaluate_multi_level_mesh_convergence(
            probes=(),
            stress_key=self.stress_key,
            displacement_key=self.displacement_key,
            theory_peak=self.theory_peak,
            tolerance=self.tolerance,
            min_levels=3,
        )

        for level in range(1, self.max_levels + 1):
            try:
                run_obj, probe = step_runner(level, current_spec)
            except Exception as e:
                diagnostics.append(f"Level {level} execution failed: {e}")
                return AdaptiveConvergenceRun(
                    status="ERROR",
                    levels_executed=level - 1,
                    final_mesh_spec=current_spec,
                    convergence_result=conv_result,
                    probes=tuple(probes),
                    final_run=last_run,
                    diagnostics=tuple(diagnostics),
                )

            if not isinstance(probe, dict) or not probe:
                diagnostics.append(f"Level {level} returned invalid or empty probe dictionary.")
                return AdaptiveConvergenceRun(
                    status="ERROR",
                    levels_executed=level - 1,
                    final_mesh_spec=current_spec,
                    convergence_result=conv_result,
                    probes=tuple(probes),
                    final_run=last_run,
                    diagnostics=tuple(diagnostics),
                )

            last_run = run_obj
            # Ensure physical mesh metric is attached to probe if step_runner did not supply one
            has_mesh_metric = any(
                k in probe for k in ("seed_size", "mesh_size", "global_size", "total_elements", "total_nodes")
            )
            if not has_mesh_metric:
                if current_spec.local_seeds and current_spec.local_seeds[0].size is not None:
                    probe["seed_size"] = current_spec.local_seeds[0].size
                elif current_spec.global_size is not None:
                    probe["global_size"] = current_spec.global_size

            probes.append(probe)

            if level >= 2:
                conv_result = evaluate_multi_level_mesh_convergence(
                    probes=probes,
                    stress_key=self.stress_key,
                    displacement_key=self.displacement_key,
                    theory_peak=self.theory_peak,
                    tolerance=self.tolerance,
                    min_levels=3,
                )

                if conv_result.status == "INCOMPLETE_EVIDENCE":
                    diagnostics.append(
                        f"Level {level} produced incomplete or invalid convergence evidence: {conv_result.diagnostics}"
                    )
                    return AdaptiveConvergenceRun(
                        status="ERROR",
                        levels_executed=level,
                        final_mesh_spec=current_spec,
                        convergence_result=conv_result,
                        probes=tuple(probes),
                        final_run=last_run,
                        diagnostics=tuple(diagnostics),
                    )

                if conv_result.converged:
                    diagnostics.append(f"Convergence achieved at level {level} (final delta={conv_result.final_delta_pct}%).")
                    return AdaptiveConvergenceRun(
                        status="CONVERGED",
                        levels_executed=level,
                        final_mesh_spec=current_spec,
                        convergence_result=conv_result,
                        probes=tuple(probes),
                        final_run=last_run,
                        diagnostics=tuple(diagnostics),
                    )

                if conv_result.status == "SINGULARITY_SUSPECTED":
                    diagnostics.append(f"Refinement terminated at level {level} due to suspected stress singularity.")
                    return AdaptiveConvergenceRun(
                        status="SINGULARITY_STOPPED",
                        levels_executed=level,
                        final_mesh_spec=current_spec,
                        convergence_result=conv_result,
                        probes=tuple(probes),
                        final_run=last_run,
                        diagnostics=tuple(diagnostics),
                    )

            if level < self.max_levels:
                next_spec = self.next_mesh_spec(current_spec)
                # Check for refinement stagnation (hitting min_seed_size)
                if next_spec == current_spec:
                    diagnostics.append(
                        f"Refinement stagnated at level {level}: mesh specification did not change (hit min_seed_size {self.min_seed_size})."
                    )
                    return AdaptiveConvergenceRun(
                        status="REFINEMENT_STAGNATED",
                        levels_executed=level,
                        final_mesh_spec=current_spec,
                        convergence_result=conv_result,
                        probes=tuple(probes),
                        final_run=last_run,
                        diagnostics=tuple(diagnostics),
                    )
                current_spec = next_spec

        diagnostics.append(
            f"Maximum refinement levels ({self.max_levels}) reached without achieving {self.tolerance * 100.0}% convergence."
        )
        return AdaptiveConvergenceRun(
            status="BUDGET_EXHAUSTED",
            levels_executed=self.max_levels,
            final_mesh_spec=current_spec,
            convergence_result=conv_result,
            probes=tuple(probes),
            final_run=last_run,
            diagnostics=tuple(diagnostics),
        )
