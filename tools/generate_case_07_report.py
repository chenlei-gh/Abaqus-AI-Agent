#!/usr/bin/env python3
"""Case 07 Qualification: authoritative HTML report from an existing solve.

This entry point never runs a solver. It reads the artifacts written by
``tools/case_07_jounce_bumper_e2e.py`` (two ODBs, the .sta files, the extracted
metrics, and the acceptance verdict) and renders the official report from the
Abaqus/Explicit ODB, which is the only ODB this case's acceptance criteria are
evaluated against.

Two jobs back this case, and the report must not blur them:

  ``C07CompressJob`` Abaqus/Explicit, Step-2 51.0 mm quasi-static compression.
                     Primary evidence: every acceptance criterion, every
                     contour, and the report provenance bind to this ODB.
  ``C07SeatJob``     Abaqus/Standard, Step-1 0.50 mm interference seating.
                     Independent verification of the seating response. No
                     solver state is imported, so this ODB is recorded in the
                     manifest as separate evidence and is never presented as a
                     predecessor state of the Explicit compression.

Because the official pipeline accepts exactly one ``odb_path``, the Standard
job is materialised as manifest evidence (path, SHA-256, solver, purpose, .sta
completion marker) rather than being merged into the figure provenance.

The delivery gate stays closed unless the driver's verdict says
``deliverable=True``. A non-deliverable verdict is reported and the report is
refused; the gate is never bypassed to produce a file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.acceptance import (
    AcceptanceFindings,
    AcceptanceResult,
    CriterionResult,
)
from abaqus_ai_agent.contracts.provenance import issue_agent_run_record
from abaqus_ai_agent.execution.batch import resolve_default_launcher
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

DEFAULT_PROJECT = None
RUN_ID_PREFIX = "case07_live_"
CASE_ID = "CASE_07_AUTOMOTIVE_JOUNCE_BUMPER"
COMPRESS_STEP = "Step2Compression"
SEAT_STEP = "Step1Seating"
REPORT_NAME = "Case_07_Jounce_Bumper_Report.html"
ARCHIVE_REL = Path(
    "machine_validation/p2_cases/case_07_jounce_bumper_self_contact/" + REPORT_NAME
)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_evidence(project: Path, run_id: str | None) -> tuple[Path, dict]:
    """Locate the driver's qualification summary and read it."""
    evidence_root = project / "evidence"
    if run_id:
        candidates = [evidence_root / run_id / "case_07_live_qualification.json"]
    else:
        candidates = sorted(
            evidence_root.glob(RUN_ID_PREFIX + "*/case_07_live_qualification.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    for path in candidates:
        if path.is_file():
            return path, json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "Case 07 qualification summary not found under %s. "
        "Run tools/case_07_jounce_bumper_e2e.py first." % evidence_root
    )


def acceptance_from_evidence(summary: dict) -> AcceptanceResult:
    """Rebuild the driver's verdict without re-deciding it here.

    The criteria, gates, and deliverability are copied from the qualification
    run. Nothing is upgraded: if the driver recorded a failure, the rebuilt
    result keeps it and the report gate stays closed.
    """
    acc = summary.get("acceptance") or {}
    criteria = tuple(
        CriterionResult(
            name=str(c["name"]),
            passed=bool(c["passed"]),
            actual=float(c["actual"]) if c.get("actual") is not None else float("nan"),
            operator=str(c.get("operator", "")),
            limit=float(c.get("limit", 0.0)),
            unit=str(c.get("unit", "")),
        )
        for c in acc.get("criteria", [])
    )
    gates = dict(acc.get("gates") or {})
    justifications = dict(acc.get("gate_justifications") or {})
    failures = tuple(str(f) for f in acc.get("failures") or ())
    return AcceptanceResult(
        passed=bool(acc.get("passed")),
        criteria=criteria,
        failures=failures,
        status=str(acc.get("status", "UNKNOWN")),
        acceptance_status=str(acc.get("status", "UNKNOWN")),
        gates=gates,
        gate_justifications=justifications,
        result_validity="VALID" if summary.get("result_status") == "completed" else "SOLVER_FAILED",
        odb_status="valid" if not summary.get("degenerate_odbs") else "degenerate",
        deliverable=bool(acc.get("deliverable")),
        findings=AcceptanceFindings(failures=failures),
    )


def visualization_specs() -> list[VisualizationSpec]:
    return [
        VisualizationSpec(
            artifact_id="FIG-C07-MISES",
            visualization_type="stress_hotspot",
            field_name="S",
            component="mises",
            step_name=COMPRESS_STEP,
            frame_index=-1,
            view_mode="FRONT",
            output_position="INTEGRATION_POINT",
            target_filename="c07_mises.png",
            caption_zh="缓冲块压缩至 51 mm 时的 von Mises 应力分布云图",
            caption_en="Jounce Bumper von Mises Stress at 51 mm Compression",
        ),
        VisualizationSpec(
            artifact_id="FIG-C07-DISP",
            visualization_type="displacement_contour",
            field_name="U",
            component="magnitude",
            step_name=COMPRESS_STEP,
            frame_index=-1,
            view_mode="FRONT",
            output_position="NODAL",
            target_filename="c07_displacement.png",
            caption_zh="缓冲块位移幅值分布云图（行程 51 mm）",
            caption_en="Jounce Bumper Displacement Magnitude at 51 mm Stroke",
        ),
        VisualizationSpec(
            artifact_id="FIG-C07-CPRESS",
            visualization_type="contact_pressure",
            field_name="CPRESS",
            # CPRESS has no invariant or component to refine: the Viewer rejects
            # refinement=(INVARIANT|COMPONENT, ...) for it, so an empty component
            # must reach setPrimaryVariable as a plain label call.
            component="",
            step_name=COMPRESS_STEP,
            frame_index=-1,
            view_mode="FRONT",
            output_position="NODAL",
            target_filename="c07_contact_pressure.png",
            caption_zh="肋间自接触接触压力分布云图",
            caption_en="Rib Self-Contact Pressure Distribution",
        ),
    ]


def build_manifest(
    summary: dict,
    compress_odb: Path,
    seat_odb: Path | None,
    report_path: Path,
    report_sha256: str,
) -> dict:
    """Record both ODBs as separate evidence with their own provenance."""
    job_states = summary.get("job_states") or {}

    def job_record(name: str, solver: str, purpose: str, primary: bool, step: str) -> dict:
        state = job_states.get(name) or {}
        sta = state.get("sta") or {}
        return {
            "job": name,
            "solver": solver,
            "purpose": purpose,
            "primary_evidence": primary,
            "step": step,
            "odb_path": state.get("odb_path"),
            "odb_sha256": state.get("odb_sha256"),
            "odb_bytes": state.get("odb_bytes"),
            "odb_authentic": state.get("odb_authentic"),
            "completed": state.get("completed"),
            "executed_this_run": state.get("executed_this_run"),
            "sta_completion_marker": sta.get("completed"),
            "sta_last_line": sta.get("last_line"),
        }

    return {
        "case_id": CASE_ID,
        "report": {
            "path": str(report_path),
            "sha256": report_sha256,
            "size_bytes": report_path.stat().st_size,
        },
        "solver_evidence": [
            job_record(
                "compress", "Abaqus/Explicit",
                "51.0 mm quasi-static compression; source of every acceptance "
                "criterion and every contour figure in this report.",
                True, COMPRESS_STEP,
            ),
            job_record(
                "seat", "Abaqus/Standard",
                "0.50 mm interference seating, solved as an independent job. "
                "No solver state is imported into the Explicit job, so this is "
                "a separate seating verification and not a predecessor state.",
                False, SEAT_STEP,
            ),
        ],
        "figure_odb": str(compress_odb),
        "seat_odb": str(seat_odb) if seat_odb else None,
        "metrics": summary.get("metrics"),
        "seat_metrics": summary.get("seat_metrics"),
        "geometry_fidelity": summary.get("geometry_fidelity"),
        "acceptance": summary.get("acceptance"),
        "result_status": summary.get("result_status"),
    }


def generate_case_07_report(
    project: Path,
    run_id: str | None = None,
    launcher: str | None = None,
    output_dir: Path | None = None,
    archive_root: Path | None = None,
) -> dict:
    project = Path(project).resolve()
    evidence_path, summary = load_evidence(project, run_id)
    resolved_run_id = str(summary.get("run_id") or "").strip()
    if not resolved_run_id:
        raise ValueError("Qualification summary carries no run_id: %s" % evidence_path)

    compress_odb = Path(summary["odb_path"])
    seat_odb_raw = summary.get("seat_odb_path")
    seat_odb = Path(seat_odb_raw) if seat_odb_raw else None

    if not compress_odb.is_file():
        raise FileNotFoundError("Explicit ODB recorded in evidence is missing: %s" % compress_odb)
    if summary.get("degenerate_odbs"):
        raise ValueError(
            "Refusing to report a degenerate result: %s" % summary["degenerate_odbs"]
        )

    acceptance = acceptance_from_evidence(summary)
    if not acceptance.deliverable:
        raise PermissionError(
            "Case 07 is not deliverable (status=%s, failures=%s). "
            "An official report is not generated from a non-deliverable verdict."
            % (acceptance.status, list(acceptance.failures) or "none recorded")
        )

    # Provenance binding: the Explicit INP is the solved deck, so its digest is
    # the input hash the report and every figure are bound to. The ODB digest is
    # the output hash, and it must equal what the driver recorded.
    compress_inp = compress_odb.with_suffix(".inp")
    if not compress_inp.is_file():
        raise FileNotFoundError("Solved input deck is missing: %s" % compress_inp)
    input_hash = sha256_file(compress_inp)
    output_hash = sha256_file(compress_odb)
    recorded_hash = summary.get("odb_sha256")
    if recorded_hash and recorded_hash != output_hash:
        raise PermissionError(
            "ODB on disk no longer matches the qualification evidence "
            "(recorded=%s, live=%s). Re-run the driver." % (recorded_hash, output_hash)
        )

    resolved_launcher = resolve_default_launcher(launcher or os.environ.get("ABAQUS_BAT") or "abaqus")

    metrics = summary.get("metrics") or {}
    results_info = [
        {"metric": "max_mises_stress", "value": metrics.get("max_mises_mpa"), "unit": "MPa"},
        {"metric": "max_displacement", "value": metrics.get("max_displacement_mm"), "unit": "mm"},
        {"metric": "peak_reaction_force", "value": metrics.get("reaction_force_kn"), "unit": "kN"},
        {"metric": "max_contact_pressure", "value": metrics.get("max_contact_pressure_mpa"),
         "unit": "MPa"},
        {"metric": "max_self_contact_penetration", "value": metrics.get("contact_penetration"),
         "unit": "mm"},
        {"metric": "kinetic_internal_energy_ratio",
         "value": metrics.get("kinetic_internal_energy_ratio"), "unit": "-"},
    ]

    target_dir = (Path(output_dir) if output_dir else project / "delivery").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    pipeline = DeterministicReportPipeline()
    delivery_card, report_pointer, _report_data = pipeline.build_and_render(
        output_dir=target_dir,
        title="汽车悬架超弹性缓冲块大变形自接触分析报告",
        case_id=CASE_ID,
        run_id=resolved_run_id,
        model_info={
            "name": "C07Compress",
            "geometry": "轴对称带肋缓冲块，自由高度 85 mm，外径 70 mm，内孔 16 mm，3 条肋",
            "element_type": "CAX4R",
            "material": "超弹性 Mooney-Rivlin (C10=0.55, C01=0.14, D1=0.02)",
            "solver": "Abaqus/Explicit, Step2Compression, 2.0 s 准静态加载",
            "stroke_mm": 51.0,
            "contact": "通用接触自接触，摩擦系数 0.15",
            "max_mises_mpa": metrics.get("max_mises_mpa"),
            "max_displacement_mm": metrics.get("max_displacement_mm"),
        },
        results_info=results_info,
        acceptance_info=acceptance,
        visualization_specs=visualization_specs(),
        require_deliverable=True,
        odb_path=compress_odb,
        input_hash=input_hash,
        launcher=resolved_launcher,
        provenance=issue_agent_run_record(
            run_id=resolved_run_id,
            model_name="C07Compress",
            job_name="C07CompressJob",
            input_hash=input_hash,
            output_hash=output_hash,
            executor="qualification_script",
            requirement_kind="engineering_intent",
            jev_routed=False,
            agent_entry="generate_case_07_report",
        ).replace(abaqus_version="2025"),
    )

    official = target_dir / REPORT_NAME
    shutil.copyfile(report_pointer.location, official)
    official_sha = sha256_file(official)
    if official_sha != report_pointer.checksum_sha256:
        raise PermissionError(
            "Published report copy does not match the pipeline checksum "
            "(pipeline=%s, copy=%s)" % (report_pointer.checksum_sha256, official_sha)
        )

    manifest = build_manifest(summary, compress_odb, seat_odb, official, official_sha)
    manifest["delivery_card"] = {
        "deliverable": delivery_card.deliverable,
        "figures_count": delivery_card.figures_count,
        "acceptance_status": delivery_card.acceptance_status,
        "key_metrics": delivery_card.key_metrics,
    }
    manifest_path = target_dir / "case_07_jounce_bumper_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    archived = None
    if archive_root is not None:
        archive_path = (Path(archive_root) / ARCHIVE_REL).resolve()
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(official, archive_path)
        archive_sha = sha256_file(archive_path)
        if archive_sha != official_sha:
            raise PermissionError(
                "Archived report differs from the delivered report "
                "(delivery=%s, archive=%s)" % (official_sha, archive_sha)
            )
        archive_manifest = archive_path.parent / manifest_path.name
        shutil.copyfile(manifest_path, archive_manifest)
        archived = {
            "path": str(archive_path),
            "sha256": archive_sha,
            "manifest_path": str(archive_manifest),
        }

    manifest["archive"] = archived
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the Case 07 report from an existing solve (never re-solves)."
    )
    parser.add_argument("--project", required=True, help="External Case 07 project directory")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--launcher", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--archive-root",
        default=None,
        help="Repository root that receives the machine_validation archive copy (optional).",
    )
    args = parser.parse_args()

    manifest = generate_case_07_report(
        project=Path(args.project),
        run_id=args.run_id,
        launcher=args.launcher,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        archive_root=Path(args.archive_root) if args.archive_root else None,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
