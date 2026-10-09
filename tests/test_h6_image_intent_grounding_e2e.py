import json
import shutil
from pathlib import Path
import pytest
from tools.h6_image_intent_grounding_e2e import run_h6_grounding_e2e


def test_h6_image_intent_grounding_e2e():
    has_launcher = bool(
        shutil.which("abaqus")
        or shutil.which("abaqus.bat")
        or Path(r"C:\SIMULIA\Commands\abaqus.bat").exists()
    )
    if not has_launcher:
        pytest.skip("Live Abaqus launcher not available for H.6 E2E CAE execution")

    evidence = run_h6_grounding_e2e()
    assert evidence["status"] == "PASS"
    assert len(evidence["intents"]) == 2
    assert evidence["cae_verification"]["status"] == "PASS"
    assert evidence["cae_verification"]["fixed_face_count"] == 1
    assert evidence["cae_verification"]["tip_face_count"] == 1

    ev_file = Path(evidence["case"]).name
    # Verify written evidence
    evidence_path = Path("machine_validation") / "h6_image_intent_grounding_evidence.json"
    assert evidence_path.exists()
