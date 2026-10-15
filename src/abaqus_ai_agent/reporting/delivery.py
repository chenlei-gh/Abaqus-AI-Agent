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
from .renderer import render_html

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
    if isinstance(record, dict):
        payload = dict(record)
        nested = payload.get("provenance")
        if isinstance(nested, dict) or nested is not None:
            provenance = provenance_from_mapping(nested)
            if provenance is not None:
                payload["provenance"] = provenance.to_dict()
    else:
        provenance = provenance_from_mapping(record)
        payload = {"provenance": provenance.to_dict()} if provenance is not None else {}
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

    HTML is the only file this function writes. A Markdown request, including an
    otherwise authorized one, writes nothing: no `report.md` and no `*.preview.md`.
    A refused HTML request may become a bannered `*.diagnostic.html` only when
    diagnostic drafts are allowed. A refused formal write never creates the
    requested formal filename.
    """
    target = Path(path)
    suffix = target.suffix.lower()
    requested_markdown = fmt == "markdown" or suffix in {".md", ".markdown"}
    if requested_markdown:
        raise PermissionError(
            "Markdown engineering reports are not written. HTML is the only report file."
        )
    resolved_fmt = "html"
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
    formal_name = (
        target.stem.lower() in _FORMAL_STEMS
        or target.name.lower() in {"report.html", "report.md"}
    )
    write_path = target
    write_kind = "deliverable"

    if allowed:
        provenance = payload.get("provenance")
        if report is not None:
            stamped = _with_authorization(report, gate, provenance)
            body = render_html(stamped, language=language, base_dir=target.parent)
        else:
            body = content or ""
            if "Abaqus-AI-Agent \u7f16\u5236" in body or "Prepared by Abaqus-AI-Agent" in body:
                if not gate.get("allow_agent_attribution"):
                    raise PermissionError(
                        "Refusing to write a pre-rendered report that claims Agent authorship "
                        "without a JEV-routed run record."
                    )
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(body, encoding="utf-8")
        return {
            "written": True,
            "kind": write_kind,
            "path": str(write_path),
            "formal_path_refused": str(target) if write_path != target else None,
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

    # A refused report is never filed as Markdown. HTML keeps the banner visible.
    draft_suffix = target.suffix or ".html"
    if draft_suffix.lower() != ".html":
        draft_suffix = ".html"
    draft_path = target.with_name(target.stem + ".diagnostic" + draft_suffix)
    if report is not None:
        draft = _diagnostic_report(report, gate)
        body = render_html(draft, language=language, base_dir=target.parent)
    else:
        body = _diagnostic_text(content or "", "html")
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
