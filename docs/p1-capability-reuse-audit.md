# Phase P1 商业产品化现有能力全面盘点与防重复建设审计矩阵
# (Capability Reuse Matrix & Anti-Duplication Audit)

**版本:** 2026-10-04  
**审计基线:** 当前 `main` 真实代码结构与物理验证工件  
**战略目的:** 坚决杜绝从零重复造轮子，精准锁定各需求模块的真实代码资产，明确“已有可复用”、“真实缺口”、“最小新增代码”与“严禁重复建设”边界。

---

## 一、核心审计结论与战略定调

经过对当前仓库 `src/abaqus_ai_agent/`、`tools/`、`tests/` 及 `machine_validation/` 的端到端真实代码核查，得出以下核心结论：

> **Abaqus-AI-Agent 仓库内已经积累了极其丰富且经过真机验证的工程资产。P1 商业产品化绝对不能“推倒重来”或“从零开发”，而必须是针对已有资产的精细组装与前端感知补齐！**

### 关键资产存量盘点事实：
1. **多模态与几何落地 (P1.1 基础)**：
   - 仓库不仅已有 `VisualCallout`、`BlueprintView`、`GroundingObservation`，还拥有完整的 `MultimodalHITLWorkflow` 状态机与 Fail-Closed 门禁；
   - 拥有基于 3D 射线的候选打分拾取器 (`GA-2A`)；
   - 更重要的是：`tools/h6_image_intent_grounding_e2e.py` 早已在**真实 Abaqus/CAE** 上完成物理验证，实现了从 `ImagePoint` 到几何候选、再到原生 `findAt` 表达式和 Set 创建的全链路。
2. **参数推理与澄清 (P1.2 基础)**：
   - `typesafe_intent.py` 内的 `JevIntentRouter` 早已内建物理域分类、单位制判断、参数完整性检测与 `NEEDS_CLARIFICATION` 状态机制；
   - `contracts/material_resolver.py` 已具备严密的单位制转换、环境温度防外推拦截（超过 $50^\circ\text{C}$ 严格阻断 `BLOCKED`）；
   - `contracts/mesh_strategy.py` 与 `mesh_gate.py` 已拥有几何特征网格划分策略与质量门禁，且通过 `tools/mesh_convergence_e2e.py` 拥有真实的 GCI 网格收敛凭证。
3. **成果交付与可视化 (P1.3 基础)**：
   - `reporting/renderer.py` 已经支持单文件独立 HTML 和 Markdown 交付报告的渲染，内嵌样式、图表与 Evidence V2 验签徽标；
   - 验证工件 `machine_validation/static_golden_engineering_report.html` 已是成熟可用的交付样板。
4. **发散诊断与自愈 (P1.4 基础)**：
   - `diagnostics/solver_patterns.py` 已经沉淀了奇异 (`ZERO_PIVOT`)、负特征值 (`NEGATIVE_EIGENVALUE`)、时间步截断 (`CUTBACK_EXCEEDED`) 等经典发散特征的确定性正则库；
   - `analysis_run_diff.py` 已经实现了两个 `AnalysisRun` 之间从 Solver、Intent、Snapshot 到 Metrics、Acceptance 的全方位物理 Diff 算法。

---

## 二、P1 全模块能力复用与审计矩阵 (Capability Reuse Matrix)

下表逐项审计 P1.1 至 P1.4 的原子需求，明确现有代码、测试与凭证，指明真实缺口，划定禁止重复建设的红线：

| 需求代号 | 需求名称 | 现有生产代码资产 | 现有测试与真机证据 | 真实缺口 (Gap) | 最小新增代码动作 | 严格禁止重复建设的模块 (Redline) |
|:---|:---|:---|:---|:---|:---|:---|
| **REQ-P1-010** | 多格式工程图纸/图像摄入 | 无专门摄入管道；仅有基础文件路径操作 | 无 | 缺乏对 PDF（矢量/光栅）、高清 PNG/TIFF 图像的预处理与多图层/瓦片切分 | 新增 `perception/ingestion.py`：实现图像标准化预处理与瓦片切片 | 🛑 严禁重造底层图像格式解析库，直接基于标准库/Pillow/pypdf 处理 |
| **REQ-P1-011** | 工程专业 OCR 与技术规范提取 | `grounding/multimodal.py` 中有基于正则的关键词提取 | `test_ga2b_multimodal_golden.py` 中有文本匹配测试 | 现有逻辑仅能处理上游传来的文本，**缺乏从真实图像像素中进行 OCR 识别的能力** | 新增 `perception/ocr_adapter.py`：调用 Vision/OCR 引擎将图片文字转换为文本行 | 🛑 严禁重写文字语义解析规则，直接对接现有 `parse_drawing_callout` |
| **REQ-P1-012** | 尺寸标注线与公差解析 | 仅在 `VisualCallout` 中有 `magnitude` 与 `unit` 字段 | 无 | 缺乏对工程图纸中尺寸线、箭头、尺寸公差框格的检测与关联 | 新增 `perception/dimension_extractor.py`：提取尺寸数值与公差 | 🛑 严禁新造尺寸数据结构，必须统一封装为 `VisualCallout(type=DIMENSION)` |
| **REQ-P1-013** | 载荷箭头与约束符号解析 | `VisualCallout` 已有 `direction_vector`, `magnitude`, `semantic_intent` | `contracts/multimodal.py` 已有完整数据契约 | 缺乏对图像中受力箭头与约束简图（固定端、铰支座）的视觉识别模型对接 | 新增 `perception/symbol_extractor.py`：识别箭头方向与类型 | 🛑 严禁重造载荷与边界契约，必须直接输出标准的 `VisualCallout` |
| **REQ-P1-014** | 结构化 `VisualCallout` 输出 | `contracts/multimodal.py`<br>`grounding/multimodal.py` 已完全实现 | `test_ga2b_multimodal_golden.py` (661 PASS) | 无架构缺口；仅需将前序提取器输出组装为元组 | 无需新建架构；直接调用已有的 `VisualCallout` 构造器 | 🛑 **绝对禁止重造 VisualCallout 数据类** |
| **REQ-P1-015** | 强制人机协同确认门禁 (HITL) | `MultimodalHITLWorkflow`<br>`HITLStatus`<br>`synthesize_specs` 已完全实现 | `ga2b_multimodal_manifest.json` 真实 Abaqus 闭环认证 | 缺乏轻量交互触发层（当前只能通过代码传决策，缺自动化交互接口） | 仅在工作流层暴露简易交互方法，供 CLI/测试使用 | 🛑 **绝对禁止重写 HITL 状态机与 Fail-Closed 门禁逻辑** |
| **REQ-P1-016** | 视觉防伪与防幻觉红线 | `grounding/multimodal.py` 严格走 `GroundedRegion` 与 `RegionResolver` | `tools/h6_image_intent_grounding_e2e.py` (真实 Abaqus findAt 验证) | 架构已闭环，无物理缺口 | 保持当前架构不变 | 🛑 **绝对禁止允许 Vision 模型直接输出 Abaqus Python 脚本** |
| **REQ-P1-020** | 材料牌号匹配与环境超限预警 | `contracts/material_resolver.py`<br>`adapters/materials/campus.py`<br>`manufacturer.py` | `tests/test_material_resolver.py`<br>`tests/test_campus_adapter.py` | 缺乏中文通用材料别名（如“Q235”、“45号钢”、“304”）快速映射字典 | 新增 `planning/material_alias.py`：补充中国常用材料别名与物性对照表 | 🛑 严禁重写 `MaterialResolver` 的单位转换与温度外推阻断逻辑 |
| **REQ-P1-021** | 透明网格推荐与依据记录 | `contracts/mesh_strategy.py`<br>`planning/mesh_strategy.py`<br>`mesh_gate.py` | `tools/mesh_convergence_e2e.py`<br>`machine_validation/mesh_convergence_e2e.json` | 缺乏“几何壁厚/孔径 $\to$ 推荐网格尺寸并显式记录依据文本”的规则函数 | 新增 `planning/mesh_advisor.py`：实现启发式网格尺寸推荐与依据生成 | 🛑 严禁静默赋予默认网格，严禁重写网格质量检查与 GCI 算法 |
| **REQ-P1-022** | 载荷/约束边界歧义消除 | `typesafe_intent.py` 中已有基础约束完整性检查 | `test_p1_product_solve_golden.py` 中有缺约束拦截 | 缺乏静力学刚体自由度欠约束（Mechanisms）启发式拓扑检查 | 新增 `planning/mechanism_check.py`：检查平动与转动约束完整性 | 🛑 严禁重构主编译器或求解器本身的奇异检测，仅做前置检查 |
| **REQ-P1-023** | 需求澄清标准协议 | `typesafe_intent.py` 中的 `NEEDS_CLARIFICATION` 已有框架 | `test_p1_product_entry_audit.py` (20/20 PASS) | 澄清信息目前多针对自然语言，需扩展支持图纸与参数推理层面的缺失项 | 在 `solve_requirement` 中统一收口缺失项提示信息 | 🛑 严禁抛出未捕获的裸 Python 异常，必须返回标准 `TaskResult` |
| **REQ-P1-030** | 无头自动化 ODB 云图提取 | `contracts/report.py` 中有 `ReportFigure`<br>`machine_validation/` 中有现存云图 | `tools/h1_engineering_report_e2e.py` | 缺乏通用的批处理 Python 脚本，以在无头环境下驱动 Abaqus 导出 PNG | 新增 `reporting/figures.py`：编写无头 ODB 云图导出脚本 | 🛑 严禁使用虚假模拟云图，必须从真实 ODB 中渲染导出 |
| **REQ-P1-031** | 动力学历程曲线与守恒图表 | `contracts/fmbd.py` 中已有能量变量定义 | `tools/fmbd_l4_golden_e2e.py` 已成功提取 ALLIE/ALLKE/ETOTAL | 缺乏从 ODB 历史数据自动调用 Matplotlib 绘制 SVG/PNG 并 Base64 编码的函数 | 在 `reporting/figures.py` 中增加能量历程曲线与 P-u 曲线绘制函数 | 🛑 严禁重造 ODB 历史变量提取逻辑，直接复用现有提取器 |
| **REQ-P1-032** | 独立交付级工程报告生成 | `reporting/renderer.py` 完整支持 HTML/Markdown 报告 | `machine_validation/static_golden_engineering_report.html` | 报告模板需要针对多模态来源（图纸截图）和云图提供更佳的排版槽位 | 微调 `reporting/renderer.py` 的 HTML 模板布局 | 🛑 **绝对禁止重写报告生成引擎与 Evidence V2 验签逻辑** |
| **REQ-P1-040** | 求解器发散特征深度诊断 | `diagnostics/solver_patterns.py` 包含 4 类核心发散正则 | `tools/h5_solver_failure_diagnostics_e2e.py` | 需增加对接触 SDI 震荡与刚度矩阵奇异的更细粒度节点定位 | 扩充 `diagnostics/solver_patterns.py` 中的正则模式 | 🛑 严禁自造发散数据结构，必须复用 `DiagnosticIssue` |
| **REQ-P1-041** | 受控自愈策略库与自动重算 | `AnalysisRunner` 已具备重算基础能力 | 无完整自动自愈重算测试 | 缺乏根据发散诊断结果自动调整 `ActionPlan`（如添加接触阻尼）并触发重算的调度器 | 新增 `healing/doctor.py`：基于诊断结果执行自愈策略编排 | 🛑 严禁隐蔽重算或篡改物理模型，自愈修改必须完全透明并审计 |
| **REQ-P1-042** | 自愈审计追踪与防伪红线 | `analysis_run_diff.py` 完整实现两次 Run 间的物理 Diff | `tests/test_run_diff_and_diagnostics.py` (PASS) | 缺乏将 Diff 结论直接内嵌进工程报告呈现的胶水层 | 将 `AnalysisRunDiff` 结果挂载到 `EngineeringReportData` | 🛑 **绝对禁止重写两次运行的 Diff 比较算法** |

---

## 三、P1.1 极简最小实现清单（避免重复造轮子）

基于上述审计，**P1.1 真实工程多模态输入感知层** 的真实代码实现范围可以极其聚焦、干净，仅需实现一个子包 `src/abaqus_ai_agent/perception/`：

```text
src/abaqus_ai_agent/perception/
├── __init__.py
├── ingestion.py             # 1. 负责 PDF/PNG/JPG 文件读取、图像校验与尺寸归一化 (REQ-P1-010)
├── ocr_adapter.py           # 2. 负责提取图像中的文字、材料标记与技术要求 (REQ-P1-011)
├── symbol_extractor.py      # 3. 负责解析载荷箭头、方向矢量与约束符号 (REQ-P1-012, REQ-P1-013)
└── drawing_pipeline.py      # 4. 组装上述输出，生成标准的 VisualCallout，并调用现有的 correlate_callout_with_cad (REQ-P1-014~016)
```

### 数据流闭环关系（100% 接入现有主干）：
```text
真实工程图纸 (PDF/PNG/JPG)
         │
         ▼
[ perception/ingestion.py ]  ── 图像归一化与切片
         │
         ▼
[ perception/ocr_adapter.py & symbol_extractor.py ]  ── 提取文字/尺寸/箭头/约束
         │
         ▼
生成标准的 Tuple[VisualCallout]  (已有 contracts/multimodal.py)
         │
         ▼
调用现有 correlate_callout_with_cad()  (已有 grounding/multimodal.py)
         │
         ▼
生成标准的 GroundingObservation  (已有 contracts/multimodal.py)
         │
         ▼
送入现有 MultimodalHITLWorkflow  (已有 grounding/multimodal.py，严格门禁)
         │
         ▼
生成现有 IntentBoundarySpec & IntentLoadSpec  (已有 planning/compiler.py)
         │
         ▼
送入现有 solve_requirement()  (P1.0 已闭环主入口)
         │
         ▼
20 L4 物理求解与单出口验收 (100% 复用真实内核)
```

---

## 四、实施纪律与审查红线

1. **红线 1：严禁产生平行数据结构**  
   任何视觉模块输出，必须是 `contracts/multimodal.py` 中的 `VisualCallout`、`BlueprintView` 与 `GroundingObservation`。严禁定义 `CADCallout`、`DrawingEntity`、`VisionResult` 等冗余副本。
2. **红线 2：严禁绕开现有人机协同门禁 (HITL)**  
   多模态解析出的任何候选意图，必须通过 `MultimodalHITLWorkflow` 注册。置信度 $<0.95$ 或存在多重几何候选时，必须强制进入 `NEEDS_CONFIRMATION`，严禁 Agent 替用户拍板。
3. **红线 3：严禁多模态直接出代码**  
   多模态模块的代码职责只到输出结构化意图，绝对禁止直接编写、拼接或生成 Abaqus CAE/Python 脚本。所有求解代码必须由 `compile_intent_to_actions()` 与 `AnalysisRunner` 统一生成。
