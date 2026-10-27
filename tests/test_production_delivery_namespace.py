"""Pilot 3 offline contracts: namespace migration + host terminal-state gates
for tools/production_delivery_e2e.py (remediation items P1-5 / T5 / T7).
"""

import ast
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.production_delivery_e2e import build_production_delivery_cae_script


def _render(tmp_path) -> str:
    return build_production_delivery_cae_script(project_root=tmp_path)


# --- T1-equivalent: generated script parses and uses the namespace -------------

def test_rendered_production_script_parses(tmp_path):
    rendered = _render(tmp_path)
    ast.parse(rendered)
    assert "\t" not in rendered


def test_production_script_uses_kernel_namespace_not_globals(tmp_path):
    rendered = _render(tmp_path)
    assert "KernelNamespace" in rendered
    assert "_NS.execute(code" in rendered
    assert "globals()" not in rendered


def test_blocked_marker_present_in_template(tmp_path):
    assert "AIAgent_PROD_DELIVERY_BLOCKED:AWAITING_APPROVAL" in _render(tmp_path)


# --- T5: pseudo-kernel exception injection --------------------------------------

def _fake_cae_modules(monkeypatch):
    fake_abaqus = types.ModuleType("abaqus")
    fake_abaqus.mdb = object()
    fake_abaqus.__all__ = ["mdb"]
    fake_const = types.ModuleType("abaqusConstants")
    fake_const.LOG = "SymbolicConstant<LOG>"
    fake_const.__all__ = ["LOG"]
    monkeypatch.setitem(sys.modules, "abaqus", fake_abaqus)
    monkeypatch.setitem(sys.modules, "abaqusConstants", fake_const)


def _extract_harness(rendered: str) -> str:
    head, sep, rest = rendered.partition("_NS = KernelNamespace")
    assert sep
    block = sep + rest.split("class CAEInProcessExecutor", 1)[0]
    return (
        "from abaqus_ai_agent.execution.kernel_namespace import "
        "KernelNamespace, build_cae_seed\n" + block
    )


def test_fragment_exception_propagates_without_success_or_stale_result(tmp_path, monkeypatch):
    _fake_cae_modules(monkeypatch)
    env = {}
    exec(_extract_harness(_render(tmp_path)), env)
    run_code = env["_run_code"]

    assert run_code("result = {\"a\": 1}") == {"a": 1}
    with pytest.raises(ValueError):
        run_code("raise ValueError(\"injected\")")
    # no success payload, no stale result after the failure
    assert run_code("z = 1") == {"status": "COMPLETED"}
    assert "result" not in env and "z" not in env


# --- T7/P1-5: host terminal-state gates ------------------------------------------

class _FakeProc:
    def __init__(self, rc, settled, note=None):
        self.return_code = rc
        self.settled = settled
        self.settle_note = note
        self.stdout = ""
        self.stderr = ""
        self.succeeded = rc == 0


def _run_with_fake_process(tmp_path, monkeypatch, proc):
    import tools.production_delivery_e2e as mod

    monkeypatch.setattr(mod, "find_abaqus_executable", lambda *a, **k: "abaqus")

    class _FakeBatch:
        def __init__(self, *a, **k):
            pass

        def run_nogui(self, script, timeout=None):
            return proc

    monkeypatch.setattr(mod, "BatchExecutor", _FakeBatch)
    return mod.run_production_delivery_e2e(launcher="abaqus", project_dir=tmp_path)


def test_nonzero_host_exit_fails_closed(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="return_code=1"):
        _run_with_fake_process(tmp_path, monkeypatch, _FakeProc(rc=1, settled=True))


def test_unsettled_artifacts_fail_closed(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="not settled"):
        _run_with_fake_process(tmp_path, monkeypatch, _FakeProc(rc=0, settled=False, note="still changing"))


def test_approval_blocked_marker_raises_actionable_error(tmp_path, monkeypatch):
    proc = _FakeProc(rc=1, settled=True)
    proc.stderr = "AIAgent_PROD_DELIVERY_BLOCKED:AWAITING_APPROVAL"
    with pytest.raises(RuntimeError, match="AWAITING_APPROVAL"):
        _run_with_fake_process(tmp_path, monkeypatch, proc)
