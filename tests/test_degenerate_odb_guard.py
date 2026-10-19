"""Regression tests for the degenerate-solution guard on ODB verification.

Abaqus/Standard can report COMPLETED SUCCESSFULLY while writing NaN into the
field outputs. Measured on this machine (Job_X1_valued): S had 0/2688 finite
values and U had 1/2250, yet the .sta said the analysis completed. Without this
guard such a run reached acceptance as VALID, because acceptance only sees the
ODB summary and the job status.
"""

import math

import pytest

from abaqus_ai_agent.execution.solver import (
    _CORE_RESULT_FIELDS,
    _MIN_FINITE_FRACTION,
    _degenerate_solution_error,
    _finite_counts,
)


class Values:
    def __init__(self, data):
        self.data = data


class FieldOutput:
    """Mirrors odbAccess: a FieldOutput exposes .values, not a bare list."""

    def __init__(self, values):
        self.values = list(values)


class Frame:
    def __init__(self, fields):
        self.fieldOutputs = {k: FieldOutput(v) for k, v in fields.items()}


class Step:
    def __init__(self, *frames):
        self.frames = list(frames)


class Odb:
    def __init__(self, step):
        self.steps = {"Step-1": step}


NAN = float("nan")


def test_counts_skip_non_numeric_components():
    total, finite = _finite_counts([Values((1.0, NAN, 3.0)), Values((NAN, NAN, 5.0))])
    assert (total, finite) == (6, 3)


def test_counts_accept_scalar_data():
    total, finite = _finite_counts([Values(1.0), Values(NAN)])
    assert (total, finite) == (2, 1)


def test_all_nan_core_field_is_degenerate():
    step = Step(Frame({"S": [Values((NAN,) * 6)]}))
    error, nonfinite = _degenerate_solution_error(Odb(step), "Step-1")
    assert error is not None
    assert "degenerate" in error
    assert "S" in nonfinite


def test_mostly_nan_core_field_is_degenerate():
    # Reproduces the measured U field: 1 finite value out of 2250.
    values = [Values((NAN, NAN, NAN))] * 749 + [Values((0.0, NAN, NAN))]
    step = Step(Frame({"U": values}))
    error, _ = _degenerate_solution_error(Odb(step), "Step-1")
    assert error is not None
    assert "U" in error


def test_healthy_solution_is_accepted():
    step = Step(Frame({"U": [Values((1.0, 2.0, 3.0))],
                       "S": [Values((10.0,) * 6)]}))
    error, nonfinite = _degenerate_solution_error(Odb(step), "Step-1")
    assert error is None
    assert nonfinite == []


def test_contact_only_fields_do_not_mask_a_dead_displacement_field():
    # Real failure shape: contact outputs stay finite while U and S are NaN.
    step = Step(Frame({
        "CPRESS": [Values((0.0,) * 4)],
        "S": [Values((NAN,) * 6)],
        "U": [Values((NAN,) * 3)],
    }))
    error, _ = _degenerate_solution_error(Odb(step), "Step-1")
    assert error is not None


def test_empty_frame_is_not_evidence_of_failure():
    step = Step(Frame({}))
    error, nonfinite = _degenerate_solution_error(Odb(step), "Step-1")
    assert error is None
    assert nonfinite == []


def test_missing_step_is_reported_not_silently_accepted():
    step = Step(Frame({}))
    error, _ = _degenerate_solution_error(Odb(step), "Step-Does-Not-Exist")
    assert error is not None
    assert "degenerate-result check failed" in error


def test_guard_constant_keeps_core_fields_meaningful():
    assert {"U", "S", "RF"} <= set(_CORE_RESULT_FIELDS)
    assert 0.0 < _MIN_FINITE_FRACTION < 1.0
