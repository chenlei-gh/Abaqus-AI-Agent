from tools.static_golden_e2e import build_static_golden_script, _extract_report


def test_static_golden_script_uses_existing_pipeline():
    script = build_static_golden_script()
    for marker in (
        "build_static_plan(",
        "AnalysisRunner(executor).run(",
        "extract_field(",
        "reaction_balance_from_field_evidence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
        "plan.actions[-1]",
    ):
        assert marker in script


def test_static_golden_script_has_no_direct_process_solver_bypass():
    script = build_static_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_static_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    import json
    stdout = (
        "noise\n"
        "AIAgent_STATIC_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_STATIC_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_static_golden_report_parser_rejects_missing_markers():
    assert _extract_report("{}") is None
def _extract_migrated_harness(script):
    """Pull the migrated namespace harness (_NS + _run_code) out of the
    generated CAE script so offline tests can drive it with a fake kernel."""
    head, sep, rest = script.partition("_NS = KernelNamespace")
    assert sep, "generated script must construct a KernelNamespace"
    harness_src = sep + rest.split("class CAEInProcessExecutor", 1)[0]
    return (
        "from abaqus_ai_agent.execution.kernel_namespace import "
        "KernelNamespace, build_cae_seed\n" + harness_src
    )


def _fake_cae_modules(monkeypatch):
    import sys
    import types

    fake_abaqus = types.ModuleType("abaqus")
    fake_abaqus.mdb = object()
    fake_abaqus.__all__ = ["mdb"]
    fake_const = types.ModuleType("abaqusConstants")
    fake_const.LOG = "SymbolicConstant<LOG>"
    fake_const.__all__ = ["LOG"]
    monkeypatch.setitem(sys.modules, "abaqus", fake_abaqus)
    monkeypatch.setitem(sys.modules, "abaqusConstants", fake_const)


def test_migrated_run_code_runs_fragments_in_isolated_namespace(monkeypatch):
    _fake_cae_modules(monkeypatch)
    script = build_static_golden_script()
    env = {}
    exec(_extract_migrated_harness(script), env)
    run_code = env["_run_code"]

    sentinel = object()
    globals()["LOG"] = sentinel
    try:
        # seed constants are visible to fragments; caller LOG is untouched
        out = run_code("result = {\"log\": LOG}")
        assert out == {"log": "SymbolicConstant<LOG>"}
        assert globals()["LOG"] is sentinel
        # cross-fragment persistence inside the namespace
        run_code("carried = 41")
        assert run_code("result = {\"v\": carried + 1}") == {"v": 42}
        # a fragment that sets no result must not see the stale one
        assert run_code("other = 1") == {"status": "COMPLETED"}
        # fragment exceptions propagate
        import pytest

        with pytest.raises(ValueError):
            run_code("raise ValueError(\"fragment-boom\")")
    finally:
        globals().pop("LOG", None)
    # harness bookkeeping never entered the caller env
    assert "carried" not in env
    assert "result" not in env
