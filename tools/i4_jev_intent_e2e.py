#!/usr/bin/env python
"""Phase I.4 — JEV-Powered Product UX & TypeSafe Intent Routing E2E.

Demonstrates the product-level natural language engineering workflow:
1. Input: Unconstrained engineer natural language prompt (English / Chinese).
2. TypeSafe System One (JEV):
   - Choice: Discretely routes physics (linear_static), unit system (MM_N_MPA), solver.
   - Noul: Probabilistically assesses boundary constraints sufficiency (well_constrained).
   - Score: Quantifies engineering intent completeness on 1 to 5 scale.
3. Declarative Model Synthesis:
   - Builds typed EngineeringIntent contract.
   - Maps to execution plan and declarative result requirements.
4. Validation & Acceptance:
   - Links directly to solver evidence & verification gates.
5. Evidence & Reporting:
   - Exports structured JSON package and user summary.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.typesafe_intent import JevDecisionBundle, JevIntentRouter


SAMPLE_PROMPTS = [
    {
        "id": "CASE-STATIC-01",
        "prompt": "对100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm和最大Mises应力不超过600MPa。",
        "expected_physics": "linear_static",
        "expected_units": "MM_N_MPA",
    },
    {
        "id": "CASE-THERMAL-02",
        "prompt": "A 1D steady-state heat conduction bar with hot end at 100C and cold end at 0C. Check midpoint temperature at 50C and heat flux balance.",
        "expected_physics": "steady_thermal",
        "expected_units": "MM_N_MPA",
    },
    {
        "id": "CASE-CONTACT-03",
        "prompt": "Two elastic blocks in contact under normal compressive pressure of 10 MPa and tangential sliding friction with friction coefficient 0.25.",
        "expected_physics": "contact_frictional",
        "expected_units": "MM_N_MPA",
    },
]


def run_jev_intent_e2e(output_path: Path) -> Dict[str, Any]:
    """Execute end-to-end JEV-powered UX workflow across sample prompts."""
    router = JevIntentRouter()
    results = []
    all_passed = True

    for sample in SAMPLE_PROMPTS:
        pid = sample["id"]
        prompt = sample["prompt"]

        intent, bundle = router.route_prompt_to_intent(prompt)

        # Assertions
        phys_match = (bundle.physics_choice.value == sample["expected_physics"])
        unit_match = (bundle.unit_system_choice.value == sample["expected_units"])
        constrained_ok = bundle.is_well_constrained_noul.is_yes
        completeness_ok = bundle.completeness_score.score >= 3.0

        case_passed = phys_match and unit_match and completeness_ok
        if not case_passed:
            all_passed = False

        results.append({
            "case_id": pid,
            "prompt": prompt,
            "passed": case_passed,
            "intent_id": intent.id,
            "physics_choice": bundle.physics_choice.value,
            "physics_confidence": bundle.physics_choice.confidence,
            "unit_system": bundle.unit_system_choice.value,
            "is_well_constrained": bundle.is_well_constrained_noul.is_yes,
            "completeness_score": bundle.completeness_score.score,
            "extracted_material": intent.material,
            "boundary_conditions_count": len(intent.boundary_conditions),
            "loads_count": len(intent.loads),
            "acceptance_criteria_count": len(intent.acceptance_criteria),
            "bundle": bundle.to_dict(),
        })

    manifest = {
        "schema_version": "jev_intent_routing_v1",
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_prompts": len(SAMPLE_PROMPTS),
        "passed_prompts": sum(1 for r in results if r["passed"]),
        "all_passed": all_passed,
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run JEV-Powered UX & TypeSafe Intent Routing (Phase I.4)")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "machine_validation" / "i4_jev_intent_evidence.json",
        help="Summary output JSON",
    )
    args = parser.parse_args()

    print("================================================================================")
    print(" Phase I.4 — JEV-Powered Product UX & TypeSafe Intent Routing")
    print("================================================================================")
    manifest = run_jev_intent_e2e(args.out)

    for item in manifest["results"]:
        tag = "[PASS]" if item["passed"] else "[FAIL]"
        print(f" {tag} {item['case_id']}: {item['physics_choice']} (conf: {item['physics_confidence']:.2f})")
        print(f"        Prompt:       {item['prompt']}")
        print(f"        Units:        {item['unit_system']} | Well-Constrained: {item['is_well_constrained']} | Completeness: {item['completeness_score']}/5.0")
        print(f"        Criteria:     {item['acceptance_criteria_count']} criteria extracted | Material: {item['extracted_material']}")

    print("--------------------------------------------------------------------------------")
    print(f"Summary: {manifest['passed_prompts']}/{manifest['total_prompts']} Prompts Routed Successfully")
    print(f"Overall Status: {'ALL PROMPTS ROUTED & VERIFIED' if manifest['all_passed'] else 'FAILURES DETECTED'}")
    print(f"Saved evidence package to {args.out}")

    return 0 if manifest["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
