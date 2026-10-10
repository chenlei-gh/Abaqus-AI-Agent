"""Adaptive Mesh Convergence Controller for closed-loop refinement."""

from __future__ import annotations

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
        self.base_mesh_spec = base_mesh_spec
        self.tolerance = tolerance
        self.max_levels = max(2, max_levels)
        self.refinement_ratio = max(0.1, min(0.9, refinement_ratio))
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

            last_run = run_obj
            probes.append(probe)

            if level >= 2:
                conv_result = evaluate_multi_level_mesh_convergence(
                    probes=probes,
                    stress_key=self.stress_key,
                    displacement_key=self.displacement_key,
                    theory_peak=self.theory_peak,
                    tolerance=self.tolerance,
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
                current_spec = self.next_mesh_spec(current_spec)

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
