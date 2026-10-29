from .contracts.sensitivity import SensitivityCase, SensitivityReport, SensitivityResult


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


def parse_sensitivity_request(intent):
    """Accept only an explicit one-factor-at-a-time screening request.

    A mesh-refinement curve is not a sensitivity study. Ranges are never invented.
    Each case must change exactly one sourced factor.
    """
    meta = getattr(intent, "metadata", None) or {}
    if not isinstance(meta, dict):
        return None, "not_requested"
    raw = meta.get("sensitivity_study")
    if not isinstance(raw, dict) or not raw.get("requested"):
        return None, "not_requested"
    if raw.get("kind") == "mesh_refinement":
        return None, "mesh_refinement_is_not_sensitivity"
    cases = raw.get("cases") or ()
    if not cases:
        return None, "sensitivity_refused:no_sourced_cases"
    accepted = []
    for case in cases:
        if not isinstance(case, dict):
            return None, "sensitivity_refused:case_not_declared"
        factors = case.get("factors") or case.get("parameters") or {}
        if not isinstance(factors, dict) or len(factors) != 1:
            return None, "sensitivity_refused:one_factor_only"
        name = next(iter(factors))
        spec = factors[name]
        if not isinstance(spec, dict) or not spec.get("source") or "value" not in spec:
            return None, "sensitivity_refused:missing_source:%s" % name
        accepted.append({
            "name": str(case.get("name") or name),
            "factor": str(name),
            "value": spec["value"],
            "source": str(spec["source"]),
            "scope": "local_screening",
        })
    return {
        "requested": True,
        "scope": "local_screening",
        "baseline_frozen": True,
        "cases": tuple(accepted),
        "not_global_uncertainty": True,
    }, None


def sensitivity_from_intent(intent):
    """Return a refusal or a frozen local-screening plan. Never launches a solve."""
    plan, reason = parse_sensitivity_request(intent)
    if plan is None and reason == "not_requested":
        return None
    if plan is None:
        return SensitivityReport(
            {},
            (SensitivityResult(
                case=SensitivityCase(name="rejected", parameters={}),
                values={},
                relative_changes={},
                status="refused",
                diagnostics=({'error': reason},),
            ),),
            (),
        )
    return plan


def execute_sensitivity(executor, runner, model_name, job_name, baseline_values,
                        cases, value_extractor, timeout=3600, case_applier=None):
    """Run declared sensitivity cases through the existing AnalysisRunner.

    This helper does not create a new orchestration layer. The caller supplies
    the runner and a result extractor, while each case remains explicit.
    """
    baseline = dict(baseline_values)
    if case_applier is None:
        return SensitivityReport(
            baseline, tuple(
                SensitivityResult(
                    case=case,
                    values={},
                    relative_changes={},
                    status="failed",
                    diagnostics=({"error": "case_applier is required to materialize sensitivity parameters"},),
                ) for case in build_sensitivity_cases(model_name, job_name, cases)
            ), ()
        )
    results = []
    for case in build_sensitivity_cases(model_name, job_name, cases):
        try:
            case_applier(executor, case)
            run = runner.run(
                case.model_name or model_name,
                case.job_name or ("%s_%s" % (job_name, case.name)),
                criteria=(),
                result_values=None,
                timeout=timeout,
            )
            values = dict(value_extractor(executor, run, case) or {})
            status = "completed" if run.state.value in ("accepted", "completed", "results_extracted", "odb_validated") else "failed"
            diagnostics = tuple(run.diagnostics or ())
            results.append(SensitivityResult(
                case=case,
                values=values,
                relative_changes={
                    key: relative_change(value, baseline[key])
                    for key, value in values.items()
                    if key in baseline
                },
                status=status,
                diagnostics=diagnostics,
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
