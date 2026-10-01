# AI / Agent Capability Boundary

## Purpose

The Agent and the AI are deliberately allowed to overlap in what they can
describe or generate. The boundary is **authority and evidence**, not raw
problem-solving ability.

- **AI** may interpret intent, reason about engineering choices, draft native
  Abaqus Python, explain limitations, and propose a path.
- **Agent** provides the controlled execution surface: typed Actions,
  validation, execution, deterministic inspection, verification, Evidence,
  and acceptance evaluation against explicitly supplied criteria.
- **Abaqus** remains the native execution/solver environment.
- **Human engineering judgment** supplies requirements, missing assumptions,
  and final responsibility for engineering decisions.

Therefore:

> AI being able to generate an operation does not make that operation a
> formally supported Agent capability.

## Capability states

| State | Meaning | What the Agent may claim |
|---|---|---|
| SUPPORTED | Typed Action plus explicit validation/execution path; downstream result/evidence semantics exist where applicable. | The Agent supports the operation. |
| EXECUTABLE | The native Python escape hatch can execute it, but the Agent does not own the operation's full domain semantics. | The Agent can execute it, **not** that the engineering operation is verified. |
| ASSISTED | AI can reason or prepare the operation, but the Agent has no reliable execution path. | Planning/proposal assistance only. |
| UNSUPPORTED | No reliable Agent execution path exists. | Do not claim completion. |
| BLOCKED | A path exists in principle, but required runtime/data/evidence is unavailable. | Report the blocker; do not silently downgrade. |

The Python enum names EXECUTABLE as "executable_unverified" to prevent it being
mistaken for engineering verification.

## Practical routing rule

    User Engineering Intent
            |
            v
           AI
            |
            v
     Capability Boundary
       +----+---------+----------------+
       |              |                |
    SUPPORTED     EXECUTABLE       ASSISTED /
       |              |             UNSUPPORTED
    Typed Action   Native Python       |
       |              |               |
    Validation      limited          proposal /
       |             semantics       explanation
    Execution         |
       |             Execution
    Verification      |
       |             raw execution evidence
       |             != domain correctness
       v
    Acceptance against declared criteria
       |
       v
    Evidence / Report

The important rule is that AI should not silently bypass the Agent execution
boundary for model mutations. When a missing typed capability can be handled
through native Abaqus Python, it should cross the boundary explicitly as
EXECUTABLE, with its weaker semantic status preserved.

## When the Agent cannot do something but AI can

Do not create a fake typed capability just because an LLM can produce
working-looking Python.

Use this progression:

1. Try SUPPORTED if the operation already has a typed Action and the required
   validation/evidence path exists.
2. Use EXECUTABLE when the native Abaqus API can perform the operation but no
   typed semantic contract exists yet.
3. Use ASSISTED when AI can prepare the solution but no safe execution boundary
   exists.
4. Use BLOCKED when execution is possible in principle but runtime, input, or
   required evidence is missing.
5. Promote EXECUTABLE to SUPPORTED only after adding the missing semantic
   contract, validation, deterministic result semantics, and tests; release-
   specific behavior still requires real Abaqus validation.

This keeps the Escape Hatch useful without turning it into a loophole that
inflates the project's capability claims.

## Evidence hierarchy

    API invocation
        != model-state evidence
        != Job execution evidence
        != solver artifact evidence
        != ODB evidence
        != result evidence
        != engineering acceptance evidence

A successful python_action therefore proves, at most, that the requested
native Python crossed the execution boundary successfully. It does not by
itself prove that the model is correct, the solver succeeded, the intended
result exists, or an engineering requirement is satisfied.

## Promotion rule

A new typed capability should normally have:

- an explicit AbaqusAction contract;
- a Builder or equivalent construction path;
- deterministic input validation;
- native script generation;
- a deterministic observation/result path when the operation has a result;
- Evidence semantics;
- tests;
- documented release/runtime limitations;
- real B28 validation before claiming B28 compatibility.

This is deliberately a contract boundary, not a new orchestration or
governance service.
