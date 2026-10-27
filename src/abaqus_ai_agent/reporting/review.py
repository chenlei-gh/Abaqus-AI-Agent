"""PRE_SOLVE_REVIEW report renderer (Phase A artifact).

This report is a review document for a human decision BEFORE any solver
submission. It is deliberately NOT produced by the formal delivery pipeline
and carries no agent issuance stamp, no acceptance verdict, and no ODB
evidence, so it can never satisfy ``verify_deliverable``. Every page states
that it is not an engineering conclusion.

The same file (``pre_solve_review.html`` in the run workdir) is what the
approval binds via its content hash: approving after reviewing means the
record proves which document the reviewer saw.
"""

import html
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ..contracts.approval import ExecutionCandidate

REVIEW_BANNER = (
    "PRE-SOLVE REVIEW - 待批准 · 未求解 · 不可作为正式工程结论 "
    "(awaiting human approval; no solver run has happened; not a formal deliverable)"
)


def _esc(value: Any) -> str:
    import html as _html
    return _html.escape("" if value is None else str(value))


def _kv_table(rows: Iterable[Tuple[str, Any]]) -> str:
    body = "".join(
        f"<tr><th>{_esc(k)}</th><td><code>{_esc(v)}</code></td></tr>" for k, v in rows if v not in (None, "")
    )
    return f"<table class=kv>{body}</table>" if body else "<p class=none>(none recorded)</p>"


def _section(title: str, body_html: str) -> str:
    return f"<section><h2>{_esc(title)}</h2>{body_html}</section>"


def render_pre_solve_review(
    workdir: Any,
    candidate: ExecutionCandidate,
    *,
    sections: Optional[Mapping[str, Mapping[str, Any]]] = None,
    notes: Iterable[str] = (),
    filename: str = "pre_solve_review.html",
) -> Path:
    """Write the Phase A review report and return its path.

    ``sections`` maps a section title to key/value rows (model & mesh,
    material, analysis settings, loads & BCs, acceptance preview, risks).
    Callers pass what they actually know; absent sections render as not
    recorded instead of being invented.
    """
    rows = [
        ("candidate_id", candidate.candidate_id),
        ("status", candidate.status.value),
        ("execution_manifest_hash", candidate.execution_manifest_hash),
        ("inp_sha256", candidate.inp_sha256),
        ("solver_config_hash", candidate.solver_config_hash),
        ("model_hash", candidate.model_hash),
        ("intent_hash", candidate.intent_hash),
        ("action_plan_hash", candidate.action_plan_hash),
        ("generator_version", candidate.generator_version),
        ("created_at", candidate.created_at),
    ]
    parts = [
        "<!DOCTYPE html><html><head><meta charset=utf-8>",
        "<title>Pre-Solve Review</title>",
        "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:2em;max-width:960px}",
        ".banner{background:#fff3cd;border:2px solid #d39e00;padding:1em;font-weight:bold}",
        "table.kv{border-collapse:collapse}table.kv th{text-align:left;vertical-align:top;",
        "padding:2px 12px 2px 0;color:#555}table.kv td code{word-break:break-all}",
        "section{margin-top:1.5em}h1{font-size:1.4em}h2{font-size:1.1em;border-bottom:1px solid #ccc}",
        ".none{color:#888;font-style:italic}</style></head><body>",
        f"<div class=banner>{_esc(REVIEW_BANNER)}</div>",
        "<h1>Pre-Solve Review / 求解前评审</h1>",
        _section("Execution candidate / 执行候选版本", _kv_table(rows)),
    ]
    if candidate.dependency_hashes:
        dep_rows = sorted(candidate.dependency_hashes.items())
        parts.append(_section("Input dependencies (*INCLUDE) / 输入依赖", _kv_table(dep_rows)))
    for title, kv in (sections or {}).items():
        parts.append(_section(title, _kv_table(kv.items())))
    note_items = "".join(f"<li>{_esc(n)}</li>" for n in notes if n)
    if note_items:
        parts.append(_section("Notes / 说明", f"<ul>{note_items}</ul>"))
    parts.append(_section(
        "How to approve / 如何批准",
        "<p>Approve exactly this content version, then re-run with the same workdir:</p>"
        f'<pre>python -m abaqus_ai_agent approve --workdir "{_esc(workdir)}" --by &lt;your name&gt;</pre>'
        "<p>Any change to the deck, its dependencies, or the solver config supersedes this "
        "candidate and requires a new review. Approval digests are tamper-evidence, not "
        "identity signatures.</p>",
    ))
    parts.append("</body></html>")
    out = Path(workdir) / filename
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
