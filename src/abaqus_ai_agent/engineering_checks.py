from .contracts.engineering_checks import EngineeringCheck, EngineeringCheckReport


# Declared check families only; numerical limits remain problem-specific.
STANDARD_ENGINEERING_CHECKS = {
    "static": (
        "global_equilibrium",
        "displacement_sanity",
        "stress_result_sanity",
        "energy_sanity",
    ),
    "dynamic": (
        "energy_balance",
        "kinetic_internal_energy",
        "time_step_evidence",
    ),
    "contact": (
        "contact_state",
        "contact_opening_pressure",
        "contact_reaction_consistency",
    ),
    "thermal": (
        "temperature_result_sanity",
        "thermal_energy_sanity",
    ),
    "coupled": (
        "temperature_result_sanity",
        "displacement_sanity",
        "thermal_mechanical_consistency",
    ),
}


def relative_error(actual, expected):
    denominator = max(abs(float(expected)), 1e-30)
    return abs(float(actual) - float(expected)) / denominator


def check_balance(name, actual, expected, tolerance, unit=""):
    error = relative_error(actual, expected)
    return EngineeringCheck(
        name=name,
        passed=error <= tolerance,
        actual=float(actual),
        expected=float(expected),
        tolerance=float(tolerance),
        unit=unit,
        message="relative_error=%g" % error,
    )


def evaluate_checks(checks, warnings=()):
    return EngineeringCheckReport(tuple(checks), tuple(warnings))


def check_load_balance(applied_load, reaction_load, tolerance, unit=""):
    """Check scalar equilibrium using the convention applied + reaction = 0."""
    return check_balance(
        "global_load_balance",
        float(reaction_load),
        -float(applied_load),
        tolerance,
        unit,
    )


def check_energy_ratio(numerator, denominator, tolerance, name="energy_ratio"):
    """Check an energy component ratio against a declared engineering limit."""
    denominator = abs(float(denominator))
    if denominator <= 1e-30:
        return EngineeringCheck(
            name, False, float(numerator), 0.0, float(tolerance), "",
            "zero energy denominator"
        )
    ratio = abs(float(numerator)) / denominator
    return EngineeringCheck(
        name, ratio <= float(tolerance), ratio, 0.0, float(tolerance),
        "ratio", "ratio=%g" % ratio
    )


def sum_reaction_components(field_values):
    """Sum RF field values explicitly; does not infer the applied load."""
    totals = [0.0, 0.0, 0.0]
    count = 0
    for item in field_values or ():
        data = item.get("data") if isinstance(item, dict) else item
        if isinstance(data, (int, float)):
            data = (data,)
        if not isinstance(data, (tuple, list)):
            continue
        for i in range(min(3, len(data))):
            if isinstance(data[i], (int, float)):
                totals[i] += float(data[i])
        if data:
            count += 1
    return {"components": tuple(totals), "count": count}


def check_declared_load_balance(applied_components, reaction_components,
                                tolerance, unit=""):
    """Compare declared applied-load components with extracted RF resultants.

    The engineering convention is:
        sum(applied) + sum(reaction) = 0

    Applied components must be supplied explicitly by the caller. This
    function never infers loads from the ODB or from model names.
    """
    if len(applied_components) != len(reaction_components):
        raise ValueError("applied/reaction component lengths must match")
    ref_scale = max([abs(float(x)) for x in applied_components] + [1.0])
    checks = []
    for i, (applied, reaction) in enumerate(
            zip(applied_components, reaction_components), 1):
        expected = -float(applied)
        actual = float(reaction)
        if abs(expected) > 1e-9:
            error = abs(actual - expected) / abs(expected)
        else:
            error = abs(actual - expected) / ref_scale
        checks.append(EngineeringCheck(
            name="global_load_balance_RF%d" % i,
            passed=error <= tolerance,
            actual=actual,
            expected=expected,
            tolerance=float(tolerance),
            unit=unit,
            message="relative_error=%g" % error,
        ))
    return evaluate_checks(tuple(checks))


def sum_scalar_flux(field_values):
    """Sum scalar RFL (reaction heat flux) values across nodes."""
    total = 0.0
    count = 0
    for item in field_values or ():
        data = item.get("data") if isinstance(item, dict) else item
        if isinstance(data, (int, float)):
            total += float(data)
            count += 1
        elif isinstance(data, (tuple, list)) and data and isinstance(data[0], (int, float)):
            total += float(data[0])
            count += 1
    return {"total": total, "count": count}


def check_thermal_flux_balance(total_reaction_flux, reference_flux=5000.0, tolerance=0.01, unit="mW"):
    """Check conservation of thermal energy: sum(RFL) should equal 0 in steady state."""
    ref_scale = max(abs(float(reference_flux)), 1.0)
    error = abs(float(total_reaction_flux)) / ref_scale
    passed = error <= tolerance
    check = EngineeringCheck(
        name="thermal_energy_balance_RFL",
        passed=passed,
        actual=float(total_reaction_flux),
        expected=0.0,
        tolerance=float(tolerance),
        unit=unit,
        message="relative_error=%g (ref_scale=%g)" % (error, ref_scale),
    )
    return evaluate_checks((check,))


def check_coulomb_friction_ratio(normal_force, friction_force, friction_coefficient, tolerance=0.05, unit=""):
    """Check that observed friction force ratio matches Coulomb friction law (|F_tangential| / |F_normal| = mu)."""
    norm = abs(float(normal_force))
    fric = abs(float(friction_force))
    if norm < 1e-9:
        raise ValueError("normal_force must be non-zero to evaluate friction ratio")
    actual_mu = fric / norm
    expected_mu = float(friction_coefficient)
    ref_scale = max(abs(expected_mu), 1.0)
    error = abs(actual_mu - expected_mu) / ref_scale
    passed = error <= tolerance
    check = EngineeringCheck(
        name="coulomb_friction_law",
        passed=passed,
        actual=actual_mu,
        expected=expected_mu,
        tolerance=float(tolerance),
        unit=unit,
        message="effective_mu=%g, expected_mu=%g (relative_error=%g)" % (actual_mu, expected_mu, error),
    )
    return evaluate_checks((check,))


def check_pendulum_kinematics(actual_period, expected_period, actual_max_omega, expected_max_omega,
                              period_tolerance=0.03, omega_tolerance=0.05):
    """Check oscillation period and maximum angular velocity against analytical physical pendulum theory."""
    t_act = float(actual_period)
    t_exp = float(expected_period)
    t_err = abs(t_act - t_exp) / t_exp
    t_passed = t_err <= period_tolerance
    check_t = EngineeringCheck(
        name="pendulum_oscillation_period",
        passed=t_passed,
        actual=t_act,
        expected=t_exp,
        tolerance=float(period_tolerance),
        unit="s",
        message="actual_period=%g s, expected_period=%g s (relative_error=%g)" % (t_act, t_exp, t_err),
    )

    w_act = float(actual_max_omega)
    w_exp = float(expected_max_omega)
    w_err = abs(w_act - w_exp) / w_exp
    w_passed = w_err <= omega_tolerance
    check_w = EngineeringCheck(
        name="pendulum_max_angular_velocity",
        passed=w_passed,
        actual=w_act,
        expected=w_exp,
        tolerance=float(omega_tolerance),
        unit="rad/s",
        message="actual_max_omega=%g rad/s, expected_max_omega=%g rad/s (relative_error=%g)" % (w_act, w_exp, w_err),
    )
    return evaluate_checks((check_t, check_w))


def check_mechanical_energy_conservation(energy_loss, initial_energy, tolerance=0.03, unit="mJ"):
    """Check that mechanical energy dissipation/loss remains bounded in undamped free vibration."""
    loss = abs(float(energy_loss))
    e0 = max(abs(float(initial_energy)), 1e-6)
    ratio = loss / e0
    passed = ratio <= tolerance
    check = EngineeringCheck(
        name="mechanical_energy_conservation",
        passed=passed,
        actual=ratio,
        expected=0.0,
        tolerance=float(tolerance),
        unit=unit,
        message="energy_fluctuation_ratio=%g (loss=%g %s, ref_energy=%g %s)" % (ratio, loss, unit, e0, unit),
    )
    return evaluate_checks((check,))


def check_revolute_joint_kinematics(joint_drift_max, joint_drift_tolerance=1e-3,
                                    relative_rotation_max=None, min_relative_rotation=0.01,
                                    unit_length="mm", unit_angle="rad"):
    """Check revolute connector kinematic continuity (zero translational drift) and articulation."""
    drift_act = float(joint_drift_max)
    drift_tol = float(joint_drift_tolerance)
    drift_passed = drift_act <= drift_tol
    check_drift = EngineeringCheck(
        name="revolute_joint_drift",
        passed=drift_passed,
        actual=drift_act,
        expected=0.0,
        tolerance=drift_tol,
        unit=unit_length,
        message="max_joint_drift=%g %s (tolerance=%g %s)" % (drift_act, unit_length, drift_tol, unit_length),
    )
    checks = [check_drift]

    if relative_rotation_max is not None:
        rel_act = float(relative_rotation_max)
        min_rel = float(min_relative_rotation)
        rel_passed = rel_act >= min_rel
        check_rel = EngineeringCheck(
            name="revolute_relative_articulation",
            passed=rel_passed,
            actual=rel_act,
            expected=min_rel,
            tolerance=0.0,
            unit=unit_angle,
            message="max_relative_rotation=%g %s (min_required=%g %s)" % (rel_act, unit_angle, min_rel, unit_angle),
        )
        checks.append(check_rel)

    return evaluate_checks(tuple(checks))


def check_double_pendulum_kinematics(actual_period, expected_period, period_tolerance=0.05):
    """Check double pendulum fundamental period against analytical Lagrangian small-angle theory."""
    t_act = float(actual_period)
    t_exp = float(expected_period)
    t_err = abs(t_act - t_exp) / t_exp
    t_passed = t_err <= period_tolerance
    check_t = EngineeringCheck(
        name="double_pendulum_fundamental_period",
        passed=t_passed,
        actual=t_act,
        expected=t_exp,
        tolerance=float(period_tolerance),
        unit="s",
        message="actual_period=%g s, expected_period=%g s (relative_error=%g)" % (t_act, t_exp, t_err),
    )
    return evaluate_checks((check_t,))
