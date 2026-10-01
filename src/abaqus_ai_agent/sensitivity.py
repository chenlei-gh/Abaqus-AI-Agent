from .contracts.sensitivity import SensitivityReport, SensitivityResult


def relative_change(value, baseline):
    denominator = max(abs(float(baseline)), 1e-30)
    return (float(value) - float(baseline)) / denominator


def evaluate_sensitivity(baseline, cases):
    baseline = dict(baseline)
    results = []
    influence = {}
    for case in cases:
        changes = {
            key: relative_change(value, baseline[key])
            for key, value in case.values.items()
            if key in baseline
        }
        results.append(SensitivityResult(
            case=case.case,
            values=dict(case.values),
            relative_changes=changes,
            status=case.status,
        ))
        for key, change in changes.items():
            influence[key] = max(influence.get(key, 0.0), abs(change))
    ranking = tuple(sorted(influence.items(), key=lambda item: item[1], reverse=True))
    return SensitivityReport(baseline, tuple(results), ranking)


def build_sensitivity_cases(base_model, base_job, cases):
    """Normalize declared cases without executing or mutating engineering assumptions."""
    normalized = []
    for case in cases:
        normalized.append(
            case if case.model_name or case.job_name
            else type(case)(
                name=case.name,
                parameters=dict(case.parameters),
                model_name=base_model,
                job_name="%s_%s" % (base_job, case.name),
            )
        )
    return tuple(normalized)


def summarize_sensitivity_results(baseline, results):
    """Build a report from explicitly supplied run results."""
    return evaluate_sensitivity(baseline, tuple(results))


def execute_sensitivity(executor, runner, model_name, job_name, baseline_values,
                        cases, value_extractor, timeout=3600):
    """Run declared sensitivity cases through the existing AnalysisRunner.

    This helper does not create a new orchestration layer. The caller supplies
    the runner and a result extractor, while each case remains explicit.
    """
    baseline = dict(baseline_values)
    results = []
    for case in build_sensitivity_cases(model_name, job_name, cases):
        try:
            run = runner.run(
                case.model_name or model_name,
                case.job_name or ("%s_%s" % (job_name, case.name)),
                criteria=(),
                result_values=None,
                timeout=timeout,
            )
            execution_completed = run.state.value != "failed"
            try:
                values = dict(value_extractor(executor, run, case) or {})
                result_status = "available" if values else "unavailable"
            except Exception as exc:
                values = {}
                result_status = "error"
                extraction_error = {"error": str(exc), "stage": "result_extraction"}
            else:
                extraction_error = None

            acceptance_value = getattr(run, "acceptance_passed", None)
            acceptance_status = (
                "passed" if acceptance_value is True
                else "failed" if acceptance_value is False
                else "not_evaluated"
            )
            status = (
                "completed"
                if execution_completed and result_status == "available"
                else "failed"
            )
            diagnostics = list(run.diagnostics or ())
            if extraction_error:
                diagnostics.append(extraction_error)
            if acceptance_status == "failed":
                diagnostics.append({
                    "stage": "acceptance",
                    "acceptance_passed": False,
                })
            results.append(SensitivityResult(
                case=case,
                values=values,
                relative_changes={
                    key: relative_change(value, baseline[key])
                    for key, value in values.items()
                    if key in baseline
                },
                status=status,
                execution_status="completed" if execution_completed else "failed",
                result_status=result_status,
                acceptance_status=acceptance_status,
                diagnostics=tuple(diagnostics),
            ))
        except Exception as exc:
            results.append(SensitivityResult(
                case=case,
                values={},
                relative_changes={},
                status="failed",
                diagnostics=({"error": str(exc)},),
            ))
    return SensitivityReport(
        baseline,
        tuple(results),
        tuple(sorted(
            {
                key: max(
                    [abs(r.relative_changes[key]) for r in results if key in r.relative_changes] or [0.0]
                )
                for key in baseline
            }.items(),
            key=lambda item: item[1],
            reverse=True,
        )),
    )
