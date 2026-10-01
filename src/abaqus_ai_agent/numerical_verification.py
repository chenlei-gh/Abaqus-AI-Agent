import math
from dataclasses import replace

from .contracts.numerical import NumericalVerificationResult


def assess_singularity_interpretation(*, identified=False, basis="", local_values=(), global_values=()):
    """Classify explicit singularity evidence without guessing from mesh trends.

    A singularity is only treated as identified when the caller supplies an
    explicit basis. The helper never infers a singularity merely because a
    scalar result fails to converge.
    """
    local = tuple(float(v) for v in local_values)
    global_ = tuple(float(v) for v in global_values)
    if not identified:
        return {
            "status": "not_identified",
            "interpretation": "global",
            "basis": "",
            "local_trend": (),
            "global_trend": global_,
        }
    if not str(basis).strip():
        raise ValueError("singularity basis is required when identified=True")
    return {
        "status": "identified",
        "interpretation": "singularity_limited",
        "basis": str(basis),
        "local_trend": local,
        "global_trend": global_,
    }


def verify_series(name, values, tolerance):
    """Check successive result changes and return explicit verification method."""
    values = tuple(float(v) for v in values)
    tolerance = float(tolerance)
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if len(values) < 2:
        return NumericalVerificationResult(
            name=name,
            status="insufficient_data",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="successive_relative_change",
            message="at least two points are required",
        )
    reference = max(abs(values[-1]), 1e-30)
    error = abs(values[-1] - values[-2]) / reference
    status = "converged" if error <= tolerance else "not_converged"
    return NumericalVerificationResult(
        name=name,
        status=status,
        error=error,
        tolerance=tolerance,
        points=values,
        method="successive_relative_change",
        message="relative_change=%g" % error,
    )


def verify_richardson(name, values, refinement_ratio, tolerance, safety_factor=1.25):
    """Estimate observed order and fine-grid GCI from three refinements.

    Values must be ordered coarse -> medium -> fine and correspond to a
    constant mesh/time refinement ratio. This is numerical evidence only; it
    does not decide whether a mesh is physically adequate or whether a
    singularity invalidates the convergence interpretation.
    """
    values = tuple(float(v) for v in values)
    ratio = float(refinement_ratio)
    tolerance = float(tolerance)
    safety_factor = float(safety_factor)
    if ratio <= 1.0:
        raise ValueError("refinement_ratio must be > 1")
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if safety_factor <= 0:
        raise ValueError("safety_factor must be > 0")
    if len(values) < 3:
        return NumericalVerificationResult(
            name=name,
            status="insufficient_data",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="three refinement levels are required",
        )

    coarse, medium, fine = values[-3:]
    d21 = medium - coarse
    d32 = fine - medium
    if abs(d21) <= 1e-30 or abs(d32) <= 1e-30:
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="zero difference between refinement levels",
        )

    quotient = abs(d32 / d21)
    if quotient <= 0.0:
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="invalid refinement difference ratio",
        )

    observed_order = -math.log(quotient) / math.log(ratio)
    if observed_order <= 0.0 or not math.isfinite(observed_order):
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="observed order is not positive",
            observed_order=observed_order,
        )

    denominator = ratio ** observed_order - 1.0
    if abs(denominator) <= 1e-30:
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="GCI denominator is zero",
            observed_order=observed_order,
        )

    reference = max(abs(fine), 1e-30)
    extrapolated = fine + (fine - medium) / denominator
    gci = safety_factor * abs((fine - medium) / reference) / abs(denominator)
    status = "converged" if gci <= tolerance else "not_converged"
    return NumericalVerificationResult(
        name=name,
        status=status,
        error=gci,
        tolerance=tolerance,
        points=values,
        method="richardson_gci",
        message="observed_order=%g gci=%g" % (observed_order, gci),
        observed_order=observed_order,
        extrapolated_value=extrapolated,
        gci=gci,
    )


def execute_refinement_study(
    executor,
    runner,
    name,
    dimension,
    model_name,
    job_name,
    cases,
    criteria,
    tolerance,
    method="successive_relative_change",
    refinement_ratio=None,
    value_key=None,
    timeout=3600,
    singularity_evidence=None,
):
    """Execute mesh/time-step refinements through AnalysisRunner.

    Cases are ordered coarse -> fine by refinement_value. The value is only a
    declared refinement coordinate; an explicit action_plan is required to
    actually change the Abaqus model/step. Results are extracted through the
    existing AnalysisRunner criteria path. No new solver or extraction layer
    is introduced.
    """
    from .contracts.numerical import NumericalRefinementReport

    normalized = tuple(sorted(
        cases,
        key=lambda case: case.refinement_value,
        reverse=True,
    ))
    runs = []
    values = []

    for case in normalized:
        action_plan = tuple(case.action_plan or ())
        if not action_plan:
            runs.append({
                "case": case.name,
                "refinement_value": case.refinement_value,
                "status": "failed",
                "diagnostics": ({
                    "reason": "refinement_action_plan_required",
                    "dimension": dimension,
                },),
            })
            continue
        try:
            run = runner.run(
                case.model_name or model_name,
                case.job_name or ("%s_%s" % (job_name, case.name)),
                criteria=criteria,
                action_plan=action_plan,
                timeout=timeout,
            )
            if run.state.value == "failed":
                runs.append({
                    "case": case.name,
                    "refinement_value": case.refinement_value,
                    "status": "failed",
                    "run_id": run.id,
                    "diagnostics": tuple(run.diagnostics or ()),
                    "provenance": run.provenance,
                })
                continue

            observed = dict(run.metadata.get("result_values") or {})
            if value_key is None:
                if len(observed) != 1:
                    raise ValueError("value_key is required when refinement result is not unique")
                observed_value = next(iter(observed.values()))
            else:
                if value_key not in observed:
                    raise ValueError("missing refinement result: %s" % value_key)
                observed_value = observed[value_key]

            observed_value = float(observed_value)
            values.append(observed_value)
            runs.append({
                "case": case.name,
                "refinement_value": case.refinement_value,
                "status": "completed",
                "run_id": run.id,
                "value": observed_value,
                "acceptance_passed": run.acceptance_passed,
                "evidence": run.evidence,
                "provenance": run.provenance,
                "diagnostics": tuple(run.diagnostics or ()),
            })
        except Exception as exc:
            runs.append({
                "case": case.name,
                "refinement_value": case.refinement_value,
                "status": "failed",
                "diagnostics": ({"error": str(exc)},),
            })

    if len(values) < len(normalized):
        verification = NumericalVerificationResult(
            name=name,
            status="insufficient_data",
            error=float("inf"),
            tolerance=float(tolerance),
            points=tuple(values),
            method=method,
            message="one or more refinement cases failed",
        )
    elif method == "successive_relative_change":
        verification = verify_series(name, values, tolerance)
    elif method == "richardson_gci":
        if refinement_ratio is None:
            raise ValueError("refinement_ratio is required for richardson_gci")
        verification = verify_richardson(
            name, values, refinement_ratio, tolerance
        )
    else:
        raise ValueError("unsupported numerical refinement method: %s" % method)

    if singularity_evidence is not None:
        interpretation = assess_singularity_interpretation(**dict(singularity_evidence))
        verification = replace(
            verification,
            interpretation=interpretation["interpretation"],
            message="%s; interpretation=%s"
            % (verification.message, interpretation["interpretation"]),
        )

    return NumericalRefinementReport(
        name=name,
        dimension=dimension,
        cases=normalized,
        values=tuple(values),
        verification=verification,
        runs=tuple(runs),
    )
