"""Single file-write gate for engineering reports.

Formal filenames may be written only after verify_deliverable() accepts an
Agent-issued run record. A missing record, or results that are not bound to an
ODB content hash, must not produce a formal deliverable and must not be
captioned as Abaqus-AI-Agent work.

The digest checked here is tamper-evidence for an unsynced edit. It is not a
keyed signature and does not prove who produced the file.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, Optional

from ..contracts.provenance import provenance_from_mapping, verify_deliverable
from ..contracts.report import EngineeringReportData
from .renderer import render_html, render_markdown

_FORMAL_STEMS = {
    "report",
    "engineering_report",
    "fatigue_engineering_report",
    "static_golden_engineering_report",
    "live_test_report",
    "report_mp1",
    "report_mp2",
    "report_mp3",
    "report_mp4",
}

_DRAFT_BANNER = (
    "DIAGNOSTIC NON-DELIVERABLE DRAFT. "
    "Not authorized to be captioned as prepared by Abaqus-AI-Agent. "
    "No verifiable Agent run record, or results are not bound to an ODB content hash. "
    "This file is not an engineering deliverable."
)


def _as_record(record: Any, odb_sha256: Optional[str] = None, results: Any = None) -> Dict[str, Any]:
    provenance = provenance_from_mapping(record)
    if provenance is not None:
        payload: Dict[str, Any] = {"provenance": provenance.to_dict()}
    elif isinstance(record, dict):
        payload = dict(record)
    else:
        payload = {}
    if odb_sha256 and not payload.get("odb_sha256"):
        payload["odb_sha256"] = odb_sha256
    if results is not None and not payload.get("results"):
        payload["results"] = list(results)
    return payload


def _with_authorization(report: EngineeringReportData, gate: Dict[str, Any], provenance: Any) -> EngineeringReportData:
    metadata = dict(report.metadata or {})
    metadata["deliverable_authorization"] = gate
    changes: Dict[str, Any] = {"metadata": metadata}
    if provenance is not None and not report.provenance:
        changes["provenance"] = provenance
    return dataclasses.replace(report, **changes)


def _diagnostic_report(report: EngineeringReportData, gate: Dict[str, Any]) -> EngineeringReportData:
    metadata = dict(report.metadata or {})
    metadata["deliverable_authorization"] = gate
    metadata["is_diagnostic_draft"] = True
    title = report.title or "Engineering report"
    if not title.startswith("[DIAGNOSTIC"):
        title = "[DIAGNOSTIC / NON-DELIVERABLE DRAFT] " + title
    return dataclasses.replace(report, title=title, metadata=metadata)


def _diagnostic_text(body: str, fmt: str) -> str:
    if fmt == "html":
        banner = (
            '<div class="diagnostic-banner">%s</div>\n'
            '<p>Not authorized to be captioned as prepared by Abaqus-AI-Agent.</p>\n'
        ) % _DRAFT_BANNER
        if "<body" in body.lower():
            return body.replace("<body>", "<body>\n" + banner, 1).replace("<BODY>", "<BODY>\n" + banner, 1)
        return "<html><body>%s<pre>%s</pre></body></html>" % (banner, body)
    return "> %s\n\n%s" % (_DRAFT_BANNER, body)


def write_gated_engineering_report(
    path,
    report=None,
    content=None,
    record=None,
    odb_sha256=None,
    results=None,
    fmt=None,
    allow_diagnostic_draft=True,
    language=None,
) -> Dict[str, Any]:
    """Write a report only if the same delivery gate used by the product allows it.

    Returns a dict with written, kind ('deliverable' or 'diagnostic_draft'),
    path, and the gate decision. A refused formal write never creates the
    requested formal filename.
    """
    target = Path(path)
    suffix = target.suffix.lower()
    resolved_fmt = fmt or ("html" if suffix == ".html" else "markdown")
    payload = _as_record(record, odb_sha256=odb_sha256, results=results)
    if report is not None and not payload.get("results"):
        report_results = getattr(report, "results", None) or ()
        if report_results:
            payload["results"] = list(report_results)
    if report is not None and not payload.get("provenance"):
        provenance = provenance_from_mapping(getattr(report, "provenance", None))
        if provenance is not None:
            payload["provenance"] = provenance.to_dict()

    gate = verify_deliverable(payload)
    allowed = bool(gate.get("deliverable_file_allowed"))
    formal_name = target.stem.lower() in _FORMAL_STEMS or target.name.lower() in {"report.html", "report.md"}

    if allowed:
        provenance = payload.get("provenance")
        if report is not None:
            stamped = _with_authorization(report, gate, provenance)
            body = render_html(stamped, language=language) if resolved_fmt == "html" else render_markdown(stamped, language=language)
        else:
            body = content or ""
            if "Abaqus-AI-Agent 编制" in body or "Prepared by Abaqus-AI-Agent" in body:
                if not gate.get("allow_agent_attribution"):
                    raise PermissionError(
                        "Refusing to write a pre-rendered report that claims Agent authorship "
                        "without a JEV-routed run record."
                    )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return {
            "written": True,
            "kind": "deliverable",
            "path": str(target),
            "gate": gate,
        }

    if formal_name and not allow_diagnostic_draft:
        raise PermissionError(
            "Official engineering delivery blocked: Agent run record refused (%s). "
            "No report artifacts were written."
            % ", ".join(gate.get("reasons") or ["unspecified"])
        )
    if not allow_diagnostic_draft:
        raise PermissionError(
            "Engineering report write blocked: %s"
            % ", ".join(gate.get("reasons") or ["unspecified"])
        )

    draft_path = target.with_name(target.stem + ".diagnostic" + target.suffix)
    if report is not None:
        draft = _diagnostic_report(report, gate)
        body = render_html(draft, language=language) if resolved_fmt == "html" else render_markdown(draft, language=language)
    else:
        body = _diagnostic_text(content or "", resolved_fmt)
    if "Abaqus-AI-Agent 编制" in body:
        body = body.replace("Abaqus-AI-Agent 编制", "未授权署名")
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(body, encoding="utf-8")
    return {
        "written": True,
        "kind": "diagnostic_draft",
        "path": str(draft_path),
        "formal_path_refused": str(target),
        "gate": gate,
    }
