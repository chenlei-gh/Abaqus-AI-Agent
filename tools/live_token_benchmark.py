"""Live Token Benchmark Suite for Case 1 and Case 3.

Evaluates real provider-reported tokens (usage.prompt_tokens and usage.completion_tokens)
comparing:
  - Branch A (Unmanaged Baseline): Full Static Schemas (24) + Bloated History + Raw Result Dump
  - Branch B (Managed Three-Plane Architecture): Dynamic Schemas + State Context + Result Query + Delivery Card
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Tuple

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.abaqus_ai_agent.context.manager import StateBasedContextManager
from src.abaqus_ai_agent.context.state import (
    EngineeringState,
    ExecutionState,
    GeometryState,
    ModelState,
    VerificationState,
)
from src.abaqus_ai_agent.contracts.artifact import ArtifactPointer
from src.abaqus_ai_agent.llm.client import LiveLLMClient, LiveLLMResponse
from src.abaqus_ai_agent.telemetry.contracts import EngineeringPhase
from src.abaqus_ai_agent.telemetry.tracker import _heuristic_count_tokens
from src.abaqus_ai_agent.tools.registry import build_default_cae_tool_registry
from src.abaqus_ai_agent.tools.router import DynamicToolRouter


def build_case_01_payloads() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build real prompt payloads for Case 1 (Bolted Flange Assembly)."""
    # 1. Branch A: Unmanaged Baseline
    registry = build_default_cae_tool_registry()
    all_tools = [t.to_openai_schema(minimal=False) for t in registry.list_all()]

    unmanaged_messages = [
        {"role": "system", "content": "You are an Abaqus CAE finite element simulation assistant."},
        {"role": "user", "content": "Simulate high pressure bolted flange with 1000N preload under 15MPa internal pressure."},
        {"role": "assistant", "content": "Parsed requirement. Model built with pipe inner radius 50mm, outer radius 65mm. Submitting Abaqus job."},
        {"role": "user", "content": "Job completed. Please analyze stress, displacement, and generate full report."},
        {
            "role": "assistant",
            "content": "Raw field output dump: " + json.dumps({
                "nodes": [{"id": i, "coord": [i * 1.5, i * 2.0, 0.0], "U_mag": 0.0007 + i * 1e-6} for i in range(80)],
                "elements": [{"id": j, "type": "C3D10", "S_mises": 300.0 + (j % 15) * 1.2} for j in range(80)],
            }),
        },
        {"role": "user", "content": "Please write a comprehensive 20-section bilingual engineering report with all derivations."},
    ]

    branch_a_payload = {
        "messages": unmanaged_messages,
        "tools": all_tools,
        "description": "Case 1 Unmanaged Baseline (24 full tool schemas + history + raw node/element dump)",
    }

    # 2. Branch B: Managed Architecture
    router = DynamicToolRouter(registry=registry)
    route_res = router.resolve_tools(phase=EngineeringPhase.VERIFICATION, minimal_schema=True)
    managed_tools = list(route_res.minimal_schemas)

    state = EngineeringState(
        run_id="RUN-CASE01-LIVE",
        phase=EngineeringPhase.VERIFICATION,
        case_id="case_01_bolted_flange",
        physics_domain="structural",
        active_task="Evaluate flange sealing and yield margin",
        last_user_intent="Evaluate flange sealing and yield margin under 1000N preload and 15MPa internal pressure",
        geometry=GeometryState(
            status="grounded",
            cad_file="models/pipe_flange.step",
            bounding_box={"xmin": -75.0, "xmax": 75.0, "ymin": -75.0, "ymax": 75.0, "zmin": 0.0, "zmax": 200.0},
            grounded_regions={"PIPE_INNER": "SURFACE_INNER", "FLANGE_FACE": "SURFACE_SEALING"},
            artifact_id="ART-GEO-01",
        ),
        model=ModelState(
            status="meshed",
            model_name="BoltedFlange",
            element_type="C3D10",
            material_parameters={"youngs_modulus_mpa": 210000.0, "poisson_ratio": 0.3, "yield_strength_mpa": 355.0},
            boundary_conditions=({"name": "FixedBase", "region": "PIPE_END", "type": "ENCASTRE"},),
            loads=(
                {"name": "InternalPressure", "magnitude": 15.0, "unit": "MPa", "region": "PIPE_INNER"},
                {"name": "BoltPreload", "magnitude": 1000.0, "unit": "N", "direction": "-Z"},
            ),
            mesh_stats={"nodes": 18450, "elements": 12890},
            inp_artifact_id="ART-INP-01",
        ),
        execution=ExecutionState(
            status="completed",
            job_name="Job-Flange-01",
            exit_code=0,
            odb_artifact_id="ART-ODB-01",
            execution_time_seconds=42.5,
        ),
        verification=VerificationState(
            status="passed",
            acceptance_status="PASS",
            max_mises_mpa=312.4,
            max_displacement_mm=0.048,
            reaction_force_balance_pct=0.002,
            acceptance_id="ACC-GATE-01",
        ),
        artifact_pointers=(
            ArtifactPointer(artifact_id="ART-ODB-01", type="odb", media_type="application/octet-stream", location="jobs/flange.odb", size_bytes=10485760, created_by="abaqus"),
            ArtifactPointer(artifact_id="ART-FIG-01", type="figure", media_type="image/gif", location="figures/transient_evolution.gif", size_bytes=45200, created_by="pipeline"),
        ),
        unresolved_questions=(),
    )
    context_mgr = StateBasedContextManager(initial_state=state)
    context_mgr.add_key_decision("Bolt preload converged with zero contact penetration.")
    compacted = context_mgr.compact()
    managed_context = compacted.to_llm_system_context()

    managed_messages = [
        {"role": "system", "content": "You are an engineering specialist. Review compact verified state and provide a brief InterpretationCard (observations, risk notes, recommendations)."},
        {"role": "user", "content": f"Current Verified Engineering State:\n{managed_context}\n\nProvide InterpretationCard:"},
    ]

    branch_b_payload = {
        "messages": managed_messages,
        "tools": managed_tools,
        "description": "Case 1 Managed Architecture (2 minimal schemas + state card + interpretation target)",
    }

    return branch_a_payload, branch_b_payload


def build_case_03_payloads() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build real prompt payloads for Case 3 (Exhaust Manifold Thermo-Mechanical)."""
    registry = build_default_cae_tool_registry()
    all_tools = [t.to_openai_schema(minimal=False) for t in registry.list_all()]

    unmanaged_messages = [
        {"role": "system", "content": "You are an Abaqus CAE finite element simulation assistant."},
        {"role": "user", "content": "Perform coupled thermal-mechanical contact analysis for heavy-duty exhaust manifold."},
        {"role": "assistant", "content": "Step 0 steady thermal conduction solved. Exhaust gas temperature 650C, coolant flange 90C. Step 2 coupled mechanical contact ready."},
        {"role": "user", "content": "Check gasket sealing CPRESS and flange differential thermal slip."},
        {
            "role": "assistant",
            "content": "Raw field dump for contact pressure: " + json.dumps({
                "slave_nodes": [{"id": n, "cpress_mpa": 18.5 - n * 0.1, "cslip_mm": 0.12} for n in range(100)],
                "thermal_nodes": [{"id": m, "nt11": 650.0 - m * 4.5} for m in range(100)],
            }),
        },
        {"role": "user", "content": "Output full bilingual final report for engine qualification."},
    ]

    branch_a_payload = {
        "messages": unmanaged_messages,
        "tools": all_tools,
        "description": "Case 3 Unmanaged Baseline (24 full schemas + multi-physics history + raw CPRESS dump)",
    }

    router = DynamicToolRouter(registry=registry)
    route_res = router.resolve_tools(phase=EngineeringPhase.VERIFICATION, minimal_schema=True)
    managed_tools = list(route_res.minimal_schemas)

    state = EngineeringState(
        run_id="RUN-CASE03-LIVE",
        phase=EngineeringPhase.VERIFICATION,
        case_id="case_03_manifold",
        physics_domain="thermo_mechanical_contact",
        active_task="Verify gasket sealing closure and differential slip",
        last_user_intent="Verify gasket sealing closure and differential thermal slip at 650C gas temp",
        geometry=GeometryState(
            status="grounded",
            cad_file="models/exhaust_manifold.step",
            bounding_box={"xmin": -200.0, "xmax": 200.0, "ymin": -80.0, "ymax": 80.0, "zmin": -50.0, "zmax": 150.0},
            grounded_regions={"RUNNER_INLET": "FACE_INLET", "FLANGE_SEAL": "FACE_GASKET"},
            artifact_id="ART-GEO-M3",
        ),
        model=ModelState(
            status="meshed",
            model_name="ExhaustManifold",
            element_type="C3D10",
            material_parameters={"conductivity_w_mk": 26.0, "expansion_coeff_1_k": 1.2e-5, "youngs_modulus_mpa": 175000.0},
            boundary_conditions=({"name": "HeadMount", "region": "CYLINDER_HEAD", "type": "ENCASTRE"},),
            loads=(
                {"name": "ExhaustGasThermal", "temperature_c": 650.0, "region": "RUNNER_INLET"},
                {"name": "CoolantFlangeConvection", "ambient_c": 90.0, "film_coeff": 1500.0},
            ),
            mesh_stats={"nodes": 62400, "elements": 45600},
            inp_artifact_id="ART-INP-M3",
        ),
        execution=ExecutionState(
            status="completed",
            job_name="Job-Manifold-ThermoMech",
            exit_code=0,
            odb_artifact_id="ART-ODB-M3",
            execution_time_seconds=185.0,
        ),
        verification=VerificationState(
            status="passed",
            acceptance_status="PASS",
            max_mises_mpa=284.6,
            max_displacement_mm=0.82,
            acceptance_id="ACC-GATE-M3",
        ),
        artifact_pointers=(
            ArtifactPointer(artifact_id="ART-ODB-M3", type="odb", media_type="application/octet-stream", location="jobs/manifold.odb", size_bytes=34891000, created_by="abaqus"),
            ArtifactPointer(artifact_id="ART-FIG-M3", type="figure", media_type="image/gif", location="figures/transient_evolution.gif", size_bytes=98200, created_by="pipeline"),
        ),
        unresolved_questions=(),
    )
    context_mgr = StateBasedContextManager(initial_state=state)
    context_mgr.add_key_decision("Steady thermal step converged at 650C; thermo-mechanical contact closed.")
    compacted = context_mgr.compact()
    managed_context = compacted.to_llm_system_context()

    managed_messages = [
        {"role": "system", "content": "You are an engineering specialist. Review compact verified state and provide a brief InterpretationCard (observations, risk notes, recommendations)."},
        {"role": "user", "content": f"Current Verified Engineering State:\n{managed_context}\n\nProvide InterpretationCard:"},
    ]

    branch_b_payload = {
        "messages": managed_messages,
        "tools": managed_tools,
        "description": "Case 3 Managed Architecture (2 minimal schemas + state card + interpretation target)",
    }

    return branch_a_payload, branch_b_payload


def run_benchmark(live_api: bool = True) -> Dict[str, Any]:
    """Execute live token benchmark across Case 1 and Case 3."""
    client = LiveLLMClient()

    results: Dict[str, Any] = {
        "benchmark_id": "Live-Token-Benchmark-Case1-Case3",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider_endpoint": client.base_url,
        "model": client.model,
        "cases": {},
    }

    cases = [
        ("case_01", "Case 1: Bolted Flange Assembly", build_case_01_payloads()),
        ("case_03", "Case 3: Exhaust Manifold Thermo-Mechanical", build_case_03_payloads()),
    ]

    for case_key, case_name, (branch_a, branch_b) in cases:
        print(f"\n=======================================================")
        print(f"Executing Live Benchmark: {case_name}")
        print(f"=======================================================")

        case_record: Dict[str, Any] = {
            "title": case_name,
            "branch_a": {},
            "branch_b": {},
            "metrics": {},
        }

        if live_api and client.is_configured:
            print(f"[Branch A: Unmanaged] Sending request to {client.model}...")
            res_a = client.chat_completion(
                messages=branch_a["messages"],
                tools=branch_a["tools"],
                max_tokens=600,
            )
            print(f"  -> Prompt Tokens: {res_a.prompt_tokens}, Completion Tokens: {res_a.completion_tokens}, Latency: {res_a.latency_ms}ms")

            print(f"[Branch B: Managed] Sending request to {client.model}...")
            res_b = client.chat_completion(
                messages=branch_b["messages"],
                tools=branch_b["tools"],
                max_tokens=250,
            )
            print(f"  -> Prompt Tokens: {res_b.prompt_tokens}, Completion Tokens: {res_b.completion_tokens}, Latency: {res_b.latency_ms}ms")

            reduction = (res_a.prompt_tokens - res_b.prompt_tokens) / max(res_a.prompt_tokens, 1) * 100.0
            total_red = (res_a.total_tokens - res_b.total_tokens) / max(res_a.total_tokens, 1) * 100.0

            case_record["branch_a"] = {
                "prompt_tokens": res_a.prompt_tokens,
                "completion_tokens": res_a.completion_tokens,
                "total_tokens": res_a.total_tokens,
                "latency_ms": res_a.latency_ms,
                "source": "provider_usage",
            }
            case_record["branch_b"] = {
                "prompt_tokens": res_b.prompt_tokens,
                "completion_tokens": res_b.completion_tokens,
                "total_tokens": res_b.total_tokens,
                "latency_ms": res_b.latency_ms,
                "source": "provider_usage",
            }
            case_record["metrics"] = {
                "prompt_token_reduction_pct": round(reduction, 2),
                "total_token_reduction_pct": round(total_red, 2),
                "measurement_source": "provider_usage",
                "status": "QUALIFIED_LIVE",
            }
        else:
            # Offline / dry-run estimation mode
            print(f"[Dry-Run / Offline Mode] Estimating token footprints...")
            est_a_prompt = _heuristic_count_tokens(json.dumps(branch_a["messages"]) + json.dumps(branch_a["tools"]))
            est_a_comp = 600
            est_b_prompt = _heuristic_count_tokens(json.dumps(branch_b["messages"]) + json.dumps(branch_b["tools"]))
            est_b_comp = 80

            red = (est_a_prompt - est_b_prompt) / est_a_prompt * 100.0
            case_record["branch_a"] = {
                "prompt_tokens": est_a_prompt,
                "completion_tokens": est_a_comp,
                "total_tokens": est_a_prompt + est_a_comp,
                "latency_ms": 0.0,
                "source": "estimated",
            }
            case_record["branch_b"] = {
                "prompt_tokens": est_b_prompt,
                "completion_tokens": est_b_comp,
                "total_tokens": est_b_prompt + est_b_comp,
                "latency_ms": 0.0,
                "source": "estimated",
            }
            case_record["metrics"] = {
                "prompt_token_reduction_pct": round(red, 2),
                "total_token_reduction_pct": round((est_a_prompt + est_a_comp - est_b_prompt - est_b_comp) / (est_a_prompt + est_a_comp) * 100.0, 2),
                "measurement_source": "estimated",
                "status": "DRY_RUN_READY",
            }

        results["cases"][case_key] = case_record

    # Persist evidence
    evidence_path = REPO_ROOT / "machine_validation" / "live_token_benchmark_evidence.json"
    evidence_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nBenchmark evidence persisted to: {evidence_path}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Token Benchmark Suite")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode without real API calls")
    args = parser.parse_args()

    run_benchmark(live_api=not args.dry_run)
