import pytest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tools.official_cantilever_benchmark_live import build_cantilever_cae_script


def test_official_cantilever_benchmark_script_compiles_and_has_sentinel():
    script = build_cantilever_cae_script(
        job_name="TestJob",
        run_id="test_run_123",
        sentinel_path="test_sentinel.flag",
        wait_timeout=180
    )
    # Must compile under Python 3 without syntax error
    compile(script, "<cantilever_test>", "exec")
    
    # Assert essential benchmark components
    assert "CantileverModel" in script
    assert "C3D20R" in script
    assert "waitForCompletion(timeOut=180)" in script
    assert "waitForCompletion()" not in script
    assert "test_sentinel.flag" in script
    assert "BENCHMARK_RESULTS_JSON:" in script
