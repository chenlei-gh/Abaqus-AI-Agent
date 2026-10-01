from .contracts.uncertainty import UncertaintyReport


def build_uncertainty_scenarios(base_model, base_job, scenarios):
    """Normalize scenario identity without applying parameter assumptions.

    Parameter values are metadata unless the scenario supplies an explicit
    action_plan that mutates the model. This prevents the execution layer from
    claiming that an uncertainty value was applied when no executable change
    was declared.
    """
    normalized = []
    for scenario in scenarios:
        normalized.append(
            type(scenario)(
                name=scenario.name,
                parameters=dict(scenario.parameters),
                model_name=scenario.model_name or base_model,
                job_name=scenario.job_name or "%s_%s" % (base_job, scenario.name),
                action_plan=tuple(scenario.action_plan or ()),
            )
        )
    return tuple(normalized)


def aggregate_uncertainty_outputs(outputs):
    """Aggregate completed numerical scenario outputs as deterministic bounds."""
    completed = [item for item in outputs if item.get("status") == "completed"]
    keys = sorted({
        key
        for item in completed
        for key, value in (item.get("values") or {}).items()
        if isinstance(value, (int, float))
    })
    aggregated = []
    for key in keys:
        values = [
            float(item["values"][key])
            for item in completed
            if isinstance(item.get("values", {}).get(key), (int, float))
        ]
        lower, upper = min(values), max(values)
        aggregated.append({
            "value_key": key,
            "min": lower,
            "max": upper,
            "mean": sum(values) / float(len(values)),
            "range": upper - lower,
            "count": len(values),
        })
    return tuple(aggregated)


def execute_uncertainty(
    executor,
    runner,
    model_name,
    job_name,
    scenarios,
    criteria=(),
    scenario_action_plans=None,
    timeout=3600,
):
    """Execute explicit uncertainty scenarios through AnalysisRunner.

    Every scenario must have an executable action plan, either on the scenario
    itself or in scenario_action_plans keyed by scenario name. The parameter
    dictionary records the declared uncertainty input; the action plan is the
    authority for actually applying it to the model.
    """
    normalized = build_uncertainty_scenarios(model_name, job_name, scenarios)
    plans = dict(scenario_action_plans or {})
    outputs = []

    for scenario in normalized:
        action_plan = tuple(scenario.action_plan or plans.get(scenario.name, ()) or ())
        if not action_plan:
            outputs.append({
                "scenario": scenario.name,
                "parameters": dict(scenario.parameters),
                "model_name": scenario.model_name,
                "job_name": scenario.job_name,
                "status": "failed",
                "values": {},
                "diagnostics": ({
                    "reason": "scenario_action_plan_required",
                    "message": "uncertainty parameters are declarative; an explicit action plan is required to apply them",
                },),
            })
            continue

        try:
            run = runner.run(
                scenario.model_name or model_name,
                scenario.job_name or ("%s_%s" % (job_name, scenario.name)),
                criteria=criteria,
                result_values=None,
                action_plan=action_plan,
                environment={
                    "uncertainty_scenario": scenario.name,
                    "uncertainty_parameters": dict(scenario.parameters),
                },
                timeout=timeout,
            )
            if run.state.value == "failed":
                outputs.append({
                    "scenario": scenario.name,
                    "parameters": dict(scenario.parameters),
                    "model_name": scenario.model_name,
                    "job_name": scenario.job_name,
                    "status": "failed",
                    "values": {},
                    "run_id": run.id,
                    "provenance": run.provenance,
                    "diagnostics": tuple(run.diagnostics or ()),
                })
                continue

            values = dict(run.metadata.get("result_values") or {})
            if not values and criteria and run.odb_path:
                from .execution.results import extract_criteria
                values, _ = extract_criteria(executor, run.odb_path, criteria)
            if criteria and not values:
                raise ValueError("uncertainty scenario produced no result values")

            outputs.append({
                "scenario": scenario.name,
                "parameters": dict(scenario.parameters),
                "model_name": scenario.model_name,
                "job_name": scenario.job_name,
                "status": "completed",
                "values": values,
                "run_id": run.id,
                "provenance": run.provenance,
                "acceptance_passed": run.acceptance_passed,
                "evidence": run.evidence,
                "diagnostics": tuple(run.diagnostics or ()),
            })
        except Exception as exc:
            outputs.append({
                "scenario": scenario.name,
                "parameters": dict(scenario.parameters),
                "model_name": scenario.model_name,
                "job_name": scenario.job_name,
                "status": "failed",
                "values": {},
                "diagnostics": ({"error": str(exc)},),
            })

    return UncertaintyReport(
        scenarios=normalized,
        outputs=tuple(outputs),
        method="tolerance_bounds",
    ), aggregate_uncertainty_outputs(outputs)


def sample_uniform_parameters(parameters, sample_count, seed=0):
    """Generate reproducible uniform samples from explicit parameter bounds."""
    import random
    if int(sample_count) < 1:
        raise ValueError("sample_count must be positive")
    params = tuple(parameters)
    if not params:
        raise ValueError("parameters must not be empty")
    rng = random.Random(seed)
    return tuple(
        {
            parameter.name: float(parameter.lower)
            + rng.random() * (float(parameter.upper) - float(parameter.lower))
            for parameter in params
        }
        for _ in range(int(sample_count))
    )


def summarize_probabilistic_outputs(outputs, quantiles=(0.05, 0.5, 0.95)):
    """Summarize completed outputs without assuming a fitted distribution."""
    completed = [item for item in outputs if item.get("status") == "completed"]
    if not completed:
        return ()
    result = []
    keys = sorted({
        key for item in completed
        for key, value in (item.get("values") or {}).items()
        if isinstance(value, (int, float))
    })
    for key in keys:
        values = sorted(
            float(item["values"][key])
            for item in completed
            if isinstance(item.get("values", {}).get(key), (int, float))
        )
        n = len(values)
        mean = sum(values) / n
        variance = sum((value - mean) ** 2 for value in values) / n
        quantile_values = {}
        for q in quantiles:
            q = float(q)
            if not 0.0 <= q <= 1.0:
                raise ValueError("quantiles must be between 0 and 1")
            position = q * (n - 1)
            lo = int(position)
            hi = min(lo + 1, n - 1)
            fraction = position - lo
            quantile_values[str(q)] = values[lo] + fraction * (values[hi] - values[lo])
        result.append({
            "value_key": key,
            "count": n,
            "mean": mean,
            "stddev_population": variance ** 0.5,
            "min": values[0],
            "max": values[-1],
            "quantiles": quantile_values,
        })
    return tuple(result)


def execute_probabilistic_uncertainty(
    executor, runner, model_name, job_name, parameters, sample_count,
    action_plan_factory, criteria=(), seed=0, timeout=3600,
):
    """Execute reproducible uniform samples through the existing AnalysisRunner."""
    if not callable(action_plan_factory):
        raise TypeError("action_plan_factory must be callable")
    samples = sample_uniform_parameters(parameters, sample_count, seed=seed)
    scenarios = tuple(
        UncertaintyScenario(
            name="sample_%04d" % index,
            parameters=dict(sample),
            model_name=model_name,
            job_name="%s_sample_%04d" % (job_name, index),
            action_plan=tuple(action_plan_factory(dict(sample))),
        )
        for index, sample in enumerate(samples, 1)
    )
    report, _ = execute_uncertainty(
        executor, runner, model_name, job_name, scenarios,
        criteria=criteria, timeout=timeout,
    )
    return report, summarize_probabilistic_outputs(report.outputs)
