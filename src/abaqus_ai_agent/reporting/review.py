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
import re
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..contracts.approval import ExecutionCandidate

REVIEW_BANNER = (
    "PRE-SOLVE REVIEW - 待批准 · 未求解 · 不可作为正式工程结论 "
    "(awaiting human approval; no solver run has happened; not a formal deliverable)"
)

# Human labels for keys the product already writes. Unknown keys stay visible
# with a readable name; nothing is invented to fill a missing row.
_FIELD_LABELS = {
    "model_name": ("Model name", "模型名"),
    "part_name": ("Part name", "零件名"),
    "unit_system": ("Unit system", "单位制"),
    "mesh_requirements": ("Mesh requirements", "网格要求"),
    "mesh_quality": ("Mesh quality", "网格质量"),
    "mesh_quality_status": ("Mesh quality status", "网格质量状态"),
    "mesh_quality_parts": ("Parts in the mesh gate", "进入网格门的零件"),
    "mesh_quality_failed_elements": ("Failed elements", "不合格单元数"),
    "material": ("Material", "材料"),
    "solver": ("Solver", "求解器"),
    "strategy": ("Strategy", "分析策略"),
    "requires_user_confirmation": ("Needs confirmation", "是否需要确认"),
    "inp_path": ("Input deck", "输入文件"),
    "inp_sha256": ("Input digest", "输入摘要"),
    "job_name": ("Job name", "作业名"),
    "mode": ("Mode", "模式"),
    "candidate_id": ("Candidate", "候选编号"),
    "status": ("Status", "状态"),
    "execution_manifest_hash": ("Content hash the approval binds", "批准绑定的内容哈希"),
    "solver_config_hash": ("Solver config digest", "求解配置摘要"),
    "model_hash": ("Model digest", "模型摘要"),
    "intent_hash": ("Intent digest", "意图摘要"),
    "action_plan_hash": ("Action plan digest", "动作计划摘要"),
    "generator_version": ("Generator", "生成器版本"),
    "created_at": ("Created", "生成时间"),
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
_IMAGE_KEY_RE = re.compile(r"(image|figure|screenshot|png|jpg|svg)", re.IGNORECASE)


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _human_key(key: str) -> str:
    text = str(key)
    if text in _FIELD_LABELS:
        en, zh = _FIELD_LABELS[text]
        return "%s / %s" % (en, zh)
    numbered = re.match(r"^(load|bc|criterion|mesh)_(.+)$", text)
    names = {
        "load": ("Load", "载荷"),
        "bc": ("Boundary condition", "边界条件"),
        "criterion": ("Acceptance criterion", "验收准则"),
        "mesh": ("Mesh detail", "网格明细"),
    }
    if numbered and numbered.group(1) in names:
        en, zh = names[numbered.group(1)]
        return "%s %s / %s %s" % (en, numbered.group(2), zh, numbered.group(2))
    readable = text.replace("_", " ").strip()
    return readable[:1].upper() + readable[1:] if readable else text


def _rows(mapping: Optional[Mapping[str, Any]]) -> List[Tuple[str, str]]:
    rows = []
    for key, value in (mapping or {}).items():
        if value in (None, ""):
            continue
        rows.append((str(key), "" if value is None else str(value)))
    return rows


def _section_blob(title: str, rows: Sequence[Tuple[str, str]]) -> str:
    return (title + " " + " ".join(value for _, value in rows)).lower()


def _looks_like_image(key: str, value: str) -> bool:
    text = value.strip().strip('"').strip("'")
    if not text or "\n" in text or len(text) > 400:
        return False
    lower = text.lower()
    if not lower.endswith(_IMAGE_SUFFIXES):
        return False
    return bool(_IMAGE_KEY_RE.search(key) or _IMAGE_KEY_RE.search(Path(text).name))


def _real_images(workdir: Path, sections: Mapping[str, Mapping[str, Any]]) -> List[Tuple[str, Path]]:
    found = []
    seen = set()
    for title, mapping in sections.items():
        for key, value in _rows(mapping):
            if not _looks_like_image(key, value):
                continue
            candidate = Path(value.strip().strip('"').strip("'"))
            if not candidate.is_absolute():
                candidate = workdir / candidate
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_file() or resolved in seen:
                continue
            seen.add(resolved)
            found.append((title, resolved))
    return found


def _table(rows: Sequence[Tuple[str, str]], *, keep_keys: bool = False) -> str:
    if not rows:
        return "<p class=none>（未记录 / not recorded）</p>"
    body = []
    for key, value in rows:
        label = key if keep_keys else _human_key(key)
        body.append(
            "<tr><th>%s</th><td><code>%s</code></td></tr>" % (_esc(label), _esc(value))
        )
    return (
        "<div class=table-wrapper><table class='report-table kv'>"
        "<thead><tr><th>项目 / Item</th><th>记录值 / Recorded value</th></tr></thead>"
        "<tbody>%s</tbody></table></div>" % "".join(body)
    )


def _section(number: str, title: str, body_html: str, lead: str = "") -> str:
    lead_html = "<p class=report-p>%s</p>" % _esc(lead) if lead else ""
    return (
        "<section><h2 class=section-heading>%s. %s</h2>%s%s</section>"
        % (_esc(number), _esc(title), lead_html, body_html)
    )


def _card(label: str, value: str, sub: str, tone: str = "") -> str:
    klass = "kpi-card" + (" " + tone if tone else "")
    return (
        "<div class='%s'><div class=kpi-label>%s</div>"
        "<div class=kpi-value>%s</div><div class=kpi-sub>%s</div></div>"
        % (klass, _esc(label), _esc(value), _esc(sub))
    )


def _schematic() -> str:
    """A labelled setup sketch. It is not a contour plot and not a solved result."""
    return """
<figure class="report-figure schematic">
  <svg viewBox="0 0 760 220" role="img" aria-label="Schematic of restraint, load and mesh gate">
    <rect x="1" y="1" width="758" height="218" fill="#f8fafc" stroke="#e2e8f0"/>
    <text x="16" y="24" class="svg-title">示意图 / Schematic only — 不是求解结果，不是应力云图</text>
    <g transform="translate(24,48)">
      <text x="0" y="14" class="svg-label">约束 / Restraint</text>
      <rect x="0" y="28" width="16" height="72" fill="#1e3a8a"/>
      <path d="M16 40 H150" stroke="#334155" stroke-width="8"/>
      <path d="M150 28 L178 40 L150 52 Z" fill="#b45309"/>
      <text x="28" y="86" class="svg-note">固定端示意</text>
      <text x="118" y="86" class="svg-note">载荷方向示意</text>
    </g>
    <g transform="translate(280,48)">
      <text x="0" y="14" class="svg-label">网格门 / Mesh gate</text>
      <rect x="0" y="28" width="150" height="28" fill="#dcfce7" stroke="#86efac"/>
      <rect x="0" y="60" width="150" height="28" fill="#fef3c7" stroke="#fcd34d"/>
      <text x="8" y="47" class="svg-note">记录到的零件指标</text>
      <text x="8" y="79" class="svg-note">未求解，无收敛结论</text>
    </g>
    <g transform="translate(500,48)">
      <text x="0" y="14" class="svg-label">本页没有 / Not on this page</text>
      <text x="0" y="48" class="svg-note">位移云图</text>
      <text x="0" y="70" class="svg-note">应力云图</text>
      <text x="0" y="92" class="svg-note">热点 / 安全系数</text>
    </g>
  </svg>
  <figcaption class="figure-caption">图 1 / Figure 1 · 约束、载荷方向与网格门的示意图。没有几何截图时不绘制云图。</figcaption>
</figure>
""".strip()


def _image_figures(images: Sequence[Tuple[str, Path]]) -> str:
    blocks = []
    for index, (title, path) in enumerate(images, start=2):
        uri = path.resolve().as_uri()
        blocks.append(
            "<figure class='report-figure evidence-image'>"
            "<img class=figure-img src=\"%s\" alt=\"%s\">"
            "<figcaption class=figure-caption>图 %s / Figure %s · 来自已有证据文件，不是本页生成的求解云图。"
            "来源章节：%s。文件：<code>%s</code></figcaption></figure>"
            % (_esc(uri), _esc(path.name), index, index, _esc(title), _esc(path.name))
        )
    return "".join(blocks)


def _risk_lines(sections: Mapping[str, Mapping[str, Any]], notes: Sequence[str]) -> List[str]:
    lines = [
        "本页批准的是即将执行的输入版本，不是分析结果。批准后内容一变，批准即失效。",
        "This page approves the input version that would run. It is not an analysis result. Any later change supersedes the approval.",
    ]
    for title, mapping in sections.items():
        blob = _section_blob(title, _rows(mapping))
        if "mesh" in title.lower() or "网格" in title:
            if any(token in blob for token in ("fail", "warning", "expired", "unsupported")):
                lines.append(
                    "网格记录里有未通过、警告或过期状态。批准前请核对逐零件明细，不要只看汇总。"
                )
            if "not_run" in blob or "not checked" in blob:
                lines.append("网格质量尚未形成可引用结论，不能把“未检查”读成合格。")
    for note in notes:
        if note and note not in lines:
            lines.append(note)
    return lines


def _not_solved_section(number: str) -> str:
    rows = (
        ("位移 / 应力结果", "未求解，不在本页"),
        ("热点坐标 / 节点", "未求解，不在本页"),
        ("安全系数 / 安全裕度", "未求解，不在本页"),
        ("ODB / 结果云图", "未生成，本页不引用"),
    )
    body = "".join("<tr><th>%s</th><td>%s</td></tr>" % (_esc(k), _esc(v)) for k, v in rows)
    return _section(
        number,
        "Results, hotspots and safety factors / 结果、热点与安全系数",
        "<div class=table-wrapper><table class=report-table><thead><tr>"
        "<th>正式报告才会有的章节 / Later report section</th>"
        "<th>本页状态 / Status on this page</th></tr></thead><tbody>%s</tbody></table></div>"
        % body,
        "这些章节属于求解之后的正式报告。此处留空是边界，不是漏数据。",
    )


def _styles() -> str:
    return """
:root { --bg:#f8fafc; --card:#fff; --text:#0f172a; --muted:#475569; --border:#e2e8f0; --warn:#fff3cd; --warn-border:#d39e00; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font-family:"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif; line-height:1.6; padding:28px 16px; }
.report { max-width:1080px; margin:0 auto; background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:36px 40px 48px; }
.banner { background:var(--warn); border:2px solid var(--warn-border); border-radius:8px; padding:14px 16px;
  font-weight:700; margin-bottom:20px; }
h1 { font-size:26px; margin:0 0 8px; }
.lead { color:var(--muted); margin:0 0 22px; }
.kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:18px 0 8px; }
.kpi-card { background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:14px; }
.kpi-card.warn { background:#fff7ed; border-color:#fdba74; }
.kpi-card.blocked { background:#fef2f2; border-color:#fca5a5; }
.kpi-label { font-size:11px; letter-spacing:.04em; text-transform:uppercase; color:#64748b; font-weight:700; }
.kpi-value { font-size:18px; font-weight:800; word-break:break-all; }
.kpi-sub { font-size:12px; color:#64748b; }
.section-heading { font-size:18px; color:#1e3a8a; margin:32px 0 10px; padding-left:10px; border-left:4px solid #2563eb; }
.report-p { color:#334155; font-size:14px; }
.table-wrapper { overflow-x:auto; border:1px solid var(--border); border-radius:8px; margin:10px 0 16px; }
table.report-table { width:100%; border-collapse:collapse; font-size:13px; }
table.report-table th { background:#0f172a; color:#f8fafc; text-align:left; padding:9px 12px; }
table.report-table td { padding:9px 12px; border-bottom:1px solid var(--border); vertical-align:top; }
table.report-table tbody tr:nth-child(even) td { background:#f8fafc; }
table.kv th { width:34%; background:#f8fafc; color:#0f172a; font-weight:650; }
table.kv td code, .hash { font-family:ui-monospace,Consolas,monospace; word-break:break-all; }
.none { color:#64748b; font-style:italic; }
.report-figure { margin:18px 0; border:1px solid var(--border); border-radius:8px; padding:12px; background:#fff; }
.schematic { background:#fffbeb; }
.svg-title { font-size:13px; font-weight:700; fill:#92400e; }
.svg-label { font-size:13px; font-weight:700; fill:#1e3a8a; }
.svg-note { font-size:12px; fill:#334155; }
.figure-img { max-width:100%; height:auto; }
.figure-caption { color:#475569; font-size:13px; margin-top:8px; }
ul.risks { margin:8px 0 0; padding-left:18px; }
ul.risks li { margin:6px 0; }
pre.approve { background:#0f172a; color:#e2e8f0; padding:12px 14px; border-radius:8px; overflow-x:auto; }
@media print { body { background:#fff; padding:0; } .report { border:0; box-shadow:none; } }
""".strip()


def render_pre_solve_review(
    workdir: Any,
    candidate: ExecutionCandidate,
    *,
    sections: Optional[Mapping[str, Mapping[str, Any]]] = None,
    notes: Iterable[str] = (),
    filename: str = "pre_solve_review.html",
) -> Path:
    """Write the Phase A review report and return its path.

    ``sections`` maps a section title to key/value rows (model and mesh,
    material, analysis settings, loads and BCs, acceptance preview, risks).
    Callers pass what they actually know; absent sections render as not
    recorded instead of being invented.
    """
    workdir_path = Path(workdir)
    section_map = dict(sections or {})
    note_list = [str(item) for item in notes if item]
    images = _real_images(workdir_path, section_map)

    identity = [
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
    short_hash = (candidate.execution_manifest_hash or "")[:12]

    parts = [
        "<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width, initial-scale=1'>",
        "<title>求解前评审 / Pre-Solve Review</title>",
        "<style>%s</style></head><body>" % _styles(),
        "<div class=report>",
        "<div class=banner>%s</div>" % _esc(REVIEW_BANNER),
        "<h1>求解前评审 / Pre-Solve Review</h1>",
        "<p class=lead>这是给人看的批准页，不是正式交付报告。下面只记录即将求解的模型、材料、约束、载荷和网格。"
        "没有求解，就没有结果、热点或安全系数。</p>",
        "<div class=kpi-grid>",
        _card("状态 / Status", "待批准", "Awaiting approval", "warn"),
        _card("求解 / Solve", "未运行", "No ODB, no contour plot", "blocked"),
        _card("绑定哈希 / Bound hash", short_hash or "(none)", "批准绑定整份候选，不只绑定这 12 位"),
        _card("正式结论 / Deliverable", "不是", "Not an engineering conclusion", "blocked"),
        "</div>",
        _schematic(),
        _image_figures(images),
        _section(
            "1",
            "What this page is / 本页是什么",
            "<p class=report-p>请按章节核对：模型与网格、材料、分析设置、边界、载荷、风险，以及页面底部的批准命令。"
            "图 1 只是约束和载荷方向的示意图。只有工作目录里已经存在的图片才会嵌进来，本页不生成云图。</p>",
        ),
        _section(
            "2",
            "Execution candidate / 执行候选版本",
            _table(identity),
            "批准绑定的是这份候选的内容哈希。候选一改，旧批准失效。",
        ),
    ]
    if candidate.dependency_hashes:
        dep_rows = sorted((str(k), str(v)) for k, v in candidate.dependency_hashes.items())
        parts.append(_section(
            "2b",
            "Input dependencies (*INCLUDE) / 输入依赖",
            _table(dep_rows, keep_keys=True),
        ))

    number = 3
    for title, mapping in section_map.items():
        rows = _rows(mapping)
        parts.append(_section(str(number), title, _table(rows)))
        number += 1

    parts.append(_not_solved_section(str(number)))
    number += 1
    risk_items = "".join("<li>%s</li>" % _esc(line) for line in _risk_lines(section_map, note_list))
    parts.append(_section(
        str(number),
        "Risks to check before approval / 批准前要看的风险",
        "<ul class=risks>%s</ul>" % risk_items,
    ))
    number += 1
    parts.append(_section(
        str(number),
        "How to approve / 如何批准",
        "<p class=report-p>只批准这一版内容。批准后用同一个工作目录重跑，不要改 INP，也不要另开一次求解。</p>"
        "<pre class=approve>python -m abaqus_ai_agent approve --workdir \"%s\" --by &lt;your name&gt;</pre>"
        "<p class=report-p>输入文件、依赖或求解配置任一变化，都会使这份候选失效，必须重新评审。"
        "批准摘要只用于发现篡改，不是身份签名。</p>" % _esc(workdir),
    ))
    parts.append("</div></body></html>")
    out = workdir_path / filename
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
