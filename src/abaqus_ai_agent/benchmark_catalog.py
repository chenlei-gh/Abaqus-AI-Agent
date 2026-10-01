"""Small declarative engineering benchmark catalog.

The catalog defines benchmark expectations and deterministic ODB extraction
defaults. Model-specific target regions and independent reference values must
still be supplied explicitly before a run is accepted as benchmark evidence.
"""

from .contracts.benchmarks import BenchmarkCase


def standard_benchmarks():
    return (
        BenchmarkCase(
            name="linear_elastic_axial_bar",
            description=(
                "1D/3D linear-elastic axial loading case. Compare displacement "
                "with the analytical PL/(AE) reference and compare the declared reaction resultant."
            ),
            expected_actions=("material", "section", "static_step", "load", "boundary_condition"),
            acceptance=(
                {"value_key": "displacement_relative_error", "observed_value_key": "axial_displacement",
                 "metric": "relative_error", "operator": "<=", "limit": 0.02,
                 "result": {"field": "U", "invariant": "MAGNITUDE", "aggregation": "max",
                            "step": "Step-1"}},
                {"value_key": "reaction_balance_error", "observed_value_key": "reaction_resultant",
                 "metric": "relative_error", "operator": "<=", "limit": 0.01,
                 "result": {"field": "RF", "invariant": "MAGNITUDE", "aggregation": "max",
                            "step": "Step-1"}},
            ),
        ),
        BenchmarkCase(
            name="linear_elastic_cantilever",
            description=(
                "Small-strain cantilever with an end load. Compare tip displacement "
                "with PL^3/(3EI) and verify the declared reaction resultant."
            ),
            expected_actions=("material", "section", "static_step", "load", "boundary_condition"),
            acceptance=(
                {"value_key": "tip_displacement_relative_error", "observed_value_key": "tip_displacement",
                 "metric": "relative_error", "operator": "<=", "limit": 0.05,
                 "result": {"field": "U", "invariant": "MAGNITUDE", "aggregation": "max",
                            "step": "Step-1"}},
                {"value_key": "reaction_balance_error", "observed_value_key": "reaction_resultant",
                 "metric": "relative_error", "operator": "<=", "limit": 0.01,
                 "result": {"field": "RF", "invariant": "MAGNITUDE", "aggregation": "max",
                            "step": "Step-1"}},
            ),
        ),
        BenchmarkCase(
            name="gravity_static_balance",
            description=(
                "Static gravity case. Compare the extracted support reaction with the "
                "independently declared reaction reference."
            ),
            expected_actions=("material", "section", "static_step", "gravity", "boundary_condition"),
            acceptance=(
                {"value_key": "reaction_balance_error", "observed_value_key": "reaction_resultant",
                 "metric": "relative_error", "operator": "<=", "limit": 0.01,
                 "result": {"field": "RF", "invariant": "MAGNITUDE", "aggregation": "max",
                            "step": "Step-1"}},
            ),
        ),
    )
