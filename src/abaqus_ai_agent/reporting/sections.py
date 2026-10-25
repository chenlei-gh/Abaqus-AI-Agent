"""Stable report section registry shared by Markdown and HTML renderers (T-P8).

Numbers are semantic identifiers, not positions in the current output. An
optional section that is absent must not renumber any later section.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class ReportSectionSpec:
    key: str
    number: str
    title_en: str
    title_zh: str


REPORT_SECTIONS: Tuple[ReportSectionSpec, ...] = (
    ReportSectionSpec("executive_summary", "1", "Executive Summary", "工程执行摘要"),
    ReportSectionSpec("model_information", "2", "Model Information", "几何模型与装配拓扑定义"),
    ReportSectionSpec("material", "3", "Material", "材料本构模型与物性温变定义"),
    ReportSectionSpec("boundary_conditions", "4", "Boundary Conditions", "边界约束与位移固定条件"),
    ReportSectionSpec("loads", "5", "Loads", "载荷工况与热流压力历程"),
    ReportSectionSpec("solver", "6", "Solver / Analysis Procedure", "求解器步序与算法控制策略"),
    ReportSectionSpec("mesh", "7", "Mesh", "有限元网格离散与质量审计"),
    ReportSectionSpec("results", "8", "Results", "关键工程物理指标计算结果"),
    ReportSectionSpec("result_intelligence", "8b", "Result Intelligence & Derived Metrics", "结果智能与空间热点衍生指标"),
    ReportSectionSpec("figures", "9", "Figures", "工程图纸与仿真云图资产"),
    ReportSectionSpec("engineering_checks", "10", "Engineering Checks", "工业工程准则合规性详细核验"),
    ReportSectionSpec("acceptance", "11", "Acceptance Criteria", "确定性工程设计准则验算与门禁"),
    ReportSectionSpec("sensitivity_uncertainty", "12", "Sensitivity / Uncertainty", "参数敏感性与不确定度量化"),
    ReportSectionSpec("mechanism_analysis", "12b", "Engineering Mechanism Analysis", "深层物理失效机理工程剖析"),
    ReportSectionSpec("fatigue", "13", "Fatigue", "高低温疲劳与寿命损伤评估"),
    ReportSectionSpec("design_recommendations", "13b", "Design Recommendations & Countermeasures", "结构改型建议与对策方案"),
    ReportSectionSpec("contact_diagnostics", "14", "Contact Diagnostics", "接触界面状态与穿透诊断"),
    ReportSectionSpec("self_healing", "14b", "Solver Diagnostics & Self-Healing Audit", "求解器自愈生命周期审计"),
    ReportSectionSpec("mechanism_kinematics", "15", "Mechanism Kinematics & Topology", "机构运动学与拓扑参数"),
    ReportSectionSpec("assumptions_limitations", "16", "Assumptions / Limitations", "基础工程假设与分析局限性"),
    ReportSectionSpec("classified_facts", "16b", "Classified Engineering Facts", "工程事实分类（实测结果 / 限制 / 研发过程）"),
    ReportSectionSpec("evidence", "17", "Evidence", "电子证据链与产物内容摘要"),
    ReportSectionSpec("provenance", "18", "Provenance", "模型版本与运行出处追溯"),
    ReportSectionSpec("conclusion", "19", "Conclusion", "工程分析最终裁决结论"),
    ReportSectionSpec("conclusion_binding", "19b", "Conclusions & Evidence Binding", "结论与证据绑定"),
)

REPORT_SECTION_BY_KEY: Dict[str, ReportSectionSpec] = {
    spec.key: spec for spec in REPORT_SECTIONS
}


def section_title(spec: ReportSectionSpec, is_zh: bool = False) -> str:
    """Render a stable number and title without depending on output order."""
    en = f"{spec.number}. {spec.title_en}"
    if not is_zh:
        return en
    return f"{en} / {spec.title_zh}"
