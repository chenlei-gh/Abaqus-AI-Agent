"""Small declarative engineering benchmark catalog.

The catalog defines what a benchmark must prove; it does not execute Abaqus.
Observed values must come from a real model/ODB workflow before a benchmark
result can be considered engineering evidence.
"""

from .contracts.benchmarks import BenchmarkCase


def standard_benchmarks():
    return (
        BenchmarkCase(
            name="linear_elastic_axial_bar",
            description=(
                "1D/3D linear-elastic axial loading case. Compare displacement "
                "with the analytical PL/(AE) reference and verify reaction balance."
            ),
            expected_actions=("material", "section", "static_step", "load", "boundary_condition"),
            acceptance=(
                {"value_key": "displacement_relative_error", "operator": "<=", "limit": 0.02},
                {"value_key": "reaction_balance_error", "operator": "<=", "limit": 0.01},
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
                {"value_key": "tip_displacement_relative_error", "operator": "<=", "limit": 0.05},
                {"value_key": "reaction_balance_error", "operator": "<=", "limit": 0.01},
            ),
        ),
        BenchmarkCase(
            name="gravity_static_balance",
            description=(
                "Static gravity case. Verify that the declared body force is "
                "balanced by the extracted support reaction."
            ),
            expected_actions=("material", "section", "static_step", "gravity", "boundary_condition"),
            acceptance=(
                {"value_key": "reaction_balance_error", "operator": "<=", "limit": 0.01},
            ),
        ),
    )
