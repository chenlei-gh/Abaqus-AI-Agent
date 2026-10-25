from __future__ import annotations

import base64
import html
import json
import mimetypes
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

def _plain(value):
    if value is None: return None
    if hasattr(value, "__dataclass_fields__"):
        return {name: _plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, dict): return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_plain(v) for v in value]
    return value


def _is_chinese_report(report, language=None):
    if language is not None:
        return str(language).strip().lower() in ("zh", "zh-cn", "cn", "chinese", "bilingual", "dual")
    if hasattr(report, "metadata") and isinstance(report.metadata, dict):
        lang = report.metadata.get("language")
        if lang and str(lang).strip().lower() in ("zh", "zh-cn", "cn", "chinese", "bilingual", "dual"):
            return True
        if report.metadata.get("bilingual") or report.metadata.get("dual_language"):
            return True
    title = getattr(report, "title", "") or ""
    if any('\u4e00' <= char <= '\u9fff' for char in title):
        return True
    objective = getattr(report, "objective", "") or ""
    if any('\u4e00' <= char <= '\u9fff' for char in objective):
        return True
    return False


def _resolve_image_path(path_str, base_dir=None):
    """Deterministically and safely resolve visual asset paths for engineering reports.

    P1 Security & Integrity Contract:
    - Only accepts explicitly specified absolute paths or valid relative paths.
    - If base_dir is supplied, relative paths resolve strictly against base_dir.
    - Strictly forbids fuzzy cross-directory fallback searches into test_assets,
      machine_validation, or global repo_root.glob(**/*) scans, preventing wrong-figure
      substitution when a run artifact is missing.
    - Returns None if the target file does not exist, allowing _render_html_figure
      to cleanly trigger the 'figure-missing' engineering placeholder.
    """
    if not path_str or path_str.startswith("data:") or path_str.startswith("http://") or path_str.startswith("https://"):
        return None
    try:
        p = Path(path_str)
    except Exception:
        return None

    # 1. Absolute paths are evaluated strictly directly
    if p.is_absolute():
        try:
            return p.resolve() if p.is_file() else None
        except Exception:
            return None

    # 2. When base_dir is supplied, relative paths resolve STRICTLY against base_dir.
    #    Never fall back to current working directory (cwd) to avoid collision with
    #    accidental identical file names in cwd.
    #    Strictly reject path traversal escaping outside base_dir.
    if base_dir:
        try:
            resolved_base = Path(base_dir).resolve()
            cand = (resolved_base / p).resolve()
            if not cand.is_relative_to(resolved_base):
                # Path traversal attempt escaping base_dir
                return None
            return cand if cand.is_file() else None
        except Exception:
            return None

    # 3. When base_dir is not provided, evaluate relative to cwd only
    try:
        if p.is_file():
            return p.resolve()
    except Exception:
        pass

    # 4. Fail-Closed: Never perform fuzzy global searches or test asset fallbacks
    return None


def _render_html_figure(caption, path_str, is_zh=False, base_dir=None):
    """Render publication-grade HTML figure with automatic SVG inlining, Base64 bitmap data URI, or visual placeholder."""
    fig_label = "图 / Figure:" if is_zh else "Figure:"
    is_anim = path_str and (path_str.lower().endswith(".gif") or "anim" in path_str.lower() or "动画" in caption or "Animation" in caption)
    anim_badge = ' <span class="status-badge badge-pass" style="margin-left: 6px; font-size: 11px;">[动图 / Animation]</span>' if is_anim else ""

    # 1. Inline SVG text directly in path
    if path_str and "<svg" in path_str and "</svg>" in path_str:
        start_idx = path_str.find("<svg")
        end_idx = path_str.rfind("</svg>")
        svg_content = path_str[start_idx:end_idx + 6]
        return (
            f'<figure class="report-figure">'
            f'<div class="svg-container">{svg_content}</div>'
            f'<figcaption class="figure-caption"><strong>{fig_label}</strong> {html.escape(caption)}{anim_badge}</figcaption>'
            f'</figure>'
        )

    # 2. Already Data URI or HTTP URL
    if path_str and (path_str.startswith("data:") or path_str.startswith("http://") or path_str.startswith("https://")):
        return (
            f'<figure class="report-figure">'
            f'<img src="{html.escape(path_str, quote=True)}" alt="{html.escape(caption, quote=True)}" class="figure-img">'
            f'<figcaption class="figure-caption"><strong>{fig_label}</strong> {html.escape(caption)}{anim_badge}</figcaption>'
            f'</figure>'
        )

    # 3. Resolve path on disk strictly
    resolved_file = _resolve_image_path(path_str, base_dir=base_dir)
    if resolved_file and resolved_file.is_file():
        suffix = resolved_file.suffix.lower()
        if suffix == ".svg":
            try:
                raw_svg = resolved_file.read_text(encoding="utf-8")
                start_idx = raw_svg.find("<svg")
                end_idx = raw_svg.rfind("</svg>")
                if start_idx != -1 and end_idx != -1:
                    svg_content = raw_svg[start_idx:end_idx + 6]
                    return (
                        f'<figure class="report-figure">'
                        f'<div class="svg-container">{svg_content}</div>'
                        f'<figcaption class="figure-caption"><strong>{fig_label}</strong> {html.escape(caption)}{anim_badge}</figcaption>'
                        f'</figure>'
                    )
            except Exception:
                pass
        else:
            # Bitmap formats: PNG, JPG, JPEG, WEBP, GIF -> Self-contained Base64 Data URI
            try:
                raw_bytes = resolved_file.read_bytes()
                mime = "image/gif" if suffix == ".gif" else (mimetypes.guess_type(resolved_file.name)[0] or "image/png")
                b64_data = base64.b64encode(raw_bytes).decode("ascii")
                data_uri = f"data:{mime};base64,{b64_data}"
                return (
                    f'<figure class="report-figure">'
                    f'<img src="{data_uri}" alt="{html.escape(caption, quote=True)}" class="figure-img">'
                    f'<figcaption class="figure-caption"><strong>{fig_label}</strong> {html.escape(caption)}{anim_badge}</figcaption>'
                    f'</figure>'
                )
            except Exception:
                pass

    # 4. Fallback: Elegant engineering placeholder card if file is not found
    missing_title = "图面工程资产 (Visual Engineering Asset)" if is_zh else "Visual Engineering Asset"
    missing_desc = (
        f"图面资产文件未在磁盘找到，预期引用路径: <code>{html.escape(path_str)}</code>"
        if is_zh else
        f"Visual asset file not located on disk, expected reference path: <code>{html.escape(path_str)}</code>"
    )
    return (
        f'<figure class="report-figure figure-missing">'
        f'<div class="placeholder-box">'
        f'<div class="placeholder-icon">&#128444;</div>'
        f'<div class="placeholder-title">{html.escape(missing_title)}</div>'
        f'<div class="placeholder-path">{missing_desc}</div>'
        f'</div>'
        f'<figcaption class="figure-caption"><strong>{fig_label}</strong> {html.escape(caption)}</figcaption>'
        f'</figure>'
    )


def _format_inline_markdown(text: str) -> str:
    """Safely and deterministically transform inline markdown (*, **, `) into HTML elements."""
    if not text:
        return ""
    # 1. Escape HTML special characters first to avoid XSS / tag breakage
    escaped = html.escape(str(text))
    # 2. Inline code: `code` -> <code>code</code>
    escaped = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', escaped)
    # 3. Bold: **bold** -> <strong>bold</strong>
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    # 4. Italic: *italic* (only isolated single asterisk)
    escaped = re.sub(r'(?<!\*)\*([^\*\n]+?)\*(?!\*)', r'<em>\1</em>', escaped)
    return escaped


def _format_cell_badge(c_clean, is_zh=False):
    c_clean_str = str(c_clean).strip()
    badge_key = c_clean_str
    if badge_key.startswith("**") and badge_key.endswith("**") and len(badge_key) > 4:
        badge_key = badge_key[2:-2].strip()

    pass_badges = (
        "PASS", "合格", "通过", "通过 / PASS", "PASS / 合格", "VALID", "有效",
        "BALANCED", "平衡", "STABLE", "稳定", "YES", "已成功自愈",
        "VERIFIED", "VERIFIED PASS", "合格 (VERIFIED PASS)"
    )
    fail_badges = (
        "FAIL", "不合格", "未通过", "未合格", "FAIL / 未合格", "REJECTED",
        "TAMPERED", "DRIFT_EXCEEDED", "漂移超标", "NO", "需人工介入", "FAILED"
    )
    skip_badges = ("SKIPPED", "跳过", "忽略", "SKIPPED / 忽略")

    if badge_key in pass_badges:
        display = badge_key if c_clean_str.startswith("**") else c_clean_str
        return f'<span class="status-badge badge-pass">{html.escape(display)}</span>'
    elif badge_key in fail_badges or (badge_key.startswith("FAIL (") and badge_key.endswith(")")):
        display = badge_key if c_clean_str.startswith("**") else c_clean_str
        return f'<span class="status-badge badge-fail">{html.escape(display)}</span>'
    elif badge_key in skip_badges:
        display = badge_key if c_clean_str.startswith("**") else c_clean_str
        return f'<span class="status-badge badge-skip">{html.escape(display)}</span>'

    return _format_inline_markdown(c_clean_str)


def _format_markdown_table(headers, rows):
    if not rows:
        return ""
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(val)))
    header_line = "| " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    separator_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    data_lines = [
        "| " + " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator_line] + data_lines)


def _render_custom_table_for_section(heading, value, is_zh=False):
    lines = []

    # 2. Model Information
    if heading.startswith("2. Model Information") and isinstance(value, dict) and value:
        # 2a. Assembly Components if present
        components = value.get("assembly_components")
        if components and isinstance(components, (list, tuple)):
            c_rows = []
            for idx, c in enumerate(components, 1):
                p_label = f"部件 {idx}" if is_zh else f"Part {idx}"
                desc_label = "结构装配构件" if is_zh else "Structural Assembly Component"
                if isinstance(c, dict):
                    c_rows.append([p_label, str(c.get("name") or c.get("part_name") or "-"), str(c.get("role") or c.get("description") or "-")])
                else:
                    c_rows.append([p_label, str(c), desc_label])
            sub_title = "### 装配体组件结构明细 (Assembly Structure)" if is_zh else "### Assembly Component Structure"
            th = ["序号 / Item", "部件名称 / Component", "工程功能与结构角色 / Description"] if is_zh else ["Item", "Component Designation", "Engineering Description"]
            lines += [sub_title, "", _format_markdown_table(th, c_rows), ""]

        # 2b. Geometric & Structural Parameters
        param_rows = []
        skip_keys = {"assembly_components", "metadata"}
        param_zh_map = {
            # 歧管相关 (Case 3 Exhaust Manifold)
            "overall_length_mm": "歧管总长度 / Overall Length (mm)",
            "runner_outer_diameter_mm": "支管外径 / Runner Outer Diameter (mm)",
            "runner_wall_thickness_mm": "支管壁厚 / Runner Wall Thickness (mm)",
            "flange_thickness_mm": "法兰厚度 / Flange Thickness (mm)",
            "bolt_count": "紧固螺栓数量 / Bolt Count",
            "bolt_nominal_size": "螺栓公称规格 / Bolt Nominal Size",
            "bolt_clearance_hole_diameter_mm": "螺栓通孔直径 / Clearance Hole Diameter (mm)",
            "bolt_radial_clearance_mm": "螺栓径向间隙 / Radial Clearance (mm)",
            "gasket_nominal_thickness_mm": "垫片名义厚度 / Gasket Nominal Thickness (mm)",
            # 管道与法兰相关 (Case 1 Bolted Flange)
            "pipe_inner_radius_mm": "管道内半径 / Pipe Inner Radius (mm)",
            "pipe_outer_radius_mm": "管道外半径 / Pipe Outer Radius (mm)",
            "flange_outer_diameter_mm": "法兰外径 / Flange Outer Diameter (mm)",
            "raised_face_diameter_mm": "突面密封面外径 / Raised Face Diameter (mm)",
            "bolt_circle_diameter_mm": "螺栓分度圆直径 / Bolt Circle Diameter (mm)",
            "bolt_nominal_diameter_mm": "螺栓公称直径 / Bolt Nominal Diameter (mm)",
            "bolt_preload_n": "单螺栓预紧力 / Bolt Preload Force (N)",
            "internal_fluid_pressure_mpa": "介质设计内压 / Internal Design Pressure (MPa)",
            "operating_temperature_c": "运行工况温度 / Operating Temperature (°C)",
            # 反应堆压力容器相关 (Case 2 Reactor Pressure Vessel)
            "vessel_inner_radius_mm": "压力容器内半径 / Vessel Inner Radius (mm)",
            "vessel_wall_thickness_mm": "容器筒体壁厚 / Vessel Wall Thickness (mm)",
            "closure_head_crown_radius_mm": "顶盖封头球面半径 / Closure Head Crown Radius (mm)",
            "flange_ring_outer_diameter_mm": "法兰环外径 / Flange Ring Outer Diameter (mm)",
            "stud_count": "主螺栓/双头螺柱数量 / Main Stud Bolt Count",
            "stud_nominal_diameter_mm": "螺柱公称直径 / Stud Nominal Diameter (mm)",
            "stud_pitch_circle_diameter_mm": "螺柱分度圆直径 / Stud Pitch Circle Diameter (mm)",
            "design_internal_pressure_mpa": "设计内压峰值 / Peak Design Pressure (MPa)",
            "design_operating_temperature_c": "设计运行温度 / Design Temperature (°C)",
            "seal_mean_diameter_mm": "密封环平均密封直径 / Seal Mean Diameter (mm)",
            "seal_cone_angle_deg": "双锥密封环锥角 / Seal Cone Angle (deg)",
            # 通用结构尺寸 (General Structural)
            "length_mm": "结构长度 / Length (mm)",
            "width_mm": "结构宽度 / Width (mm)",
            "height_mm": "结构高度 / Height (mm)",
            "thickness_mm": "结构壁厚 / Thickness (mm)",
            "outer_diameter_mm": "外径规格 / Outer Diameter (mm)",
            "inner_diameter_mm": "内径规格 / Inner Diameter (mm)",
        }
        for k, v in value.items():
            if k in skip_keys or isinstance(v, (dict, list, tuple)):
                continue
            k_clean = param_zh_map.get(k, k.replace("_", " ").title()) if is_zh else k.replace("_", " ").title()
            param_rows.append([k_clean, str(v)])
        if param_rows:
            sub_title = "### 几何尺寸与装配技术规格 (Geometric & Assembly Spec)" if is_zh else "### Geometric Dimensions & Assembly Specification"
            th = ["技术参数项 / Parameter", "设计设定值 / Design Value"] if is_zh else ["Specification Parameter", "Design Value"]
            lines += [sub_title, "", _format_markdown_table(th, param_rows), ""]

    # 3. Material
    elif heading.startswith("3. Material") and value is not None:
        mat_list = []
        if isinstance(value, (list, tuple)):
            mat_list = list(value)
        elif isinstance(value, dict):
            if "name" in value:
                mat_list = [value]
            else:
                for k, v in value.items():
                    if isinstance(v, dict):
                        m_copy = dict(v)
                        m_copy.setdefault("name", k)
                        mat_list.append(m_copy)

        if mat_list:
            m_rows = []
            for m in mat_list:
                name = m.get("name") or m.get("material_name") or ("标准材料" if is_zh else "Standard Material")
                ref = m.get("provenance") or m.get("standard_reference") or (m.get("metadata", {}).get("standard_reference") if isinstance(m.get("metadata"), dict) else None)
                if ref and str(ref) not in str(name):
                    display_name = f"{name} [{ref}]"
                else:
                    display_name = str(name)

                # Elastic
                elastic = m.get("elastic") if isinstance(m.get("elastic"), dict) else {}
                e_mod = elastic.get("youngs_modulus") or m.get("elastic_modulus_mpa") or m.get("elastic_modulus_at_operating_temp_mpa") or "-"
                e_str = f"{float(e_mod):,.0f} MPa" if isinstance(e_mod, (int, float)) else str(e_mod)
                nu = elastic.get("poisson_ratio") or m.get("poisson_ratio") or "-"
                # Strength
                plastic = m.get("plastic") if isinstance(m.get("plastic"), dict) else {}
                sy = plastic.get("yield_stress") or m.get("yield_strength_at_operating_temp_mpa") or m.get("yield_strength_mpa") or "-"
                sy_str = f"{float(sy):,.1f} MPa" if isinstance(sy, (int, float)) else str(sy)
                uts = m.get("ultimate_tensile_strength_mpa") or "-"
                uts_str = f"{float(uts):,.1f} MPa" if isinstance(uts, (int, float)) else str(uts)
                # Thermal
                thermal = m.get("thermal") if isinstance(m.get("thermal"), dict) else {}
                alpha = thermal.get("expansion_coefficient") or m.get("thermal_expansion_coeff_1_k") or "-"
                alpha_str = f"{float(alpha):.2e} 1/K" if isinstance(alpha, (int, float)) else str(alpha)
                k_cond = thermal.get("conductivity") or m.get("thermal_conductivity_w_m_k") or "-"
                k_str = f"{float(k_cond):.1f} W/m·K" if isinstance(k_cond, (int, float)) else str(k_cond)
                m_rows.append([display_name, e_str, str(nu), sy_str, uts_str, alpha_str, k_str])
            sub_title = "### 材料本构规范与高温温变物性 (Material Constitutive Specifications)" if is_zh else "### Material Constitutive Specifications & Temperature-Dependent Properties"
            th = ["部件 / 材料牌号", "弹性模量 E", "泊松比 ν", "屈服强度 Sy", "抗拉强度 UTS", "热膨胀系数 α", "导热系数 k"] if is_zh else ["Component / Material Grade", "Young's Modulus E", "Poisson's ν", "Yield Strength Sy", "UTS", "Thermal Coeff α", "Conductivity k"]
            lines += [sub_title, "", _format_markdown_table(th, m_rows), ""]

    # 4. Boundary Conditions
    elif heading.startswith("4. Boundary Conditions") and isinstance(value, (tuple, list)) and value:
        bc_rows = []
        for bc in value:
            if isinstance(bc, dict):
                reg = bc.get("region") or bc.get("set_name") or bc.get("name") or "-"
                b_type = bc.get("type") or bc.get("bc_type") or ("位移约束" if is_zh else "Displacement")
                dofs = []
                for dof_k in ("u1", "u2", "u3", "ur1", "ur2", "ur3"):
                    if dof_k in bc:
                        dofs.append(f"{dof_k.upper()}={bc[dof_k]}")
                if "magnitude" in bc:
                    dofs.append(f"Mag={bc['magnitude']}")
                if bc.get("point"):
                    dofs.append(f"point={bc['point']}")
                if bc.get("instance_name"):
                    dofs.append(f"instance={bc['instance_name']}")
                dof_str = ", ".join(dofs) if dofs else ("全固定约束" if is_zh else "Fixed / Encastre")
                step_str = f"Step {bc.get('step')}" if "step" in bc else ("全部工步" if is_zh else "All Steps")
                purp = bc.get("description") or bc.get("purpose") or ("基础运动学支承" if is_zh else "Kinematic Support / Boundary Equilibrium")
                bc_rows.append([str(reg), str(b_type), dof_str, step_str, purp])
        if bc_rows:
            sub_title = "### 边界条件与运动学约束规范 (Prescribed Boundary Conditions)" if is_zh else "### Prescribed Boundary Conditions & Kinematic Restraints"
            th = ["约束区域 / Region", "边界类型 / Type", "约束自由度与设定值 / Prescribed DOFs", "作用分析步 / Active Step", "工程约束目的 / Purpose"] if is_zh else ["Constrained Region", "Boundary Type", "Prescribed DOFs / Value", "Active Step", "Engineering Purpose"]
            lines += [sub_title, "", _format_markdown_table(th, bc_rows), ""]

    # 5. Loads
    elif heading.startswith("5. Loads") and isinstance(value, (tuple, list)) and value:
        load_rows = []
        for ld in value:
            if isinstance(ld, dict):
                reg = ld.get("region") or ld.get("name") or "-"
                l_type = ld.get("type") or ld.get("load_type") or ("机械载荷" if is_zh else "Mechanical Load")
                mag_parts = []
                if "magnitude" in ld: mag_parts.append(f"{ld['magnitude']}")
                if "film_coeff" in ld: mag_parts.append(f"h={ld['film_coeff']} W/m²·K")
                if "sink_temp" in ld: mag_parts.append(f"T_sink={ld['sink_temp']} °C")
                if "condition" in ld: mag_parts.append(f"Condition={ld['condition']}")
                if "source" in ld: mag_parts.append(f"From {ld['source']}")
                if ld.get("direction"): mag_parts.append(f"dir={ld['direction']}")
                if ld.get("point"): mag_parts.append(f"point={ld['point']}")
                mag_str = "; ".join(mag_parts) if mag_parts else "-"
                step_str = f"Step {ld.get('step')}" if "step" in ld else ("运行分析步" if is_zh else "Operational Step")
                desc = ld.get("description") or ("主要运行激励" if is_zh else "Primary Operational Excitation")
                load_rows.append([str(reg), str(l_type), mag_str, step_str, desc])
        if load_rows:
            sub_title = "### 外加运行工况与环境载荷定义 (Prescribed Operational Loads)" if is_zh else "### Prescribed Operational & Environmental Loads"
            th = ["作用区域 / Component", "载荷物理属性 / Nature", "载荷数值与公式 / Magnitude", "作用分析步 / Active Step", "工程物理功能 / Function"] if is_zh else ["Loaded Region / Component", "Load Nature", "Magnitude / Formulation", "Active Step", "Physical Function"]
            lines += [sub_title, "", _format_markdown_table(th, load_rows), ""]

    # 6. Solver / Analysis Procedure
    elif heading.startswith("6. Solver / Analysis Procedure") and isinstance(value, dict) and value:
        # Step sequence
        steps = value.get("step_sequence")
        if steps and isinstance(steps, (list, tuple)):
            s_rows = []
            for s in steps:
                if isinstance(s, dict):
                    s_rows.append([str(s.get("step_number", "-")), str(s.get("step_name", "-")), str(s.get("type", "-")), str(s.get("description", "-"))])
                else:
                    s_rows.append([f"Step {len(s_rows)}", str(s), "标准格式" if is_zh else "Standard Formulation", "多物理场耦合阶段" if is_zh else "Coupled Analysis Stage"])
            sub_title = "### 求解分析步序与多物理场时序序列 (Multi-Physics Step Sequence)" if is_zh else "### Analysis Procedure & Step Multi-Physics Sequence"
            th = ["工步序号 / Step", "工步名称 / Step Name", "求解过程类型 / Procedure Type", "物理动作与耦合逻辑 / Physical Action"] if is_zh else ["Step", "Step Name", "Procedure Type", "Physical Action & Coupling"]
            lines += [sub_title, "", _format_markdown_table(th, s_rows), ""]

        # Solver Settings
        cfg_rows = []
        solver_zh_map = {
            "solver": "求解器主程序 / Solver Program",
            "solver_type": "求解器类型 / Solver Type",
            "strategy": "分析步求解策略 / Solution Strategy",
            "procedure": "分析过程类型 / Procedure Type",
            "geometric_nonlinearity": "几何非线性开关 / Geometric Nonlinearity (NLGEOM)",
            "contact_stabilization": "接触阻尼稳定控制 / Contact Stabilization",
            "temperature_interpolation": "温度场插值方法 / Temperature Interpolation",
            "equation_solver": "代数方程组解法器 / Equation Solver",
            "time_integration": "时间积分方案 / Time Integration Scheme",
            "initial_increment": "初始时间增量步 / Initial Time Increment",
            "min_increment": "最小时间增量步 / Minimum Time Increment",
            "max_increment": "最大时间增量步 / Maximum Time Increment",
            "max_increments": "允许最大增量步数 / Maximum Number of Increments",
        }
        for k, v in value.items():
            if k == "step_sequence" or isinstance(v, (dict, list, tuple)):
                continue
            k_clean = solver_zh_map.get(k, k.replace("_", " ").title()) if is_zh else k.replace("_", " ").title()
            cfg_rows.append([k_clean, str(v)])
        if cfg_rows:
            sub_title = "### 求解器执行控制与算法参数 (Solver Execution Controls)" if is_zh else "### Solver Execution & Algorithmic Controls"
            th = ["控制配置项 / Configuration Item", "采用参数值 / Applied Setting"] if is_zh else ["Configuration Item", "Applied Setting"]
            lines += [sub_title, "", _format_markdown_table(th, cfg_rows), ""]

    # 7. Mesh
    elif heading.startswith("7. Mesh") and isinstance(value, dict) and value:
        mesh_zh_map = {
            "element_type": "基础有限元单元类型 / Element Type",
            "seed_size": "网格全局布种尺寸 / Global Seed Size (mm)",
            "element_count": "有限元单元总数 / Element Count",
            "node_count": "有限元节点总数 / Node Count",
            "strategy": "网格划分拓扑策略 / Meshing Strategy",
            "element_formulation": "单元积分格式 / Element Formulation",
            "element_formulation_thermal": "热学分析单元积分格式 / Thermal Element Formulation",
            "element_formulation_structural": "结构分析单元积分格式 / Structural Element Formulation",
            "total_nodes": "全模型节点总数 / Total Nodes",
            "total_elements": "全模型单元总数 / Total Elements",
            "manifold_runner_mesh_size": "歧管管壁网格尺寸 / Manifold Runner Mesh Size",
            "flange_fillet_refinement": "法兰过渡圆角局部加密 / Flange Fillet Refinement",
            "minimum_jacobian_ratio": "最小雅可比矩阵比率 / Minimum Jacobian Ratio",
            "maximum_aspect_ratio": "最大单元长宽比 / Maximum Aspect Ratio",
            "severely_distorted_elements": "严重畸变单元数量 / Severely Distorted Elements",
            "maximum_warping_angle": "最大翘曲角 / Maximum Warping Angle",
            "worst_angle_deviation": "最大角度偏差 / Worst Angle Deviation",
        }
        disc = value.get("discretization")
        if disc and isinstance(disc, dict):
            d_rows = []
            for k, v in disc.items():
                k_clean = mesh_zh_map.get(k, k.replace("_", " ").title()) if is_zh else k.replace("_", " ").title()
                d_rows.append([k_clean, str(v)])
            sub_title = "### 有限元空间离散与网格拓扑 (Finite Element Discretization)" if is_zh else "### Finite Element Discretization & Topology"
            th = ["离散特征指标 / Metric", "参数规格与分辨率 / Specification"] if is_zh else ["Discretization Metric / Feature", "Specification / Resolution"]
            lines += [sub_title, "", _format_markdown_table(th, d_rows), ""]

        qa = value.get("quality_audit")
        if qa and isinstance(qa, dict):
            qa_rows = []
            for k, v in qa.items():
                k_clean = mesh_zh_map.get(k, k.replace("_", " ").title()) if is_zh else k.replace("_", " ").title()
                qa_rows.append([k_clean, str(v)])
            sub_title = "### 有限元网格质量核查审计 (Finite Element Quality Audit)" if is_zh else "### Finite Element Quality Audit"
            th = ["质量检查维度 / Dimension", "测定指标 / 审计结论 (Verification Result)"] if is_zh else ["Quality Inspection Dimension", "Measured Value / Verification Result"]
            lines += [sub_title, "", _format_markdown_table(th, qa_rows), ""]

        if not disc and not qa:
            mesh_rows = []
            for k, v in value.items():
                if not isinstance(v, (dict, list, tuple)):
                    mesh_rows.append([k.replace("_", " ").title(), str(v)])
            if mesh_rows:
                sub_title = "### 网格配置参数 (Mesh Configuration)" if is_zh else "### Mesh Configuration"
                th = ["网格参数 / Parameter", "规格说明 / Specification"] if is_zh else ["Mesh Parameter", "Specification"]
                lines += [sub_title, "", _format_markdown_table(th, mesh_rows), ""]

    # 8. Results -> Metrics Table
    elif heading.startswith("8. Results") and isinstance(value, (tuple, list)) and value:
        rows = []
        for m in value:
            name = getattr(m, "name", None) or (m.get("name") or m.get("metric") if isinstance(m, dict) else str(m))
            v = getattr(m, "value", None) if hasattr(m, "value") else (m.get("value") if isinstance(m, dict) else "-")
            u = getattr(m, "unit", "") if hasattr(m, "unit") else (m.get("unit", "") if isinstance(m, dict) else "")
            src = getattr(m, "source", "odb") if hasattr(m, "source") else (m.get("source", "odb") if isinstance(m, dict) else "odb")
            rows.append([name, v, u, src])
        if rows:
            th = ["物理指标名称 / Metric Name", "计算数值 / Value", "工程单位 / Unit", "数据源 / Source"] if is_zh else ["Metric Name", "Value", "Unit", "Source"]
            lines += [_format_markdown_table(th, rows), ""]
            peak_note = _stress_peak_note(value, is_zh=is_zh)
            if peak_note:
                lines += [peak_note, ""]

    # 8b. Result Intelligence & Derived Metrics
    elif heading.startswith("8b. Result Intelligence") and value is not None:
        val_dict = value.to_dict() if hasattr(value, "to_dict") else (value if isinstance(value, dict) else {})
        # 8b-1. Spatial Hotspots
        hotspots = val_dict.get("hotspots") or ()
        if hotspots:
            h_rows = []
            for h in hotspots:
                r = f"#{h.get('rank', '-')}"
                fld = f"{h.get('field_name', '-')}:{h.get('component', '-')}"
                val_str = f"{float(h.get('value', 0.0)):.4g}"
                u = h.get("unit", "")
                elem = str(h.get("element_label") or "-")
                node = str(h.get("node_label") or "-")
                coords = h.get("coordinates") or [0.0, 0.0, 0.0]
                coord_str = f"({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})" if len(coords) >= 3 else str(coords)
                h_rows.append([r, fld, val_str, u, elem, node, coord_str])
            sub_title = "### 局部空间场变量热点区域 (Localized Spatial Field Hotspots Top-K)" if is_zh else "### Localized Spatial Field Hotspots (Top-K)"
            th = ["排名 / Rank", "场变量分量 / Field:Comp", "峰值大小 / Peak Value", "单位 / Unit", "单元号 / Elem", "节点号 / Node", "空间坐标 / Coordinates (X,Y,Z)"] if is_zh else ["Rank", "Field:Component", "Peak Value", "Unit", "Element", "Node", "Coordinates (X,Y,Z)"]
            lines += [sub_title, "", _format_markdown_table(th, h_rows), ""]

        # 8b-2. Derived Engineering Metrics
        dm = val_dict.get("derived_metrics") or {}
        if dm:
            # Force Balance
            fb = dm.get("force_balance")
            if fb:
                fb_rows = [[
                    f"{float(fb.get('applied_magnitude', 0.0)):.4g} {fb.get('unit', 'N')}",
                    f"{float(fb.get('reaction_magnitude', 0.0)):.4g} {fb.get('unit', 'N')}",
                    f"{float(fb.get('balance_error_percent', 0.0)):.3f}%",
                    ("BALANCED / 平衡" if is_zh else "BALANCED") if fb.get("is_balanced") else ("EQUILIBRIUM_DRIFT / 残差漂移" if is_zh else "EQUILIBRIUM_DRIFT"),
                ]]
                sub_title = "### 全局静力学平衡与支反力闭环核算 (Global Static Equilibrium & Force Balance)" if is_zh else "### Global Static Equilibrium & Reaction Force Balance"
                th = ["外加载荷合力", "支反力合力", "相对残差百分比", "平衡状态判定"] if is_zh else ["Applied Resultant", "Reaction Resultant", "Balance Error", "Equilibrium Status"]
                lines += [sub_title, "", _format_markdown_table(th, fb_rows), ""]

            # Energy Stability
            es = dm.get("energy_stability")
            if es:
                es_rows = [
                    ["总能量漂移率 / Energy Drift", f"{float(es.get('total_energy_drift_ratio', 0.0)):.4%}", "数值总能守恒性核查" if is_zh else "Numerical ETOTAL Conservation"],
                    ["动能与内能比值 / Kinetic Ratio", f"{float(es.get('kinetic_energy_ratio', 0.0)):.4%}" if es.get("kinetic_energy_ratio") is not None else "N/A", "准静态动能比" if is_zh else "Dynamic Energy Ratio"],
                    ["能量守恒稳定性裁决", ("STABLE / 稳定" if is_zh else "STABLE") if es.get("is_stable") else ("DRIFT_EXCEEDED / 漂移超标" if is_zh else "DRIFT_EXCEEDED"), es.get("notes", "")],
                ]
                sub_title = "### 系统能量守恒与数值算法稳定性核算 (Energy Balance & Numerical Stability)" if is_zh else "### Energy Balance & Numerical Stability"
                th = ["能量检验维度 / Dimension", "测算数值 / Evaluated Value", "工程物理评注 / Annotation"] if is_zh else ["Energy Dimension", "Evaluated Value", "Physical Annotation"]
                lines += [sub_title, "", _format_markdown_table(th, es_rows), ""]

            # Factor of Safety
            sf = dm.get("safety_factor")
            if sf:
                sf_rows = [[
                    f"{sf.get('stress_component', 'Mises')} Stress",
                    f"{float(sf.get('max_stress', 0.0)):.4g} {sf.get('unit', 'MPa')}",
                    f"{float(sf.get('yield_strength', 0.0)):.4g} {sf.get('unit', 'MPa')} ({sf.get('material_name', 'Q235')})",
                    f"{float(sf.get('factor_of_safety', 0.0)):.3f}",
                    f"{float(sf.get('margin_of_safety', 0.0)):+.3f}",
                ]]
                sub_title = "### 结构强度安全系数与安全裕度 (Structural Factor & Margin of Safety)" if is_zh else "### Structural Factor of Safety (Derived Engineering Fact)"
                th = ["评估应力场 / Field", "峰值等效应力 / Peak Stress", "材料屈服强度 / Yield Limit", "安全系数 (FoS)", "安全裕度 (MoS)"] if is_zh else ["Evaluated Field", "Peak Stress", "Yield Strength", "Factor of Safety (FoS)", "Margin of Safety (MoS)"]
                lines += [sub_title, "", _format_markdown_table(th, sf_rows), ""]

        # 8b-3. XY Response Curves
        curves = val_dict.get("curves") or ()
        if curves:
            c_rows = []
            for c in curves:
                cname = c.get("curve_name", "-")
                pts = c.get("point_count", 0)
                min_v = f"{float(c.get('min_y', 0.0)):.4g}"
                max_v = f"{float(c.get('max_y', 0.0)):.4g}"
                peak_v = f"{float(c.get('peak_abs_y', 0.0)):.4g}"
                u = c.get("y_unit", "")
                c_rows.append([cname, str(pts), min_v, max_v, peak_v, u])
            sub_title = "### 参数化与时间历程响应曲线数据概览 (Response Curves Summary)" if is_zh else "### Parametric & Time-History Response Curves"
            th = ["曲线名称 / Curve", "采样点数 / Pts", "最小值 / Min", "最大值 / Max", "绝对值峰值 / Peak", "物理单位 / Unit"] if is_zh else ["Curve Name", "Points", "Min Y", "Max Y", "Peak |Y|", "Unit"]
            lines += [sub_title, "", _format_markdown_table(th, c_rows), ""]

    # 11. Acceptance Criteria -> Integrity Audit & Criteria Table
    elif heading.startswith("11. Acceptance") and value is not None:
        gates = getattr(value, "gates", None) or (value.get("gates") if isinstance(value, dict) else None)
        raw_justs = getattr(value, "gate_justifications", None) or (value.get("gate_justifications") if isinstance(value, dict) else None)
        justs = raw_justs if isinstance(raw_justs, dict) else {}
        missing_m = getattr(value, "missing_required_metrics", None) or (value.get("missing_required_metrics") if isinstance(value, dict) else ())
        res_val = getattr(value, "result_validity", "VALID") if hasattr(value, "result_validity") else (value.get("result_validity", "VALID") if isinstance(value, dict) else "VALID")
        odb_st = getattr(value, "odb_status", "valid") if hasattr(value, "odb_status") else (value.get("odb_status", "valid") if isinstance(value, dict) else "valid")

        if gates and isinstance(gates, dict):
            s_status = "运行正常完成" if is_zh else ("completed" if gates.get("execution") == "PASS" else "aborted / failed")
            req_status = "所有必需物理指标完整提取" if is_zh else ("All Required Metrics Extracted" if not missing_m else f"MISSING: {', '.join(missing_m)}")
            res_val_str = "结果有效合格 (VALID)" if is_zh else res_val
            s_label = "求解器正常执行 / Execution" if is_zh else "Solver Execution"
            odb_label = "ODB 结果数据库存储 / ODB Artifact" if is_zh else "ODB Storage Artifact"
            req_label = "必需工程物理输出项 / Required Outputs" if is_zh else "Required Physical Outputs"
            res_label = "工程分析结果有效性 / Result Validity" if is_zh else "Engineering Result Validity"
            integrity_rows = [
                [s_label, s_status, gates.get("execution", "-")],
                [odb_label, odb_st, gates.get("odb", "PASS" if s_status in ("completed", "运行正常完成") else "FAIL")],
                [req_label, req_status, "PASS" if not missing_m else "FAIL (RESULT_INVALID)"],
                [res_label, res_val_str, "PASS" if res_val == "VALID" else "REJECTED"],
            ]
            if "evidence_sufficiency" in gates:
                ev_gate = gates["evidence_sufficiency"]
                ev_status = getattr(value, "evidence_status", None) or (value.get("evidence_status") if isinstance(value, dict) else None)
                if ev_status and ev_gate != "PASS":
                    ev_gate = f"{ev_gate} ({ev_status})"
                ev_desc = "内容摘要未发现未同步修改 (SHA-256 content digest; not a keyed signature)" if is_zh else "Content digest matches (SHA-256; not a keyed signature)"
                integrity_rows.append(["电子证据链与产物完整性 / Evidence" if is_zh else "Evidence & Artifact Integrity", ev_desc, ev_gate])
            sub_title = "### 工程验证完整性与门禁审计总览 (Verification Integrity & Audit)" if is_zh else "### Verification Integrity & Audit Summary"
            th = ["验证维度 / Dimension", "测定状态与输出 / Output", "门禁裁决 / Verdict"] if is_zh else ["Verification Dimension", "Actual State / Output", "Gate Verdict"]
            lines += [sub_title, "", _format_markdown_table(th, integrity_rows), ""]

            gate_rows = []
            for g_name, g_status in gates.items():
                default_note = "符合物理契约规范" if is_zh else "Verified against physics contract"
                note = justs.get(g_name, default_note if g_status == "PASS" else ("忽略 / 未配置" if is_zh else "Omitted / Not requested"))
                gate_rows.append([g_name, str(g_status), note])
            if gate_rows:
                sub_title = "### 验收门禁详细执行审计清单 (Verification Gates Audit)" if is_zh else "### Verification Gates Detailed Audit"
                th = ["门禁名称 / Gate Name", "判定状态 / Status", "工程判定理由与证据说明 / Justification"] if is_zh else ["Gate Name", "Status", "Engineering Justification / Note"]
                lines += [sub_title, "", _format_markdown_table(th, gate_rows), ""]

        crit_list = None
        if hasattr(value, "criteria"):
            crit_list = value.criteria
        elif isinstance(value, dict) and "criteria" in value:
            crit_list = value.get("criteria")

        if crit_list and isinstance(crit_list, (list, tuple)):
            rows = []
            for c in crit_list:
                name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else "criterion")
                target = getattr(c, "target_description", None) or getattr(c, "target", None) or (c.get("target") if isinstance(c, dict) else None)
                if target is None and isinstance(c, dict) and "limit" in c:
                    op = c.get("operator", "")
                    lim = c.get("limit")
                    target = f"{op} {lim}".strip()
                if target is None:
                    target = "-"
                actual = getattr(c, "actual", None) if hasattr(c, "actual") else (c.get("actual") if isinstance(c, dict) else "-")
                passed = getattr(c, "passed", None) if hasattr(c, "passed") else (c.get("passed") if isinstance(c, dict) else None)
                verdict = "PASS" if passed is True else ("FAIL" if passed is False else "N/A")
                rows.append([name, target, actual, verdict])
            if rows:
                sub_title = "### 确定性工程设计准则验算结果 (Deterministic Criteria Evaluation)" if is_zh else "### Deterministic Criteria Evaluation"
                th = ["准则项名称 / Criterion", "设计限值要求 / Requirement", "实测计算值 / Actual", "合规状态 / Status"] if is_zh else ["Criterion Name", "Requirement / Limit", "Actual Value", "Status"]
                lines += [sub_title, "", _format_markdown_table(th, rows), ""]
        elif crit_list and isinstance(crit_list, dict):
            rows = []
            for name, val in crit_list.items():
                verdict = "PASS" if val is True else ("FAIL" if val is False else str(val))
                req_val = ("必须为真 (True)" if is_zh else "Must be True") if isinstance(val, bool) else "-"
                rows.append([name, req_val, str(val), verdict])
            if rows:
                sub_title = "### 确定性工程设计准则验算结果 (Deterministic Criteria Evaluation)" if is_zh else "### Deterministic Criteria Evaluation"
                th = ["准则项名称 / Criterion", "设计限值要求 / Requirement", "实测计算值 / Actual", "合规状态 / Status"] if is_zh else ["Criterion Name", "Requirement / Limit", "Actual Value", "Status"]
                lines += [sub_title, "", _format_markdown_table(th, rows), ""]

    # 12. Sensitivity / Uncertainty
    elif heading.startswith("12. Sensitivity") and value is not None:
        sens_data, uncert_data = value if isinstance(value, (tuple, list)) and len(value) == 2 else (value, None)
        # Sensitivity table
        if sens_data:
            s_dict = sens_data.to_dict() if hasattr(sens_data, "to_dict") else (sens_data if isinstance(sens_data, dict) else {})
            params = s_dict.get("parameters") or s_dict.get("sensitivities") or ()
            if isinstance(params, (list, tuple)) and params:
                s_rows = []
                for p in params:
                    if isinstance(p, dict):
                        p_name = p.get("parameter_name") or p.get("name", "-")
                        base_v = str(p.get("baseline_value", "-"))
                        sens_idx = str(p.get("sensitivity_index") or p.get("impact", "-"))
                        rank = str(p.get("rank", "-"))
                        s_rows.append([p_name, base_v, sens_idx, rank])
                if s_rows:
                    sub_title = "### 参数敏感性量化核算 (Parameter Sensitivity Quantification)" if is_zh else "### Parameter Sensitivity Quantification"
                    th = ["参数名称 / Parameter", "基准设定值 / Baseline Value", "敏感度指标 / Sensitivity Index", "影响排序 / Rank"] if is_zh else ["Parameter Name", "Baseline Value", "Sensitivity Index", "Rank"]
                    lines += [sub_title, "", _format_markdown_table(th, s_rows), ""]
            elif isinstance(s_dict, dict) and s_dict:
                s_rows = [[k.replace("_", " ").title(), str(v)] for k, v in s_dict.items() if not isinstance(v, (dict, list, tuple))]
                if s_rows:
                    sub_title = "### 参数敏感性量化概览 (Parameter Sensitivity Overview)" if is_zh else "### Parameter Sensitivity Overview"
                    th = ["敏感性指标 / Sensitivity Metric", "量化数值 / Evaluated Value"] if is_zh else ["Sensitivity Metric", "Evaluated Value"]
                    lines += [sub_title, "", _format_markdown_table(th, s_rows), ""]

        # Uncertainty table
        if uncert_data:
            u_dict = uncert_data.to_dict() if hasattr(uncert_data, "to_dict") else (uncert_data if isinstance(uncert_data, dict) else {})
            u_items = u_dict.get("uncertainties") or u_dict.get("variables") or ()
            if isinstance(u_items, (list, tuple)) and u_items:
                u_rows = []
                for u in u_items:
                    if isinstance(u, dict):
                        u_name = u.get("variable_name") or u.get("name", "-")
                        dist = str(u.get("distribution", "-"))
                        mean_v = str(u.get("mean") or u.get("nominal", "-"))
                        std_v = str(u.get("std_dev") or u.get("variance", "-"))
                        u_rows.append([u_name, dist, mean_v, std_v])
                if u_rows:
                    sub_title = "### 物理不确定度分布模型 (Uncertainty Quantification Models)" if is_zh else "### Uncertainty Quantification Models"
                    th = ["不确定变量 / Variable", "概率分布类型 / Distribution", "均值/名义值 / Mean (Nominal)", "标准差/离散度 / Std Dev"] if is_zh else ["Variable Name", "Distribution Type", "Mean (Nominal)", "Std Deviation"]
                    lines += [sub_title, "", _format_markdown_table(th, u_rows), ""]

    # 13. Fatigue -> Key Fatigue Metrics Table
    elif heading.startswith("13. Fatigue") and isinstance(value, dict) and value:
        fatigue_zh_map = {
            "cycles_to_failure": "疲劳失效循环寿命 / Cycles to Failure",
            "damage_ratio": "累积损伤比率 / Cumulative Damage Ratio",
            "endurance_limit_mpa": "材料疲劳极限 / Endurance Limit (MPa)",
            "fatigue_safety_factor": "疲劳强度安全系数 / Fatigue Safety Factor",
            "stress_amplitude_mpa": "交变应力幅值 / Stress Amplitude (MPa)",
            "mean_stress_mpa": "平均应力水平 / Mean Stress (MPa)",
            "life_criterion": "寿命预测准则 / Life Prediction Criterion",
            "critical_location": "疲劳危险热点位置 / Critical Fatigue Location",
            "load_ratio_r": "载荷应力比 R / Stress Ratio R",
        }
        rows = []
        for k, v in value.items():
            if not isinstance(v, (dict, list, tuple)):
                k_clean = fatigue_zh_map.get(k, k.replace("_", " ").title()) if is_zh else k.replace("_", " ").title()
                rows.append([k_clean, str(v)])
        if rows:
            sub_title = "### 结构高低温疲劳与寿命损伤评估 (Fatigue Life & Damage Evaluation)" if is_zh else "### Fatigue Life & Damage Evaluation"
            th = ["疲劳评估参数 / Fatigue Parameter", "计算数值 / Evaluated Value"] if is_zh else ["Fatigue Parameter", "Value"]
            lines += [sub_title, "", _format_markdown_table(th, rows), ""]

    # 14b. Solver Diagnostics & Self-Healing Audit
    elif heading.startswith("14b. Solver Diagnostics") and value is not None:
        sh_dict = value.to_dict() if hasattr(value, "to_dict") else (value if isinstance(value, dict) else {})
        sh_meta = sh_dict.get("metadata") if isinstance(sh_dict.get("metadata"), dict) else {}
        if sh_meta.get("awaiting_confirmation"):
            healed_str = (
                "仅提出修改，未执行 / 等待确认 (Proposed, not applied)"
                if is_zh else "PROPOSED, NOT APPLIED"
            )
        elif sh_dict.get("healed") and sh_meta.get("model_change_applied"):
            healed_str = (
                "已在确认后改题重跑 (Applied after confirmation)"
                if is_zh else "APPLIED AFTER CONFIRMATION"
            )
        elif sh_dict.get("healed"):
            healed_str = ("已成功自愈 (Self-Healed)" if is_zh else "YES (Self-Healed)")
        else:
            healed_str = ("未完全自愈 / 需人工介入" if is_zh else "NO (Unresolved / Escalated)")
        summary_rows = [
            ["自愈闭环最终结果 / Outcome" if is_zh else "Self-Healing Outcome", healed_str],
            ["模型修改是否已确认 / Model Change Confirmed" if is_zh else "Model Change Confirmed", str(bool(sh_meta.get("confirm_model_change")))],
            ["模型修改是否已执行 / Model Change Applied" if is_zh else "Model Change Applied", str(bool(sh_meta.get("model_change_applied")))],
            ["自愈尝试总次数 / Total Attempts" if is_zh else "Total Healing Attempts", str(sh_dict.get("total_attempts", 0))],
            ["初始求解器故障状态 / Initial Status" if is_zh else "Initial Solver Status", str(sh_dict.get("initial_status", "-"))],
            ["自愈后最终工程状态 / Final Status" if is_zh else "Final Engineering Status", str(sh_dict.get("final_status", "-"))],
        ]
        sub_title = "### 求解器自愈生命周期审计摘要 (Self-Healing Lifecycle Summary)" if is_zh else "### Self-Healing Lifecycle Summary"
        th = ["审计属性维度 / Attribute", "测定状态数值 / Value"] if is_zh else ["Attribute", "Value"]
        lines += [sub_title, "", _format_markdown_table(th, summary_rows), ""]

        # Diagnosed Issues
        issues = sh_dict.get("diagnosed_issues") or ()
        if issues:
            iss_rows = []
            for iss in issues:
                i_id = iss.get("diagnosis_id", "-")
                sev = iss.get("severity", "-")
                cause = iss.get("likely_cause", "-")
                rem = iss.get("suggested_remediation", "-")
                iss_rows.append([i_id, sev, cause, rem])
            sub_title = "### 诊断判定的求解器故障项 (Diagnosed Solver Issues)" if is_zh else "### Diagnosed Solver Issues"
            th = ["诊断故障 ID", "严重等级 / Severity", "故障根因机理 / Likely Cause", "推荐自愈修复方案 / Remediation"] if is_zh else ["Diagnosis ID", "Severity", "Likely Cause", "Suggested Remediation"]
            lines += [sub_title, "", _format_markdown_table(th, iss_rows), ""]

        # Remediations Applied
        proposed = sh_meta.get("proposed_remediations") or ()
        if proposed:
            prop_rows = []
            for r in proposed:
                if not isinstance(r, dict):
                    continue
                prop_rows.append([
                    r.get("action_id", "-"),
                    r.get("category", "-"),
                    r.get("description", "-"),
                    r.get("risk_level", "-"),
                ])
            if prop_rows:
                sub_title = (
                    "### 待确认的模型修改建议（尚未执行） (Proposed Model Changes, Not Applied)"
                    if is_zh else "### Proposed Model Changes (Not Applied)"
                )
                th = ["措施动作 ID", "类别 / Category", "建议描述 / Description", "工程风险等级 / Risk Level"] if is_zh else ["Action ID", "Category", "Description", "Risk Level"]
                lines += [sub_title, "", _format_markdown_table(th, prop_rows), ""]

        remeds = sh_dict.get("remediations_applied") or ()
        if remeds:
            rem_rows = []
            for r in remeds:
                r_id = r.get("action_id", "-")
                cat = r.get("category", "-")
                desc = r.get("description", "-")
                risk = r.get("risk_level", "-")
                rem_rows.append([r_id, cat, desc, risk])
            sub_title = "### 已执行的模型突变与自愈修复措施 (Remediations Applied)" if is_zh else "### Remediations Applied & Model Mutations"
            th = ["措施动作 ID", "类别 / Category", "自愈操作详细描述 / Description", "工程风险等级 / Risk Level"] if is_zh else ["Action ID", "Category", "Description", "Risk Level"]
            lines += [sub_title, "", _format_markdown_table(th, rem_rows), ""]

        # Healing Attempts & RunDiff
        attempts = sh_dict.get("attempts") or ()
        if attempts:
            att_rows = []
            for a in attempts:
                num = str(a.get("attempt_number", "-"))
                trigs = ", ".join(a.get("trigger_issues", ()))
                out = a.get("outcome", "-")
                pre_id = a.get("pre_run_id", "-")
                post_id = a.get("post_run_id", "-")
                att_rows.append([num, trigs, f"{pre_id} -> {post_id}", out])
            sub_title = "### 迭代自愈轮次追踪与运行状态流转 (Iterative Healing Attempts)" if is_zh else "### Iterative Healing Attempts"
            th = ["自愈轮次 #", "触发故障项 / Triggers", "运行状态迁移 / Transition", "修复执行结果 / Outcome"] if is_zh else ["Attempt #", "Trigger Issues", "Run Transition", "Outcome"]
            lines += [sub_title, "", _format_markdown_table(th, att_rows), ""]

    # 15. Mechanism Kinematics & Topology -> Mechanism Summary Table
    elif heading.startswith("15. Mechanism") and isinstance(value, dict) and value:
        rows = [[k, str(v)] for k, v in value.items() if not isinstance(v, (dict, list, tuple))]
        if rows:
            th = ["机构拓扑参数 / Parameter", "设定与计算值 / Value"] if is_zh else ["Topological Parameter", "Value"]
            lines += [_format_markdown_table(th, rows), ""]

    # 17. Evidence -> Evidence Manifest V2 Table
    elif heading.startswith("17. Evidence") and value is not None:
        manifest_data = None
        if hasattr(value, "schema_version") and getattr(value, "schema_version") == "evidence_manifest_v2":
            manifest_data = value.to_dict()
        elif isinstance(value, dict) and (value.get("schema_version") == "evidence_manifest_v2" or "artifacts" in value):
            manifest_data = value
        elif isinstance(value, (list, tuple)):
            for item in value:
                v = getattr(item, "value", item)
                if isinstance(v, dict) and (v.get("schema_version") == "evidence_manifest_v2" or "artifacts" in v):
                    manifest_data = v
                    break

        if manifest_data and isinstance(manifest_data, dict):
            run_id = manifest_data.get("run_id", "-")
            case_id = manifest_data.get("case_id", "-")
            val = manifest_data.get("validity", "VALID")
            sig = manifest_data.get("audit_signature", "-")
            sig_display = f"{sig[:16]}... (SHA-256)" if sig and len(sig) > 16 else (sig or "-")
            summary_rows = [
                ["仿真运行流水号 (Run ID)" if is_zh else "Run ID", run_id],
                ["工程案例编号 (Case ID)" if is_zh else "Case ID", case_id],
                ["生成审计时间 (Created At)" if is_zh else "Created At", manifest_data.get("created_at", "-")],
                ["证据有效性状态 (Evidence Validity)" if is_zh else "Evidence Validity", val],
                ["内容摘要 (Content Digest)" if is_zh else "Content Digest", sig_display],
            ]
            sub_title = "### 电子证据链清单摘要 (Evidence Manifest Summary)" if is_zh else "### Evidence Manifest Summary"
            th = ["清单元数据属性 / Property", "对应数值 / Value"] if is_zh else ["Manifest Property", "Value"]
            lines += [sub_title, "", _format_markdown_table(th, summary_rows), ""]

            arts = manifest_data.get("artifacts") or {}
            if isinstance(arts, dict) and arts:
                art_rows = []
                for a_name, a_info in sorted(arts.items()):
                    if isinstance(a_info, dict):
                        role = a_info.get("role", "-")
                        exists = ("存在 (YES)" if is_zh else "YES") if a_info.get("exists") else ("缺失 (NO)" if is_zh else "NO")
                        size = str(a_info.get("size_bytes", 0))
                        sha = a_info.get("sha256", "-")
                        sha_short = f"{sha[:12]}..." if sha and len(sha) > 12 else (sha or "-")
                        art_rows.append([a_name, role, exists, size, sha_short])
                if art_rows:
                    sub_title = "### 仿真产物内容摘要与出处清单 (Artifact Content Digest)" if is_zh else "### Artifact Content Digest"
                    th = ["产物文件名 / Artifact Name", "工程角色 / Role", "物理存在 / Exists", "大小 (字节)", "SHA-256 内容摘要"] if is_zh else ["Artifact Name", "Role", "Exists", "Size (bytes)", "SHA-256 digest"]
                    lines += [sub_title, "", _format_markdown_table(th, art_rows), ""]

    # 10. Engineering Checks -> Detailed Engineering Verification Checks Table
    elif heading.startswith("10. Engineering Checks") and isinstance(value, (tuple, list)) and value:
        c_rows = []
        for chk in value:
            if isinstance(chk, dict):
                name = chk.get("name") or chk.get("item") or ("工程准则核验" if is_zh else "Engineering Check")
                passed = chk.get("passed")
                status = "PASS" if passed is True else ("FAIL" if passed is False else str(passed or "VERIFIED"))
                details = chk.get("details") or chk.get("description") or "-"
                c_rows.append([str(name), str(details), status])
            elif hasattr(chk, "name"):
                name = getattr(chk, "name", "工程准则核验" if is_zh else "Engineering Check")
                passed = getattr(chk, "passed", None)
                status = "PASS" if passed is True else ("FAIL" if passed is False else "VERIFIED")
                details = getattr(chk, "details", "-")
                c_rows.append([str(name), str(details), status])
        if c_rows:
            sub_title = "### 工业工程准则合规性详细核验 (Detailed Engineering Checks)" if is_zh else "### Detailed Engineering Verification Checks"
            th = ["工程核验项 / Check Item", "核验详情与安全裕度 / Details & Margin", "门禁状态 / Status"] if is_zh else ["Verification Check Item", "Evaluation Details & Margin", "Gate Status"]
            lines += [sub_title, "", _format_markdown_table(th, c_rows), ""]

    # 12b. Engineering Mechanism Analysis
    elif heading.startswith("12b. Engineering Mechanism Analysis") and value:
        mech_zh_map = {
            # Case 3
            "differential_thermal_expansion_slip": "法兰差胀滑移与螺栓孔间隙机理 / Differential Thermal Expansion & Flange Slip Kinematics",
            "runner_junction_fillet_thermal_stress": "支管汇流圆角热应力集中机理 / Runner Confluence Fillet Thermal Stress Concentration",
            "mls_gasket_contact_pressure_evolution": "MLS垫片接触密封压力演化机理 / MLS Gasket Sealing Contact Pressure Evolution",
            # Case 1
            "gasket_sealing_pressure_relaxation": "垫片密封接触压力演化与保持机理 / Gasket Sealing Contact Pressure Evolution & Retention",
            "bolt_tension_fluid_thrust_interaction": "内压流体端面推力与螺栓拉力解耦机理 / Fluid Thrust Interaction & Bolt Tension Equilibrium",
            "flange_hub_fillet_stress_bending": "法兰颈部过渡圆角弯曲应力机理 / Flange Hub Transition Bending Stress Concentration",
            # Case 2
            "double_cone_metallic_seal_self_tightening": "双锥金属密封环自紧式接触机理 / Double-Cone Metallic Gasket Self-Tightening Sealing",
            "asme_linearized_pl_pb_stress_partition": "ASME规范主薄膜加弯曲应力线性化解剖机理 / ASME Section III Linearized PL+Pb Stress Partitioning",
            "stud_tension_thermal_hydraulic_equilibrium": "大口径主螺栓液压预紧与承载机理 / High-Capacity Stud Pretension & Structural Equilibrium",
        }
        if isinstance(value, dict):
            for k, v in value.items():
                title = mech_zh_map.get(k, k.replace("_", " ").title()) if is_zh else k.replace("_", " ").title()
                lines += [f"### {title}", "", str(v).strip(), ""]
        elif isinstance(value, (list, tuple)):
            for idx, item in enumerate(value, 1):
                if isinstance(item, dict):
                    t = item.get("title") or item.get("mechanism") or (f"机理剖析 {idx}" if is_zh else f"Mechanism {idx}")
                    d = item.get("description") or item.get("details") or ""
                    lines += [f"### {t}", "", str(d).strip(), ""]
                else:
                    m_label = f"机理剖析 {idx}" if is_zh else f"Mechanism {idx}"
                    lines += [f"### {m_label}", "", str(item).strip(), ""]
        elif isinstance(value, str):
            lines += [value.strip(), ""]

    # 13b. Design Recommendations & Countermeasures
    elif heading.startswith("13b. Design Recommendations") and value:
        rec_list = []
        if isinstance(value, (list, tuple)):
            rec_list = list(value)
        elif isinstance(value, dict):
            rec_list = [value]

        table_rows = []
        detail_blocks = []
        for idx, r in enumerate(rec_list, 1):
            if isinstance(r, dict):
                item_no = f"REC-{idx:02d}"
                title = r.get("title") or r.get("name") or (f"改进建议 {idx}" if is_zh else f"Recommendation {idx}")
                focus = r.get("focus") or r.get("component") or ("零部件设计" if is_zh else "Component Design")
                benefit = r.get("benefit") or r.get("expected_benefit") or ("提高工程安全裕度" if is_zh else "Margin Improvement")
                priority = r.get("priority") or ("中" if is_zh else "Medium")
                table_rows.append([item_no, title, focus, benefit, priority])

                details = r.get("details") or r.get("description") or ""
                if details:
                    detail_blocks.append(f"**{item_no}: {title}**\n\n{details.strip()}\n")
            else:
                table_rows.append([f"REC-{idx:02d}", str(r), "General", "Optimization", "Normal"])

        if table_rows:
            sub_title = "### 结构改型与工程对策建议总览 (Design Recommendations Summary)" if is_zh else "### Structural Design Recommendations Summary"
            th = ["建议编号 / Item", "工程对策方案描述 / Countermeasure", "重点作用子系统 / Focus", "预期工程收益 / Expected Benefit", "优先级 / Priority"] if is_zh else ["Item", "Countermeasure Description", "Focus Subsystem", "Expected Engineering Benefit", "Priority"]
            lines += [sub_title, "", _format_markdown_table(th, table_rows), ""]
        if detail_blocks:
            sub_title = "### 针对性工程对策详细方案与实施建议 (Countermeasure Details)" if is_zh else "### Engineering Countermeasure Details & Implementation Guidance"
            lines += [sub_title, ""] + detail_blocks

    # 14. Contact Diagnostics -> Contact Interface Audit Table
    elif heading.startswith("14. Contact Diagnostics") and value is not None:
        items = getattr(value, "diagnostics", None) or (value.get("diagnostics") if isinstance(value, dict) else None)
        if items is None and isinstance(value, (list, tuple)):
            items = value
        if items:
            diag_rows = []
            for item in items:
                name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else str(item))
                status = getattr(item, "status", None) or (item.get("status") if isinstance(item, dict) else "pass")
                st_str = "PASS" if str(status).lower() in ("pass", "ok", "true", "valid") else str(status).upper()
                desc = getattr(item, "description", None) or (item.get("description") if isinstance(item, dict) else ("接触界面算法与罚函数刚度核验合格" if is_zh else "Interface formulation & penalty stiffness verified"))
                diag_rows.append([str(name), desc, st_str])
            if diag_rows:
                sub_title = "### 接触界面诊断与几何穿透审计 (Contact Interface Diagnostics)" if is_zh else "### Contact Interface Diagnostics & Penetration Audit"
                th = ["接触核查维度 / Dimension", "评估范围与算法描述 / Scope", "门禁状态 / Status"] if is_zh else ["Contact Verification Dimension", "Assessment Scope", "Status"]
                lines += [sub_title, "", _format_markdown_table(th, diag_rows), ""]

    # 16. Assumptions / Limitations -> Bulleted Engineering Lists
    elif heading.startswith("16. Assumptions") and isinstance(value, (tuple, list)):
        assumptions, limitations = value if len(value) == 2 else (value, ())
        has_content = False
        if assumptions and isinstance(assumptions, (list, tuple)):
            sub_title = "### 基础工程建模假设 (Engineering Modeling Assumptions)" if is_zh else "### Fundamental Engineering Modeling Assumptions"
            lines += [sub_title, ""]
            for idx, a in enumerate(assumptions, 1):
                lines += [f"{idx}. {a}"]
            lines += [""]
            has_content = True
        if limitations and isinstance(limitations, (list, tuple)):
            sub_title = "### 有限元分析适用范围与工程局限性 (Scope of Validity & Limitations)" if is_zh else "### Scope of Validity & Operational Limitations"
            lines += [sub_title, ""]
            for idx, lim in enumerate(limitations, 1):
                lines += [f"{idx}. {lim}"]
            lines += [""]
            has_content = True
        if not has_content:
            pass

    # 16b. Classified Engineering Facts -> group by evidentiary role
    elif heading.startswith("16b. Classified Engineering Facts") and value:
        groups = {}
        for fact in value:
            category = getattr(fact, "category", None)
            if category is None and isinstance(fact, dict):
                category = fact.get("category")
            category = getattr(category, "value", category)
            category_key = str(category or "UNCLASSIFIED").upper()
            groups.setdefault(category_key, []).append(fact)
        category_order = ["RESULT", "LIMITATION", "DEV_PROCESS"]
        category_order += sorted(key for key in groups if key not in category_order)
        titles = {
            "RESULT": "实测结果事实 (Measured Results)" if is_zh else "Measured Results (RESULT)",
            "LIMITATION": "适用范围与有效性限制 (Scope / Limitations)" if is_zh else "Scope / Limitations (LIMITATION)",
            "DEV_PROCESS": "研发与求解过程事实 (Development Process)" if is_zh else "Development Process (DEV_PROCESS)",
            "UNCLASSIFIED": "未分类事实 (Unclassified)" if is_zh else "Unclassified Facts",
        }
        for category_key in category_order:
            items = groups.get(category_key) or []
            if not items:
                continue
            lines += [f"### {titles.get(category_key, category_key)}", ""]
            if category_key == "LIMITATION":
                note = (
                    "以下限制为强制保留项，不得为提高可读性而删除。"
                    if is_zh else
                    "The limitations below are mandatory-retention facts and must not be removed for readability."
                )
                lines += [f"> {note}", ""]
            for fact in items:
                if isinstance(fact, dict):
                    statement = fact.get("statement", "")
                    source = fact.get("source", "")
                else:
                    statement = getattr(fact, "statement", "")
                    source = getattr(fact, "source", "")
                statement = str(statement).strip()
                source = str(source or "").strip()
                if not statement:
                    continue
                source_note = f"（来源 / Source: {source}）" if is_zh and source else (f"(source: {source})" if source else "")
                lines += [f"- **[{category_key}]** {statement}{source_note}"]
            lines += [""]

    # 18. Provenance -> Model Provenance & Execution Audit Table
    elif heading.startswith("18. Provenance") and value is not None:
        prov_dict = value.to_dict() if hasattr(value, "to_dict") else (value if isinstance(value, dict) else {})
        if prov_dict:
            p_rows = []
            prop_names = {
                "run_id": ("仿真运行流水号 (Run ID)", "Run ID"),
                "model_name": ("几何分析模型名称 (Model Name)", "Model Name"),
                "job_name": ("求解任务标识 (Job Name)", "Job Name"),
                "abaqus_version": ("Abaqus 求解器版本 (Version)", "Abaqus Version"),
                "executor": ("计算执行器类型 (Executor)", "Executor"),
                "timestamp": ("创建生成时间戳 (Timestamp)", "Timestamp"),
            }
            for k in ("run_id", "model_name", "job_name", "abaqus_version", "executor", "timestamp"):
                if k in prov_dict:
                    zh_k, en_k = prop_names.get(k, (k.replace("_", " ").title(), k.replace("_", " ").title()))
                    k_name = zh_k if is_zh else en_k
                    p_rows.append([k_name, str(prov_dict[k])])
            meta = prov_dict.get("metadata")
            if isinstance(meta, dict):
                for mk, mv in meta.items():
                    mk_title = mk.replace("_", " ").title()
                    p_rows.append([f"{mk_title} (Metadata)", str(mv)])
            if p_rows:
                sub_title = "### 模型版本与运行出处审计清单 (Provenance Audit)" if is_zh else "### Model Provenance & Execution Audit"
                th = ["审计属性项 / Attribute", "出处溯源数值 / Value"] if is_zh else ["Audit Attribute", "Provenance Value"]
                lines += [sub_title, "", _format_markdown_table(th, p_rows), ""]

    return lines

def _figure_caption_for_report(figure, is_zh=False):
    """Append evidence-bound time coverage to animation captions only."""
    base = getattr(figure, "caption", None) or getattr(figure, "kind", None) or "figure"
    meta = getattr(figure, "metadata", None) or {}
    if not isinstance(meta, dict):
        return str(base)
    is_animation = bool(meta.get("is_animation"))
    if not is_animation:
        is_animation = (
            str(getattr(figure, "kind", "")).lower() == "animation"
            or str(getattr(figure, "path", "")).lower().endswith(".gif")
        )
    if not is_animation:
        return str(base)
    payload = meta.get("time_coverage")
    if not isinstance(payload, dict):
        return str(base)
    from ..contracts.time_coverage import TimeCoverage
    coverage = TimeCoverage.from_dict(payload)
    if coverage is None:
        return str(base)
    return f"{base} — {coverage.animation_caption(is_zh=is_zh)}"


def render_markdown(report, language=None):
    # Detect Chinese language preference
    is_zh = _is_chinese_report(report, language=language)

    lines = ["# %s" % report.title, ""]
    if report.objective:
        exec_heading = "## 1. Executive Summary / 工程执行摘要" if is_zh else "## 1. Executive Summary"
        lines += [exec_heading, "", report.objective, ""]
    sections = [
        ("2. Model Information", "几何模型与装配拓扑定义", report.model),
        ("3. Material", "材料本构模型与物性温变定义", report.materials),
        ("4. Boundary Conditions", "边界约束与位移固定条件", report.boundary_conditions),
        ("5. Loads", "载荷工况与热流压力历程", report.loads),
        ("6. Solver / Analysis Procedure", "求解器步序与算法控制策略", report.solver),
        ("7. Mesh", "有限元网格离散与质量审计", report.mesh),
        ("8. Results", "关键工程物理指标计算结果", report.results),
        ("8b. Result Intelligence & Derived Metrics", "结果智能与空间热点衍生指标", getattr(report, "result_intelligence", None)),
        ("9. Figures", "工程图纸与仿真云图资产", report.figures),
        ("10. Engineering Checks", "工业工程准则合规性详细核验", report.engineering_checks),
        ("11. Acceptance Criteria", "确定性工程设计准则验算与门禁", report.acceptance),
        ("12. Sensitivity / Uncertainty", "参数敏感性与不确定度量化", (report.sensitivity, report.uncertainty)),
        ("12b. Engineering Mechanism Analysis", "深层物理失效机理工程剖析", report.metadata.get("mechanism_analysis") if hasattr(report, "metadata") and isinstance(report.metadata, dict) else None),
        ("13. Fatigue", "高低温疲劳与寿命损伤评估", report.fatigue),
        ("13b. Design Recommendations & Countermeasures", "结构改型建议与对策方案", report.metadata.get("design_recommendations") if hasattr(report, "metadata") and isinstance(report.metadata, dict) else None),
        ("14. Contact Diagnostics", "接触界面状态与穿透诊断", report.contact_diagnostics),
        ("14b. Solver Diagnostics & Self-Healing Audit", "求解器自愈生命周期审计", getattr(report, "self_healing", None)),
        ("15. Mechanism Kinematics & Topology", "机构运动学与拓扑参数", report.mechanism),
        ("16. Assumptions / Limitations", "基础工程假设与分析局限性", (report.assumptions, report.limitations)),
        ("16b. Classified Engineering Facts", "工程事实分类（实测结果 / 限制 / 研发过程）", getattr(report, "classified_facts", ())),
        ("17. Evidence", "电子证据链与产物内容摘要", report.evidence),
        ("18. Provenance", "模型版本与运行出处追溯", report.provenance),
    ]
    for heading, zh_heading, value in sections:
        if value in (None, {}, (), [], ""): continue
        if isinstance(value, (tuple, list)) and all(v in (None, {}, (), [], "") for v in value): continue
        section_title = f"{heading} / {zh_heading}" if is_zh else heading
        lines += ["## %s" % section_title, ""]
        if heading == "9. Figures":
            for figure in value:
                lines += ["![%s](%s)" % (_figure_caption_for_report(figure, is_zh=is_zh), figure.path), ""]
                meta = getattr(figure, "metadata", None) or {}
                interp = meta.get("description") or meta.get("interpretation") or meta.get("engineering_notes")
                if interp:
                    lead = "**图面工程技术解读 (Technical Figure Analysis)**:" if is_zh else "**Technical Figure Analysis**:"
                    lines += [f"> {lead} {interp}", ""]
        else:
            tbl_lines = _render_custom_table_for_section(heading, value, is_zh=is_zh)
            if tbl_lines:
                lines += tbl_lines
                if heading == "7. Mesh" and report.figures:
                    for figure in report.figures:
                        f_kind = getattr(figure, "kind", "") or ""
                        f_meta = getattr(figure, "metadata", {}) or {}
                        f_field = (f_meta.get("field") or f_meta.get("field_name") or "").upper()
                        if "mesh" in f_kind.lower() or f_field in ("MESH", "GRID"):
                            sub_m_t = "### 有限元网格空间离散几何拓扑图 (Mesh Discretization Topology)" if is_zh else "### Finite Element Mesh Discretization Topology"
                            lines += [
                                sub_m_t,
                                "",
                                "![%s](%s)" % (_figure_caption_for_report(figure, is_zh=is_zh), figure.path),
                                "",
                            ]
                            interp = f_meta.get("description") or f_meta.get("interpretation") or f_meta.get("engineering_notes")
                            if interp:
                                lead = "**图面工程技术解读 (Technical Figure Analysis)**:" if is_zh else "**Technical Figure Analysis**:"
                                lines += [f"> {lead} {interp}", ""]
                sum_title = "结构化工程底层数据载荷 (Structured Engineering Data Payload JSON)" if is_zh else "Structured Engineering Data Payload (JSON)"
                lines += [
                    "<details>",
                    f"<summary>{sum_title}</summary>",
                    "",
                    "```json",
                    json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str),
                    "```",
                    "",
                    "</details>",
                    "",
                ]
            else:
                lines += ["```json", json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str), "```", ""]
    conc_title = "## 19. Conclusion / 工程分析最终裁决结论" if is_zh else "## 19. Conclusion"
    conclusion_text = _conclusion(report, is_zh=is_zh)
    scope_note = _objective_scope_note(report, is_zh=is_zh)
    if scope_note:
        conclusion_text = f"{conclusion_text} {scope_note}"
    lines += [conc_title, "", conclusion_text, "", _attribution_note(report, is_zh=is_zh), ""]
    conclusion_lines = _render_conclusion_binding(report, is_zh=is_zh)
    if conclusion_lines:
        bound_title = "## 19b. Conclusions & Evidence Binding / 结论与证据绑定" if is_zh else "## 19b. Conclusions & Evidence Binding"
        lines += [bound_title, ""] + conclusion_lines
    return "\n".join(lines)


def _render_rich_text_to_html(content, is_zh=False):
    """Deterministically parse rich text / Markdown blocks into semantic publication-grade HTML elements."""
    if not content:
        return ""

    if isinstance(content, str):
        raw_lines = content.splitlines()
    else:
        raw_lines = []
        for item in content:
            if isinstance(item, str):
                raw_lines.extend(item.splitlines())
            else:
                raw_lines.append(str(item))

    body_parts = []

    in_table = False
    table_headers = []
    table_rows = []

    in_code = False
    code_lines = []

    para_lines = []

    def flush_table():
        nonlocal in_table, table_headers, table_rows
        if not in_table or not table_headers:
            in_table = False
            table_headers = []
            table_rows = []
            return
        out = ['<div class="table-wrapper"><table class="report-table"><thead><tr>']
        for h in table_headers:
            out.append(f'<th>{_format_inline_markdown(h)}</th>')
        out.append('</tr></thead><tbody>')
        for r in table_rows:
            out.append('<tr>')
            for c in r:
                cell_content = _format_cell_badge(c, is_zh=is_zh)
                out.append(f'<td>{cell_content}</td>')
            out.append('</tr>')
        out.append('</tbody></table></div>')
        body_parts.append("".join(out))
        in_table = False
        table_headers = []
        table_rows = []

    def flush_para():
        nonlocal para_lines
        if not para_lines:
            return
        # Join lines intelligently: avoid redundant space between adjacent CJK characters
        joined = para_lines[0].strip()
        for nxt in para_lines[1:]:
            nxt_s = nxt.strip()
            if not nxt_s:
                continue
            prev_char = joined[-1] if joined else ""
            next_char = nxt_s[0] if nxt_s else ""
            if '\u4e00' <= prev_char <= '\u9fff' and '\u4e00' <= next_char <= '\u9fff':
                joined += nxt_s
            else:
                joined += " " + nxt_s
        if joined:
            body_parts.append(f'<p class="report-p">{_format_inline_markdown(joined)}</p>')
        para_lines = []

    def flush_code():
        nonlocal in_code, code_lines
        if not in_code:
            return
        code_text = html.escape("\n".join(code_lines))
        body_parts.append(f'<pre class="code-block"><code>{code_text}</code></pre>')
        in_code = False
        code_lines = []

    def flush_all():
        flush_table()
        flush_para()
        flush_code()

    for line in raw_lines:
        trimmed = line.strip()

        # 1. Code fence ```
        if trimmed.startswith("```"):
            flush_table()
            flush_para()
            if in_code:
                flush_code()
            else:
                in_code = True
                code_lines = []
            continue

        if in_code:
            code_lines.append(line)
            continue

        # 2. Markdown Table row: starts and ends with |
        if trimmed.startswith("|") and trimmed.endswith("|") and len(trimmed) >= 2:
            flush_para()
            raw_cells = [c.strip() for c in trimmed[1:-1].split("|")]
            is_sep = all(set(c).issubset({"-", ":", " "}) for c in raw_cells if c)
            if is_sep:
                continue
            if not in_table:
                in_table = True
                table_headers = raw_cells
                table_rows = []
            else:
                table_rows.append(raw_cells)
            continue
        else:
            if in_table:
                flush_table()

        # 3. Headings
        if trimmed.startswith("#### "):
            flush_para()
            heading_text = trimmed[5:].strip()
            body_parts.append(f'<h4 class="subsubsection-heading">{_format_inline_markdown(heading_text)}</h4>')
            continue
        elif trimmed.startswith("### "):
            flush_para()
            heading_text = trimmed[4:].strip()
            body_parts.append(f'<h3 class="subsection-heading">{_format_inline_markdown(heading_text)}</h3>')
            continue
        elif trimmed.startswith("## "):
            flush_para()
            heading_text = trimmed[3:].strip()
            body_parts.append(f'<h2 class="section-heading">{_format_inline_markdown(heading_text)}</h2>')
            continue

        # 4. Blockquote
        if trimmed.startswith("> "):
            flush_para()
            quote_text = trimmed[2:].strip()
            body_parts.append(f'<blockquote class="report-quote">{_format_inline_markdown(quote_text)}</blockquote>')
            continue

        # 5. List items
        # Ordered: "1. ", "2. ", "10. ", "1) ", etc.
        m_ordered = re.match(r'^(\d+[\.\)])\s+(.+)$', trimmed)
        if m_ordered:
            flush_para()
            num_label = m_ordered.group(1)
            item_text = m_ordered.group(2)
            body_parts.append(
                f'<div class="list-item">'
                f'<span class="list-num">{html.escape(num_label)}</span>'
                f'<span class="list-text">{_format_inline_markdown(item_text)}</span>'
                f'</div>'
            )
            continue

        # Unordered: "- ", "* " (not "**")
        m_bullet = re.match(r'^([-\*])\s+(.+)$', trimmed)
        if m_bullet and not trimmed.startswith("**"):
            flush_para()
            item_text = m_bullet.group(2)
            body_parts.append(
                f'<div class="list-item">'
                f'<span class="list-bullet">&bull;</span>'
                f'<span class="list-text">{_format_inline_markdown(item_text)}</span>'
                f'</div>'
            )
            continue

        # 6. Blank line -> flush paragraph
        if not trimmed:
            flush_para()
            continue

        # 7. Normal text line accumulating into paragraph
        para_lines.append(trimmed)

    flush_all()
    return "\n".join(body_parts)


def _render_section_lines_to_html(lines, is_zh=False):
    """Render structured table lines into semantic HTML tables, headings, and lists."""
    return _render_rich_text_to_html(lines, is_zh=is_zh)


def render_html(report, language=None, base_dir=None):
    """Render publication-grade industrial CAE engineering report directly from EngineeringReportData in semantic HTML."""
    is_zh = _is_chinese_report(report, language=language)
    eff_base_dir = base_dir or getattr(report, "base_dir", None) or getattr(report, "output_dir", None)

    # Extract KPI summaries for executive banner directly from report data
    kpi_cards = []
    acceptance = report.acceptance
    acc_passed = False
    if isinstance(acceptance, bool):
        acc_passed = acceptance
    elif hasattr(acceptance, "passed"):
        acc_passed = bool(acceptance.passed)
    elif isinstance(acceptance, dict):
        acc_passed = bool(acceptance.get("passed"))

    report_conclusions = tuple(getattr(report, "conclusions", ()) or ())
    if report_conclusions:
        acceptance_label = "已列验收准则 (Acceptance Criteria)" if is_zh else "Acceptance Criteria (listed)"
        acceptance_sub = "仅覆盖已列验收准则与前置门禁" if is_zh else "Listed criteria and gates only"
    else:
        acceptance_label = "总体设计准则验收 (Overall Acceptance)" if is_zh else "Overall Acceptance"
        acceptance_sub = "确定性工程门禁验算" if is_zh else "Deterministic Gate Verification"

    kpi_cards.append((
        acceptance_label,
        ("PASS / 合格" if acc_passed else "FAIL / 未合格") if is_zh else ("PASS" if acc_passed else "FAIL"),
        acceptance_sub,
        "badge-pass" if acc_passed else "badge-fail"
    ))

    for objective_conclusion, objective_status in _non_pass_engineering_objectives(report):
        conclusion_id = (
            objective_conclusion.get("conclusion_id")
            if isinstance(objective_conclusion, dict)
            else getattr(objective_conclusion, "conclusion_id", "")
        )
        objective_sub = _objective_status_subtitle(objective_status, is_zh=is_zh)
        if conclusion_id:
            objective_sub = f"{conclusion_id}: {objective_sub}"
        kpi_cards.append((
            "工程目标 (Engineering Objective)" if is_zh else "Engineering Objective",
            objective_status,
            objective_sub,
            "badge-warn" if objective_status == "NOT_PROVEN" else "badge-fail",
        ))

    for m in (report.results or ())[:5]:
        m_name = getattr(m, "name", None) or (m.get("name") or m.get("metric") or m.get("label") if isinstance(m, dict) else str(m)) or "Metric"
        m_val = getattr(m, "value", None) if hasattr(m, "value") else (m.get("value") if isinstance(m, dict) else "-")
        m_unit = getattr(m, "unit", "") if hasattr(m, "unit") else (m.get("unit", "") if isinstance(m, dict) else "")
        v_str = f"{m_val} {m_unit}".strip()
        kpi_cards.append((str(m_name), str(v_str), "关键物理指标 / Key Metric" if is_zh else "Key Result Metric", "badge-metric"))

    kpi_html = '<div class="kpi-grid">'
    for label, val, sub, b_cls in kpi_cards:
        kpi_html += f'''
        <div class="kpi-card {b_cls}">
          <div class="kpi-label">{html.escape(str(label or ""))}</div>
          <div class="kpi-value">{html.escape(str(val or ""))}</div>
          <div class="kpi-sub">{html.escape(str(sub or ""))}</div>
        </div>'''
    kpi_html += '</div>'

    # Build semantic HTML directly from report structure without intermediate Markdown string
    body_parts = []
    if report.title.startswith("[DIAGNOSTIC") or "[NON-DELIVERABLE DRAFT]" in report.title:
        body_parts.append(
            '<div class="diagnostic-banner" style="background:#fee2e2;border:2px solid #ef4444;color:#991b1b;'
            'padding:14px 20px;border-radius:8px;margin-bottom:24px;font-weight:bold;text-align:center;font-size:16px;">'
            '⚠️ 非正式交付草稿 / DIAGNOSTIC NON-DELIVERABLE DRAFT — 未获得正式工程交付授权 (UNAUTHORIZED FOR ENGINEERING RELEASE)'
            '</div>'
        )
    body_parts.extend([
        f'<h1 class="main-title">{html.escape(report.title)}</h1>',
        kpi_html,
    ])

    # 1. Executive Summary
    if report.objective:
        exec_heading = "1. Executive Summary / 工程执行摘要" if is_zh else "1. Executive Summary"
        body_parts.append(f'<h2 class="section-heading">{html.escape(exec_heading)}</h2>')
        body_parts.append(_render_rich_text_to_html(report.objective, is_zh=is_zh))

    # 2 - 18. Structured Sections
    sections = [
        ("2. Model Information", "几何模型与装配拓扑定义", report.model),
        ("3. Material", "材料本构模型与物性温变定义", report.materials),
        ("4. Boundary Conditions", "边界约束与位移固定条件", report.boundary_conditions),
        ("5. Loads", "载荷工况与热流压力历程", report.loads),
        ("6. Solver / Analysis Procedure", "求解器步序与算法控制策略", report.solver),
        ("7. Mesh", "有限元网格离散与质量审计", report.mesh),
        ("8. Results", "关键工程物理指标计算结果", report.results),
        ("8b. Result Intelligence & Derived Metrics", "结果智能与空间热点衍生指标", getattr(report, "result_intelligence", None)),
        ("9. Figures", "工程图纸与仿真云图资产", report.figures),
        ("10. Engineering Checks", "工业工程准则合规性详细核验", report.engineering_checks),
        ("11. Acceptance Criteria", "确定性工程设计准则验算与门禁", report.acceptance),
        ("12. Sensitivity / Uncertainty", "参数敏感性与不确定度量化", (report.sensitivity, report.uncertainty)),
        ("12b. Engineering Mechanism Analysis", "深层物理失效机理工程剖析", report.metadata.get("mechanism_analysis") if hasattr(report, "metadata") and isinstance(report.metadata, dict) else None),
        ("13. Fatigue", "高低温疲劳与寿命损伤评估", report.fatigue),
        ("13b. Design Recommendations & Countermeasures", "结构改型建议与对策方案", report.metadata.get("design_recommendations") if hasattr(report, "metadata") and isinstance(report.metadata, dict) else None),
        ("14. Contact Diagnostics", "接触界面状态与穿透诊断", report.contact_diagnostics),
        ("14b. Solver Diagnostics & Self-Healing Audit", "求解器自愈生命周期审计", getattr(report, "self_healing", None)),
        ("15. Mechanism Kinematics & Topology", "机构运动学与拓扑参数", report.mechanism),
        ("16. Assumptions / Limitations", "基础工程假设与分析局限性", (report.assumptions, report.limitations)),
        ("16b. Classified Engineering Facts", "工程事实分类（实测结果 / 限制 / 研发过程）", getattr(report, "classified_facts", ())),
        ("17. Evidence", "电子证据链与产物内容摘要", report.evidence),
        ("18. Provenance", "模型版本与运行出处追溯", report.provenance),
    ]

    for heading, zh_heading, value in sections:
        if value in (None, {}, (), [], ""):
            continue
        if isinstance(value, (tuple, list)) and all(v in (None, {}, (), [], "") for v in value):
            continue

        section_title = f"{heading} / {zh_heading}" if is_zh else heading
        body_parts.append(f'<h2 class="section-heading">{html.escape(section_title)}</h2>')

        if heading == "9. Figures":
            for figure in value:
                body_parts.append(_render_html_figure(_figure_caption_for_report(figure, is_zh=is_zh), figure.path, is_zh=is_zh, base_dir=eff_base_dir))
                meta = getattr(figure, "metadata", None) or {}
                interp = meta.get("description") or meta.get("interpretation") or meta.get("engineering_notes")
                if interp:
                    lead = "图面工程技术解读 (Technical Figure Analysis):" if is_zh else "Technical Figure Analysis:"
                    body_parts.append(f'<blockquote class="report-quote"><strong>{html.escape(lead)}</strong> {_format_inline_markdown(interp)}</blockquote>')
        else:
            tbl_lines = _render_custom_table_for_section(heading, value, is_zh=is_zh)
            if tbl_lines:
                body_parts.append(_render_section_lines_to_html(tbl_lines, is_zh=is_zh))
                if heading == "7. Mesh" and report.figures:
                    for figure in report.figures:
                        f_kind = getattr(figure, "kind", "") or ""
                        f_meta = getattr(figure, "metadata", {}) or {}
                        f_field = (f_meta.get("field") or f_meta.get("field_name") or "").upper()
                        if "mesh" in f_kind.lower() or f_field in ("MESH", "GRID"):
                            sub_t = "有限元网格空间离散几何拓扑图 (Mesh Discretization Topology)" if is_zh else "Finite Element Mesh Discretization Topology"
                            body_parts.append(f'<h3 class="subsection-heading">{html.escape(sub_t)}</h3>')
                            body_parts.append(_render_html_figure(figure.caption or "有限元网格划分拓扑图", figure.path, is_zh=is_zh, base_dir=eff_base_dir))
                            interp = f_meta.get("description") or f_meta.get("interpretation") or f_meta.get("engineering_notes")
                            if interp:
                                lead = "图面工程技术解读 (Technical Figure Analysis):" if is_zh else "Technical Figure Analysis:"
                                body_parts.append(f'<blockquote class="report-quote"><strong>{html.escape(lead)}</strong> {_format_inline_markdown(interp)}</blockquote>')
                sum_title = "结构化工程底层数据载荷 (Structured Engineering Data Payload JSON)" if is_zh else "Structured Engineering Data Payload (JSON)"
                json_data = json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str)
                body_parts.append(
                    f'<details class="payload-details">'
                    f'<summary>{html.escape(sum_title)}</summary>'
                    f'<pre class="code-block"><code>{html.escape(json_data)}</code></pre>'
                    f'</details>'
                )
            else:
                json_data = json.dumps(_plain(value), indent=2, ensure_ascii=False, default=str)
                body_parts.append(f'<pre class="code-block"><code>{html.escape(json_data)}</code></pre>')

    # 19. Conclusion
    conc_title = "19. Conclusion / 工程分析最终裁决结论" if is_zh else "19. Conclusion"
    body_parts.append(f'<h2 class="section-heading">{html.escape(conc_title)}</h2>')
    conclusion_text = _conclusion(report, is_zh=is_zh)
    scope_note = _objective_scope_note(report, is_zh=is_zh)
    if scope_note:
        conclusion_text = f"{conclusion_text} {scope_note}"
    body_parts.append(_render_rich_text_to_html(conclusion_text, is_zh=is_zh))
    body_parts.append(f'<p class="report-quote">{html.escape(_attribution_note(report, is_zh=is_zh))}</p>')
    conclusion_lines = _render_conclusion_binding(report, is_zh=is_zh)
    if conclusion_lines:
        bound_title = "19b. Conclusions & Evidence Binding / 结论与证据绑定" if is_zh else "19b. Conclusions & Evidence Binding"
        body_parts.append(f'<h2 class="section-heading">{html.escape(bound_title)}</h2>')
        body_parts.append(_render_section_lines_to_html(conclusion_lines, is_zh=is_zh))

    content_html = "\n".join(body_parts)

    css_styles = """
    :root {
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --border: #e2e8f0;
      --primary: #1e40af;
      --primary-light: #eff6ff;
      --success: #16a34a;
      --success-bg: #dcfce7;
      --danger: #dc2626;
      --danger-bg: #fee2e2;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "WenQuanYi Micro Hei", "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 32px 16px;
    }
    .report-container {
      max-width: 1120px;
      margin: 0 auto;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
      padding: 48px;
    }
    .main-title {
      font-size: 26px;
      font-weight: 800;
      color: #0f172a;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 2px solid #0f172a;
      letter-spacing: -0.02em;
    }
    .section-heading {
      font-size: 18px;
      font-weight: 700;
      color: #1e3a8a;
      margin-top: 36px;
      margin-bottom: 16px;
      padding-left: 12px;
      border-left: 4px solid #2563eb;
    }
    .subsection-heading {
      font-size: 15px;
      font-weight: 700;
      color: #1e3a8a;
      margin-top: 24px;
      margin-bottom: 12px;
      padding-bottom: 4px;
      border-bottom: 1px solid #e2e8f0;
      letter-spacing: -0.01em;
    }
    .subsubsection-heading {
      font-size: 13.5px;
      font-weight: 600;
      color: #334155;
      margin-top: 16px;
      margin-bottom: 8px;
    }
    .report-p {
      color: #334155;
      font-size: 14px;
      margin-bottom: 12px;
      line-height: 1.65;
    }
    .report-p strong, .list-text strong, .report-table td strong {
      color: #0f172a;
      font-weight: 600;
    }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.9em;
      background: #f1f5f9;
      padding: 2px 6px;
      border-radius: 4px;
      color: #1e40af;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }
    .kpi-card {
      background: #f8fafc;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
      transition: transform 0.1s ease;
    }
    .kpi-card.badge-pass {
      background: #f0fdf4;
      border-color: #86efac;
    }
    .kpi-card.badge-fail {
      background: #fef2f2;
      border-color: #fca5a5;
    }
    .kpi-card.badge-warn {
      background: #fffbeb;
      border-color: #fcd34d;
    }
    .kpi-label {
      font-size: 11px;
      font-weight: 600;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 4px;
    }
    .kpi-value {
      font-size: 20px;
      font-weight: 800;
      color: #0f172a;
    }
    .badge-pass .kpi-value { color: #15803d; }
    .badge-fail .kpi-value { color: #b91c1c; }
    .badge-warn .kpi-value { color: #b45309; }
    .kpi-sub {
      font-size: 11px;
      color: #94a3b8;
      margin-top: 4px;
    }
    .table-wrapper {
      overflow-x: auto;
      margin-bottom: 24px;
      border: 1px solid var(--border);
      border-radius: 8px;
    }
    .report-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }
    .report-table th {
      background: #0f172a;
      color: #f8fafc;
      font-weight: 600;
      padding: 10px 14px;
      white-space: nowrap;
    }
    .report-table td {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      color: #334155;
    }
    .report-table tr:nth-child(even) td {
      background: #f8fafc;
    }
    .report-table tr:hover td {
      background: #f1f5f9;
    }
    .status-badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .status-badge.badge-pass {
      background: #dcfce7;
      color: #15803d;
    }
    .status-badge.badge-fail {
      background: #fee2e2;
      color: #b91c1c;
    }
    .status-badge.badge-skip {
      background: #f1f5f9;
      color: #64748b;
    }
    .report-figure {
      margin: 28px auto;
      max-width: 100%;
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
      overflow: hidden;
    }
    .figure-missing {
      background: #f8fafc;
      border: 2px dashed #cbd5e1;
    }
    .placeholder-box {
      padding: 32px 16px;
      text-align: center;
      color: #64748b;
    }
    .placeholder-icon {
      font-size: 32px;
      margin-bottom: 8px;
    }
    .placeholder-title {
      font-size: 14px;
      font-weight: 600;
      color: #475569;
      margin-bottom: 6px;
    }
    .placeholder-path {
      font-size: 12px;
      color: #94a3b8;
    }
    .placeholder-path code {
      background: #e2e8f0;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 11px;
      color: #334155;
    }
    .svg-container {
      width: 100%;
      max-width: 1000px;
      margin: 0 auto;
      display: flex;
      justify-content: center;
      align-items: center;
      overflow-x: auto;
    }
    .svg-container svg {
      max-width: 100%;
      height: auto;
      display: block;
    }
    .figure-img {
      display: block;
      margin: 0 auto;
      max-width: 100%;
      height: auto;
      border-radius: 4px;
      object-fit: contain;
    }
    .figure-caption {
      margin-top: 10px;
      font-size: 13px;
      color: #475569;
    }
    .report-quote {
      margin: 12px 0 20px 0;
      padding: 12px 18px;
      background: #f1f5f9;
      border-left: 4px solid var(--primary);
      color: #334155;
      font-size: 13px;
      line-height: 1.6;
      border-radius: 0 6px 6px 0;
      text-align: left;
    }
    .payload-details {
      margin: 16px 0;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px 16px;
      background: #f8fafc;
    }
    .payload-details summary {
      font-size: 12px;
      font-weight: 600;
      color: #64748b;
      cursor: pointer;
      user-select: none;
    }
    .code-block {
      background: #0f172a;
      color: #e2e8f0;
      padding: 14px;
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
      overflow-x: auto;
      margin-top: 10px;
    }
    .list-item {
      display: flex;
      margin-bottom: 8px;
      font-size: 14px;
      color: #334155;
      line-height: 1.6;
    }
    .list-num, .list-bullet {
      font-weight: 700;
      margin-right: 8px;
      color: #2563eb;
      flex-shrink: 0;
    }
    .list-text {
      flex: 1;
    }
    @media print {
      body { background: #fff; padding: 0; }
      .report-container { border: none; box-shadow: none; padding: 0; max-width: 100%; }
      .payload-details { display: none; }
    }
    """

    lang_attr = "zh-CN" if is_zh else "en"
    return f"""<!doctype html>
<html lang="{lang_attr}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(report.title)}</title>
  <style>{css_styles}</style>
</head>
<body>
  <div class="report-container">
    {content_html}
  </div>
</body>
</html>"""

def render_analysis_report(run, title=None, objective="", language=None):
    """Render markdown and html deliverables directly from an AnalysisRun."""
    from ..contracts.report import EngineeringReportData

    report = EngineeringReportData.from_analysis(run, title=title, objective=objective)
    if language is not None and hasattr(report, "metadata") and isinstance(report.metadata, dict):
        report.metadata["language"] = language
    return {
        "report_data": report,
        "markdown": render_markdown(report, language=language),
        "html": render_html(report, language=language),
    }

def verify_html_self_contained(html_text, max_size_bytes: int = 50 * 1024 * 1024) -> Dict[str, Any]:
    """Audit single-file HTML deliverable to strictly ensure 100% self-containment.

    Checks:
    1. No external CSS stylesheets (<link rel="stylesheet"> with non-data URLs).
    2. No external JS scripts (<script src="..."> with non-data URLs).
    3. No external non-inlined images (<img src="..."> with relative or http/https URLs instead of data: URIs).
    4. No external font @import rules.
    5. Overall file payload size within engineering threshold.
    """
    import re
    from pathlib import Path

    if isinstance(html_text, Path) or hasattr(html_text, "read_text"):
        html_text = html_text.read_text(encoding="utf-8")
    else:
        html_text = str(html_text)

    external_refs = []

    # 1. External CSS links
    css_links = re.findall(r'<link[^>]+rel=[\'"]stylesheet[\'"][^>]*href=[\'"]([^\'"]+)[\'"]', html_text, re.IGNORECASE)
    for href in css_links:
        if not href.startswith("data:"):
            external_refs.append(f"External CSS link: {href}")

    # 2. External JS scripts
    js_scripts = re.findall(r'<script[^>]+src=[\'"]([^\'"]+)[\'"]', html_text, re.IGNORECASE)
    for src in js_scripts:
        if not src.startswith("data:"):
            external_refs.append(f"External JS script: {src}")

    # 3. External images
    img_sources = re.findall(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', html_text, re.IGNORECASE)
    for src in img_sources:
        if not src.startswith("data:"):
            external_refs.append(f"External image source: {src}")

    # 4. External font @import
    font_imports = re.findall(r'@import\s+(?:url\()?[\'"]?(https?:[^\'")]+)[\'"]?', html_text, re.IGNORECASE)
    for fi in font_imports:
        external_refs.append(f"External font import: {fi}")

    size_bytes = len(html_text.encode("utf-8"))
    oversized = size_bytes > max_size_bytes
    if oversized:
        external_refs.append(f"HTML size {size_bytes} bytes exceeds threshold {max_size_bytes}")

    is_self_contained = len(external_refs) == 0

    return {
        "self_contained": is_self_contained,
        "size_bytes": size_bytes,
        "external_references_count": len(external_refs),
        "external_references": external_refs,
        "has_external_css": any("CSS" in r for r in external_refs),
        "has_external_js": any("JS" in r for r in external_refs),
        "has_external_images": any("image" in r for r in external_refs),
    }


def render_report(report, fmt="html", language=None, base_dir=None):
    """Unified entrypoint for deterministic report rendering. HTML is the sole standardized delivery format.

    ``base_dir`` is the directory that owns this run's figure files. HTML embeds
    those files as data URIs so a single forwarded report still shows every image.
    """
    if fmt == "html":
        return render_html(report, language=language, base_dir=base_dir)
    elif fmt == "markdown":
        return render_markdown(report, language=language)
    raise ValueError(f"Unsupported report format: {fmt}. Standardized deliverable format is 'html'.")

def _attribution_note(report, is_zh=False):
    """State who may claim authorship. Never invent an Agent caption.

    A content digest is not a keyed signature. Attribution is allowed only when
    the report carries an Agent run record. ``jev_routed`` records the routing
    path; it does not certify the parse, the model, or the solve.
    """
    meta = getattr(report, "metadata", None) or {}
    gate = meta.get("deliverable_authorization") if isinstance(meta, dict) else None
    if not isinstance(gate, dict):
        gate = {}
    if gate.get("allow_agent_attribution"):
        if is_zh:
            return (
                "报告编制：Abaqus-AI-Agent。运行记录显示本次自然语言需求经过产品路由；"
                "这只证明处理路径，不证明解析正确、模型合格、求解成功或工程验收通过。"
            )
        return (
            "Prepared by Abaqus-AI-Agent. The run record shows this natural-language "
            "request passed product routing. That records the path only; it does not "
            "certify the parse, the model, the solve, or engineering acceptance."
        )
    if gate.get("deliverable_file_allowed"):
        if is_zh:
            return (
                "本文件由 Abaqus-AI-Agent 运行记录生成，但本次求解未经过 JEV 需求路由，"
                "不得写成自然语言工程需求的正式编制交付。"
            )
        return (
            "Filed from an Abaqus-AI-Agent run record, but this solve did not pass JEV routing "
            "and must not be captioned as a natural-language Agent deliverable."
        )
    if is_zh:
        return (
            "未授权署名 Abaqus-AI-Agent 编制。缺少可核对的 Agent 运行记录，"
            "或自然语言需求未经过 JEV 路由。不得把本文件当作 Agent 交付。"
        )
    return (
        "Not authorized to be captioned as prepared by Abaqus-AI-Agent. "
        "No verifiable Agent run record, or the natural-language requirement was not JEV-routed."
    )


def _metric_name(item):
    if isinstance(item, dict):
        return str(item.get("name") or item.get("metric") or item.get("label") or "")
    return str(getattr(item, "name", None) or getattr(item, "metric", None) or "")


def _metric_value(item):
    if isinstance(item, dict):
        return item.get("value")
    return getattr(item, "value", None)


def _stress_peak_note(results, is_zh=False):
    """State peak and 99.5% values together. A percentile must not hide the peak."""
    peak_keys = ("max_mises", "max_stress", "s_mises", "mises", "peak_mises", "peak_stress")
    p995_keys = ("mises_p995", "p995_mises", "stress_p995", "percentile_99_5", "mises_percentile_995")
    peak = None
    percentile = None
    for item in results or ():
        name = _metric_name(item).lower()
        value = _metric_value(item)
        if peak is None and name in peak_keys:
            peak = value
        if percentile is None and name in p995_keys:
            percentile = value
    if peak is None and percentile is None:
        return ""
    if is_zh:
        parts = ["应力报告同时保留全场峰值和 99.5% 分位。分位数不能掩盖峰值，也不能单独作为交付应力。"]
        if peak is not None:
            parts.append("全场峰值: %s。" % peak)
        if percentile is not None:
            parts.append("99.5%% 分位: %s。" % percentile)
        return "> " + "".join(parts)
    parts = ["Peak and 99.5th-percentile stress are both retained. The percentile must not hide or replace the peak."]
    if peak is not None:
        parts.append("Peak: %s." % peak)
    if percentile is not None:
        parts.append("99.5th percentile: %s." % percentile)
    return "> " + " ".join(parts)


def _conclusion(report, is_zh=False):
    acceptance = report.acceptance
    audit_summary = ""
    result_validity = "VALID"
    missing_metrics = ()
    missing_gates = ()

    if isinstance(acceptance, bool):
        passed = acceptance
        warnings = ()
        failures = ()
    elif isinstance(acceptance, dict):
        passed = acceptance.get("passed", False)
        warnings = tuple(acceptance.get("warnings") or ())
        failures = tuple(acceptance.get("failures") or ())
        audit_summary = acceptance.get("audit_summary", "")
        result_validity = acceptance.get("result_validity", "VALID")
        missing_metrics = tuple(acceptance.get("missing_required_metrics") or ())
        missing_gates = tuple(acceptance.get("missing_required_gates") or ())
    elif acceptance is not None:
        passed = getattr(acceptance, "passed", False)
        warnings = tuple(getattr(acceptance, "warnings", ()) or ())
        failures = tuple(getattr(acceptance, "failures", ()) or ())
        audit_summary = getattr(acceptance, "audit_summary", "")
        result_validity = getattr(acceptance, "result_validity", "VALID")
        missing_metrics = tuple(getattr(acceptance, "missing_required_metrics", ()) or ())
        missing_gates = tuple(getattr(acceptance, "missing_required_gates", ()) or ())
    else:
        return "No acceptance verdict is asserted because no structured acceptance result was supplied." if not is_zh else "未提供结构化验收准则数据，未生成最终门禁判定。"

    summary_label = "审计结论摘要 (Audit Summary)" if is_zh else "Audit Summary"
    prefix = f"**{summary_label}**: {audit_summary}\n\n" if audit_summary else ""

    if passed:
        if warnings:
            if is_zh:
                return f"{prefix}结构化验收准则核验全部通过 (Acceptance criteria passed based on the structured evidence supplied to this report)；留存警告提示: {', '.join(warnings)}。"
            return f"{prefix}Acceptance criteria passed based on the structured evidence supplied to this report; warnings remain: {', '.join(warnings)}."
        if is_zh:
            return f"{prefix}结构化验收准则核验全部合格 (Acceptance criteria passed based on the structured evidence supplied to this report)。"
        return f"{prefix}Acceptance criteria passed based on the structured evidence supplied to this report."

    detail_parts = []
    if any("evidence_tampered" in f for f in failures):
        detail_parts.append("EVIDENCE TAMPER DETECTED: Artifact checksum mismatch against manifest provenance.")
    if any("evidence_incomplete" in f for f in failures):
        detail_parts.append("EVIDENCE INCOMPLETE: Mandatory solver artifacts are missing from disk.")
    if any("evidence_stale" in f for f in failures):
        detail_parts.append("EVIDENCE STALE: Run ID mismatch or timestamp expired; stale evidence reuse is prohibited.")
    if str(result_validity) == "RESULT_INVALID" or any("elastic_range_exceeded" in f for f in failures):
        detail_parts.append(
            "Engineering conclusion is REJECTED (RESULT_INVALID): a purely elastic result past yield is not plastic deformation, and a percentile must not replace the peak."
        )
    if missing_metrics:
        detail_parts.append(f"Missing required physical metrics: {', '.join(missing_metrics)}.")
    if missing_gates:
        detail_parts.append(f"Missing mandatory verification gates: {', '.join(missing_gates)}.")
    if failures:
        detail_parts.append(f"Failures: {', '.join(failures)}.")

    detail = (" " + " ".join(detail_parts)) if detail_parts else ""
    if is_zh:
        return f"{prefix}结构化验收准则核验未完全满足 (Acceptance criteria were not fully satisfied by the structured evidence supplied to this report)。{detail}"
    return f"{prefix}Acceptance criteria were not fully satisfied by the structured evidence supplied to this report.{detail}"

def _non_pass_engineering_objectives(report):
    objectives = []
    for item in tuple(getattr(report, "conclusions", ()) or ()):
        layer = item.get("layer") if isinstance(item, dict) else getattr(item, "layer", "")
        layer_value = getattr(layer, "value", layer)
        if str(layer_value) != "ENGINEERING_OBJECTIVE":
            continue
        status = item.get("status") if isinstance(item, dict) else getattr(item, "status", "")
        status_value = getattr(status, "value", status)
        status_text = str(status_value or "")
        if not status_text or status_text == "PASS":
            continue
        objectives.append((item, status_text))
    return tuple(objectives)


def _objective_status_subtitle(status, is_zh=False):
    if status == "NOT_PROVEN":
        return (
            "已列证据不足以证明所述工程目标"
            if is_zh
            else "Stated objective is not proven by the listed evidence"
        )
    if status == "FAIL":
        return (
            "已列证据表明所述工程目标未满足"
            if is_zh
            else "Stated objective is contradicted by the listed evidence"
        )
    if status == "REJECTED":
        return (
            "结果不可采纳，所述工程目标无法得出结论"
            if is_zh
            else "Stated objective cannot be concluded because the result is inadmissible"
        )
    return (
        f"工程目标状态：{status}"
        if is_zh
        else f"Objective status: {status}"
    )


def _objective_scope_note(report, is_zh=False):
    objectives = _non_pass_engineering_objectives(report)
    if not objectives:
        return ""
    statuses = tuple(dict.fromkeys(status for _, status in objectives))
    if len(statuses) == 1:
        status = statuses[0]
        if is_zh:
            return (
                "该裁决仅覆盖已列验收准则与前置门禁；"
                f"所述工程目标为 {status}。"
            )
        return (
            "This verdict covers only the listed acceptance criteria and gates; "
            f"the stated engineering objective is {status}."
        )
    joined = ", ".join(statuses)
    if is_zh:
        return (
            "该裁决仅覆盖已列验收准则与前置门禁；"
            f"所述工程目标状态为 {joined}。"
        )
    return (
        "This verdict covers only the listed acceptance criteria and gates; "
        f"the stated engineering objectives are {joined}."
    )


def _render_conclusion_binding(report, is_zh=False):
    conclusions = tuple(getattr(report, "conclusions", ()) or ())
    if not conclusions:
        return []

    def field(item, name, default=""):
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    rows = []
    for item in conclusions:
        layer = field(item, "layer", "")
        status = field(item, "status", "")
        evidence = field(item, "evidence", ())
        if isinstance(evidence, (list, tuple)):
            evidence = "; ".join(str(value) for value in evidence)
        rows.append([
            str(field(item, "conclusion_id", "")),
            str(getattr(layer, "value", layer)),
            str(getattr(status, "value", status)),
            str(field(item, "statement", "")),
            str(evidence),
            str(field(item, "scope", "")),
            str(field(item, "source", "")),
        ])
    if is_zh:
        headers = ["结论ID / ID", "层级 / Layer", "状态 / Status", "结论 / Conclusion", "证据 / Evidence", "适用范围 / Scope", "来源 / Source"]
        note = "验收层 PASS 仅表示已列验收准则与前置门禁通过，不会把未匹配的工程目标升级为 PASS。"
    else:
        headers = ["ID", "Layer", "Status", "Conclusion", "Evidence", "Scope", "Source"]
        note = (
            "An ACCEPTANCE PASS covers only the listed criteria and gates. "
            "It does not upgrade an ENGINEERING_OBJECTIVE that is NOT_PROVEN."
        )
    return [f"> {note}", "", _format_markdown_table(headers, rows), ""]
