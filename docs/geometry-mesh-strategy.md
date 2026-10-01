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

