import json
from pathlib import Path
from tools.h8_case_memory_comparison_e2e import run_h8_case_memory_comparison


def test_h8_case_memory_comparison_e2e():
    evidence = run_h8_case_memory_comparison()
    assert evidence["status"] == "PASS"
    assert evidence["total_indexed_runs"] == 3
    assert evidence["queries_verified"]["standard_count"] == 2
    assert evidence["queries_verified"]["explicit_count"] == 1
    assert evidence["queries_verified"]["high_stress_count"] == 1
    assert evidence["comparison_verified"]["solver_changed"] is True

    ev_path = Path("machine_validation") / "h8_case_memory_comparison_evidence.json"
    assert ev_path.exists()
