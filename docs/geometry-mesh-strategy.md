# Geometry-aware meshing strategy

The geometry layer feeds mesh planning rather than directly mutating geometry.

\`\`\`text
Geometry grounding
  -> feature characterization
  -> engineering-critical regions
  -> mesh refinement plan
  -> local seed / partition candidate / feature review
  -> mesh generation
  -> quality
  -> convergence
\`\`\`

Key rules:
- Geometry identifies where refinement is possible; engineering intent identifies where it matters.
- Existing edges are preferred for local seeds.
- A region without a usable seedable edge becomes a partition candidate, not an automatic geometry mutation.
- Small geometry is a review signal, not an automatic deletion/refinement rule.
- Local refinement is not convergence evidence; convergence must verify the quantity of interest.
- Sharp corners can produce stress singularities, so mesh refinement alone must not be treated as physical peak-stress validation.

The current planner is deliberately runtime-neutral. Actual Abaqus B28 partition execution and curvature/proximity measurement remain machine-validation work.


## Existing mesh-contract bridge

```text
GeometryMeshPlan
  ├─ Edge/Region local_seed ──> LocalSeed ──> MeshSpecification
  └─ Face/Cell/etc. partition_then_seed ──> remains a partition candidate
```

A partition-required request is never silently downgraded to a seed on the unpartitioned geometry.

## Local convergence

Mesh convergence points may carry an optional `refinement_target`. A convergence policy can select one critical region, allowing a local refinement study to be evaluated independently from unrelated mesh changes. This does not turn local refinement into convergence evidence by itself: the solver must still produce the result points and the selected quantity must be engineering-relevant.



## Geometry feature characterization

The characterization layer is deliberately evidence-first. Current extraction provides size, centroid and normal; those fields alone are not sufficient to declare an entity a hole, fillet, thin wall or sharp corner. Therefore the classifier keeps such entities as `unknown` unless an upstream source explicitly supplies a feature kind and confidence. Optional curvature/radius/thickness/gap/aspect-ratio evidence is preserved when available.

This prevents a common failure mode: turning a small edge into an automatic geometry mutation simply because it is small. Engineering relevance may be supplied independently by a critical-region binding, and only then can mesh planning use it as a refinement driver.



## Mesh quality gate and convergence evidence

The mesh-quality stage now prefers Abaqus native verification over a hand-written geometric proxy. The executor can use `Part.verifyMeshQuality()` for native shape/size criteria such as aspect ratio, angular deviation, large/small corner angles, geometric deviation factor, and the solver/input-processor analysis checks. The result records aggregate metrics, violations, warnings, evidence, and failed/warning element counts. This keeps the agent aligned with the Abaqus mesh-verification semantics rather than silently inventing a universal quality score.

Two boundaries are deliberate:

- `min_jacobian` and the legacy `max_skew` fields are retained for contract compatibility, but are reported as unsupported/unmapped unless a native criterion or element-specific API is available.
- Mesh quality is a quality gate/evidence source, not convergence proof. A mesh can pass quality checks and still be too coarse for the engineering quantity of interest.

Mesh convergence now rejects duplicate mesh sizes, can carry result quantity/source and per-point quality status, and can optionally require all convergence points to have passed the mesh-quality gate. A failed quality gate prevents the result from being marked converged. This follows the engineering distinction between mesh quality and mesh-convergence evidence: NAFEMS recommends convergence studies based on the critical result at a defined location across increasing mesh density, while local refinement and transition regions can be used around the region of interest. citeturn0search4turn0search5

For Abaqus specifically, the native Verify Mesh workflow reports worst/average values and can identify elements failing shape, size, or analysis checks; Abaqus documentation also recommends changing seeds, partitions, or mesh technique before resorting to direct mesh editing. citeturn1search0turn1search1

B28 runtime verification remains deferred: the repository-side contract and script generation are closed, but the exact B28 behavior of every native verification criterion still needs a real Abaqus execution check.
