import base64
from pathlib import Path
from abaqus_ai_agent.contracts.report import EngineeringReportData, ReportFigure
from abaqus_ai_agent.reporting.renderer import (
    render_markdown,
    render_html,
    render_analysis_report,
    _resolve_image_path,
    _render_html_figure,
    _is_chinese_report,
)


def test_is_chinese_report_detection():
    # 1. English title and metadata
    rep_en = EngineeringReportData(title="Standard Stress Analysis Report", objective="Linear static FEA")
    assert _is_chinese_report(rep_en) is False
    assert _is_chinese_report(rep_en, language="zh") is True

    # 2. Chinese title
    rep_zh_title = EngineeringReportData(title="四进一排气歧管热机耦合有限元分析报告", objective="Evaluate thermal stress")
    assert _is_chinese_report(rep_zh_title) is True

    # 3. Chinese objective
    rep_zh_obj = EngineeringReportData(title="Cantilever Beam Analysis", objective="校核悬臂梁最大应力与下垂挠度")
    assert _is_chinese_report(rep_zh_obj) is True

    # 4. Metadata language
    rep_zh_meta = EngineeringReportData(title="Analysis Report", objective="Static run", metadata={"language": "zh"})
    assert _is_chinese_report(rep_zh_meta) is True


def test_html_report_chinese_language_rendering():
    report = EngineeringReportData(
        title="柴油机排气歧管热力耦合工程分析报告",
        objective="完成排气歧管在650℃高温废气与螺栓预紧工况下的热机耦合强度与密封性校核。",
        materials=[
            {"name": "SiMo铸铁", "elastic_modulus": 175e9, "poisson_ratio": 0.27, "yield_strength": 240e6}
        ],
        results=[
            {"name": "最大等效应力", "value": 215.8, "unit": "MPa"},
            {"name": "垫片平均密封接触压强", "value": 38.6, "unit": "MPa"},
        ],
        acceptance={"passed": True, "criteria": [{"name": "法兰密封面密封性", "target": ">= 25 MPa", "actual": 38.6, "passed": True}]},
    )

    html_content = render_html(report)

    # 1. HTML5 document declaration and zh-CN lang
    assert '<html lang="zh-CN">' in html_content
    assert '<meta charset="utf-8">' in html_content

    # 2. Chinese font stack
    assert '"PingFang SC"' in html_content
    assert '"Microsoft YaHei"' in html_content

    # 3. Executive KPI banner
    assert "总体设计准则验收 (Overall Acceptance)" in html_content
    assert "PASS / 合格" in html_content

    # 4. Section headings bilingual or localized
    assert "1. Executive Summary / 工程执行摘要" in html_content
    assert "3. Material / 材料本构模型与物性温变定义" in html_content
    assert "8. Results / 关键工程物理指标计算结果" in html_content
    assert "11. Acceptance Criteria / 确定性工程设计准则验算与门禁" in html_content

    # 5. Table headers localized
    assert "部件 / 材料牌号" in html_content
    assert "物理指标名称 / Metric Name" in html_content
    assert "准则项名称 / Criterion" in html_content

    # 6. Status badge formatting
    assert '<span class="status-badge badge-pass">PASS</span>' in html_content


def test_html_report_inline_svg_rendering(tmp_path):
    # Create a test SVG file
    svg_file = tmp_path / "test_contour.svg"
    svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><rect width="400" height="200" fill="blue"/><text x="20" y="50" fill="white">Mises Stress Contour</text></svg>'
    svg_file.write_text(svg_content, encoding="utf-8")

    report = EngineeringReportData(
        title="SVG Figure Test Report",
        figures=[
            ReportFigure(path=str(svg_file), caption="等效应力分布云图", kind="contour", metadata={"description": "高温高应力区出现在中间汇流R4圆角处"})
        ],
        acceptance=True,
    )

    html_content = render_html(report)

    # Verify inline SVG
    assert '<div class="svg-container">' in html_content
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in html_content
    assert 'Mises Stress Contour' in html_content
    assert '等效应力分布云图' in html_content
    assert '高温高应力区出现在中间汇流R4圆角处' in html_content


def test_html_report_bitmap_base64_data_uri(tmp_path):
    # Create a 1x1 transparent PNG file
    png_file = tmp_path / "test_screenshot.png"
    # Minimal valid 1x1 PNG bytes
    png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    png_file.write_bytes(png_bytes)

    report = EngineeringReportData(
        title="Bitmap Figure Test Report",
        figures=[
            ReportFigure(path=str(png_file), caption="结构形变真实渲染图", kind="screenshot")
        ],
        acceptance=True,
    )

    html_content = render_html(report)

    # Verify Base64 Data URI embedding
    assert 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB' in html_content
    assert '<img src="data:image/png;base64,' in html_content
    assert '结构形变真实渲染图' in html_content


def test_html_report_missing_image_placeholder():
    report = EngineeringReportData(
        title="Missing Image Fallback Test",
        figures=[
            ReportFigure(path="non_existent_manifold_stress_map_9999.png", caption="缺失的仿真云图", kind="contour")
        ],
        acceptance=True,
    )

    # In Chinese mode
    html_zh = render_html(report, language="zh")
    assert 'figure-missing' in html_zh
    assert 'placeholder-box' in html_zh
    assert '图面工程资产 (Visual Engineering Asset)' in html_zh
    assert 'non_existent_manifold_stress_map_9999.png' in html_zh

    # In English mode
    report_en = EngineeringReportData(
        title="Missing Image Fallback Test EN",
        figures=[
            ReportFigure(path="non_existent_plot.svg", caption="Missing Plot", kind="contour")
        ],
        acceptance=True,
    )
    html_en = render_html(report_en, language="en")
    assert '<html lang="en">' in html_en
    assert 'figure-missing' in html_en
    assert 'Visual Engineering Asset' in html_en
