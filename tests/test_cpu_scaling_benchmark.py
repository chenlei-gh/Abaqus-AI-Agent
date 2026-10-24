"""Offline tests for the T-P4 benchmark deck generator.

These tests never launch Abaqus. They lock the keyword syntax that the real
benchmark validated on Abaqus 2025, so a future refactor cannot silently emit
an invalid deck.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_benchmark():
    spec = importlib.util.spec_from_file_location(
        "cpu_scaling_benchmark", ROOT / "tools" / "cpu_scaling_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_beam_divisions_are_cubic_10_1_1():
    mod = _load_benchmark()
    nx, ny, nz = mod._beam_divisions(21970)
    assert (nx, ny, nz) == (130, 13, 13)
    assert nx == 10 * ny == 10 * nz


def test_standard_deck_uses_static_step_and_full_integration_hex(tmp_path):
    mod = _load_benchmark()
    nx, ny, nz = mod._beam_divisions(3430)
    path = tmp_path / "standard.inp"
    mesh = mod._write_inp(path, "standard", nx, ny, nz, increments=40, step_time=1e-3)
    text = path.read_text(encoding="ascii")
    assert mesh["elements"] == 3430
    assert "*STEP, NAME=LOAD, INC=80" in text
    assert "*STATIC" in text
    assert "TYPE=C3D8," in text
    assert "C3D8R" not in text
    assert "*OUTPUT, FIELD, VARIABLE=PRESELECT, FREQUENCY=0" in text


def test_explicit_deck_uses_blank_initial_increment_and_time_period(tmp_path):
    mod = _load_benchmark()
    nx, ny, nz = mod._beam_divisions(7290)
    path = tmp_path / "explicit.inp"
    mesh = mod._write_inp(path, "explicit", nx, ny, nz, increments=10, step_time=5e-4)
    text = path.read_text(encoding="ascii")
    assert mesh["elements"] == 7290
    assert "*DYNAMIC, EXPLICIT" in text
    assert "\n, 0.0005\n" in text
    assert "INC=" not in text
    assert "TYPE=C3D8R," in text
    assert "*DENSITY" in text
    assert "*OUTPUT, FIELD, VARIABLE=PRESELECT, NUMBER INTERVAL=10000" in text