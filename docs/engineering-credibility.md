# Engineering Credibility

The project treats engineering credibility as a chain of independently observable evidence.

## Layers

1. **Requirements** — what must be demonstrated.
2. **Model verification** — whether the model setup is internally consistent.
3. **Numerical verification** — whether the numerical solution is sufficiently resolved.
4. **Execution evidence** — whether the intended Abaqus job actually ran.
5. **Result verification** — whether required ODB quantities exist and are extracted deterministically.
6. **Engineering sanity checks** — force/energy/thermal/contact checks where applicable.
7. **Acceptance** — explicit requirement-specific criteria.
8. **Provenance** — enough metadata to reproduce and audit the run.

## Important boundary

A solver-completed job is not automatically an accepted engineering result.

The current contracts in this document are deterministic primitives. They do not claim that a generic check can prove physical correctness for every model.

## Planned execution-backed checks

The next real-Abaqus phases should connect these contracts to:

- reaction/load balance;
- energy balance;
- contact status and penetration;
- mesh and time convergence;
- sensitivity sweeps;
- tolerance-bound scenarios;
- benchmark models;
- reproducible run manifests.

No automatic correction should mutate engineering assumptions such as material, loads, boundary conditions, contact definitions, or geometry without an explicit policy/confirmation boundary.
