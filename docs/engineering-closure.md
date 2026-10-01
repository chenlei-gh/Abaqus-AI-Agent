# Engineering Closure

This document records the engineering-credibility work that can be completed independently of a licensed Abaqus runtime.

## Evidence chain

The intended result path is:

```
intent
  -> plan
  -> validated actions
  -> execution
  -> job/ODB evidence
  -> numerical verification
  -> engineering sanity checks
  -> declared acceptance
  -> provenance
```

A successful Python invocation is not treated as solver success, and solver completion is not treated as engineering acceptance.

## Completed foundations

- deterministic result acceptance with explicit solver-status gating;
- engineering load/reaction balance using the convention
  `sum(applied) + sum(reaction) = 0`;
- energy-ratio sanity checks;
- contact field/history evidence with explicit missing and ambiguous states;
- reaction-force field/history evidence;
- standard energy-history evidence;
- stable provenance hashing and artifact-manifest hashing;
- bounded deterministic parameter identification/calibration;
- empirical reliability and two-parameter Weibull MLE with right censoring;
- sensitivity, uncertainty, benchmark, numerical-verification and bounded-correction contracts;
- explicit repair authorization when a repair candidate requires confirmation;
- unit-system and dimensional consistency primitives;
- conservative B28 smoke harness and executor integration.

## Current limitations

### Numerical verification

The verifier includes successive relative change and Richardson/GCI, plus executable element-size/time-step refinement studies through AnalysisRunner. Singularity interpretation is explicit-evidence-only; physical adequacy remains problem-specific.

### Benchmarks

Benchmark contracts and deterministic evaluation exist. A licensed Abaqus runtime is still required to populate benchmark observations from real solver runs.

### Provenance

The normal analysis path now records executor/runtime metadata, a model-snapshot hash when a snapshot is available, and the generated output-action plan. Artifact-manifest hashing remains a metadata hash (path, existence, size and modification time); solver/model byte hashes are deliberately left unset unless a future executor can provide them reliably.

### Controlled correction

Repair candidates are policy-filtered, and confirmation is an explicit execution gate. Engineering assumptions such as material, load, boundary condition, contact or geometry are not silently mutated.

## Next non-runtime work

Completed in the current non-runtime closure tranche:

1. declarative engineering benchmark catalog;
2. Richardson/GCI numerical verification primitive;
3. RF/energy evidence-to-engineering-check adapters;
4. explicit repair authorization gate;
5. bounded sensitivity execution through the existing AnalysisRunner;
6. runtime-aware provenance population;
7. unit/dimensional validation at planning and result-requirement boundaries;
8. bounded standard engineering-check families.

Remaining non-runtime work is deliberately limited to broader problem-specific engineering evidence: FORM/SORM, Bayesian inference, critical-plane/non-proportional fatigue, and future release-specific validation. Benchmark, uncertainty, numerical-refinement, controlled-correction, bounded calibration, and bounded reliability execution paths are implemented.

## Deferred runtime validation

The B28 smoke harness must still be executed on an actual Abaqus V5 R2018/B28 installation. Until then, B28 compatibility remains unverified.


### Fatigue post-processing

Fatigue post-processing is implemented for existing scalar Abaqus stress histories: Rainflow cycle counting with half/full-cycle weights, explicit range/amplitude/mean semantics, Goodman, Gerber, Soderberg and Walker mean-stress corrections, log-log S-N interpolation, and Palmgren-Miner damage. Critical-plane and non-proportional multiaxial fatigue criteria remain outside the implemented scope.
