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
