from __future__ import annotations

import subprocess

import pytest

from abaqus_ai_agent.paths import get_repo_root


ROOT = get_repo_root()


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "--", relative_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise AssertionError(result.stderr.strip() or f"git check-ignore failed for {relative_path}")
    return result.returncode == 0


@pytest.mark.parametrize(
    "relative_path",
    [
        "deliverables/candidate/report.html",
        "runs/candidate/run_evidence.json",
        "invalid/candidate/problem.json",
        "machine_validation/candidate/manifest.json",
        "validation_assets/cases/candidate/asset.png",
        "test_assets/candidate/problem.json",
    ],
)
def test_governance_directories_are_not_blanket_ignored(relative_path):
    assert not _is_ignored(relative_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        "runs/live_environment_gate.json",
        "runs/h6_grounding_validation/h6_grounding_live_result.json",
        "runs/candidate/reproduce_case_script.py",
        "runs/images/slide_01_img_02.png",
        "runs/candidate/Job-1.odb",
        "machine_validation/candidate/scratch.inp",
    ],
)
def test_only_known_ephemeral_outputs_are_ignored(relative_path):
    assert _is_ignored(relative_path)
