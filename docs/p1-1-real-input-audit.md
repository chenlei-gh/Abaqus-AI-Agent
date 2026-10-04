# P1.1 真实工程图输入资格审计报告 (Real-Input Qualification Audit)

**状态：** QUALIFICATION PENDING (基础设施 QUALIFIED / 真实输入 AUDITED)  
**日期：** 2026-10-04  
**基线版本：** `7af3d8c` (全库测试 739/739 严格警告全绿通过)  
**审计范围：** P1.1 工程输入感知层在真实工程图纸、多模态真实输入与物理求解闭环下的资格认定

---

## 1. 审计裁决与总体结论

在完成 P1.0 产品主入口（`solve_requirement()`）与 P1.1 感知基础设施（`src/abaqus_ai_agent/perception/`）的严格收口后，本报告针对“真实工程图纸与真实多模态输入”进行了系统性的资格审查。

### 1.1 核心裁决结论

| 层次 / 领域 | 当前定级 | 核心依据与客观状态 |
|:---|:---:|:---|
| **P1.1 感知软件基础设施** | **QUALIFIED** | 具备完整的文档解析分流、可逆坐标映射、多维置信度矩阵、严格非法坐标与零向量拦截、正交抽取器、与 GA-2A CAD Grounding 和 GA-2B HITL 的双向无缝桥接，全库 739/739 测试严格通过。 |
| **真实图纸与外部 Provider 资格** | **PENDING** | 当前测试与验证主要依赖离线确定性 `MockVisionProvider` 与正则 `RuleBasedVisionProvider`，尚未在真实工业 PDF/扫描件与商用/开源 OCR/VLM 模型下完成真实世界资格认定。 |
| **图纸到 Abaqus 求解端到端 Golden** | **READY TO BUILD** | 既有 MBD/Contact/Fatigue/FMBD 等 20 个 L4 物理域均已具备真机闭环；但尚未固化“真实图纸文件 $\to$ 真实感知 $\to$ 3D Grounding $\to$ HITL 确认 $\to$ Abaqus 2025 真实求解 $\to$ ODB 证据”的单一端到端 Canonical Golden。 |

> **关键工程共识：**  
> 软件链路的 100% 单元/集成测试通过，证明了“管道畅通与契约有效”，但绝不能等同于“在带有工业噪声、复杂线型、多重标注重叠的真实工程图纸上具备商业级可用性”。  
> 坚决贯彻 **“基础设施先闭环，真实工程证据再盖戳”** 的质量方针，杜绝将 Mock 测试充当真实多模态验证。

---

## 2. 17 项真实输入矩阵系统评估

本节严格对照工程落地的 17 项真实输入指标，逐一评估当前现状、客观差距与商业化验收合格门禁。

| # | 审计项 | 当前现状与已有能力 | 客观差距 (Gap Analysis) | 商业化合格门禁准则 (Gate Criteria) |
|:---:|:---|:---|:---|:---|
| **1** | **原生矢量 PDF** | 已实现纯 Python 内存解析器（`DocumentIngestionPipeline._parse_pdf_streams`），支持解析 MediaBox、解压缩 FlateDecode 流并提取 `BT...ET` 块及基本文本/坐标。 | 缺乏对复杂工业图纸中 Type0/CIDFont/ToUnicode CMap 映射的支持；对多重 `cm`/`Tm` 复合变换矩阵、路径构造（`m`/`l`/`c`）图元线段解析不足。 | 采用标准矢量引擎（如 `pypdf`/`pymupdf`），对 AutoCAD/SolidWorks 导出的典型机械零件图，文字与坐标解析准确率 $\ge 99\%$，且图框尺寸解析无漂移。 |
| **2** | **扫描 PDF** | 架构上支持通过光栅化转为图像处理，保留 `is_vector=False` 标识及页面原生物理尺寸。 | 当前 `_load_pdf` 仅做了流解析，当 PDF 内无可用矢量流时仅返回默认页面结构，未集成工业级光栅化渲染引擎（如 `pdf2image`/`fitz`）。 | 面对 150~300 DPI 工业灰度/二值化扫描图，光栅化后图像长宽比保真度 100%，无跨页截断，清晰度满足 OCR 识别要求。 |
| **3** | **PNG/JPG 工程图** | `_load_raster_image` 基于 PIL 完整支持 PNG、JPG、TIFF、BMP、WebP，精确提取像素宽高，实现原生像素到归一化 $[0, 1]$ 空间可逆换算。 | 工业手机实拍或网页截图常带有透视倾斜、畸变或不同色深通道，目前缺乏自动倾斜校正（Deskew）与对比度预处理增强。 | 工业常用图像格式加载成功率 100%，宽高比与坐标归一化转换双向往返误差 $\le 10^{-6}$。 |
| **4** | **多页 PDF** | `IngestedPage` 严格绑定 `page_index`，并在 `ObservationProvenance` 中全程透传页面序号与源路径，契约层天然支持多页。 | 既有测试主要针对单页展开；缺乏“第一页为装配总图+材料明细栏，第二页为主视图+局部剖视尺寸”的跨页图纸关联解析逻辑。 | 多页图纸每一页具有完全独立的瞬态观测集与不可篡改的 `page_index` 溯源；跨页引用必须经由 HITL 显式确认关联。 |
| **5** | **中文工程图 (GB/T)** | `RuleBasedVisionProvider` 已内置对“固定”、“固支”、“铰支”、“简支”、“压强”、“压力”、“集中力”、“载荷”、“对称”等中文工程关键词的匹配。 | 尚未覆盖“焊接”、“公称尺寸”、“粗糙度”、“基准代号（A/B/C）”、“热处理要求”及 GB/T 常用材料牌号（如 Q235B、45#、QT400）的图纸自动识别。 | 中文 GB/T 图纸常见边界约束与载荷关键字识别召回率 $\ge 95\%$；材料牌号能正确对接 `MaterialResolver`。 |
| **6** | **英文工程图 (ISO/ANSI)** | 内置支持 `fixed`, `encastre`, `pinned`, `roller`, `pressure`, `force`, `load`, `symmetry` 等 ISO/ANSI 词汇识别。 | 缺乏对 `TYP` (Typical)、`REF` (Reference)、`THRU` (贯通孔)、`MIN/MAX` 等工程缩写和配合代号（如 `H7/g6`）的语义解析。 | 常见 ISO/ANSI 标注模式精确归一化为标准枚举类型，无语义歧义泄漏。 |
| **7** | **尺寸 + 公差** | `DimensionExtractor` 已支持线性尺寸、公差（如 `100 ± 0.05`）、单位（`mm`/`m`/`in`）及标签提取，严格正交解耦。 | 尚未针对直径符号（$\Phi$/$\varnothing$）、半径（R）、球面半径（SR）、倒角（C）及形变位置度等 GD&T 几何公差框格建立结构化模型。 | 线性尺寸数值解析准确率 100%；公差上下限解耦无误；提取出的尺寸能直接驱动参数化几何建模或尺寸验证。 |
| **8** | **集中力箭头** | `BoundaryLoadExtractor` 支持从 `RawSymbolObservation` 抽取 `ARROW` 载荷符号，强制校验非零方向向量与标量幅值。 | 真实的图纸中箭头常为绘制线条图元，依靠纯规则很难直接提取出空间 2D 向量；依赖上游 Vision Provider 提供准确的 `(dx, dy)`。 | 集中力箭头位置 `(x, y)` 误差 $\le 2\%$ 图纸跨度；方向向量必须归一化；零向量或未指定方向 100% 触发阻断拦截。 |
| **9** | **压力/面载荷** | 已支持 `PRESSURE` 符号与文本注法解析，并支持向指定方向（如法向）映射。 | 缺乏对“沿截面线性分布载荷（梯形/三角形水压载荷）”及局部坐标系压强说明的解析支持。 | 均布压力数值与量纲（MPa/Pa/bar）准确归一化为 SI 单位系统；面载荷关联到 CAD 对应面时拓扑匹配明确。 |
| **10** | **力矩/扭矩** | `boundary_load_extractor.py` 已预留 `TORQUE`/`MOMENT` 识别分支，并具备幅值解析能力。 | 弧形旋转箭头（顺时针/逆时针）的符号检测难度高于直线箭头；尚未建立力矩旋转方向与右手法则的映射约定。 | 扭矩/弯矩的数值与旋转轴/方向在 2D 视图中具有确定的符号定义，不确定的情况必须进入 HITL 确认。 |
| **11** | **固定/铰/滚支撑** | 已定义 `FIXED`, `PINNED`, `ROLLER` 标准符号映射，并自动映射到 `CalloutType.BOUNDARY_CONDITION`。 | 缺乏图形学符号模板（如斜剖面阴影线代表大地固支、小圆圈底座代表滚柱支撑）的视觉检测模型。 | 支撑类型与约束自由度（U1, U2, U3, UR1, UR2, UR3）对应明确，无自由度误闭锁或漏约束。 |
| **12** | **多标注同时存在** | 感知管线严格串行编排 `DimensionExtractor` 与 `BoundaryLoadExtractor`，各自独立输出并汇聚，天然支持多标注共存。 | 当尺寸引出线与载荷箭头在同一局部区域交叉重叠时，文本块的就近几何从属判定算法较为简朴，可能出现文本归属错位。 | 在包含 $\ge 10$ 个混合标注的典型图纸中，各标注正交分离率 100%，无尺寸被误判为载荷或反之。 |
| **13** | **标注与 CAD Grounding** | `PerceptionPipeline.correlate_with_cad()` 已无缝衔接 GA-2A `correlate_callout_with_cad()`，支持 `DIMENSION`/`BC`/`LOAD` 全类型反投影。 | 2D 图纸视图视角（俯视图、主视图、等轴测图）与 3D CAD 空间坐标系的对齐矩阵（`ViewProjection`）当前多依赖手工指定或默认视角。 | 标注锚点能以空间距离与法向夹角准确关联到 3D 几何的 Face/Edge/Vertex，候选排序得分 Top-1 具有明确的几何解释。 |
| **14** | **模糊/歧义标注 $\to$ HITL** | `PerceptionConfidence` 包含多维置信度指标，且 `correlate_callout_with_cad` 在低置信度或存在多重候选时触发 `NEEDS_CONFIRMATION`。 | 当前 `has_ambiguous_candidates` 阈值主要采用固定 0.85 策略，未根据高危工况（如高温高压或主受力区域）动态加权调整。 | 任何存在歧义候选几何（Candidate 数量 $> 1$ 且前两名分差 $< 0.15$）或坐标越界的观测，100% 阻断并转入 HITL。 |
| **15** | **错误单位 $\to$ Fail-Closed** | `contracts.py` 与抽取器严格校验单位，无法识别或冲突的量纲拒绝猜测，记录 `RejectedObservation`。 | 缺乏针对工程图纸“未标注尺寸单位按 mm 计、未标注角度按度计”等图纸通则（General Notes）的上下文继承推断机制。 | 遇到非法单位（如 `1000 xx`）绝对禁止默认放行；通用图纸通则必须在图纸标题栏或技术要求明确声明后方可继承。 |
| **16** | **真实 OCR/Vision Provider** | 定义了清晰抽象类 `BaseVisionProvider`，完全解耦了下游逻辑与具体厂商模型；零直接生成脚本保证了模型安全。 | 尚未实现对接真实开源端侧模型（如 PaddleOCR/Qwen2-VL）或商业 API（如 GPT-4o/Claude）的生产级 Adapter。 | 生产级 Adapter 具备超时重试、格式熔断、幻觉清洗与离线降级能力，测试覆盖全部网络异常场景。 |
| **17** | **最终 Abaqus 求解闭环** | P1.0 `solve_requirement()` 已实现与底层 20 个 L4 物理域、Evidence V2 及 Acceptance 门禁的单一出口闭环。 | 缺乏一个串联“图纸图片 $\to$ 真实 Provider $\to$ Grounding $\to$ HITL 确认 $\to$ Abaqus 真实求解 $\to$ 报告”的统一 E2E Golden 脚本。 | 建立标准 Real-Machine Golden Case，在现场真实 Abaqus 2025 环境中执行并通过全部 6 大核心门禁，生成真实 ODB。 |

---

## 3. 真实工程图纸测试集规范 (Benchmark Suite)

为跨越“离线软件通过”到“真实工业可用”的鸿沟，建立三级工业基准图纸样本集（Golden Benchmark Dataset），存放于 `test_assets/drawings/` 目录下：

```
test_assets/drawings/
├── tier1_vector_pdf/
│   ├── GB_bracket_part_drawing.pdf       # GB/T 机械支架（原生矢量，中文，含固定与力标注）
│   ├── ISO_clevis_flange_drawing.pdf      # ISO 轴承法兰（原生矢量，英文，含圆周孔阵与压强）
│   └── ANSI_stepped_shaft_drawing.pdf     # ANSI 阶梯轴（原生矢量，英文，多尺寸公差与扭矩）
├── tier2_scanned_pdf/
│   ├── scanned_cantilever_noisy.pdf      # 200 DPI 工业灰度扫描悬臂梁（轻微旋转 1.5°，印章遮挡）
│   └── scanned_pressure_vessel_multipage.pdf # 2页扫描图纸（P1 技术要求与材料，P2 剖面与载荷）
├── tier3_raster_images/
│   ├── photo_weldment_phone_camera.png    # 工业手机实拍焊接结构（透视变形、反光、红色记号笔标注）
│   └── screenshot_fea_spec_drawing.png    # CAD/CAE 交互界面截图（带标注引出线与位移约束标号）
└── ground_truth/
    ├── GB_bracket_part_drawing.json       # 严格人工标注的标准 Callout 集合与 3D 几何拓扑对应表
    └── ISO_clevis_flange_drawing.json
```

### 3.1 标注真值 (Ground Truth) 格式规范

每个真值 JSON 严格对应真实物理意图：

```json
{
  "source_document": "GB_bracket_part_drawing.pdf",
  "page_index": 0,
  "canonical_cad_model": "test_assets/cad/bracket_part.step",
  "expected_callouts": [
    {
      "callout_type": "BOUNDARY_CONDITION",
      "text": "固定底面",
      "location": [0.25, 0.85],
      "boundary_type": "ENCASTRE",
      "ground_truth_cad_target": "Face_Bottom_Mounting"
    },
    {
      "callout_type": "LOAD",
      "text": "载荷 5000 N",
      "location": [0.75, 0.35],
      "magnitude": 5000.0,
      "unit": "N",
      "direction": [0.0, -1.0],
      "ground_truth_cad_target": "Face_Hole_Inner"
    }
  ],
  "expected_acceptance_criteria": {
    "max_mises_stress_range_mpa": [45.0, 52.0],
    "max_displacement_range_mm": [0.12, 0.15]
  }
}
```

---

## 4. 外部 Vision / OCR Provider 真实适配器规范

为了接入真实的 OCR 与多模态视觉大模型，同时严格遵守已冻结的架构契约，必须实现遵循 `BaseVisionProvider` 的生产级 Adapter。

### 4.1 架构铁律与防护防线

```
+----------------------------------------------------------------+
|                     External Vision Model                      |
|             (Qwen-VL / GPT-4o / Claude / PaddleOCR)            |
+----------------------------------------------------------------+
                               |
                               | (Raw JSON / Markdown / Text)
                               v
+----------------------------------------------------------------+
|                   Production Vision Adapter                    |
|  1. Timeout & Retry Guard (30s timeout, max 2 retries)         |
|  2. Structured JSON Extraction (regex / pydantic normalization)|
|  3. Coordinate In-Bounds Validation (strictly in [0, 1])       |
|  4. Direction Vector Validation (norm > 0, reject zero vector) |
|  5. Hallucination Sanitizer (strip any generated python code)  |
+----------------------------------------------------------------+
                               |
                               | (Emits: RawText / RawSymbol / RawDimension)
                               v
+----------------------------------------------------------------+
|                 P1.1 Perception Core Pipeline                  |
|     contracts.py -> dimension/load extractors -> VisualCallout  |
+----------------------------------------------------------------+
```

### 4.2 适配器安全拦截准则

1. **绝对禁止执行模型输出的代码：**  
   若外部模型返回包含 `import abaqus`、`mdb.models[...]` 或 `findAt(...)` 的内容，适配器立即熔断抛弃，记录 `RejectedObservation(reason="ILLEGAL_CODE_GENERATION_ATTEMPT")`。
2. **严禁静默修复坐标：**  
   若模型给出坐标超出 $[0, 1]$（例如 `x = 1.05`），绝不允许通过 `min(1.0, max(0.0, x))` 截断修正，必须按拒绝处理。
3. **不可靠量纲强制进入安全阻断：**  
   若提取出数值但单位未知或解析出非物理单位，赋予 `unit_confidence = 0.0`，驱动 `MultimodalHITLWorkflow` 阻断。

---

## 5. 真实机端到端 Golden 案例设计蓝图 (Real-Machine Golden Blueprint)

为了彻底完成从“感知基础设施”到“真实图纸+真实求解器”的最后一公里跨越，需设计并建立首个真实图纸端到端黄金标准测试：`tools/p1_drawing_to_odb_golden_e2e.py`。

### 5.1 黄金用例拓扑与工况定义

- **测试对象：** 典型工业 L 型安装支架（L-Bracket），材料为 Q235B 结构钢（$E = 210\,\text{GPa}, \nu = 0.3, \rho = 7850\,\text{kg/m}^3$）。
- **图纸输入：** `test_assets/drawings/tier1_vector_pdf/GB_bracket_part_drawing.pdf`。
  - 标注 1：底座安装面声明“底座固定（Encastre）”。
  - 标注 2：悬臂端圆孔受向下垂直集中力“载荷 5000 N”。
  - 标注 3：技术要求栏声明“材料：Q235B，未注公差按 GB/T 1804-m 执行”。
- **CAD 实体：** `test_assets/cad/bracket_part.step`。

### 5.2 8 步全链路端到端闭环流程

```
[步骤 1: 图纸解析]
GB_bracket_part_drawing.pdf
  --> DocumentIngestionPipeline
  --> IngestedPage (保留原生矢量与坐标转换)

[步骤 2: 视觉抽取]
Real/RuleBased Provider
  --> RawTextObservation + RawSymbolObservation
  --> DimensionExtractor + BoundaryLoadExtractor
  --> 产生 2 个合法的 VisualCallout (BC & Load)

[步骤 3: 3D CAD Grounding]
correlate_callout_with_cad()
  --> 结合 ViewProjection 将 2D 标注反投影至 3D CAD 面
  --> 匹配出 Face_Bottom (固定) 与 Face_Hole (施载)
  --> 生成 GroundingObservation (Candidate 明确，Top-1 评分 > 0.90)

[步骤 4: HITL 门禁审计]
MultimodalHITLWorkflow
  --> 检验综合感知与对齐置信度
  --> 无歧义项自动生成 EngineeringIntent (BC + Load + Material)

[步骤 5: 产品主入口求解]
solve_requirement(intent)
  --> CapabilityResolver 路由至 Linear Static 物理域
  --> ActionCompiler 编译为 ActionPlan
  --> Plan Preflight 预检通过 (100% 规则合规)

[步骤 6: Abaqus 2025 真实求解]
AnalysisRunner
  --> 现场调用 real Abaqus 2025 求解器 (CONN3D2/C3D8R)
  --> 生成真实物理工件: .inp, .odb, .sta, .msg, .dat, .log

[步骤 7: ODB 证据提取与防伪]
EvidenceManifestV2
  --> 提取真实场输出 (S, U, RF, 支反力平衡)
  --> 计算 SHA-256 哈希防篡改绑定

[步骤 8: 严格 Acceptance 裁决]
evaluate_result_acceptance()
  --> Gate 1 (execution) = PASS
  --> Gate 2 (odb) = PASS
  --> Gate 3 (evidence_sufficiency) = PASS
  --> Gate 4 (criteria: 支反力总和 = 5000 N ± 0.1%, 最大 Mises 应力与解析解误差 < 5%) = PASS
  --> EngineeringTaskResult.status = COMPLETED / ACCEPTED
```

---

## 6. 资格认定工作分解与推进路线

根据本审计结论，P1.1 的全面商业化资格认定应分三步有序推进：

```
+-------------------------------------------------------------------------+
| Phase 1: 真实样本与适配器基建 (Current Priority)                          |
| - 固化 3 类典型工业图纸测试样本 (Tier 1/2/3)                             |
| - 实现标准外部 OCR / 视觉模型 Provider Adapter (含熔断与防代码注入)         |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| Phase 2: 真实图纸感知与 Grounding 离线验证套件                            |
| - 编写自动化测试矩阵: 真实样本 -> 视觉抽取 -> CAD 对齐 -> HITL           |
| - 验证中文 GB/T 与英文 ISO 图纸的识别精度与 Fail-Closed 表现              |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| Phase 3: Abaqus 2025 端到端 Real-Machine Golden 闭环                     |
| - 实现 tools/p1_drawing_to_odb_golden_e2e.py                            |
| - 现场求解真实支架模型，生成 machine_validation/ 证据清单                 |
| - 签署 P1.1 真实工程输入 QUALIFIED 终审报告                              |
+-------------------------------------------------------------------------+
```

---

## 7. 审计终审结论总结

1. **软件工程质量极佳：**  
   P1.1 感知架构（分流摄入、正交抽取、多维置信度、严格零容忍坐标校验、与 GA-2A/GA-2B/P1.0 深度融合）已在代码层面完整就绪并通过 739 项严格回归。
2. **商业化落地缺口已精准定位：**  
   核心瓶颈不再是代码结构或求解器对接，而是**工业级复杂矢量 PDF 的完备解析器**、**生产级外部 Vision Provider Adapter** 以及 **首个图纸直达 ODB 的真机端到端 Golden 证据**。
3. **节奏管控建议：**  
   先以本审计确立的 17 项矩阵和合格准则为红线，启动真实样本集与真实机 Golden 准备，不盲目提前开工 P1.2，确保每一步交付的工程物理成果均经得起工业审查。
