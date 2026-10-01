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
