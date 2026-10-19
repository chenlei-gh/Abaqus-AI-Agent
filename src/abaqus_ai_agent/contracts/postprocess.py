from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PostProcessingProfile:
    """Deterministic post-processing requirements associated with an analysis strategy."""
    name: str
    required_results: Tuple[str, ...] = ()
    history_variables: Tuple[str, ...] = ()
    checks: Tuple[str, ...] = ()
    plots: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
    history_step: str = "Step-1"


def profile_for_solver_selection(selection):
    strategy = getattr(selection, "strategy", "")
    if strategy == "STATIC_GENERAL":
        return PostProcessingProfile(
            "static_structural",
            ("max_mises", "max_displacement", "max_reaction_force"),
            (),
            ("reaction_balance",),
            ("stress_contour", "displacement_contour"),
            (),
            "Step-1",
        )
    if strategy == "QUASI_STATIC_EXPLICIT":
        return PostProcessingProfile(
            "explicit_quasi_static",
            ("max_mises", "max_displacement"),
            # ALLWK is required by the dynamic energy balance contract, which
            # cross-checks ETOTAL = ALLIE + ALLKE - ALLWK on real output. Omitting
            # it here would plan a deck whose gate can only ever BLOCK.
            ("ALLIE", "ALLKE", "ALLWK", "ETOTAL"),
            ("energy_ratio", "reaction_balance"),
            ("stress_contour", "displacement_contour", "energy_history"),
            ("Kinetic energy should remain small relative to internal energy for a quasi-static interpretation.",),
            "Step-1",
        )
    if strategy == "DYNAMIC_EXPLICIT":
        return PostProcessingProfile(
            "dynamic_explicit",
            ("max_mises", "max_displacement"),
            # Same requirement as above: the explicit branch of the dynamic energy
            # contract needs ALLWK present in the ODB, not inferred from components.
            ("ALLIE", "ALLKE", "ALLWK", "ETOTAL"),
            ("energy_balance",),
            ("stress_contour", "displacement_contour", "energy_history"),
            (),
            "Step-1",
        )
    if strategy == "DYNAMIC_IMPLICIT":
        return PostProcessingProfile(
            "dynamic_implicit",
            ("max_mises", "max_displacement"),
            # Requested so the dynamic energy balance gate can have evidence at all.
            # Requesting output is not a claim that the balance is acceptable; the
            # contract still blocks until the caller declares a threshold.
            ("ALLIE", "ALLKE", "ALLWK", "ETOTAL"),
            ("reaction_balance", "energy_balance"),
            ("stress_contour", "displacement_contour", "energy_history"),
            (),
            "Step-1",
        )
    if strategy == "FREQUENCY":
        return PostProcessingProfile(
            "frequency", ("frequency",), (), (), ("mode_shape", "frequency_table")
        )
    if strategy == "BUCKLING":
        return PostProcessingProfile(
            "buckling", ("buckling_factor",), (), (), ("mode_shape", "eigenvalue_table")
        )
    if strategy == "HEAT_TRANSFER":
        return PostProcessingProfile(
            "thermal", ("max_temperature",), (), (), ("temperature_contour",)
        )
    if strategy.startswith("COUPLED_TEMPERATURE_DISPLACEMENT"):
        return PostProcessingProfile(
            "coupled",
            ("max_mises", "max_displacement", "max_temperature"),
            ("ALLIE",),
            ("reaction_balance",),
            ("stress_contour", "displacement_contour", "temperature_contour"),
        )
    return PostProcessingProfile(
        "generic",
        ("max_mises", "max_displacement"),
        (),
        (),
        ("stress_contour", "displacement_contour"),
        ("Post-processing profile is generic; explicit result requirements should be declared before execution.",),
    )
