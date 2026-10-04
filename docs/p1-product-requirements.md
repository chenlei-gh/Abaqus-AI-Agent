# P1 阶段商业产品化与工程 Agent 需求规范与需求清单 (Product Requirements & Backlog)

**版本:** 2026-10-04  
**基线状态:** 20 L4 / 0 L3 物理工程领域已全部通过真实机全链路合格认证 (Agent Full-Chain Qualified)  
**最新进展:** P1.0 基础设施与产品主入口已完成代码加固与 Post-Hardening 真实 Abaqus 2025 求解器端到端复验（100% QUALIFIED, 726/726 PASS）  
**战略阶段:** Phase P1 — 商业产品化与自主工程智能体 (Commercial Productization & Autonomous Engineering Agent)

---

## 一、战略背景与代码基线现状

### 1.1 核心事实与战略定位转折
经过 Phase A 至 Phase M 以及 Post-RC1 关键战役（GA-2A 空间拾取、GA-F4 疲劳全链路、GA-2B 意图落地与 HITL 协议、GA-C4 机构连接器、GA-M4 刚柔耦合系统），当前仓库真实代码呈现一个核心事实：

> **Abaqus-AI-Agent 不是“缺几个功能”，而是已经建立起一个高度完整、单向防御、经过真机物理验证的后端工程执行闭环；真正缺的是前端工程意图如何自然、可信、免黑盒地进入这条闭环的能力。**

当前系统的后端底座已无可撼动：
- **单一出口防伪门禁**：`AnalysisRunner` + `EvidenceManifestV2` + `evaluate_result_acceptance`，杜绝任何外部假结果或注入数据通往 `ACCEPTED`；
- **真实 Abaqus 2025 求解器闭环**：端到端从 INP 生成、批处理计算、到 ODB 真实场变量张量提取；
- **20 个物理工程领域 L4 认证**：覆盖结构静力、动力学、接触、热力耦合、螺栓预紧、疲劳、机构连接、刚柔耦合（FMBD）等全部声明领域；
- **严格 Fail-Closed**：未知域、几何缺失、材料未定义、边界歧义、证据篡改一律阻断，零伪造、零虚假绿灯。

### 1.2 前置关键战役裁决与边界诚实原则 (Stated Scope Precision)
在推进 P1 商业产品化前，必须对已有基线边界保持高度诚实与客观审视：

| 战役代号 | 核心交付成果 | 真实机验证状态 | 明确边界与当前限制说明 |
|:---|:---|:---:|:---|
| **GA-2A** | 3D 空间拾取与几何着陆 | 🟢 QUALIFIED (631 PASS) | 2D 视口 $\to$ 3D 射线 $\to$ 几何拾取 $\to$ `GroundedRegion` $\to$ `RegionResolver` $\to$ `EngineeringIntent` 主链接入，避免依赖脆弱名字字符串。 |
| **GA-F4** | 高周/低周疲劳 L3 $\to$ L4 晋级 | 🟢 QUALIFIED (Real Abaqus) | 主 Agent 意图驱动；多分析步应力历史提取；Rainflow 计数 + Goodman/Gerber 修正 + Miner 线性累积损伤；Gate 8 疲劳门禁；真实 ODB 凭证。限于声明的高周疲劳与 S-N 范围。 |
| **GA-2B** | 多模态工程意图与 HITL 协议 | 🟢 QUALIFIED (Backend) | 建立 `VisualCallout` $\to$ `GroundingObservation` $\to$ `GroundedRegion` $\to$ HITL 确认 $\to$ Abaqus 2025 闭环。**明确限制：当前视觉感知属于结构化 Callout Ingestion 与规则匹配，真正的图纸/照片 OCR 与多模态 Vision 模型留待 P1.1 攻坚；HITL 目前为协议门禁，尚未开发图形 UI。** |
| **GA-C4** | 运动学连接器 L3 $\to$ L4 晋级 | 🟢 QUALIFIED (Real Abaqus) | 采用专用连接单元 `CONN3D2`；提取 `CU, CTF, CP` 专属相对运动与力指标；Gate 13 机构门禁；8 项负向探针防假通过；不跨越至复杂摩擦塑性损伤全集。 |
| **GA-M4** | 刚柔耦合多体动力学 (FMBD) L4 | 🟢 QUALIFIED (Real Abaqus) | 刚体与柔性体混合拓扑；Gate 14 动力学门禁；真实求解 336 帧；指标严格收口：$\max(\text{ALLSE})/\max(\text{ALLIE})$ 明确为柔性体应变能激活指标，$|\max(\text{ETOTAL})-\min(\text{ETOTAL})|/E_{\text{ref}}$ 明确为数值总能量平衡漂移指标，$\sigma_{\text{mises}} \ge 0.01\text{ MPa}$ 明确为非平凡响应活性探针。 |
| **P1.0** | 统一 Agent 产品主入口 | 🟢 QUALIFIED (Real Abaqus) | `solve_requirement()` 单一生产出口；内部验证注水拦截 (`INJECTION_BLOCKED`)；20 L4 自动化参数化矩阵 (20/20 PASS)；六状态双向强一致性；Post-Hardening 真实机 7 项负向探针全闭环 (726 PASS)。 |

### 1.3 战略聚焦与执行红线
根据最终决议，P1 阶段必须严格坚守以下两条执行红线：
1. 🛑 **坚决不做 UI 工作**：Web 前端、Desktop 界面排在最后的 P1.5，在底层输入感知、推理补全与报告能力成熟前，严禁把精力浪费在写前端界面或页面组件上。
2. 🛑 **绝不再向 20 个物理域堆叠基础 FEA 功能**：物理求解能力已经 100% 达标，禁止横向分散去写新的材料模型或小众单元类型。
3. 🎯 **主线唯一聚焦**：
   $$\text{真实图纸/照片/截图 (PNG/JPG/PDF)} \longrightarrow \text{P1.1 Vision/OCR 感知} \longrightarrow \text{P1.2 参数智能推理} \longrightarrow \text{HITL 确认} \longrightarrow \text{20 L4 稳定执行内核}$$

---

### 1.4 现有能力复用与防重复建设审计原则 (Capability Reuse Matrix)
在启动 P1.1 及后续研发前，全量审计了当前代码库在 Phase A~M 及 Post-RC1 沉淀的大量高成熟度资产（详细审计详见专报 [`docs/p1-capability-reuse-audit.md`](p1-capability-reuse-audit.md)）：
* **P1.1 多模态层**：严禁重写 `VisualCallout`、`GroundingObservation` 及 `MultimodalHITLWorkflow` 状态机；严禁重写 3D 射线拾取与几何候选算法（复用 GA-2A 与 H.6 真实机已验证资产）；**P1.1 唯一任务是补齐最前端的图像/图纸 OCR 与符号提取适配器**。
* **P1.2 推理补全层**：严禁重写 `MaterialResolver` 的单位转换与温度外推阻断逻辑；严禁重构 `JevIntentRouter`；严禁重写网格指标与 GCI 算法；**P1.2 唯一任务是建立常用材料别名字典与网格透明推荐依据记录器**。
* **P1.3 可视化与报告层**：严禁重构 `EngineeringReportData` 与 HTML 报告渲染器；**仅补齐无头 ODB 云图导出脚本与 Matplotlib 动力学能量曲线生成器**。
* **P1.4 求解医生层**：严禁重写发散模式正则库与两次 Run 的物理对比算法（复用 `PATTERNS` 与 `AnalysisRunDiff`）；**仅补齐自愈调度闭环编排器**。

---

## 二、P1 产品需求总矩阵与执行看板

Phase P1 商业产品化采用“系统层解耦、执行层渐进、真实工程可验证”的阶梯推进路线：

```text
               Phase P1: Commercial Productization & Engineering Grounding
                                            │
    ┌───────────────────────────────────────┴───────────────────────────────────────┐
    ▼                                                                               ▼
[ P1.0 Agent 产品主入口 (已完成 🏆) ]                             [ P1.1 真实工程多模态感知 (当前主线 🎯) ]
- solve_requirement() 生产单一出口                                - 机械工程图纸/实物照片/截图 Ingestion
- 20 个 L4 物理域自动化参数化全矩阵 (20/20)                       - 工程 OCR 文本、公差、技术要求提取
- 六状态双向强一致性断言 (Multi-State Equivalence)               - 载荷箭头、约束符号与方向矢量解析
- 内部验证防注水拦截 (Anti-Injection Defense)                     - 结构化 VisualCallout 映射与 HITL 门禁
    │                                                                               │
    └───────────────────────────────────────┬───────────────────────────────────────┘
                                            ▼
                         [ P1.2 工程参数智能推理与补全 (当前主线 🎯) ]
                         - 材料本构中文别名匹配与温度场预警 (MaterialResolver)
                         - 透明网格策略推荐与依据记录 (防 5mm C3D8R 黑盒)
                         - 载荷/约束边界歧义消除与机制未约束检测
                         - NEEDS_CLARIFICATION 交互式澄清协议
                                            │
                                            ▼
                         [ P1.3 交付级多维结果可视化与深度报告 (下一阶段) ]
                         - 无头 ODB 云图提取 (Mises, 位移, 接触压力, 温度)
                         - 动力学能量守恒曲线与载荷-位移历程图
                         - 独立交付级 HTML 工程报告 (内嵌 Base64、Evidence V2)
                                            │
                                            ▼
                         [ P1.4 求解故障智能诊断与自愈 (Solver Doctor) ]
                         - .msg/.sta 发散特征识别 (奇异, SDI 震荡, Cutback)
                         - 受控修复策略库 (接触稳定, 增量步控制, 弱刚度辅助)
                         - 自愈前后 Diff 溯源与物理守恒防伪门禁
                                            │
                                            ▼
                         [ P1.5 商业级工程工作台 (UI/UX - 远期规划) ]
                         - 3D 模型视口拾取交互、HITL 确认卡片、算例资产管理
```

### 需求模块总览表

| 需求代号 | 需求模块名称 | 核心工程目标 | 优先级 | 当前状态 | 牵引测试 / 凭证 |
|:---|:---|:---|:---:|:---:|:---|
| **P1.0** | **Agent 产品主入口** | 自然语言需求 $\to$ 意图编译 $\to$ 20 域能力解析 $\to$ 真实求解 $\to$ 单一出口验收 | **P0 (已收口)** | 🏆 **QUALIFIED** | `tools/p1_product_solve_golden_e2e.py`<br>`tests/test_p1_product_entry_audit.py` (726 PASS) |
| **P1.1** | **真实工程多模态感知** | 工程图纸/现场照片/截图 OCR $\to$ 尺寸/公差/载荷箭头提取 $\to$ `VisualCallout` $\to$ HITL 门禁 | **P0 (当前主线)** | 🚧 **READY TO EXECUTE** | `tests/test_p1_multimodal_ingestion.py`<br>`machine_validation/p1_vision_manifest.json` |
| **P1.2** | **工程参数智能推理** | 缺参识别、材料别名匹配、网格推荐透明化、边界歧义消除、Fail-Closed 澄清交互 | **P0 (当前主线)** | 🚧 **READY TO EXECUTE** | `tests/test_p1_parameter_inference.py` |
| **P1.3** | **交付级多维结果可视化** | 无头 ODB 云图渲染 (S/U/CPRESS/TEMP)、能量曲线、独立 HTML 工程报告与 Evidence V2 徽章 | **P1 (下一阶段)** | 📋 **PLANNED** | `tests/test_p1_headless_visualization.py`<br>`tests/test_p1_report_deliverable.py` |
| **P1.4** | **求解故障智能自愈** | `.msg`/`.sta` 发散解析 (奇异, SDI, Cutback) $\to$ 受控自愈策略 $\to$ Diff 对比与守恒检验 | **P2** | 📋 **PLANNED** | `tests/test_p1_solver_doctor.py` |
| **P1.5** | **商业级工程工作台** | 3D WebGL 视口、HITL 协同卡片、作业队列调度与案例库 (排在最后，不做提前堆砌) | **P2** | 📋 **PLANNED** | 远期规划 |

---

## 三、P1.0 Agent 产品主入口（已收口 & 真实机复验 Qualified）

### 3.1 核心交付与技术契约
P1.0 产品主入口已彻底消除高层自然语言需求与底层 20 个 L4 求解内核之间的断层，完成代码加固与 Post-Hardening 真实求解器端到端复验：
1. **单一出口防伪门禁 (Single-Exit Acceptance)**：
   - 统一入口 `AbaqusAIAgent.solve_requirement()` 不自造第二套验收逻辑；
   - 判定必须强依赖底层 `AnalysisRunner` 最终状态：
     ```python
     is_completed = (
         (run_state == AnalysisRunState.ACCEPTED or str(run_state_val).lower() == "accepted")
         and eng_status in ("ACCEPTED", "RESULT_VALID")
         and bool(getattr(run, "acceptance_passed", False))
     )
     ```
   - 任何 `external_input` 或未通过 ODB 真实凭证验签的计算一律阻断，杜绝假结果变成 `COMPLETED`。
2. **六状态双向强一致性断言 (Multi-State Bidirectional Equivalence)**：
   - 系统级强一致性定理：
     $$\text{TaskStatus.COMPLETED} \iff \text{run.state == ACCEPTED} \iff \text{run.acceptance\_passed} \iff \text{run.acceptance.passed} \iff \text{summary\_card["status"] == COMPLETED}$$
   - 在任何局部状态失败或去同步场景下，所有相关状态同步置为 False / FAILED，杜绝局部假绿灯穿透。
3. **内部验证防注水安全红线 (Anti-Injection Defense)**：
   - 在 `solve_requirement()` 入口处拦截对 `numerical_verification`、`engineering_checks`、`mesh_quality`、`contact_diagnostics`、`connector_kinematics`、`fmbd_dynamics` 等底层内部验证对象的外部注水；
   - 阻断外部或大模型绕过求解器伪造验证结论的途径（强制返回 `status=BLOCKED`, `summary_card["status"]="INJECTION_BLOCKED"`）。
4. **20 个 L4 物理域全矩阵自动化参数化审计 (20/20 PASS)**：
   - 通过 `@pytest.mark.parametrize` 对 `ALL_L4_CAPABILITIES` 中的全部 20 个物理域进行独立 Intent 构造、`resolve_capability()` 映射、`PhysicsResultProfile`（必需字段、必需指标、强制 Gates）绑定、编译器编译及 `solve_requirement()` 运行，确保全域无任何模糊回退或断层。
5. **Post-Hardening 真实 Abaqus 2025 黄金案例端到端复验**：
   - 生产代码加固后，在真实 Abaqus 2025 求解器上执行端到端复验（退出码 0，端部挠度 $2.166\text{ mm}$，最大 Mises 应力 $505.03\text{ MPa}$，全数满足梁理论解）；
   - 重新采集并签署 6 类物理工件（`.inp`, `.odb`, `.sta`, `.msg`, `.dat`, `.log`）SHA-256，固化于 `machine_validation/p1_product_solve_manifest.json`；
   - 7 项负向探针（模糊提示澄清、不支持域拦截、缺几何拦截、缺材料拦截、外部伪造拦截、Preflight 阻断、**内部验证注水拦截**）100% fail-closed。

---

## 四、P1.1 真实工程多模态输入感知层（当前主线 🎯）

### 4.1 业务背景与问题痛点
当前 GA-2B 虽已完成后端闭环，但其视觉输入仍停留在“文本 Callout 规则解析”，无法直接处理工程师提供的实际工程文件（如 CAD 导出的 PDF 图纸、手机拍摄的受力件照片、视口截图）。**P1.1 的核心目标是建立真正的工程图像感知管道。**

### 4.2 子需求分解与技术契约（经 P1.1 实现级审计加固）
详细架构审计与 Provider-Neutral 抽象规范详见专报 [`docs/p1-1-implementation-audit.md`](p1-1-implementation-audit.md)。

#### REQ-P1-010: 多格式工程图纸与图像摄入管道 (Ingestion Pipeline)
- **输入支持**：
  - 工程二维图纸：DWG 导出的矢量/光栅 PDF、高清 PNG/TIFF（支持正交三视图、局部剖视图、局部放大图、标题栏与明细表）；
  - 实物受力照片：现场手机拍摄的结构件照片、测试台架照片（JPG/PNG）；
  - 屏幕视口截图：工程师使用截图工具截取的 CAE/CAD 视口，包含手绘红圈、箭头、文字批注。
- **PDF 矢量优先与光栅化分流 (Vector-First, Raster-Fallback)**：
  - 针对工程 PDF，优先调用矢量解析器提取原生矢量文字流与线段拓扑（100% 保真，无 OCR 模糊与量纲解析失真）；
  - 针对扫描件光栅图纸或三维复杂渲染图，自动以 $300\text{ DPI}$ 高分辨率光栅化为 PNG 图像，再走 Vision/OCR 感知管道；
  - 严格记录页面坐标与空间溯源：`page_number`, `page_box`, `scale_factor`，确保任意 2D 识别均可溯源至原始工程文件。

#### REQ-P1-011: Provider-Neutral 工程专业 OCR 与技术规范提取 (Engineering OCR Engine)
- **Provider-Neutral 抽象适配契约**：
  - 严禁硬编码绑定单一商业 Vision 模型；
  - 定义统一抽象基类 `BaseVisionProvider`，提供离线规则/测试桩实现 (`MockVisionProvider`)，支持生产环境热插拔商用多模态大模型或本地模型；
- **技术要求与说明文字提取**：精准提取标题栏中的零件名称、图号、设计人员，提取技术要求列表（如“未注倒角 C1”、“热处理淬火 HRC 45-50”）；
- **材料牌号自动识别**：精准捕获常见工程材料牌号（如 "Q235-B", "45#", "AL6061-T6", "SUS304", "PA66+30%GF"）；
- **表面粗糙度与焊接代号解析**：识别表面光洁度代号（$\text{Ra } 3.2$）、角焊缝/对接焊缝符号及焊脚尺寸。

#### REQ-P1-012: 几何尺寸标注线与公差解析 (Dimension & Tolerance Parsing)
- **独立解耦的尺寸提取器 (`DimensionExtractor`)**：尺寸属于几何标量度量，与外力/约束物理概念正交，单独解耦处理；
- **尺寸线拓扑识别**：识别尺寸界线、尺寸线、箭头及标注数字；
- **几何特征与跨度关联**：精准提取线性尺寸（长、宽、高、壁厚）、径向尺寸（$\Phi 20$、$\text{R } 10$）、角度尺寸、中心距与孔位阵列（如 $4 \times \Phi 8$ 等距分布）；
- **极限公差识别**：提取形位公差框格（平面度、圆柱度、同轴度、位置度）与尺寸公差（如 $\Phi 50 \text{ H7}(+0.025/0)$），输出标准 `CalloutType.DIMENSION`。

#### REQ-P1-013: 载荷箭头与约束符号矢量解析 (Boundary & Load Extractor)
- **独立解耦的力学提取器 (`BoundaryLoadExtractor`)**：面向工况外力与边界状态；
- **载荷箭头提取**：
  - 识别外力箭头（单向集中力、双向受拉、扭矩双箭头、均布压力箭头线）；
  - 计算 2D 平面方向矢量：沿坐标轴向、法向、与基准线夹角（严格确保模长非零）；
  - 提取载荷幅值与量纲：如 "5 kN", "0.8 MPa", "120 N·m"，并自动归一化到系统标准单位制（如 `MM_N_MPA`），输出 `CalloutType.ARROW`。
- **约束符号识别**：
  - 识别固定端约束符号（网格斜线固定面）、简支铰支座（三角形与滚轴）、对称面代号、螺栓连接符号，输出 `CalloutType.SYMBOL`。

#### REQ-P1-014: 规范化 `VisualCallout` 协议输出与候选生成
- 识别出的所有工程特征，统一定义为强类型 `VisualCallout`（严格匹配现有 `contracts/multimodal.py` 字段）：
  ```python
  @dataclass(frozen=True)
  class VisualCallout:
      callout_id: str                      # 唯一编号
      callout_type: str                    # CalloutType 枚举值 ("ARROW", "TEXT", "DIMENSION", "SYMBOL", "REGION_BOX")
      location: ImagePoint                 # 强类型 ImagePoint(x, y)，坐标严格在 [0.0, 1.0]
      direction_vector: Optional[Tuple[float, float]] = None # 2D 方向矢量，模长非零
      region_box: Optional[ImageRegion] = None # 强类型 ImageRegion(center, width, height)
      text_content: Optional[str] = None   # 原文识别内容，如 "5 kN 垂直向下"
      semantic_intent: Optional[str] = None# 语义枚举，如 "FIXED_SUPPORT", "PRESSURE", "CONCENTRATED_FORCE"
      magnitude: Optional[float] = None    # 标量数值 (如 5000.0)
      unit: Optional[str] = None           # 单位字符串 (如 "N")
      metadata: Dict[str, Any] = field(default_factory=dict)
  ```
- 与 GA-2B `correlate_callout_with_cad` 和 `GroundedRegion` 协议实现 100% 无缝对接。

#### REQ-P1-015: 多维工程置信度评估与强制人机协同确认门禁 (Multi-Dimensional HITL Gate)
- **废弃单一标量阈值**：严禁采用单一粗暴的 `confidence < 0.95`；
- **四维置信度矩阵 (`PerceptionConfidence`)**：
  - `ocr_confidence`: 文字与数值识别可信度；
  - `symbol_confidence`: 箭头与支座几何符号可信度；
  - `unit_confidence`: 量纲一致性与单位合理性可信度；
  - `spatial_alignment_confidence`: 2D 图纸与 3D CAD 空间对齐与候选几何匹配度；
- **Fail-Closed 门禁逻辑**：
  - 存在多重重叠几何候选（如厚度方向两个平行面），或综合置信度低于阈值，或任一关键维度置信度偏低；
  - 必须输出挂起状态 `status=NEEDS_CONFIRMATION`；
  - 明确生成结构化确认决策请求（`HITLConfirmationRequest`），严禁 Agent 私自猜测或替工程师拍板。

#### REQ-P1-016: 视觉防伪与防幻觉铁律 (Anti-Hallucination Redlines)
- 🛑 **绝对红线**：严禁 Vision/多模态模型直接生成 Abaqus CAE/Python 执行代码；
- 🛑 **绝对红线**：所有视觉提取数据必须经过 `VisualCallout` $\to$ `GroundedRegion` 校验，未经验证的几何标记禁止流入编译器。

---

## 五、P1.2 工程参数智能推理与交互补全（当前主线 🎯）

### 5.1 业务背景与问题痛点
工程师在下达工程需求时，往往习惯省略部分低阶或标准决策（例如未指定分析步时长、未声明网格类型、未给出泊松比或仅指定了商用材料家族名称）。**Agent 必须具备工程常识推理能力，同时坚守透明性与防黑盒原则。**

### 5.2 子需求分解与技术契约

#### REQ-P1-020: 工程材料牌号识别与本构参数匹配 (MaterialResolver)
- **多语种与商业牌号别名解析**：支持“45号钢”、“碳钢”、“304不锈钢”、“铝合金”、“黄铜”、“铸铁 HT200”、“POM”、“聚碳酸酯 PC”等自然语言别名匹配；
- **权威材料物性库挂载**：对接受控材料库，提取严格的弹性模量 $E$、泊松比 $\nu$、密度 $\rho$、屈服应力 $\sigma_y$ 与抗拉强度 $R_m$；
- **环境工况校验**：当分析类型包含热或高温环境时，校验材料适用温度区间。若无高温数据，严禁静默使用常温物性，必须发出警告并提示确认。

#### REQ-P1-021: 网格策略透明推荐与依据记录 (Transparent Mesh Recommendation)
- **防黑盒公理**：
  > **系统严禁在无依据的情况下“默默赋予 5mm C3D8R”。**
- **工程启发式推荐规则**：
  - 依据几何模型特征（特征厚度 $t_{\min}$、最小孔径 $d_{\min}$、弯曲变形主导 vs 剪切变形主导）计算推荐网格尺寸：
    $$h_{\text{rec}} = \min\left(\frac{t_{\min}}{3}, \frac{d_{\min}}{4}, \frac{L_{\text{char}}}{20}\right)$$
  - 依据分析物理场推荐单元类型（弯曲主导推荐 C3D20R / C3D8I；大变形塑性与接触推荐 C3D8R 配合沙漏控制；不可压缩材料推荐杂交单元 C3D8H）；
- **透明可追溯记录**：在任务结果 `summary_card` 与工程报告中显式记录推荐依据（如 `“检测到板厚为 3.0mm，按至少3层单元捕捉弯曲应力推荐网格尺寸 1.0mm，单元类型 C3D8I”`）；工程师可一键覆写。

#### REQ-P1-022: 载荷与边界歧义消除 (Ambiguity & Mechanism Detection)
- **刚体位移与机构奇异检测**：
  - 针对静力分析，预先检查三向平动与三向转动自由度约束情况；
  - 若检测到潜在欠约束或滑动面无切向限制，主动提示工程师确认是否添加弱弹簧（Weak Springs）或对称约束。
- **对称面智能建议**：检测到几何与载荷具备 $1/2$ 或 $1/4$ 对称特征时，主动向工程师提议采用对称模型以大幅节约算力。

#### REQ-P1-023: 需求澄清标准协议 (`NEEDS_CLARIFICATION`)
- 当关键物理参数（几何尺寸、材料属性、载荷大小/方向、约束位置）完全缺失或冲突时，严禁抛出未捕获的 Python 异常；
- 必须结构化返回 `status=TaskStatus.NEEDS_CLARIFICATION`，清晰列出缺失字段名、缺失影响、推荐缺省值与选择依据，供用户或上层交互界面展示。

---

## 六、P1.3 交付级工程成果多维可视化与深度报告（下一阶段）

### 6.1 子需求分解与技术契约

#### REQ-P1-030: 无头自动化 ODB 云图提取 (Headless Viewport Rendering)
- 通过原生 Abaqus/CAE 批处理或 ODB API 渲染无头图像（PNG 格式，分辨率不低于 $1920\times 1080$）：
  - **Mises 等效应力云图 (`S, Mises`)**：标注全场最大应力点（Hotspot）坐标、数值及对应单元编号；
  - **位移幅值云图 (`U, Magnitude`)**：显示变形形态（放大系数自适应）与危险变形区域；
  - **接触压力云图 (`CPRESS / COPEN`)**：针对接触问题输出开合状态与接触面压强分布；
  - **温度场云图 (`TEMP`)**：针对热分析输出温度等值线与关键截面热流。

#### REQ-P1-031: 动力学历程曲线与物理守恒图表
- 自动提取并绘制高质量工程曲线：
  - **能量平衡图**：全系统总能量 $\text{ETOTAL}$、内能 $\text{ALLIE}$、动能 $\text{ALLKE}$、伪能 $\text{ALLAE}$ 历程曲线，计算伪能比 $\text{ALLAE}/\text{ALLIE} \le 5\%$ 守恒指标；
  - **载荷-位移历程曲线 (P-u curve)**：提取关键加载点的载荷-变形非线性响应历程；
  - **连接器相对运动曲线**：提取连接器相对转角、相对线位移与连接器受力历程。

#### REQ-P1-032: 交付级独立工程报告 (Deliverable Engineering Report)
- 自动生成单文件独立 HTML 报告（无外部 CDN 依赖，图像内嵌 Base64）：
  - 包含工程需求复述、模型与材料参数、网格统计、载荷边界说明；
  - 包含收敛历程摘要（总迭代步数、Cutback 次数、求解耗时）；
  - 包含云图展示与关键指标结论表格；
  - 包含工程合格性评定结论（安全系数 $SF = \sigma_{\text{yield}}/\sigma_{\max}$、刚度变形校核、疲劳预期寿命）；
  - 包含密码学级 `EvidenceManifestV2` 数字验签徽章（可追溯 INP/ODB 的 SHA-256 与运行 ID）。

---

## 七、P1.4 求解故障智能诊断与自愈闭环 (Solver Doctor)

### 7.1 子需求分解与技术契约

#### REQ-P1-040: 求解器发散特征深度解析 (`.msg`, `.sta`, `.dat`)
- 捕获求解器非零退出码或 Abort 信号，深入解析文本日志：
  - `NUMERICAL_SINGULARITY`：定位出现奇异的节点与自由度编号（DOF 1~6），判定属于刚体位移还是局部单元畸变；
  - `SEVERE_DISCONTINUITY_ITERATION (SDI)`：统计接触迭代震荡次数与未能闭合的从节点集合；
  - `CUTBACK_EXCEEDED`：解析最小时间步长衰减轨迹，定位导致时间步腰斩的关键积分点状态；
  - `PLASTICITY_DRIFT`：定位应变增量过大导致本构无法收敛的单元。

#### REQ-P1-041: 受控自愈策略库与自动修复重算
- 针对接触振荡：自动引入可衰减的接触初始阻尼（Contact Stabilization），并在收敛后严格核查稳定耗能比（$< 2\%$）；
- 针对时间步过小：自动调整初始增量步长、放宽迭代控制参数（`*CONTROLS, PARAMETERS=TIME INCREMENTATION`）；
- 针对网格畸变：定位畸变单元并对其局部区域执行自适应网格加密或细化。

#### REQ-P1-042: 自愈审计追踪与防伪红线
- **完整呈现修复前后 Diff**：工程报告中必须清晰保留 `Run 1 (Initial Failure)` 与 `Run 2 (Healed)` 的对比清单，严禁静默掩盖发散历史；
- **物理守恒门禁检验**：自愈引入的数值稳定项必须经验收门禁确认未扭曲主物理响应（如附加稳定力占总外力比值 $< 1\%$）。

---

## 八、P1.5 商业级工程工作台 (Web / Desktop UI - 远期规划)

### 8.1 规划定位与需求定义
**本模块排在 P1 阶段末期，待 P1.1~P1.4 的 API、协议与能力完全收口后再行启动。**
- **REQ-P1-050: 3D 轻量级视口与面/边直接拾取**：基于 WebGL/Three.js，允许工程师点击几何面生成候选传递给后端 `RegionResolver`；
- **REQ-P1-051: HITL 交互决策卡片**：可视化呈现待确认意图与高亮候选区域；
- **REQ-P1-052: 企业级计算调度与资产库**：集中管理 Abaqus 计算令牌、历史计算算例对比与复用。

---

## 九、完整需求清单与追溯矩阵 (Requirements Traceability Matrix)

下表列出 Phase P1 商业产品化的全部原子需求清单，用于后续开发、PR 审计与交付验收：

| 需求编号 | 需求名称 | 所属模块 | 输入契约 | 输出契约 | 验证层级 | 负向探针 / Fail-Closed 规则 | 当前状态 |
|:---|:---|:---:|:---|:---|:---:|:---|:---:|
| **REQ-P1-001** | `solve_requirement` 统一入口 | P1.0 | 文本 Prompt / Intent | `EngineeringTaskResult` | Tier C | 模糊输入澄清，非法输入拦截 | 🟢 **QUALIFIED** |
| **REQ-P1-002** | 20 L4 物理域全矩阵映射 | P1.0 | 任意物理 Intent | `PhysicsResultProfile` | Tier B | 未知物理域 `UNSUPPORTED` 阻断 | 🟢 **QUALIFIED** |
| **REQ-P1-003** | 单一出口验收与防伪门禁 | P1.0 | 求解过程工件 | `ACCEPTED` / `FAILED` | Tier B | `external_input` 严禁通过验收 | 🟢 **QUALIFIED** |
| **REQ-P1-004** | 内部验证防注水安全红线 | P1.0 | 入口参数 kwargs | `INJECTION_BLOCKED` | Tier B | 外部注水验证对象一律阻断 | 🟢 **QUALIFIED** |
| **REQ-P1-005** | 六状态强一致性双向断言 | P1.0 | 任务执行全状态 | 严格等价布尔值 | Tier B | 任何状态去同步即判定 FAILED | 🟢 **QUALIFIED** |
| **REQ-P1-006** | 真实求解器黄金案例复验 | P1.0 | 悬臂梁需求 | 真实 ODB 与 6 类工件 | Tier A | 7 项负向探针全部 fail-closed | 🟢 **QUALIFIED** |
| **REQ-P1-010** | 多格式工程图纸图像摄入 | P1.1 | PDF/PNG/JPG 文件 | 矢量字符流/高DPI光栅瓦片与坐标 | Tier C | 损坏文件/不支持格式安全报错 | 🚧 **READY** |
| **REQ-P1-011** | Provider-Neutral 工程 OCR | P1.1 | 图像/矢量文字块 | 强类型文本与材料标记候选 | Tier B | 低文字置信度进入待确认 | 🚧 **READY** |
| **REQ-P1-012** | 尺寸标注线与公差解析 | P1.1 | 尺寸线与文字图像 | 尺寸数值、公差、跨度 (DIMENSION) | Tier B | 尺寸冲突或量纲缺失告警 | 🚧 **READY** |
| **REQ-P1-013** | 载荷箭头与约束符号解析 | P1.1 | 箭头与约束图标 | 幅值、方向矢量、约束 (ARROW/SYMBOL)| Tier B | 方向歧义或多候选阻断 | 🚧 **READY** |
| **REQ-P1-014** | 结构化 `VisualCallout` 输出 | P1.1 | 识别结果集 | `Tuple[VisualCallout]` (规范契约) | Tier B | 严格坐标[0,1]与非零矢量校验 | 🚧 **READY** |
| **REQ-P1-015** | 多维置信度人机协同门禁 (HITL) | P1.1 | `VisualCallout` 候选 | `HITLConfirmationRequest` | Tier B | 多候选或多维置信度不达标阻断 | 🚧 **READY** |
| **REQ-P1-016** | 视觉防伪与防幻觉红线 | P1.1 | 模型输出 | 结构化候选数据 | Tier B | 严禁 Vision 直出 Python 脚本 | 🚧 **READY** |
| **REQ-P1-020** | 材料牌号匹配与环境超限预警 | P1.2 | 材料中文别名/工况 | 严格物性参数 / 超限告警 | Tier B | 未知材料拦截，高温超限确认 | 🚧 **READY** |
| **REQ-P1-021** | 透明网格推荐与依据记录 | P1.2 | 几何特征尺寸 | 网格尺寸、单元类型、依据 | Tier B | 严禁无依据默认 5mm C3D8R | 🚧 **READY** |
| **REQ-P1-022** | 载荷/约束边界歧义消除 | P1.2 | 约束与载荷集合 | 欠约束告警、对称面建议 | Tier B | 刚体机构未约束阻断求解 | 🚧 **READY** |
| **REQ-P1-023** | 需求澄清标准协议 | P1.2 | 残缺/冲突需求 | `NEEDS_CLARIFICATION` | Tier B | 明确输出缺失字段与推荐选项 | 🚧 **READY** |
| **REQ-P1-030** | 无头自动化 ODB 云图提取 | P1.3 | 真实 ODB 场变量 | 高清 PNG 云图与 Hotspot | Tier A | 缺失场变量无法生成伪造云图 | 📋 **PLANNED** |
| **REQ-P1-031** | 动力学历程曲线与守恒图表 | P1.3 | 真实 ODB 历史变量 | 能量守恒曲线、P-u 曲线 | Tier A | 伪能比 $>5\%$ 标红阻断 | 📋 **PLANNED** |
| **REQ-P1-032** | 独立交付级工程报告生成 | P1.3 | 任务结果与验签凭证 | 单文件独立 HTML 报告 | Tier B | 验签失败报告显示 TAMPERED | 📋 **PLANNED** |
| **REQ-P1-040** | 求解器发散特征深度诊断 | P1.4 | `.msg`, `.sta` 日志 | 发散根因诊断报告 | Tier A | 无法识别的发散安全退出 | 📋 **PLANNED** |
| **REQ-P1-041** | 受控自愈策略库与自动重算 | P1.4 | 发散诊断结果 | 修复配置与自愈重算 | Tier A | 稳定能量超限即判定自愈无效 | 📋 **PLANNED** |
| **REQ-P1-042** | 自愈审计追踪与防伪红线 | P1.4 | 修复前后两次 Run | 完整 Diff 对比明细 | Tier B | 严禁静默覆盖首次失败记录 | 📋 **PLANNED** |
| **REQ-P1-050** | 3D 轻量级视口与面/边拾取 | P1.5 | 3D 几何模型 | 拾取事件与几何面候选 | Tier C | 拾取越界或歧义安全校验 | 📋 **PLANNED** |
| **REQ-P1-051** | HITL 交互决策卡片界面 | P1.5 | 确认请求对象 | 工程师点击决策与签名 | Tier C | 未确认操作严禁下发后端 | 📋 **PLANNED** |
| **REQ-P1-052** | 企业级调度与案例资产管理 | P1.5 | 批量工程计算任务 | 许可令牌与计算节点分配 | Tier C | 许可抢占与排队超时处理 | 📋 **PLANNED** |

---

## 十、工程质量与防伪铁律（Engineering Redlines）

在推进 Phase P1 商业产品化的全部过程中，全体智能体与开发团队必须绝对坚守以下四项铁律：

1. **零伪造原则 (Zero Fabrication)**：
   严禁使用任何经验公式、模拟数据或虚构数值冒充真实求解器结果。所有物理数据必须由真实 Abaqus 2025 ODB 现场提取，并具备可验证的密码学 SHA-256 签名。
2. **Fail-Closed 闭环原则**：
   在任何环节（参数缺失、拓扑无法解析、网格不合法、求解器发散、证据篡改），系统必须果断阻断并明确进入 `BLOCKED` / `NEEDS_CLARIFICATION` / `RESULT_INVALID`，绝不允许伪装成 `ACCEPTED`。
3. **单一出口原则 (Single-Exit Acceptance)**：
   外部输入、模型修饰、非标准动作脚本严禁直接触碰 `ACCEPTED` 状态。只有经由 `AnalysisRunner` $\to$ `preflight` $\to$ 真实 Abaqus 求解 $\to$ ODB 提取 $\to$ `EvidenceManifestV2` 验签 $\to$ `evaluate_result_acceptance`，才是通往工程合格裁决的唯一合法路径。
4. **范围诚实原则 (Stated Scope Precision)**：
   如实陈述已验证的边界。宣称“20 个物理领域 L4 认证”是指在各领域已声明的物理基准和工程契约范围内达到全链路闭环，严禁夸大为“无限制支持 Abaqus 全部几十万个关键词或任意复杂拓扑”。
