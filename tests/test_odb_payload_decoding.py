"""Regression tests for ODB payload decoding on the headless executor path.

The headless Abaqus Python executor returns stdout, which is a Python repr, not
JSON. Treating that string as evidence made every energy history look missing and
forced the stabilization gate to BLOCK for the wrong reason.
"""

import math

import pytest

from abaqus_ai_agent.execution.odb import _decode_payload


def test_decodes_python_repr_payload():
    raw = "{'steps': ['Step-1'], 'instances': ['BASE-1'], 'step_frames': {'Step-1': 10}}"
    assert _decode_payload(raw) == {
        "steps": ["Step-1"],
        "instances": ["BASE-1"],
        "step_frames": {"Step-1": 10},
    }


def test_decodes_json_payload():
    assert _decode_payload('{"steps": ["Step-1"]}') == {"steps": ["Step-1"]}


def test_decodes_repr_containing_nan():
    """Abaqus writes nan for unavailable energies; that must not be read as absent."""
    raw = (
        "{'status': 'available', 'step': 'Step-1', "
        "'variables': {'ALLSD': [(0.0, 0.0), (1.0, nan)], "
        "'ALLSE': [(0.0, 0.0), (1.0, nan)]}}"
    )
    decoded = _decode_payload(raw)
    assert decoded is not None
    assert decoded["variables"]["ALLSD"][1][1] != decoded["variables"]["ALLSD"][1][1]  # NaN
    assert math.isnan(decoded["variables"]["ALLSE"][1][1])


def test_passes_through_dict_unchanged():
    value = {"steps": ["Step-1"]}
    assert _decode_payload(value) is value


def test_passes_through_non_text_objects():
    class Odb:
        pass

    odb = Odb()
    assert _decode_payload(odb) is odb


def test_returns_none_for_empty_and_garbage():
    assert _decode_payload("") is None
    assert _decode_payload("   ") is None
    assert _decode_payload("not a payload at all") is None
    assert _decode_payload(None) is None
