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


def test_intermediate_frame_nan_caught_by_degenerate_check():
    """Verify that an intermediate frame with NaN core fields is caught even when the final frame recovered."""
    frame0_bad = Frame({"U": [Values((NAN, NAN, NAN))]})
    frame1_good = Frame({"U": [Values((1.0, 2.0, 3.0))]})
    step = Step(frame0_bad, frame1_good)
    error, nonfinite = _degenerate_solution_error(Odb(step), "Step-1")
    assert error is not None
    assert "frame 0" in error
    assert "degenerate" in error
    assert "U" in nonfinite


def test_guard_constant_keeps_core_fields_meaningful():
    assert {"U", "S", "RF"} <= set(_CORE_RESULT_FIELDS)
    assert 0.0 < _MIN_FINITE_FRACTION < 1.0


def test_verify_odb_in_process_multi_step_degenerate_and_fields_guard(tmp_path):
    """Verify that _verify_odb_in_process checks all non-Initial steps for degeneracy and forbids ambiguous fields."""
    import sys
    import types
    from pathlib import Path
    from abaqus_ai_agent.execution.solver import _verify_odb_in_process

    class MockInstance:
        def __init__(self):
            self.elements = [type("Elem", (), {"type": "C3D8R"})()]
            self.nodes = [type("Node", (), {})()]

    class MockAssembly:
        def __init__(self):
            self.instances = {"Inst-1": MockInstance()}

    class MockMultiOdb:
        def __init__(self, steps_dict):
            self.steps = steps_dict
            self.rootAssembly = MockAssembly()
        def close(self):
            pass

    active_odb = [None]
    mock_mod = types.ModuleType("odbAccess")
    mock_mod.openOdb = lambda path, readOnly=True: active_odb[0]

    orig_odb_acc = sys.modules.get("odbAccess")
    sys.modules["odbAccess"] = mock_mod

    try:
        # Case 1: Multi-step where Step-2 is healthy but Step-1 is degenerate (NaN in U)
        # Even when required_step is None, scanning all non-initial steps catches Step-1!
        step1_bad = Step(Frame({"U": [Values((NAN, NAN, NAN))]}))
        step2_good = Step(Frame({"U": [Values((1.0, 2.0, 3.0))]}))
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
            "Step-1": step1_bad,
            "Step-2": step2_good,
        })
        res1 = _verify_odb_in_process(Path("dummy.odb"))
        assert res1["verified"] is False
        assert "Step-1" in res1["error"]
        assert "degenerate" in res1["error"]

        # Case 2: Multi-step without required_step when required_fields is requested -> fails closed
        step1_good = Step(Frame({"U": [Values((1.0, 2.0, 3.0))]}))
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
            "Step-1": step1_good,
            "Step-2": step2_good,
        })
        res2 = _verify_odb_in_process(Path("dummy.odb"), required_fields=["U"])
        assert res2["verified"] is False
        assert "Multiple non-Initial analysis steps present" in res2["error"]

        # Case 3: Single non-Initial step safely defaults
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
            "Step-1": step1_good,
        })
        res3 = _verify_odb_in_process(Path("dummy.odb"), required_fields=["U"])
        assert res3["verified"] is True

        # Case 4: required_step="Step-2" specified, but Step-1 is degenerate -> still catches Step-1!
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
            "Step-1": step1_bad,
            "Step-2": step2_good,
        })
        res4 = _verify_odb_in_process(Path("dummy.odb"), required_fields=["U"], required_step="Step-2")
        assert res4["verified"] is False
        assert "Step-1" in res4["error"]
        assert "degenerate" in res4["error"]

        # Case 5: Intermediate frame degenerate (frame 0 NaN) while last frame (frame 1) is healthy
        step_interm_bad = Step(
            Frame({"U": [Values((NAN, NAN, NAN))]}),
            Frame({"U": [Values((1.0, 2.0, 3.0))]}),
        )
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
            "Step-1": step_interm_bad,
        })
        res5 = _verify_odb_in_process(Path("dummy.odb"), required_fields=["U"])
        assert res5["verified"] is False
        assert "frame 0" in res5["error"]
        assert "degenerate" in res5["error"]

        # Case 6: Non-Initial step has zero frames -> fails closed
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
            "Step-1": Step(),
        })
        res6 = _verify_odb_in_process(Path("dummy.odb"))
        assert res6["verified"] is False
        assert "contains zero frames" in res6["error"]

        # Case 7: ODB contains only Initial step -> fails closed
        active_odb[0] = MockMultiOdb({
            "Initial": Step(),
        })
        res7 = _verify_odb_in_process(Path("dummy.odb"))
        assert res7["verified"] is False
        assert "zero non-Initial analysis steps" in res7["error"]
    finally:
        if orig_odb_acc is not None:
            sys.modules["odbAccess"] = orig_odb_acc
        else:
            sys.modules.pop("odbAccess", None)


def test_probe_script_dual_path_consistency(tmp_path):
    """Directly execute generated probe_script to verify external launcher parity with _verify_odb_in_process."""
    import io
    import json
    import sys
    import types
    from pathlib import Path
    from abaqus_ai_agent.execution.solver import _build_odb_probe_script

    class MockInstance:
        def __init__(self):
            self.elements = [type("Elem", (), {"type": "C3D8R"})()]
            self.nodes = [type("Node", (), {})()]

    class MockAssembly:
        def __init__(self):
            self.instances = {"Inst-1": MockInstance()}

    class MockMultiOdb:
        def __init__(self, steps_dict):
            self.steps = steps_dict
            self.rootAssembly = MockAssembly()
        def close(self):
            pass

    active_odb = [None]
    mock_mod = types.ModuleType("odbAccess")
    mock_mod.openOdb = lambda path, readOnly=True: active_odb[0]

    def _run_probe(script_code: str) -> dict:
        orig_stdout = sys.stdout
        orig_mod = sys.modules.get("odbAccess")
        sys.modules["odbAccess"] = mock_mod
        stdout_buf = io.StringIO()
        sys.stdout = stdout_buf
        try:
            env = {"__name__": "__main__"}
            try:
                exec(script_code, env)
            except SystemExit:
                pass
            out = stdout_buf.getvalue()
            for line in out.splitlines():
                if "__ODB_VERIFIED__" in line:
                    payload = line.split("__ODB_VERIFIED__", 1)[1].strip()
                    return json.loads(payload)
            raise AssertionError(f"__ODB_VERIFIED__ not found in script output: {out}")
        finally:
            sys.stdout = orig_stdout
            if orig_mod is not None:
                sys.modules["odbAccess"] = orig_mod
            else:
                sys.modules.pop("odbAccess", None)

    step1_bad = Step(Frame({"U": [Values((NAN, NAN, NAN))]}))
    step2_good = Step(Frame({"U": [Values((1.0, 2.0, 3.0))]}))

    # 1. Specifying required_step="Step-2" while Step-1 is degenerate -> probe catches Step-1!
    active_odb[0] = MockMultiOdb({
        "Initial": Step(),
        "Step-1": step1_bad,
        "Step-2": step2_good,
    })
    script1 = _build_odb_probe_script(Path("dummy.odb"), required_fields=["U"], required_step="Step-2")
    res1 = _run_probe(script1)
    assert res1["valid"] is False
    assert "Step-1" in res1["error"]
    assert "degenerate" in res1["error"]

    # 2. Intermediate frame degenerate while final frame is healthy -> probe catches frame 0!
    step_interm_bad = Step(
        Frame({"U": [Values((NAN, NAN, NAN))]}),
        Frame({"U": [Values((1.0, 2.0, 3.0))]}),
    )
    active_odb[0] = MockMultiOdb({
        "Initial": Step(),
        "Step-1": step_interm_bad,
    })
    script2 = _build_odb_probe_script(Path("dummy.odb"), required_fields=["U"])
    res2 = _run_probe(script2)
    assert res2["valid"] is False
    assert "frame 0" in res2["error"]
    assert "degenerate" in res2["error"]

    # 3. ODB has zero non-Initial analysis steps -> probe fails closed
    active_odb[0] = MockMultiOdb({
        "Initial": Step(),
    })
    script3 = _build_odb_probe_script(Path("dummy.odb"))
    res3 = _run_probe(script3)
    assert res3["valid"] is False
    assert "zero non-Initial analysis steps" in res3["error"]

    # 4. Non-Initial step has zero frames -> probe fails closed
    active_odb[0] = MockMultiOdb({
        "Initial": Step(),
        "Step-1": Step(),
    })
    script4 = _build_odb_probe_script(Path("dummy.odb"))
    res4 = _run_probe(script4)
    assert res4["valid"] is False
    assert "contains zero frames" in res4["error"]

    # 5. Healthy multi-step -> probe succeeds with valid=True
    active_odb[0] = MockMultiOdb({
        "Initial": Step(),
        "Step-1": Step(Frame({"U": [Values((1.0, 2.0, 3.0))]})),
        "Step-2": step2_good,
    })
    script5 = _build_odb_probe_script(Path("dummy.odb"), required_fields=["U"], required_step="Step-2")
    res5 = _run_probe(script5)
    assert res5["valid"] is True
    assert "steps" in res5
