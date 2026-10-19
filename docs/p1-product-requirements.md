# Abaqus-AI-Agent 产品需求总清单与阶段路线

**版本:** 2026-10-04  
**战略定位:** 面向 AI Agent 的工程仿真执行、验证与结果交付基础设施，并逐步演进为可自主完成工程分析任务的 Abaqus Engineering Agent

> **本文件为项目产品需求总清单。** 旧有 P1.x 编号继续作为功能模块编号，但不再与 Phase 1/2/3/4 一一对应。
> **Phase 表示产品成熟度阶段；P1.x 表示功能模块/交付批次。** 因此 P1.4（求解诊断与受控自愈）属于 Phase 3，P1.5（工作台/UI）属于 Phase 4。

---

## 0. 总体产品路线（冻结版）

```text
Phase 1：工程闭环
P1.0 ─ P1.3
        ↓
“能从需求做到可信结果”
        ✅ COMPLETED

Phase 2：工程能力深度
Fatigue / Connector / FMBD
+ 更多真实工程场景
+ 10 个复杂真实工程问题全链路实战
        ↓
“能处理足够多的真实问题”
        🎯 CURRENT FINAL TARGET

==============================
Phase 2 完成后 → Engineering Kernel Freeze
==============================

Phase 3：Agent 自主性
        📋 POST-FREEZE ROADMAP

Phase 4：产品化
        📋 POST-FREEZE ROADMAP

Phase 3：Agent 自主性
规划 / 澄清 / 迭代 / 诊断 / 对比 / 优化
        ↓
“工程师可以把任务交给它”
        🔄 STARTED

Phase 4：产品化
MCP / UI / 部署 / Benchmark / Release
        ↓
“真正成为可使用的产品”
        📋 PLANNED
```

### 0.1 Phase 与功能模块的关系

| Phase | 产品目标 | 当前核心模块 | 状态 |
|---|---|---|---|
| **Phase 1** | 从需求做到可信结果 | P1.0 / P1.1 / P1.2 / P1.3 | 🟢 **COMPLETED** |
| **Phase 2** | 扩大真实工程问题覆盖与组合深度 | Fatigue / Connector / FMBD / 更多真实工程场景 | 🟡 **IN PROGRESS** |
| **Phase 3** | 让 Agent 能自主规划、执行、诊断、迭代与比较 | 规划 / 澄清 / 迭代 / P1.4 诊断自愈 / 对比 / 优化 | ⚪ **POST-FREEZE ROADMAP** |
| **Phase 4** | 让工程师能够稳定、方便地实际使用 | MCP / UI / 部署 / Benchmark / Release | ⚪ **POST-FREEZE ROADMAP** |

### 0.2 当前已正式闭环的能力

- P1.0 Agent 统一工程入口：QUALIFIED
- P1.1 工程多模态感知与 Grounding：QUALIFIED；Provider-Neutral 架构保持不变，真正外部 Vision/OCR 商用模型适配属于后续扩展边界
- P1.2 工程意图推理与参数补全：QUALIFIED
- P1.3 Result Intelligence 与工程报告交付：QUALIFIED
- Fatigue：L4 QUALIFIED
- Connector：L4 QUALIFIED
- FMBD：L4 QUALIFIED
- P1.4 求解器失败诊断与受控自愈：已完成实现与真实机 Golden E2E，作为 Phase 3「诊断 / 迭代」能力推进
- 全项目继续遵守 Evidence V2、Single-Exit Acceptance、Fail-Closed、Zero Fabrication 与 Stated Scope Precision。

### 0.3 Phase 2 的边界与双工作包架构

Phase 2 **不是重新堆叠大量 Abaqus 关键词或无限增加物理域**。已有 20 L4 物理域是底座。Phase 2 整体划分为两个边界明确的工作包：

```text
PHASE 2：工程能力深度与真实复杂工程实战
│
├── Package A：工程能力完善与组合验证
│   ├── Fatigue / Connector / FMBD 核心能力收口
│   ├── 20 L4 物理域交叉组合验证（Thermal→Structural, Preload→Static, Contact+Nonlinear 等）
│   ├── Phase 2 Golden Matrix 矩阵（正负向、Fail-Closed、Evidence、Acceptance）
│   └── 证明：“工程内核能力已经足够完整，而且能够自由组合”
│
└── Package B：10 个真实复杂工程项目正式实战
    ├── 10 个公开经典工业问题包导入（Problem Import）
    ├── Agent 需求意图建立与自动化模型编译（Intent → Compiler → Preflight）
    ├── 真实 Abaqus 2025 真机求解与全套求解日志保留
    ├── 独立 Result Intelligence 与 Single-Exit Acceptance 验收
    ├── 独立交付级工程报告与可审计签名凭证（Report + Manifest）
    └── 证明：“Agent 能真正接手工业级真实复杂工程问题并完成闭环交付”
```

**Phase 2 冻结准则：** `Package A (QUALIFIED) + Package B (10/10 QUALIFIED)` $\to$ **Phase 2 COMPLETE** $\to$ **Engineering Kernel FREEZE**。未完成前不得提前宣布冻结。

### 0.4 Phase 3 的边界

Phase 3 的核心不是再增加底层 Abaqus API，而是让 Agent 能完成闭环任务：

```text
工程师需求 → 需求规划 → 缺失信息识别/主动澄清 → 分析计划 → 执行
→ 结果检查 → 失败诊断/受控迭代 → 多方案比较 → 必要时优化
→ 重新验证 → 工程交付
```

P1.4 属于其中的**诊断 / 迭代**能力。

### 0.5 Phase 4 的边界

Phase 4 才开始正式产品化：MCP / Agent Tool、UI / HITL 工作台、部署、Benchmark、Release。

**在 Phase 4 前不提前堆叠 UI。**

---
# P1 阶段商业产品化与工程 Agent 需求规范与需求清单 (Product Requirements & Backlog)

**版本:** 2026-10-04  
**基线状态:** 20 L4 / 0 L3 物理工程领域已全部通过真实机全链路合格认证 (Agent Full-Chain Qualified)  
**最新进展:** 全仓 1516 项自动化回归测试 100% 通过（0 失败，`pytest -W error`，exit 0，基线 commit `55a3c9e`）；Phase 2 Package B 工业级实战案例已达成 6/10 QUALIFIED（Case 01~06 内容摘要与断言验证闭环。无密钥 SHA-256 不是身份签名），Case 07 的输入资产与负向探针已落地、求解证据待真机  
**战略阶段:** Phase 2 — 工程能力深度与真实复杂工程实战 (Package B 案例攻坚)

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
* **P1.1 多模态层（Phase 1）**：严禁重写 `VisualCallout`、`GroundingObservation` 及 `MultimodalHITLWorkflow` 状态机；严禁重写 3D 射线拾取与几何候选算法（复用 GA-2A 与 H.6 真实机已验证资产）；**P1.1 唯一任务是补齐最前端的图像/图纸 OCR 与符号提取适配器**。
* **P1.2 推理补全层（Phase 1）**：严禁重写 `MaterialResolver` 的单位转换与温度外推阻断逻辑；严禁无依据重写既有能力，允许为满足供应商中立与工程解耦契约进行受控演进；严禁重写网格指标与 GCI 算法；**P1.2 唯一任务是建立常用材料别名字典与网格透明推荐依据记录器**。
* **P1.3 可视化与报告层（Phase 1）**：严禁重构 `EngineeringReportData` 与 HTML 报告渲染器；**仅补齐无头 ODB 云图导出脚本与 Matplotlib 动力学能量曲线生成器**。
* **P1.4 求解医生层（Phase 3：诊断 / 迭代）**：严禁重写发散模式正则库与两次 Run 的物理对比算法（复用 `PATTERNS` 与 `AnalysisRunDiff`）；**仅补齐自愈调度闭环编排器**。

---

## 二、P1 产品需求总矩阵与执行看板

当前 P1.x 仍作为功能模块编号；产品成熟度阶段以第 0 章 Phase 1~4 总路线为准。P1.x 详细需求继续采用“系统层解耦、执行层渐进、真实工程可验证”的方式维护：

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
| **P1.1** | **真实工程多模态感知** | 工程图纸/现场照片/截图感知 → Grounding → HITL | **P0 (Phase 1)** | 🟢 **QUALIFIED** | `tools/p1_drawing_to_odb_golden_e2e.py`<br>756+ 严格回归 |
| **P1.2** | **工程参数智能推理** | 缺参识别、材料别名、网格推荐、边界合理性、HITL | **P0 (Phase 1)** | 🟢 **QUALIFIED** | `tools/p1_2_reasoning_qualification_e2e.py`<br>791 严格回归 |
| **P1.3** | **Result Intelligence 与工程报告** | ODB 结果、曲线、派生指标、热点、SVG、HTML/MD 报告 | **P0 (Phase 1)** | 🟢 **QUALIFIED** | `tools/p1_3_result_delivery_golden_e2e.py`<br>804 严格回归 |
| **P1.4** | **求解故障诊断与受控自愈** | 诊断 → 有界 remediation → 重算 → RunDiff → Acceptance | **P0 (Phase 3)** | 🟢 **QUALIFIED / Phase 3 STARTED** | `tools/p1_4_self_healing_golden_e2e.py`<br>820 严格回归 |
| **P1.5** | **商业级工程工作台** | 3D 视口、HITL 卡片、作业与资产管理 | **Phase 4** | ⚪ **PLANNED** | 远期产品化需求 |

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

#### REQ-P1-033: 原生静默无头动画渲染与单文件 HTML 即开即播 (方案 A 闭环)
- 调度真实 `abaqus viewer -noGUI` 后台无头渲染，从物理 ODB 导出变形/应力时程序列帧并由 PIL 自适应调色板（Adaptive Palette）合成高保真 GIF 动图；
- 动图自动转换为 Base64 Data URI 原生内嵌至单文件独立 HTML 报告，带有 `[Abaqus 原生仿真动图 / Simulation Animation]` 官方标注，离线免依赖开箱即播；
- 动力学与 MBD 工况默认开启物理单向时程循环播放（`loop=0`），杜绝倒放 ping-pong；静力学工况支持往复平滑变形动画；
- 变更范围严格收敛于核心仓库，外围工程项目保持物理隔离与暂不调整。

---

## 六.1 P1.4 资产完整性、外部项目隔离与受控模型编辑 (Asset Integrity & Controlled Editing)

### 6.1.1 子需求分解与技术契约

#### REQ-P1-035: 报告图片受控解析与同名回退收敛
- 彻底移除对 `machine_validation/`、`test_assets/` 及全局同名模糊搜索，严防拿历史同名测试图片冒充本次工程仿真成果；
- 正式报告仅接受明确绑定的绝对路径或相对于交付目录的路径，图片缺失时展示受控占位符，阻断静默错配。

#### REQ-P1-036: 生产执行外部项目上下文强制校验
- 生产环境强制提供合法、隔离的 `ExternalProjectContext`；
- 严禁生产求解静默写入仓库内部 `runs/` 或 `deliverables/`，工作目录、求解目录与交付目录全链路物理外置隔离。

#### REQ-P1-037: 动图双模态保真与抽样末帧保全
- 明确区分“忠实时程动画 (`full_timeline`)”与“活跃演示动画 (`active_presentation`)”；
- 忠实时程保留全物理时间步与平衡阶段，动态裁剪需保留审计元数据；
- 帧序列重采样严格保全首帧与关键末帧，严禁切片截断丢失最终变形状态。

#### REQ-P1-038: 用户已有模型 (CAE/INP/ODB) 输入保护通道
- 原生执行用户 `.inp`，杜绝无谓的 Python 重复几何与网格建模；
- 纯只读后处理用户 `.odb`，严禁隐式重新提交求解器；
- 导入用户 `.cae` 时建立独立工作副本（`working/`），原模型文件强制只读保护，同名不同内容哈希归档防覆盖。

#### REQ-P1-039: 受控 INP 结构化参数编辑与版本审计 (Controlled INP Structural Editing)
- **零原地修改红线**：源 INP 文件严格只读，编辑过程与保存校验源文件 SHA-256 不变，严禁在原文件上直接覆盖；
- **四类参数级受控手术式编辑**：支持材料参数（如 `*ELASTIC`, `*PLASTIC`）、分析步时间增量（如 `*STATIC`）、载荷/边界条件（如 `*CLOAD`）、场/历史输出请求（如 `*ELEMENT OUTPUT`）；
- **保留原始结构与排版**：保留所有注释行（`**`）、关键字块顺序及无关数据行，禁止破坏性重写；
- **审计追踪与 Diff 闭环**：生成 Unified Diff 与修改前/后双向 SHA-256 审计记录（`InpEditAuditRecord`）；
- **执行闭环与严谨状态**：修改后写入工作副本并在外部项目 `solver/` 隔离执行，非零退出码、异常崩溃或缺失有效 ODB 坚决判定 `FAILED`。

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
- 针对接触振荡：自动引入可衰减的接触初始阻尼（Contact Stabilization），并在收敛后按显式配置的稳定耗能比阈值核查（`ALLSD/ALLSE`，**不设内置默认值**，未配置即阻断）；
- 针对时间步过小：自动调整初始增量步长、放宽迭代控制参数（`*CONTROLS, PARAMETERS=TIME INCREMENTATION`）；
- 针对网格畸变：定位畸变单元并对其局部区域执行自适应网格加密或细化。

> 实现状态（P0-b 真机闭环，2026-10-19）：接触稳定化已接入 `StdContactControl` + `*CONTACT CONTROLS`，不再混入 `step_controls`；稳定化能量契约见 `contracts/stabilization_energy.py`。阈值为工程策略，必须由调用方显式给出并记录来源。能量门禁按 deck 关键词解析出**唯一**启用稳定化的分析步并在该步上取证：多步均启用、关键词落在 `*STEP` 块之外、或该步在 ODB 中不存在，一律 `BLOCKED`，不得借用其他步的能量数据；`ALLSD`/`ALLSE` 时间序列无法逐帧对齐同样阻断。
>
> **真机结论（Abaqus/Standard 2025，本机实测）**：
> - 编译器现会在稳定化步显式请求 `ALLSD/ALLSE`（`H-Energy-Stabilization`），否则该门禁永远缺少证据。
> - 接触振荡修复路径已可从未收敛作业触达：`CONTACT_CHATTER` 现按 Abaqus 2025 实际措辞（`POINTS CHANGED FROM ...`）匹配，并**以失败证据为前置条件**（收敛作业同样会打印少量该行，纯文本匹配必然误报；`.sta` 显示成功完成时否决该诊断）。
> - **新增 `CONTACT_OPENING`（本轮修复）**：真实的接触闭合失败（配合面尚未贴合）在 `.msg` 中表现为成百上千条 `NUMERICAL SINGULARITY WHEN PROCESSING NODE ...`，而 `POINTS CHANGED FROM` 计数为 **0**。仅靠 `CONTACT_CHATTER` 时，此类失败只会被诊断为 `ZERO_PIVOT`/`NUMERICAL_SINGULARITY`，修复建议因此落到 `ENCASTRE`（会锁死本应运动的零件），接触稳定化**从不被选中**。现该诊断以「作业确实失败」+「模型确实定义了接触对」为双重前置，命中后映射到 `CONTACT_STABILIZATION`；两者同时命中时以更具体的 `CONTACT_CHATTER` 命名动作，且只产出一条接触修复。
> - **接触模型证据分层（本轮加固）**：`CONTACT_OPENING` 不再依赖 deck 文本单一来源。证据按 deck → `.msg` 的 `CONTACT CONTROLS APPLIED TO ALL CONTACT PAIRS:`/`... TO CONTACT PAIR (...)` → `.dat` 的 `*contactpair` 回显或 `NUMBER OF INTERNAL ELEMENTS GENERATED FOR CONTACT` 非零值依次解析，命中层记录在 `metadata.contact_model_source`。实测依据：无接触模型的 `.msg` 同样打印 3 条通用接触容差行（`SOFT CONTACT CONSTRAINT COMPATIBILITY TOLERANCE` 等），因此不得以 `contact` 关键词判定；`*contactcontrols` 回显被**排除**，因为那正是修复自身写入的卡，纳入即构成循环论证。三层均无证据时仍**抑制**，退回旧诊断。同时修复了编排器只保留 `.dat` 末 100 行导致接触证据不可达的缺陷（改为头尾各 100 行窗口）。
> - **闭环实测（通过）**：滑块与基块之间存在初始间隙、贴合前切向与法向均无刚度。无稳定化的三个算例全部 `THE ANALYSIS HAS NOT BEEN COMPLETED`（`NUMERICAL SINGULARITY`、`TOO MANY ATTEMPTS`）；加入接触稳定化后全部 `COMPLETED SUCCESSFULLY`，能量全程有限，门禁在 5% 策略下全部 `PASS`（实测逐帧最大 `ALLSD/ALLSE`：3.6e-6、1.4e-4、8.7e-4、8.5e-4、5.4e-3）。
> - **步归属不再要求调用方重述**：`resolve_contact_stabilization` 本就在候选步唯一时完成绑定、在多步时 fail-closed；此前脚本生成段会丢弃该决定并报错，导致产品自己产出的修复无法编译。现将已解析的 `target_step` 回填，Initial 步创建的接触在**唯一**隐式步下可自动绑定；多步仍强制显式指定，不做任何推测。
> - **门禁语义确认**：`ALLSD` 为累积量而 `ALLSE` 为瞬时量，逐帧最大值由最早的有效帧主导。0.4 mm 间隙算例首帧 34.5%、末帧 8.4e-6，门禁按契约判 `FAIL`——这是刻意保守，不是缺陷；其含义是「早期人工阻尼已不可忽略」，不得据此宣称修复在物理上无损。
> - **前一轮结论更正**：此前记录的「NaN 由 `stabilize` 本身引起」不成立。单变量对照显示首个位移修正量在**无控制卡、仅 `*CONTACT CONTROLS` 不加 `stabilize`、`dampFactor` 从 1e-2 到 1e-8、全自动阻尼、分析步级稳定化**各变体下完全相同（`-20.8 @ node 21 dof 2`），且**不加稳定化的同款 deck 同样产出 NaN**；CAE 写回的 `*Contact Controls` 语法与手写一致。根因是捕获的 F1 模型数值病态（滑块无切向约束、4e6 N 压在 20×20 mm 上），该 deck 不再用作关于稳定化的证据。

#### REQ-P1-042: 自愈审计追踪与防伪红线
- **完整呈现修复前后 Diff**：工程报告中必须清晰保留 `Run 1 (Initial Failure)` 与 `Run 2 (Healed)` 的对比清单，严禁静默掩盖发散历史；
- **物理守恒门禁检验**：自愈引入的数值稳定项必须经验收门禁确认未扭曲主物理响应。静力自动稳定化以 `ALLSD/ALLSE` 逐帧最大比值对照显式阈值判定；动态能量平衡属于另一类契约，不得混用同一阈值。
- **退化解红线（本轮修复）**：Abaqus 可能对数值发散的作业仍报 `COMPLETED SUCCESSFULLY` 并写出 `NaN` 场。ODB 校验现增加退化解判据——核心场（`U/UT/UR/S/RF/RM`）有限值占比低于 50%，或某帧所有含数据的场均非有限，即判 `verified=False` 并阻断交付；此前仅校验二进制结构与网格，`NaN` 结果可被判为 `PASS/VALID`。

#### REQ-P1-054: 瞬态动态能量平衡契约（独立于静力稳定化）
- **指标定义（显式裁定，不在运行时推断）**：
  - `E_ref = max over frames of max(|ALLIE|, |ALLKE|, |ALLWK|)`
  - `r = max over frames of (|ETOTAL| / E_ref)`
  - 使用 `ETOTAL` 的**绝对值**作为残差：区间指标（`max−min`）在大残差近乎恒定时会误报为守恒。`E_ref` 取三者最大值而非单一分量，避免某个动能安静的帧压缩分母并制造失败。`ETOTAL` 自身**不计入** `E_ref`，否则大失衡会抬高测量它的分母。
- **恒等式校验**：逐帧验证 `ETOTAL = ALLIE + ALLKE − ALLWK`，容差**相对该帧自身能量尺度**（`1e-3`）。使用绝对下限会让容差在不同单位制下含义漂移：对焦耳量级模型，`1e-3` 下限等于默许 `1e3` 的绝对误差。违反即 `BLOCKED`，不得只采信单一残差数字。
- **求解器产品与阈值均由调用方声明**：`solver_product ∈ {standard, explicit}`；阈值无内置默认值。隐式与显式积分的耗散/累积机制不同，**不得默认共用同一阈值**（Jev 0.45，故按产品分别声明）。
- **状态语义**：`PASS` / `FAIL`（物理违反）/ `BLOCKED`（证据缺失、非有限、时间序列无法对齐、恒等式违反、全零参考）/ `INCOMPLETE`（确实测到了东西但可测残差帧不足两帧）/ `SKIPPED`（非动态分析）。`INCOMPLETE` 与 `BLOCKED` 同属阻断交付，但分开记录。
- **可测帧口径**：残差低于 `1e-12 × E_ref` 的帧（实践中即 `t = 0`）不参与漂移趋势判定——两帧全空互相吻合不构成守恒测量。
- **多步归属**：只有一个非 Initial 分析步时视为唯一目标步；多步时**必须**由调用方指定 `dynamic_energy_step`，缺失或歧义一律 `BLOCKED`。**不得**假定最后一个分析步就是关注事件。
- **门禁接入**：`acceptance.py` 新增 Gate 11c `dynamic_energy`。`FAIL` → 物理失败；`BLOCKED`/`INCOMPLETE` → 阻断且不可交付；`SKIPPED` → 不影响其余门禁。
- **范围（opt-in，Jev 0.74）**：门禁由调用方显式开启并给出阈值。未请求时 `SKIPPED`，不得对未声明策略的动态工作流施加未声明的约束。

> 实现状态（2026-10-19，真实机验证完成，契约未宣告闭合）：
> - 契约：`contracts/dynamic_energy.py`；门禁：`acceptance.py` Gate 11c；编排：`AnalysisRunner._evaluate_dynamic_energy_gate`；取证：`execution/odb.extract_energy_evidence` 现请求 `ETOTAL`；`DYNAMIC_IMPLICIT` 后处理 profile 现请求 `ALLIE/ALLKE/ALLWK/ETOTAL`（否则该门禁永远缺少证据）。
> - **真实机实测（Abaqus/Standard 2025，本机）**：现场新建并求解悬臂梁瞬态隐式动力学算例，`.sta` 报 `THE ANALYSIS HAS COMPLETED SUCCESSFULLY`；经产品自身提取器读回 `ALLIE/ALLKE/ALLWK/ALLSE/ETOTAL` 全部存在。`E_ref = 96849.47`、`max|ETOTAL| = 265.83`、`r = 2.7448e-3`、恒等式偏差 `6.24e-3` 绝对（相对 `6.4e-8`）。同一数据：1% 策略 → `PASS` 且可交付；`1e-4` 策略 → `FAIL`；缺 `ETOTAL` → `BLOCKED`；单帧 → `INCOMPLETE` 且阻断；未请求门禁 → `SKIPPED` 且不影响验收。
> - **真实数据暴露并修复的两个缺陷**：① 恒等式容差曾锚定 `max(reference, 1.0)`，在焦耳量级模型里等于默许 `1e3` 绝对误差，已改为逐帧相对尺度；② 零残差帧曾被计入「信息帧」，使只有一次真实测量的历史也能满足两帧门槛，现单独计数且不计入趋势判定。
> - **未验证项（不得宣称闭合）**：显式产品阈值未做真机验证；多步动态步归属仅有离线测试；仅一种悬臂构型，不能外推。Jev 终审 `may_declare_dynamic_contract_closed = 0.52`，`residual_risk = medium`，`next_action = explicit_dynamic_case`。
> - 证据：`machine_validation/dynamic_energy_balance.json`。
> - **显式产品真机验证（Abaqus/Explicit 2025，本机，2026-10-19）**：现场新建并求解悬臂实体显式动力学算例（C3D8R/EXPLICIT，`ExplicitDynamicsStep`，0.002 s，201 帧历史）。**关键事实**：显式求解器同样写出 `ETOTAL` 与 `ALLWK`（`ALLAE/ALLCD/ALLFD/ALLIE/ALLKE/ALLPD/ALLSE` 亦在），此前「显式 ODB 可能没有 `ETOTAL`」的不确定点由实测排除。`E_ref = 22520.28`、`max|ETOTAL| = 0.2002`、`r = 8.8911e-6`；逐帧恒等式相对偏差峰值 `2.51e-4 < 1e-3`，201 帧全部成立——Jev 在测量前对该恒等式适用性置信度仅 `0.21`（`0.47` vs `0.46` 分裂），此处以真实求解器输出裁决，而非按概率择一。同一数据：1% 显式策略 → `PASS` 且 `deliverable=true`；`1e-6` 策略 → `FAIL` 且不可交付；缺 `ETOTAL` → `BLOCKED`（**不得**用 `ALLIE+ALLKE−ALLWK` 自行合成冒充）；单信息帧 → `INCOMPLETE` 且阻断；缺阈值 / 缺 `solver_product` → 各自 `BLOCKED`。
> - **本轮修复的真实缺陷**：`contracts/postprocess.py` 的 `DYNAMIC_EXPLICIT` 与 `QUASI_STATIC_EXPLICIT` 后处理 profile 只请求 `ALLIE/ALLKE/ETOTAL`，**遗漏 `ALLWK`**。后果是规划器生成的显式 deck 必然缺少契约强制要求的证据，显式分支永远只能 `BLOCKED`，不可能 `PASS`。两处均已补齐为 `ALLIE/ALLKE/ALLWK/ETOTAL`（Jev `fix_profile_to_request_allwk`，置信度 `0.94`）。
> - **显式阈值独立性**：显式策略阈值单独声明（Jev `separate_threshold_required`，置信度 `1.0`）。本次取值与隐式策略数值相同，但这是本构型的工程选择，契约模块仍无任何内置默认值。
> - 证据：`machine_validation/explicit_dynamic_energy_balance.json`；回归：`tests/test_explicit_dynamic_energy.py`。
> - **仍未验证（不得外推）**：准静态显式（`QUASI_STATIC_EXPLICIT`）的动能/内能比属于独立工程门禁，本次未验证；显式漂移阈值的通用性未建立；单一构型，不能外推为全局结论。Jev `explicit_closure_sufficiency = 0.15`，即「单次真机 + 同源负向控制」不足以宣告整个显式分支工程闭合。

#### REQ-P1-055: 几何清理策略全入口强制（fail-closed）
- **背景（本轮发现的真实缺陷）**：`contracts/geometry_cleanup.py` 声明了 `GeometryCleanupPolicy(allow_repair=False, allow_virtual_topology=False)`，但全仓库**没有任何地方读取该策略**——`grep` 仅命中定义本身。默认拒绝声明形同虚设，`part.repairGeometry()`、`part.removeRedundantEntities()`（两者在 2025 中均**不存在**）、`part.ignoreEntity()` 均可经由 Action 或 `python` 逃生通道直接执行。
- **单一 choke point（Jev `single_choke_point_before_script_generation`，置信度 `1.0`）**：策略在 `actions/script.action_to_script()` 入口处强制执行。`actions/runner`、`agent.py`、`execution/analysis_run.py`、`planning/compiler.py`、`capability_boundary.classify_action()` 全部经由该函数，因此由构造保证覆盖，而不是逐入口补丁（逐入口必然遗漏）。
- **默认拒绝且可审计（Jev `explicit_policy_defaults_to_deny`，置信度 `0.97`）**：调用方未提供策略时，合成 `GeometryCleanupPolicySet.default()`（`part='*'`、拒绝修复与虚拓扑），并在违规载荷中以 `policy_is_default=true` 记录「这是默认值」，不做静默放行。
- **最严原则**：同一 part 命中多条策略时取最严（`allow_*` 取 `and`），新增策略不可能意外放宽权限。未知 part 不落入开放态。
- **逃生通道不可洗白修复（Jev `python_action_cannot_discharge_repair_policy`，置信度 `0.92`）**：`python` Action 的文本筛查（`repair` / `removeInvalidGeometry` / `CreateHealedPart` / `writeHealedPart` / `ignoreEntity` / `restoreIgnoredEntity` / `createVirtualTopology`）**能证明违规，不能证明合规**，因此只作为廉价前置检查，不得被记录为修复证据。真正约束自由脚本的是运行时守卫（见下条）。
- **运行时守卫（Jev `guard_mechanism_choice = official_methodcallback_runtime_guard`，置信度 `1.0`）**：`render_geometry_guard()` 生成一段幂等前置代码，通过 Abaqus 官方扩展点 `methodCallback.addCallback(methodCallback.ALL_TYPES, name, callback)` 注册回调，在**调用发生前**抛异常阻断。守卫按 `repr(method)` 解析出 part 名与方法名后查策略：命中且拒绝则阻断，未命中 part 的独有方法（虚拓扑类）一律阻断，`repair` 这类通用名在无法归属时不阻断（避免误伤）。策略来自会话级 state，同一 CAE 会话的后续脚本**交接策略**而不是叠加注册。
- **为何不用 patch / settrace**：真机实测四项否决——`abaqus.Part` 是不可变类型（`cannot set attribute of immutable type`）；实例赋值抛 `TypeError`，写 `__dict__` 不改变属性查找；`sys.setprofile` 看不到 Abaqus 方法（非 Python builtin）；`sys.settrace` 挂 `_methodCallHandler` 虽能阻断，但抛异常后 `sys.gettrace()` 立即变 `None`，守卫退化为 fail-open。四条路径全部记录在证据文件里。
- **绕过矩阵（真机验证，`machine_validation/geometry_cleanup_guard.json`）**：直接调用、`getattr` 拼接、`eval`、别名绑定、间接封装**全部阻断**，且阻断后 `ignoredEdges` 均为 0。即使用户代码用 `except Exception: pass` 吞掉异常，几何**依然未被修改**——保护来自「调用前拦截」，不是异常类型。
- **Abaqus 2025 真实 API 纠正**：`repairGeometry` / `removeRedundantEntities` / `healGeometry` 在 2025 **不存在**（这正是旧筛查名单既拦不住真实调用、类型化动作也无法执行的根因）。类型化动作现分别产出 `repair()` 与 `removeInvalidGeometry()`（Jev `map_to_remove_invalid_geometry`，`0.99`）；`ignore_entity` / `restore_entity` 现强制 `tuple(entities)`，因为 Abaqus 拒绝裸实体与 `GeomSequence`（`entities; found Edge, expecting tuple`）。
- **容差旋钮只记录不阻断（Jev `allow_but_record`，`0.76`）**：`geometryRefinement` / `geometryPrecision` 不删除也不合并拓扑实体，故不归入 repair 类拒绝；但会改变网格与结果，所以写入 `tolerance_changes` 留痕。
- **证据门禁纠正**：原 `_geometry_inspection_script` 用 `check = part.checkGeometry(detailed=True); if check is False: valid = False` 计算 `valid_geometry`，但 `checkGeometry` 成功返回 `None`、失败才抛异常，导致 `valid_geometry` **恒为 True**，而 `verify_cleanup_transition` 又要求它。现改为读 `geometryValidity`（int，实测 `1`/`0`），无法判定时保持 `None`，并记录 `check_geometry_error` 与 `validity_source`。`verify_cleanup_transition` 不再把 `None → True` 当作变化，并在任一端未知时标记 `validity_conclusive=False`。
- **虚拓扑仅候选（Jev `block_ignore_entity_and_report_candidates_only`，置信度 `1.0`）**：`ignore_entity` / `restore_entity` 在策略拒绝时阻断；`mesh_strategy` 的小特征虚拓扑仅产出 `virtual_topology_review` 候选，绝不自动执行，也不落成 `ignore_entity` 动作。
- **no-op 不算成功（Jev 0.75）**：`verify_cleanup_transition()` 对「无可观测变化」返回 `verified=False` 与 `no_observable_change`，不得把「命令返回了」当作「修复生效」。
- 回归：`tests/test_geometry_cleanup_policy.py`（43 项，含默认拒绝、跨 part 不越权、逃生通道负向、守卫策略载荷、真实 API 名、tuple 化、恒真证据反例、共享入口一致性、no-op 语义、虚拓扑仅候选）。
- 实现状态（2026-10-20）：`GeometryCleanupPolicySet` / `enforce_cleanup_policy()` / `render_geometry_guard()` / `GeometryCleanupPolicyViolation` 已落地；`action_to_script` 对 `python` 自动前置守卫，`compile_intent_to_actions` 为整份 deck 只注入一次守卫（`include_guard=False` 用于组合，避免重复膨胀）。全量回归 1751 项通过。真机端到端：编译出的 14 动作 deck 在 Abaqus/CAE 2025 noGUI 跑通，写出含 `*Boundary` / `*Static` / `*Cload` 的合法 INP，零 traceback。
- **仍不得宣称闭合的部分（Jev `qualified_but_actions_unproven`，`0.57`）**：「策略无法被 `python` 绕过」已由真机证明；但「类型化修复路径在真实无效几何上产出正确修复」**尚未验证**——需要故意损坏的 STEP 做前后对比。守卫与用户代码同进程，脚本理论上可调 `methodCallback.removeCallback` 注销它；守卫会记录自身注册与违规，使注销可被发现，但**不宣称进程内抗篡改**（Jev `guard_tamper_resistance = 0.6`）。因此本条维持 `IN_REVIEW`，残余风险已从「未知且无保护」降为「已知且可检测」。
- 证据：`machine_validation/geometry_cleanup_guard.json`。

### 7.2 JEV 意图识别与可审计工程决策层闭环 (TypeSafe JEV Decision Layer)

**架构分权契约 (Architectural Authority Separation)**：
- **JEV 作为建议层 (Advisor)**：提供自然语言物理域分类候选、参数推断以及澄清建议，提出类型化概率与置信度信号；
- **确定性规则与 Preflight 作为裁决层 (Gatekeeper)**：材料真实性、边界条件完备性、求解可行性以及工程验收标准，必须由确定性 Preflight、Solver ODB 证据提取与 Acceptance 门禁裁决，严禁 AI 模型越权裁决或绕过工程门禁。

#### REQ-P1-043: JEV 显式运行模式隔离与防静默降级 (Offline/Live/Shadow)
- **显式三态运行模式**：
  - `offline`（默认）：纯本地确定性规则引擎，用于离线环境、本地测试与无网络 CI，100% 幂等可重现；
  - `live`：真实调用外部意图 Provider，网络断开、超时、鉴权失败或响应畸形时**必须 fail-closed 抛出 `ExternalIntentApiError`**，坚决禁止静默降级为离线规则；
  - `shadow`：基准路径由离线规则主导驱动后续编译，同时并发/旁路请求外部 Provider，比对并记录二者决策差异（Diff），外部异常不破坏离线基线。
- **配置与密钥安全**：模式通过构造参数或环境变量 `EXTERNAL_INTENT_RUN_MODE` / `INTENT_RUN_MODE` 显式受控；非法模式严格拒绝；真实 API 密钥与敏感信息严禁落入日志或决策工件。

#### REQ-P1-044: 严格数值校验、载荷对齐与全链路来源审计
- **API 提问载荷与归一化对齐**：发往外部 Provider 的 Payload 覆盖 6 项核心判断；归一化器统一接入标准字典契约；
- **严格数值与概率归一化校验**：拒绝布尔值、NaN、Inf 与越界浮点数；概率分布（`distribution`）与离散等级（`levels`）必须严格满足数学归一化条件（$\sum p \approx 1.0$）；
- **深度日志脱敏**：Shadow 模式下深度清洗异常信息，消除 URL、查询参数、API 密钥与原始 Prompt；
- **决策来源完整追溯**：`IntentDecisionBundle` 如实标注 `execution_mode`、`source_model`、`latency_ms` 与审计摘要，区分模型判断与本地推断字段。

#### REQ-P1-045: 独立工程意图评测系统与上下文打通 (Context Merge)
- **独立工程意图评测系统**：构建独立的评测框架（`tools/jev_engineering_benchmark.py`），覆盖 8 大工程维度（物理域分类、参数缺失识别、探索性任务放行、合规性校核拦截、歧义澄清识别、对抗性输入阻断、Prompt/Context 冲突检测、未验证与非法证据拦截），量化输出 Match Rate、精确分立指标与延迟报表，不依赖 Abaqus License 即可秒级执行；
- **评测度量体系严格分母分立与双向闭环**：
  - 安全漏检率（False Negative Rate）：必须以“应拦截/澄清用例总数”为严格分母，分子为错误放行的用例数，杜绝以总用例数统合稀释；
  - 误拦截率（False Positive Rate）：必须以“应放行用例总数”为严格分母，分子为错误拦截的用例数；
  - 物理分类准确率：以“有预期物理域用例总数”为严格分母；
  - 缺失项召回率（Recall）与精确率（Precision）：以“预期缺失项总条目数”为召回率分母，以“实际检出项总数”为精确率分母，杜绝漏检与胡乱报缺；
  - 上下文证据错误放行率（False Acceptance Rate）：针对未验证、过期或冲突的 Context 证据，拦截率必须为 100%（False Acceptance Rate 为 0.0%）；
- **显式评测身份标记**：评测报告与元数据必须显式标明 `provider_type`（如 `offline_deterministic_baseline`），离线基线评测坚决声明系确定性规则基线评测，严禁冒充或宣传为外部真实 JEV 模型评测；
- **CAE/INP 实体证据有效性核验与物理语义防呆 (Context Merge)**：
  - 严禁单凭 `has_model: True`、`has_geometry: True`、`has_material: True`、`has_constraints: True` 等名义布尔标记直接放行硬前置条件；
  - **全实体严格类型化结构防呆校验**：
    - 几何尺寸：数值必须为有限正数（拒绝 $<=0$、NaN、Inf），字段键必须严格匹配合法尺寸键集合（`VALID_DIMENSION_KEYS`，如 length/width/height/box 等，拒绝 `stress: 300` 等非尺寸字典），且必须具备合法的长度单位（如 `mm`, `m`, `cm`, `in`），非法单位坚决拒绝；
    - 材料属性：弹性模量必须正有限，泊松比必须严格满足 $0.0 \le \nu < 0.5$（拒绝 $\nu \ge 0.5$ 体积刚度奇异及负值）；严格解耦“材料名称识别”（`NAMED_ONLY`）与“物理属性验证”（`VERIFIED_PROPERTIES`），彻底消除 `or elastic_modulus is not None` 旁路漏洞，在弹性物理域（静力、模态、动力学等）缺少有效力学物性参数时坚决阻断澄清（`unverified_material_properties`），并显式标记来源（`explicit_user_input`, `model_extracted`, `standard_reference_library`）；
    - 边界条件：必须具备明确且受支持的约束类型（精确匹配 `VALID_BC_TYPES`，拒绝 `not_fixed` 等子串伪造）与有效几何区域（`region`/`surface`/`set`/`face`），位移约束（`displacement`）必须强制包含非空且严格位于 $1..6$ 范围内的自由度集合（`dofs`）；严禁将任意非空字符串或无区域约束伪造成 `FixedFace`，Prompt 仅包含裸“固定”而未指定具体位置时坚决拒绝生成推测性区域；
    - 边界提取子句作用域隔离：提取 Prompt 边界区域时实施子句级别隔离（Clause Scoping），彻底杜绝载荷端部描述（如“端部受1000N力”）被跨子句错误窃取为约束区域；
    - 载荷实体与作用区域严格闭环：必须包含明确的有限且严格非零数值幅值（`magnitude != 0.0`，拒绝零幅值并报错 `load_magnitude_must_be_non_zero`，严禁布尔值、NaN、Inf）、受支持载荷类型（精确匹配 `VALID_LOAD_TYPES`，拒绝 `not_pressure` 等子串伪造）及目标作用区域；进入可执行 `EngineeringIntent` 的机械载荷必须 100% 具备显式区域，若 Prompt 仅有幅值而缺少作用区域且 Context 未提供，坚决 fail-closed 拦截并报错 `missing_load_application_region`，杜绝载荷前置条件放行但 Intent 缺少区域的不对称缺陷；
    - 热边界实体结构校验：彻底消除裸关键词判定绕过，必须通过 `_extract_prompt_thermal_bcs` 提取结构化实体，热边界必须包含有限数值幅值（温度/热流，完整支持合法的 $0^\circ\text{C}$ / `0.0` 数值，杜绝 falsy 丢失缺陷）与目标区域，对流换热强制环境温度与换热系数，热辐射强制环境温度与有效发射率（$0 < \epsilon \le 1.0$）；未提供有效实体时坚决输出 `missing_thermal_boundary_conditions` 阻断澄清；
    - 语义候选区域与拓扑模型 Grounding 解耦：意图元数据中显式追踪 `region_grounding_status`（Prompt 语义标签标记为 `SEMANTIC_CANDIDATE_UNRESOLVED`，经 INP/CAD 真实模型拓扑验证的标记为 `MODEL_TOPOLOGY_GROUNDED`），杜绝下游将语义推断误当成拓扑接地；
    - 验收准则：验收准则操作符必须严格限定在合法比较运算符集合（`VALID_CRITERIA_OPERATORS`），指标名称必须严格匹配工程指标白名单（`VALID_CRITERIA_METRICS`）；
    - 证据有效性标记：标有 `status: "UNVERIFIED"`、`verified: False`、`expired: True`、`conflict: True`（含布尔值与字符串）的证据严禁放行；
  - **拓扑 Grounding 严格 1-to-1 集合包含解析**：彻底杜绝 `model_topology_grounded: True` 等名义标记或任意非空 `surfaces` 绕过；必须对 Intent 中所有 BC 和 Load 引用的几何区域执行严格的 1-to-1 模型拓扑子集校验，仅当所有引用区域 100% 存在于已验证模型实体时才标记 `MODEL_TOPOLOGY_GROUNDED`，存在未解析区域时坚决标记为 `SEMANTIC_CANDIDATE_UNRESOLVED`；
  - **载荷区域子句作用域隔离（Clause Scoping）与反偷窃门禁**：对 Prompt 实施子句作用域切分，严格禁止载荷从约束分句（如“固定根部”）或验收指标分句（如“校核端部挠度不超过2.5mm”）中偷取区域；载荷专属子句未显式指定作用区域时坚决 fail-closed 阻断并报错 `missing_load_application_region`；
  - **热边界规范化参数完整保留与零伪造**：`_validate_thermal_bcs_entity` 规范化字典中 100% 完整保留对流环境温度（`ambient_temperature`）、表面传热系数（`film_coefficient`/`h`）及热辐射发射率（`emissivity`）；热流提取在当前子句未找到区域时严禁伪造 `"Surface"` 默认区域；
  - **材料参考库假设与实测已验证物性严格分级**：标准参考库默认材料（结构钢、铝合金等）严格打标为 `REFERENCE_LIBRARY` 与 `is_reference_assumption: True`，`has_verified_properties: False`；Intent 元数据明确追踪 `material_assumption: True`；只有用户显式提供或上游模型卡核验的材料实体才赋予 `VERIFIED_PROPERTIES`；
  - **前置条件与意图构造对称闭环**：前置条件判定通过的所有物理实体，必须 100% 完整映射并注入最终 `EngineeringIntent`，彻底消除前置条件判定通过却产出空约束 Intent 的断层缺陷；
  - **零原始上下文回退与零虚构几何区域（Zero Raw Context Fallback & Geometric Region De-forgery）**：
    - 路由与 Intent 构造阶段彻底断绝从未经验证的 `context` 字典直接回退提取数据（Zero Raw Context Fallback）；
    - `_build_intent_from_decisions` 与 `_build_draft_intent_from_decisions` 只能消费经由前置条件验证通过并完成规范化的统一实体结果（`verified_entities["normalized"]`）以及当前 prompt 提取的合法参数与显式几何区域；
    - **彻底杜绝虚构几何区域**：严禁在无真实证据或无显式 Prompt 区域声明时，向 Intent 中注入默认虚构的 `FixedFace`、`TipFace` 或 `TopFace`；无法确定具体几何区域时，坚决 fail-closed 进入澄清门禁（`NEEDS_CLARIFICATION`）；
  - **多维冲突检测（Prompt vs Context Conflict Detection）**：
    - 覆盖材料类别冲突、物理域冲突、载荷类型冲突、**完整跨单位同类型载荷幅值冲突（力支持 N/kN/MN、压强支持 Pa/kPa/MPa/GPa 换算，相对偏差 $> 5\%$ 触发 `conflict_load_magnitude`）**、约束自由度冲突与单位系统冲突；发生工程冲突时严禁静默覆盖，必须触发 `NEEDS_CLARIFICATION` 要求工程师确认；
- **意图路由与求解准备的严格边界及全入口 DraftIntent 阻断**：
  - 意图路由通过（`status == ROUTED`）仅表示自然语言需求语义与硬输入前置条件完备；
  - 任何带 `is_executable=False` 的 `DraftEngineeringIntent` 在所有求解与编译入口（`solve_requirement`、`compile_engineering_intent`、执行后端等）必须被严格阻断；
  - 严禁将意图路由通过等同于求解准备就绪；网格划分、接触定义、求解步设置与求解收敛性必须严格交由确定性 Preflight、求解器执行与 ODB 证据门禁进行终审。

### 7.3 开源核心独立运行与专有服务解耦隔离 (Open Source Core Decoupling)

#### REQ-P1-046: 开源核心独立运行与零外部 AI 依赖保障
- **开源核心独立可用**：Abaqus-AI-Agent 必须是一个不依赖任何专有外部 AI 服务的独立开源工程工具；系统默认模式必须为 `offline`；
- **核心工程闭环完整性**：在没有任何外部 API Key、没有外部网络连接、没有商业 AI 扩展包的环境下，从自然语言解析、确定性 Intent 编译、ActionPlan、Preflight、Abaqus 执行、ODB 提取、Acceptance 门禁到交付报告生成的全链路必须 100% 独立可用且行为确定。

#### REQ-P1-047: 供应商中立的可选外部适配器协议与插件机制
- **供应商中立抽象**：开源核心仅定义供应商中立的意图提供者协议（`ExternalIntentProviderProtocol`），核心模块不与任何特定商业供应商强绑定；
- **安全可插拔扩展**：外部商业 AI 服务仅作为可选增强插件（Adapter）存在；支持通过可调用对象、标准接口类或动态加载方式注入；未配置或未安装时，核心退居受支持的默认 offline 确定性工作流。

#### REQ-P1-048: 专有服务接入隔离与公开仓库零专有泄露
- **公开核心代码零专有泄露**：开源核心仓库中严禁硬编码特定商业服务的私有 API 端点、专有模型名称、专有 Prompt 模版与私有测试 payload；
- **服务细节封装于外部适配器**：所有关于专有商业服务的调用细节、认证协议、专有报文格式均严格封装于外部私有适配器中，不得扩散至核心开源代码。

#### REQ-P1-049: 安全凭据保护与密钥零泄露红线
- **凭据生命周期安全**：开源仓库、测试用例、配置文件、文档与 Git 提交历史中严禁出现真实商业 API Key、Token 或受保护凭据；
- **审计追踪脱敏**：任何运行日志、Run Evidence、DecisionBundle 与交付工件中严禁记录 API Key、Authorization 头或敏感专有指令。

#### REQ-P1-053: 核心功能资格与外部服务能力分离验证
- **资格分级管理**：必须严格区分“开源核心确定性资格”、“外部适配器契约资格”与“Abaqus 2025 真实求解器真机资格”；
- **禁止凭空背书**：离线测试全绿仅证明开源核心代码契约；外部服务仅在提供真实调用日志与评估指标时认证；未经验证项明确保留待验证状态。

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
| **REQ-P1-010** | 多格式工程图纸图像摄入 | P1.1 | PDF/PNG/JPG 文件 | 矢量字符流/高DPI光栅瓦片与坐标 | Tier C | 损坏文件/不支持格式安全报错 | 🟢 **QUALIFIED** |
| **REQ-P1-011** | Provider-Neutral 工程 OCR | P1.1 | 图像/矢量文字块 | 强类型文本与材料标记候选 | Tier B | 低文字置信度进入待确认 | 🟢 **QUALIFIED** |
| **REQ-P1-012** | 尺寸标注线与公差解析 | P1.1 | 尺寸线与文字图像 | 尺寸数值、公差、跨度 (DIMENSION) | Tier B | 尺寸冲突或量纲缺失告警 | 🟢 **QUALIFIED** |
| **REQ-P1-013** | 载荷箭头与约束符号解析 | P1.1 | 箭头与约束图标 | 幅值、方向矢量、约束 (ARROW/SYMBOL)| Tier B | 方向歧义或多候选阻断 | 🟢 **QUALIFIED** |
| **REQ-P1-014** | 结构化 `VisualCallout` 输出 | P1.1 | 识别结果集 | `Tuple[VisualCallout]` (规范契约) | Tier B | 严格坐标[0,1]与非零矢量校验 | 🟢 **QUALIFIED** |
| **REQ-P1-015** | 多维置信度人机协同门禁 (HITL) | P1.1 | `VisualCallout` 候选 | `HITLConfirmationRequest` | Tier B | 多候选或多维置信度不达标阻断 | 🟢 **QUALIFIED** |
| **REQ-P1-016** | 视觉防伪与防幻觉红线 | P1.1 | 模型输出 | 结构化候选数据 | Tier B | 严禁 Vision 直出 Python 脚本 | 🟢 **QUALIFIED** |
| **REQ-P1-020** | 材料牌号匹配与环境超限预警 | P1.2 | 材料中文别名/工况 | 严格物性参数 / 超限告警 | Tier B | 未知材料拦截，高温超限确认 | 🚧 **READY** |
| **REQ-P1-021** | 透明网格推荐与依据记录 | P1.2 | 几何特征尺寸 | 网格尺寸、单元类型、依据 | Tier B | 严禁无依据默认 5mm C3D8R | 🚧 **READY** |
| **REQ-P1-022** | 载荷/约束边界歧义消除 | P1.2 | 约束与载荷集合 | 欠约束告警、对称面建议 | Tier B | 刚体机构未约束阻断求解 | 🚧 **READY** |
| **REQ-P1-023** | 需求澄清标准协议 | P1.2 | 残缺/冲突需求 | `NEEDS_CLARIFICATION` | Tier B | 明确输出缺失字段与推荐选项 | 🚧 **READY** |
| **REQ-P1-030** | 无头自动化 ODB 云图提取 | P1.3 | 真实 ODB 场变量 | 高清 PNG 云图与 Hotspot | Tier A | 缺失场变量无法生成伪造云图 | 🟢 **QUALIFIED** |
| **REQ-P1-031** | 动力学历程曲线与守恒图表 | P1.3 | 真实 ODB 历史变量 | 能量守恒曲线、P-u 曲线 | Tier A | 伪能比 $>5\%$ 标红阻断 | 🟢 **QUALIFIED** |
| **REQ-P1-032** | 独立交付级工程报告生成 | P1.3 | 任务结果与验签凭证 | 单文件独立 HTML 报告 | Tier B | 验签失败报告显示 TAMPERED | 🟢 **QUALIFIED** |
| **REQ-P1-033** | 原生静默无头动画渲染与 HTML 内嵌 | P1.3+ | 真实 ODB 场/时程变量 | Base64 嵌入动图单文件报告 | Tier A | 方案 A 原生无头批处理渲染与自适应量化 | 🟢 **QUALIFIED** |
| **REQ-P1-034** | 视口安全缩放防裁剪与动态感知修剪 | P1.3++ | 视口几何包围盒与动画帧序列 | 弹性居中、防截断安全留白动图 | Tier A | 视口缩放异常降级报警，保留有效动图帧 | 🟢 **QUALIFIED** |
| **REQ-P1-035** | 报告图片受控解析与同名回退收敛 | P1.4 | 报告待嵌入图片路径 | 严格交付目录绑定与缺失占位 | Tier B | 严禁跨目录/测试资产同名图模糊回退 | 🟢 **QUALIFIED** |
| **REQ-P1-036** | 生产执行外部项目上下文强制校验 | P1.4 | 生产求解请求与工作目录 | 外部项目独立路径硬门禁 | Tier B | 生产模式未提供外部上下文立即阻断 | 🟢 **QUALIFIED** |
| **REQ-P1-037** | 动图双模态保真与抽样末帧保全 | P1.4 | 动画时程帧序列与分析类型 | 物理忠实时程 / 演示动画双轨 | Tier A | 严禁截断丢失最终关键帧，保留平衡时程 | 🟢 **QUALIFIED** |
| **REQ-P1-038** | 用户已有模型 (CAE/INP/ODB) 输入规范 | P1.4 | 用户外部模型与任务类型 | 原生执行/只读后处理/工作副本 | Tier A | 原始模型只读保护，禁止无谓重建 | 🟢 **QUALIFIED** |
| **REQ-P1-039** | 受控 INP 结构化参数编辑与版本审计 | P1.4 | 用户 INP 与参数编辑指令 | 独立工作副本、Diff 审计、求解闭环 | Tier A | 严禁原地修改，目标歧义或缺失 fail-closed | 🟢 **QUALIFIED** |
| **REQ-P1-040** | 求解器发散特征深度诊断 | P1.4 | `.msg`, `.sta` 日志 | 发散根因诊断报告 | Tier A | 无法识别的发散安全退出 | 📋 **PLANNED** |
| **REQ-P1-041** | 受控自愈策略库与自动重算 | P1.4 | 发散诊断结果 | 修复配置与自愈重算 | Tier A | 稳定能量超限即判定自愈无效 | 🟢 **QUALIFIED (Gap-closure loop: unstabilized fails, stabilized converges with finite energy and gate PASS; `CONTACT_OPENING` selects contact stabilization on real failures; unambiguous step binding no longer needs caller restatement)** |
| **REQ-P1-042** | 自愈审计追踪与防伪红线 | P1.4 | 修复前后两次 Run | 完整 Diff 对比明细 | Tier B | 严禁静默覆盖首次失败记录 | 🟢 **QUALIFIED (Degenerate guard, real rerun evidence in `machine_validation/p0b_contact_stabilization_loop.json`, and the incorrect NaN root-cause claim corrected)** |
| **REQ-P1-043** | JEV 模式隔离与防静默降级 | P1.4 | 运行模式配置与提示词 | 强类型决策与状态 | Tier B | Live 模式异常坚决 Fail-Closed | 🟢 **QUALIFIED** |
| **REQ-P1-044** | 严格数值校验、载荷对齐与全链路审计 | P1.4 | 意图提问与响应载荷 | 完整审计束与来源标记 | Tier B | 概率分布归一化 sum=1.0、深度脱敏 | 🟢 **QUALIFIED** |
| **REQ-P1-045** | 独立工程评测系统与 Context Merge 审计 | P1.4 | 8大工程维度基准评测 | 评测指标、严格分母、精确率与实体防呆 | Tier B | 8维度全指标分母分立、1-to-1拓扑Grounding、子句载荷隔离、物性分级闭环 | 🟡 **IN_REVIEW (Deep Topological & Evidence Hardening in Progress)** |
| **REQ-P1-046** | 开源核心独立运行与零外部依赖 | P1.4 | 纯离线/无网络环境输入 | 独立 Intent/编译/求解/报告 | Tier A | 核心闭环严禁外部服务阻断 | 🟢 **QUALIFIED (Offline Core Hermetic)** |
| **REQ-P1-047** | 可选外部服务适配器协议与响应归一化 | P1.4 | 通用意图提供者接口与配置 | 可插拔适配器加载与解析 | Tier B | 未安装/未配置时保持 offline 基线 | 🟢 **QUALIFIED (Protocol Contract Closed)** |
| **REQ-P1-048** | 专有服务接入隔离与零专有泄露 | P1.4 | 公开核心代码库 | 供应商中立抽象与纯净核心 | Tier A | 严禁硬编码专有端点与私有协议 | 🟢 **QUALIFIED (Code Tree Clean)** |
| **REQ-P1-049** | 安全凭据保护与密钥零泄露红线 | P1.4 | 环境变量与配置工件 | 深度脱敏审计追踪与零泄露 | Tier A | 杜绝 URL/Token/Prompt 泄露 | 🟢 **QUALIFIED (Credentials Deep Sanitized)** |
| **REQ-P1-053** | 核心与外部服务资格分离验证 | P1.4 | 测试矩阵与真实机证据 | 分立的资格认定状态 | Tier A | 严禁以离线测试冒充外部/真机通过 | 🟢 **QUALIFIED (Tiered Rules Active - Solver Unverified)** |
| **REQ-P1-054** | 瞬态动态能量平衡契约 | P1.4 | ODB 能量历史 (`ALLIE/ALLKE/ALLWK/ETOTAL`) | 动态能量漂移判定与门禁 | Tier A | 阈值与求解器产品必须显式声明，未声明即阻断；不得与静力 `ALLSD/ALLSE` 共用阈值 | 🟡 **IN_REVIEW (Implicit and explicit both verified on real Abaqus 2025 runs; explicit `ALLWK` evidence-path defect fixed; multi-step binding still unverified on machine; `explicit_closure_sufficiency=0.15`)** |
| **REQ-P1-055** | 几何清理策略全入口强制 | P1.4 | 几何清理策略与全部脚本生成路径 | 单一 choke point fail-closed 阻断 + 同进程运行时守卫 | Tier A | 默认拒绝不得被绕过；逃生通道不得洗白修复；虚拓扑仅候选 | 🟡 **IN_REVIEW (43 tests. The `python` escape hatch is now blocked at the call site by an official `methodCallback` runtime guard: direct call, `getattr` concatenation, `eval`, alias binding and indirect wrappers are all blocked on real Abaqus 2025, and a bare `except: pass` still leaves geometry unchanged. Real-API defect fixed (`repairGeometry`/`removeRedundantEntities` do not exist in 2025) and the always-True `valid_geometry` evidence gate corrected. Remaining gap per Jev `qualified_but_actions_unproven=0.57`: the typed repair path has not been proven to correct genuinely invalid geometry, and in-process tamper resistance is not claimed (`guard_tamper_resistance=0.6`))** |
| **REQ-P1-050** | 3D 轻量级视口与面/边拾取 | P1.5 | 3D 几何模型 | 拾取事件与几何面候选 | Tier C | 拾取越界或歧义安全校验 | 📋 **PLANNED** |
| **REQ-P1-051** | HITL 交互决策卡片界面 | P1.5 | 确认请求对象 | 工程师点击决策与签名 | Tier C | 未确认操作严禁下发后端 | 📋 **PLANNED** |
| **REQ-P1-052** | 企业级调度与案例资产管理 | P1.5 | 批量工程计算任务 | 许可令牌与计算节点分配 | Tier C | 许可抢占与排队超时处理 | 📋 **PLANNED** |

---

### Phase P0: 验收安全内核与全系统真实性门禁 (Security & Grounding Kernel)

| 需求编号 | 需求名称 | 归属模块 | 输入对象 / 触发条件 | 预期输出 / 行为定义 | 验证等级 | 异常与 Fail-Closed 边界 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-P0-001** | 四维正交判定与力学失败绝对保留 | Phase P0-A | 提取指标字典、判据、门禁、证据状态 | `AcceptanceResult` 包含正交四维字段与 `AcceptanceFindings` | Tier A | 真实力学超标且伴随门禁缺失时，绝对保留 `FAIL` 事实并记录 `blocked` 项，禁止降级为 BLOCKED；证据不可信时不推导力学失败 | 🟢 **QUALIFIED** |
| **REQ-P0-002** | 规范化自校验摘要与 ODB 初筛探针 | Phase P0-B | `EvidenceManifestV2`、工件文件、`role="odb"` | 确定性规范化哈希摘要、非 JSON/明文二进制初筛 | Tier A | 缺失摘要判 `INCOMPLETE`；单比特篡改判 `EVIDENCE_TAMPERED`；假 ODB 或裸字典判 `EVIDENCE_CORRUPT` | 🟢 **QUALIFIED** |
| **REQ-P0-003** | 运行因果绑定与受控生产验收入口 | Phase P0-C | `AnalysisRun`、Manifest、求解器进程记录 | `evaluate_production_acceptance()` 受控验收凭据 | Tier A | 跨运行旧工件判 `EVIDENCE_STALE`；未实际提交求解作业（仅 `abaqus help`）判 `INCOMPLETE` 并拒绝验收 | 🟢 **QUALIFIED** |
| **REQ-P0-004** | 报告管线交付资格门禁与全仓零绕过 | Phase P0-D | `deliverable` 标识、报告渲染、交付卡 | 严格门禁断言：仅 `deliverable is True` 签发正式报告 | Tier A | `deliverable is False` 强行请求生成报告时阻断或强制加注“诊断副本/未通过”水印；全仓清除 `require_evidence=False` 绕过 | 🟢 **QUALIFIED** |

---

## 十、工程质量与防伪铁律（Engineering Redlines）

在推进系统的全部过程中，全体智能体与开发团队必须绝对坚守以下六项铁律：

1. **零伪造原则 (Zero Fabrication)**：
   严禁使用任何经验公式、模拟数据或虚构数值冒充真实求解器结果。所有物理数据必须由真实 Abaqus 2025 ODB 现场提取，并具备可验证的密码学 SHA-256 签名。
2. **Fail-Closed 闭环原则**：
   在任何环节（参数缺失、拓扑无法解析、网格不合法、求解器发散、证据篡改），系统必须果断阻断并明确进入 `BLOCKED` / `NEEDS_CLARIFICATION` / `RESULT_INVALID`，绝不允许伪装成 `ACCEPTED`。
3. **单一出口原则 (Single-Exit Acceptance)**：
   外部输入、模型修饰、非标准动作脚本严禁直接触碰 `ACCEPTED` 状态。只有经由 `AnalysisRunner` $\to$ `preflight` $\to$ 真实 Abaqus 求解 $\to$ ODB 提取 $\to$ `EvidenceManifestV2` 验签 $\to$ `evaluate_production_acceptance`，才是通往工程合格裁决的唯一合法路径。
4. **范围诚实原则 (Stated Scope Precision)**：
   如实陈述已验证的边界。宣称“20 个物理领域 L4 认证”是指在各领域已声明的物理基准和工程契约范围内达到全链路闭环，严禁夸大为“无限制支持 Abaqus 全部几十万个关键词或任意复杂拓扑”。
5. **四维正交与失败保留铁律**：
   验收状态 (`acceptance_status`)、证据有效性 (`result_validity`)、交付资格 (`deliverable`) 与事实发现 (`findings`) 必须严格正交。已被证实超标的力学失效决不允许被阻断项掩盖；数据不可信时绝不从脏数据推导力学失效；`deliverable` 必须由统一验收内核计算，任何调用方严禁擅自置 `True`。
6. **全仓交付出口全封闭铁律**：
   所有正式工程报告、交付卡与导出管道必须严格校验 `deliverable is True`。算法单测入口永久标记为不可交付；未通过真实求解验证或必需门禁跳过的结果，严禁签发正式工程交付文件。

---

# 十一、Phase 2：工程能力深度与真实复杂工程实战

Phase 2 整体划分为两个边界清晰、串联收口的工程工作包：

```text
PHASE 2 架构
├── Package A：工程能力完善与组合验证（REQ-P2-001 ~ REQ-P2-005）
│   ├── 核心能力收口：Fatigue / Connector / FMBD 深度，20 L4 边界核查与补齐
│   ├── 工程组合能力：Thermal→Structural, Preload→Static, Preload→Modal, Contact+Nonlinear 等
│   └── Golden Matrix：单零件、Assembly、接触、预紧、多步、动态与正负向/Fail-Closed 闭环
└── Package B：10 个真实复杂工程项目正式实战（REQ-P2-006 终验包）
    ├── 问题导入 → Agent 意图/建模 → 真实 Abaqus 2025 → 单出口 Acceptance → 独立工程报告
    └── 10/10 独立证据、真实机求解与参考对照闭环，完成 Engineering Kernel Freeze
```

---

## 11.1 Package A：工程能力完善与组合验证

目标：**把现有 Phase 2 能力补齐、强化，并证明它们可以自由组合使用。**

### REQ-P2-001：Fatigue 工程场景深度
**状态：🟢 L4 QUALIFIED；持续扩展真实工程场景。**

在现有高周疲劳 L4 基础上，继续验证更真实的载荷历史、材料与几何组合。不得把单一 Golden 扩大解释为“覆盖全部 Abaqus 疲劳”。

验收要求：
- 真实 Abaqus ODB；
- Evidence V2；
- Rainflow / mean-stress / Miner 语义保持一致；
- 失败与边界情况 Fail-Closed。

### REQ-P2-002：Connector / Joint 工程场景深度
**状态：🟢 L4 QUALIFIED；持续扩展真实机构场景。**

重点扩展多连接器、不同方向、组合载荷与机构拓扑，而不是重写现有 Connector 内核。

### REQ-P2-003：FMBD 工程场景深度
**状态：🟢 L4 QUALIFIED；持续扩展刚柔耦合与机构组合场景。**

重点覆盖更多刚柔拓扑、闭环机构、连接器组合及动态响应验证。

### REQ-P2-004：多物理与组合工程场景
建立跨已有 L4 域的真实工程组合案例，重点验证真实组合工作流，而非孤立单项 Demo：
- Thermal → Structural；
- Preload → Static；
- Preload → Modal；
- Contact + Nonlinear；
- Connector + Contact；
- Connector + FMBD；
- Multi-step + Fatigue；
- Thermal + Fatigue；
- Assembly + 多部件；
- 多工况 / 多载荷历史对比。

**目标不是新增“能力数量”，而是证明已有能力可以组合成真实工程工作流。**

### REQ-P2-005：真实工程场景矩阵与 Package A 最终收口
建立可持续扩展的 Golden Case Matrix，覆盖：
- 单零件、Assembly、Contact、Preload、Nonlinear、Multi-step、Thermal、Dynamic、Fatigue、Connector、FMBD；
- 统一收口正向、负向、Fail-Closed、Evidence V2、Acceptance 与 Reproducibility；
- **Package A 交付标准**：证明“工程内核能力已经足够完整，而且能够自由组合”。

---

## 11.2 Package B：10 个真实复杂工程项目正式实战

### REQ-P2-006：10 个真实复杂工程问题全链路实战验收
**状态：🔴 Phase 2 最终硬门槛与终验包；未完成前不得宣布 Phase 2 冻结。**

目标：**不再测试单个功能，而是真正拿 10 个真实复杂工程问题，从问题导入一直做到最终工程报告。**

标准全链路：
`真实工程问题资料/模型导入 → 工程需求结构化 → EngineeringIntent → 参数/材料/边界/分析步骤建立 → Compiler → Preflight → Abaqus 2025 真机求解 → ODB/日志/Evidence → Result Intelligence → Acceptance → 独立工程报告`

这 10 个案例不是“把官方 `.inp` 跑通”即可。每个案例都必须证明系统能够把**问题本身**导入现有工程闭环，并最终形成可审计的工程交付物。允许使用公开案例提供的输入文件、几何、材料和参考结果作为基准，但必须保留来源、输入证据、运行证据以及与参考结果的对照；不得直接把参考结果冒充 Agent 计算结果。

**工程边界原则**：10 个案例不是为了逼项目新增 10 种全新冷门物理域，而是建立在现有 20 L4 物理底座之上；如果某个案例超出范围，应当换更契合的工程案例，绝不无限做横向扩张。

### 10 个正式验收案例

| # | 工程问题 | 主要工程难点 | 覆盖能力 | 公开来源 |
|---|---|---|---|---|
| 1 | **Bolted Pipe Flange Connection** 螺栓管法兰连接 | 螺栓预紧、垫片、接触、压力、轴对称/3D 对照 | Connector/Contact/Preload/Static | Abaqus 2025 Example Problems (🟢 **QUALIFIED**) |
| 2 | **Reactor Pressure Vessel Bolted Closure** 反应堆压力容器螺栓闭合结构 | 54 根大直径 M180 螺栓预紧 + 金属锥面密封环接触 + 17.5 MPa 内压 + ASME Sec.III 评定 | Contact/Preload/Multi-step/Plasticity | Abaqus 2025 Example Problems & ASME BPVC (🟢 **QUALIFIED**) |
| 3 | **Exhaust Manifold Assemblage** 发动机排气歧管总成 | 多部件接触、7 螺栓、300→980 K 热循环、摩擦滑移 | Thermal-Structural/Contact/Preload | Abaqus 2025 Example Problems (🟢 **QUALIFIED**) |
| 4 | **Automotive Front Subframe Multi-Axis Durability** 汽车副车架多轴耐久疲劳 | 多轴时域载荷谱、衬套刚柔连接(CONN3D2)、ASTM E1049 雨流计数与 Goodman 疲劳 | Multi-step/Connector/Fatigue/Assembly | SAE / Abaqus Engineering Benchmarks (🟢 **QUALIFIED**) |
| 5 | **Laminated Composite Cylindrical Panel Buckling** 开孔层合复合材料圆柱板屈曲 | 多层铺层、各向异性、初始缺陷、特征屈曲、Riks 后屈曲 | Composite/Buckling/Nonlinear/Riks | Abaqus 2025 Example Problems (🟢 **QUALIFIED**) |
| 6 | **Stacked Sheet Metal Assembly Submodeling** 多层钣金紧固总成子模型 | 多层薄板、紧固件、全局→局部子模型、局部应力梯度 | Assembly/Submodel/Mesh Strategy | Abaqus 2025 Example Problems (🟢 **QUALIFIED**) |
| 7 | **Automotive Jounce Bumper** 汽车悬架缓冲块 | 高可压缩橡胶/泡沫、大变形、初始过盈、自接触、接触压缩 | Nonlinear Rubber/Self-Contact/Explicit | Abaqus 2025 Example Problems (🟡 **PENDING - 输入资产已落地，求解证据待真机**) |
| 8 | **Axisymmetric Threaded Connection** 轴对称螺纹连接 | 螺纹接触、过盈/缩径、压力渗透、轴向/弯曲/内压工况 | Contact/Connector/Pressure Penetration | Abaqus 2025 Example Problems (⚪ **PRE_RESERVED**) |
| 9 | **Cylinder Head Thermomechanical Direct Cyclic Analysis** 气缸盖热机械循环 | 周期热载荷、结构约束、循环响应、热机械疲劳相关结果 | Thermal-Structural/Direct Cyclic/Fatigue Context | Abaqus 2025 Example Problems (⚪ **PRE_RESERVED**) |
| 10 | **Thin-Walled Elbow Elastic-Plastic Collapse** 薄壁弯头弹塑性失稳 | 内压 + 面内弯曲、几何非线性、材料塑性、极限承载能力 | Nonlinear/Plasticity/Structural Collapse | Abaqus 2025 Example Problems (⚪ **PRE_RESERVED**) |

### 11.2.1 案例筛选背景与五维量化准则

根据架构裁决，Package B 不应作为盲目的功能扩张实验，而必须作为 **Phase 2 最终硬门槛与工程内核冻结基准 (Engineering Kernel Freeze Gate)**。

每一个入选案例必须经过以下五维指标的严格量化评估：
1. **工程复杂度 (Engineering Complexity, 1~5 星)**：是否具备真实的工业模型复杂度（如接触非线性、预紧力、多步骤加载、材料非线性、多部件装配体等）。
2. **能力覆盖度 (20 L4 Capability Coverage, 1~5 星)**：能否有效覆盖已通过 L4 验收的 20 项核心物理能力。
3. **组合价值 (Multi-Physics Composition Value, 1~5 星)**：是否体现多物理域或多步骤组合（如 Preload $\to$ Static, Contact + Plasticity, Thermal $\to$ Structural $\to$ Fatigue 等）。
4. **公开参考基准可得性 (Reference Benchmark Availability, 1~5 星)**：是否有权威公开出版物、Abaqus 官方 Example Problems、ASME/SAE/ISO 规范解或实验数据作为绝对校准对照。
5. **新物理域风险 (New Domain Risk, 低/中/高)**：**必须为“低”**。严禁为了凑案例而强行引入当前无内核支撑的冷门物理域（如显式多组分气体充气流体腔、粒子流动力学等）。

### 11.2.2 候选案例池评估与筛选分析表

| 序号 | 候选案例名称 | 工业领域 | 复杂度 | 能力覆盖 | 组合价值 | 参考基准 | 新域风险 | 综合裁决与当前状态 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **01** | **螺栓管法兰垫片密封分析** | 压力容器/管道 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | 🟢 **入选并闭环 (Case 01, QUALIFIED)** |
| **02** | **反应堆压力容器螺栓闭合结构** | 核电/重型装备 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | 🟢 **入选并闭环 (Case 02, QUALIFIED)** |
| **03** | **重载发动机排气歧管热机械接触** | 汽车动力总成 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | 🟢 **入选并闭环 (Case 03, QUALIFIED)** |
| *--* | *侧气帘安全气囊冲击试验* | *汽车被动安全* | *★★★★★* | *★★☆☆☆* | *★★☆☆☆* | *★★★★☆* | **极高** | ❌ **排除 (依赖冷门流体腔充气模型)** |
| **04** | **汽车副车架多轴耐久与疲劳分析** (替换项) | 汽车底盘结构 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | 🟢 **入选并闭环 (Case 04, QUALIFIED, 替换气囊)** |
| **05** | **开孔层合复合材料圆柱壳屈曲分析** | 航空航天结构 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | 🟢 **入选并闭环 (Case 05, QUALIFIED)** |
| **06** | **多层钣金装配体子模型精细化分析** | 车身/通用机械 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | 🟢 **入选并闭环 (Case 06, QUALIFIED)** |
| **07** | **悬架超弹性缓冲块大变形自接触** | 汽车底盘工程 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | 🟡 **入选 (Case 07, 输入资产已落地；PENDING 待真机证据)** |
| **08** | **石油套管特殊螺纹接头弹塑性接触** | 油气能源工程 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ⚪ **入选 (Case 08, PRE_RESERVED)** |
| **09** | **内燃机气缸盖热机械低周疲劳评定** | 发动机工程 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ⚪ **入选 (Case 09, PRE_RESERVED)** |
| **10** | **薄壁管道弯头弹塑性失稳极限承载** | 化工/核电管道 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | ⚪ **入选 (Case 10, PRE_RESERVED)** |

#### 关键剔除与替换论证 (Airbag Impactor $\to$ Subframe Fatigue)
- **剔除原因**：Abaqus 官方侧气帘案例 (`simaexa-c-airbag.htm`) 深度依赖 `*AIRBAG INFLATOR`、`*FLUID CAVITY` 与多组分热力学气体状态方程（EOS），且存在高度特异性的薄织物褶皱自接触显式算法。该领域并不属于主流通用结构工程核心，若在此阶段引入会导致大量流体腔特化逻辑侵入核心编译器，违背“基于已有能力组合，不新增物理域”的铁律。
- **替换方案**：**汽车副车架多轴耐久与疲劳分析 (Automotive Front Subframe Multi-Axis Durability & Fatigue)**。完整利用系统已具备的装配体接触、铰接连接器（CONN3D2 / Bushes）、多通道时域工况加载、ASTM E1049 雨流计数法与 Goodman 修正，直接对冲高价值的整车底盘疲劳工程场景。

### 11.2.3 案例来源与选择原则

上述案例优先取自 **Abaqus 2025 官方 Example Problems**，并要求每个案例具有明确工程应用背景、可获得的输入模型/参数/参考结果或实验对照。官方案例库覆盖法兰连接、压力容器、排气歧管、复合材料屈曲、钣金子模型、橡胶自接触、螺纹连接等复杂工程问题；其中部分案例明确引用实验研究或工业模型。

### 11.2.4 每个案例的强制交付物与文件规范

每个正式实战案例必须产生以下标准受控文件：
1. **问题定义与标准参数**：`test_assets/engineering_cases/case_XX_.../problem_statement.json`。
2. **端到端执行驱动与物理提取**：`tools/p2_case_XX_<案例名>_e2e.py`（每个案例的真实求解与 ODB 提取入口）。⚠️ **事实核查：仓库中目前仅存在 `tools/generate_case_01_report.py`（Case 01 的报告渲染与交付环节），Case 02~06 的求解驱动脚本均未提交，Case 01 的求解驱动同样不在仓库内。在补齐这些驱动之前，各案例的可复现性依赖 manifest 内部摘要与已提交报告，而非可重跑脚本。**
3. **密码学验签清单**：`machine_validation/p2_cases/case_XX_..._manifest.json`（含工件 SHA-256、Abaqus 2025 运行标记与 Acceptance 状态）。
4. **独立工程交付报告**：单文件 HTML 与 Markdown 格式（含 Base64 嵌入矢量 SVG 与应力/接触/变形云图）。
5. **自动化回归断言**：全量测试纳入 `tests/test_p2_package_b_cases.py`。
6. **统一资产注册表记录**：在 `validation_assets/registry.json` 中统一登记元数据、官方参考源及资格状态。

### 10 案例的统一验收门槛

- **10/10 真机完成**：必须在 Abaqus 2025 真实机执行，不得以 pytest 或静态 INP 检查替代。
- **10/10 闭环完成**：问题导入 → 求解 → 结果 → Acceptance → 报告全部贯通。
- **10/10 有证据**：每个案例都有独立 Evidence/Manifest，不能用一个 Golden 代表全部。
- **10/10 有参考对照**：能够获得参考结果的案例必须进行数值/趋势/关键响应对照，并记录误差或差异解释；没有公开数值答案的案例必须明确写出可验证的工程判据。
- **复杂度覆盖合格**：10 个案例整体覆盖静力非线性、接触/预紧、热-结构、多步骤、动态/Explicit、大变形、自接触、复合材料/屈曲、子模型/局部精细化、塑性失稳等不同工程类别。
- **报告可交付**：报告不能只是程序日志，必须形成工程师可以审阅的结果说明。
- **失败也必须闭环**：若某案例因输入不足、能力边界或求解器问题无法完成，必须输出 `BLOCKED/NEEDS_CLARIFICATION/RESULT_INVALID` 及完整失败证据；但 Phase 2 最终验收仍要求这 10 个预先选定案例全部达到可解释的最终闭环状态。

### Phase 2 最终收口条件

**Package B (REQ-P2-006) 是 Phase 2 冻结前的硬门槛。**

`Package A (REQ-P2-001~005) = QUALIFIED`
+ `Package B (REQ-P2-006) = 10/10 QUALIFIED`
+ Phase 2 Golden Matrix 完成
+ 全项目严格回归通过
+ 关键负向/Fail-Closed 矩阵通过
+ 真实机证据与报告可追溯
$\implies$ **Phase 2 COMPLETE $\to$ Engineering Kernel FREEZE**。

---

# 十二、Phase 3：Agent 自主性需求清单

## REQ-P3-001：工程任务规划（Planning）
Agent 根据自然语言工程目标生成分析类型、所需输入、材料与边界、网格策略、求解步骤、结果需求、验收目标。

规划必须输出结构化计划，不能直接由模型生成 Abaqus 执行脚本绕过现有 Compiler / Preflight。

## REQ-P3-002：主动澄清（Clarification）
当信息不足、存在歧义或存在高风险假设时：自动识别缺失项、说明影响、给出选项、请求工程师确认；未确认不得静默执行。

复用 P1.1 HITL 与 P1.2 NEEDS_CLARIFICATION 契约，不建立第二套 HITL 状态机。

## REQ-P3-003：受控迭代（Iteration）
Agent 可以根据真实求解结果判断是否需要重新计算，修改有限且可解释的参数，重新 Preflight、重新求解、比较前后结果，并保留完整运行历史。

所有迭代必须经过现有 Acceptance 单一出口。

## REQ-P3-004：求解失败诊断与受控自愈
**对应 P1.4；状态：🟢 QUALIFIED / Phase 3 已启动。**

要求：.msg/.sta/.dat 诊断、有界尝试次数、不可自愈故障立即阻断、RunDiff 保留前后轨迹、自愈不能绕过 Preflight / Acceptance、自愈失败必须保留原始失败证据。

**重要工程红线：** 自愈策略不得为了“让求解器跑通”而未经证据改变工程问题本身；高风险 remediation 必须进入 Assisted/HITL 或 BLOCKED。

## REQ-P3-005：工程结果对比（Comparison）
支持两次 Run 对比、参数方案对比、结果指标对比、ODB / Evidence 对比及工程结论差异说明。

复用现有 AnalysisRunDiff，不得重新建立第二套 Run 状态体系。

## REQ-P3-006：工程方案优化（Optimization）
在已有求解、结果与 Acceptance 能力之上，支持受约束的参数优化：明确设计变量、目标、约束；生成候选方案；运行真实 Abaqus；对候选方案进行 Acceptance；输出 Pareto / 最优候选及证据。

优化器不得直接修改工程模型后宣称结果有效，所有候选均必须经过真实求解与验收。

## REQ-P3-007：Agent 全任务自主闭环

```text
Requirement → Planning → Clarification → Execution → Result Inspection
→ Diagnosis → Controlled Iteration → Comparison → Optimization
→ Verification → Engineering Deliverable
```

这是 Phase 3 的最终目标：**工程师可以把完整分析任务交给 Agent，而不是只能逐条调用工具。**

---

# 十三、Phase 4：产品化需求清单

## REQ-P4-001：MCP / Agent Tool 接入
提供稳定、版本化、Fail-Closed 的工具接口，使外部 Agent 能调用需求入口、模型检查、规划、求解、结果、报告、诊断与历史 Run。

不得允许外部 Agent 绕过核心 Acceptance。

## REQ-P4-002：工程师 UI / HITL 工作台
在 Phase 3 能力稳定后建设 3D 视口、Grounding 候选、HITL 确认、求解进度、诊断与自愈轨迹、结果云图/曲线、Run 对比与工程报告。

UI 只是核心后端的消费者，不得在 UI 层重新实现物理或 Acceptance。

## REQ-P4-003：部署与运行环境
覆盖 Windows + Abaqus 2025、许可证能力探测、headless 执行、环境诊断、日志、任务目录与工件管理、安装与升级。

## REQ-P4-004：Benchmark
建立公开、可复现、可审计的 Benchmark：工程任务、物理结果、失败任务、澄清任务、自愈任务、多方案比较、报告交付。

Benchmark 必须区分软件回归与真实 Abaqus 物理验证。

## REQ-P4-005：Release / 产品交付
建立版本策略、CHANGELOG、安装文档、用户文档、能力矩阵、已知限制、安全与路径脱敏、Evidence / Golden 发布证据及可复现 Release。

---

# 十四、Phase 1~4 总追溯矩阵

| Phase | 原子需求 | 当前状态 |
|---|---|---|
| Phase 1 | P1.0 Agent 主入口 | 🟢 QUALIFIED |
| Phase 1 | P1.1 感知 / Grounding | 🟢 QUALIFIED |
| Phase 1 | P1.2 工程意图推理 | 🟢 QUALIFIED |
| Phase 1 | P1.3 Result Intelligence / Report | 🟢 QUALIFIED |
| Phase 2 (Package A) | REQ-P2-001 Fatigue 工程场景深度 | 🟢 **QUALIFIED** (Gate 8, ASTM E1049, Goodman, Miner) |
| Phase 2 (Package A) | REQ-P2-002 Connector / Joint 工程场景深度 | 🟢 **QUALIFIED** (Gate 13, CONN3D2, drift <= 1e-5 mm) |
| Phase 2 (Package A) | REQ-P2-003 FMBD 工程场景深度 | 🟢 **QUALIFIED** (Gate 14, 刚柔耦合, 能量耗散 < 1%) |
| Phase 2 (Package A) | REQ-P2-004 多物理 / 多工况组合验证 | 🟢 **QUALIFIED** (热-固传递, 预紧模态应力刚化, 库伦摩擦接触) |
| Phase 2 (Package A) | REQ-P2-005 Phase 2 组合 Golden Matrix 收口 | 🟢 **QUALIFIED** (`p2_package_a_manifest.json` 密码学验签) |
| Phase 2 (Package B) | REQ-P2-006 10 个真实复杂工程问题实战终验包 | 🟡 **IN PROGRESS (6/10 QUALIFIED)**: Case 01~06 全部闭环 (法兰垫片密封、RPV螺栓闭合、排气歧管热机械接触、副车架多轴耐久、开孔复合材料壳屈曲、钣金装配子模型)；Case 07~10 待推进 |
| Phase 3 | Planning | ⚪ POST-FREEZE ROADMAP |
| Phase 3 | Clarification | ⚪ POST-FREEZE ROADMAP |
| Phase 3 | Iteration | ⚪ POST-FREEZE ROADMAP |
| Phase 3 | Diagnosis / Self-Healing | 🟢 P1.4 已实现；后续扩展留待冻结后 |
| Phase 3 | Comparison | ⚪ POST-FREEZE ROADMAP |
| Phase 3 | Optimization | ⚪ POST-FREEZE ROADMAP |
| Phase 3 | Full Agent Autonomous Loop | ⚪ POST-FREEZE ROADMAP |
| Phase 4 | MCP | ⚪ POST-FREEZE ROADMAP |
| Phase 4 | UI / HITL Workbench | ⚪ POST-FREEZE ROADMAP |
| Phase 4 | Deployment | ⚪ POST-FREEZE ROADMAP |
| Phase 4 | Benchmark | ⚪ POST-FREEZE ROADMAP |
| Phase 4 | Release | ⚪ POST-FREEZE ROADMAP |
| 全阶段基础设施 | REQ-ISO-001~005 核心仓库与外部工程项目隔离 | 🟢 **IMPLEMENTED (CODE & AUTOMATION)** (P0/P1 代码架构与 23 项隔离专项自动化测试已闭环，全仓全量回归通过；待具备 Abaqus 2025 许可环境执行 P2 物理真机端到端验证) |
| 全阶段基础设施 | 方案 A 原生静默无头动画渲染与单文件 HTML 报告交付 | 🟢 **IMPLEMENTED (CODE & AUTOMATION)** (42 项动画及报告测试全绿，全仓 1147 项全量回归通过) |

> **冻结规则：** 后续开发必须先在本表归属需求；不得因为发现单个功能缺口而重新发明 Phase 或改变总体路线。已有能力优先复用；只有真实缺口才新增代码。

---

# 十五、核心仓库与外部工程项目空间隔离需求规范 (Core vs. External Project Isolation v1.0)

本章确立 Agent 产品自身的核心研发与验证资产，与 Agent 为用户执行具体工程任务时产生的业务数据之间的物理与逻辑隔离边界。代码、运行、清理、验证和交付全链路必须严格遵守这一契约。

## 15.1 总体目标与核心原则

1. **核心资产完整性**：核心代码、自动化测试、Golden Cases、真实机验证套件及产品资格凭据必须由核心仓库（如 `Abaqus-AI-Agent/`）统一受控管理。
2. **用户工程独立性**：具体用户工程项目的原始模型、工作文件、求解中间结果、工程证据和最终交付成果必须持久化存储在核心仓库之外的专用项目空间（如 `D:\AbaqusProjects\Project-A\`）。
3. **运行路径一致性**：模型处理、脚本生成、求解、后处理、报告和交付使用同一个工程项目的统一路径上下文，不得多处脱节。
4. **安全隔离防御**：工程任务禁止意外污染或修改核心代码资产、禁止跨项目覆盖、禁止在配置缺失时静默回退写回仓库内目录。
5. **真实交付闭环**：只有完成真实机求解、结果验证、证据校验和单出口 Acceptance 的任务，才能生成正式交付物。

## 15.2 资产双层分类与归属规则 (REQ-ISO-001)

所有文件资产的归属必须依据用途、所有权与生命周期划分，严禁仅按文件后缀一刀切：

| 资产类别 | 定义与涵盖范围 | 物理存放位置 | 版本控制与生命周期 |
| :--- | :--- | :--- | :--- |
| **A 类：核心产品资产** | • 产品源码、编译器、执行器、Actions、验收与报告管线 (`src/`)<br>• 自动化单元测试、集成测试、回归套件 (`tests/`)<br>• 预制受控测试输入与几何样本 (`test_assets/`)<br>• 真实机资格认证凭据、离屏渲染黄金证据、Manifests (`machine_validation/`)<br>• 官方参考案例索引、统一资产注册表 (`validation_assets/`)<br>• 架构规范、能力边界、审计记录与需求文档 (`docs/`) | **Abaqus-AI-Agent 仓库内** | 由 Git 强版本控制与 CI 门禁直接管理，禁止清理器作为临时文件扫描或删除。 |
| **B 类：用户工程资产** | • 用户提供的原始 `.cae`、STEP、IGES、INP、需求文本<br>• 用户的材料参数表、载荷时程、位移约束与分析工况定义<br>• 面向该工程由 Agent 编译生成的 CAE 脚本、临时模型工作副本<br>• 真实 Abaqus 求解生成的 `.odb`、`.sta`、`.msg`、`.dat`、`.log`<br>• 该任务的证据清单 (Evidence JSON)、关键提取指标、离屏云图<br>• 最终交付给用户的独立 HTML 报告、导出的优化 CAE 与交付 Manifest | **核心仓库之外的外部工程空间**<br>(如 `D:\AbaqusProjects\Project-A\`) | 由外部具体工程项目生命周期管理；严禁未经授权、脱敏和正式审核直接导入仓库；严禁直接写入仓库内部 `runs/`。 |

### 核心补充约束
- **同类型多归属原则**：测试用 `.odb` 可作为 A 类受控资产受版本保护，而用户项目的计算 `.odb` 属于 B 类外部资产，两者生命周期独立。
- **保护不可逆原则**：仓库内已受控的验证资产与黄金基准，绝不得因任何用户工程执行、代码重构或临时文件清理而被误删。

## 15.3 外部工程项目目录规范与架构 (REQ-ISO-002)

外部工程项目空间推荐采用如下职责分层的子目录体系：

```text
D:\AbaqusProjects\Project-A\              # 外部工程项目根目录
├── input/                                # 用户原始输入：原始 .cae, CAD, .inp, 需求文档
├── working/                              # 工作副本：临时模型、编译生成的中间 CAE 脚本
├── solver/                               # 求解工作区：提交 Abaqus 的工作目录，输出 .odb/.sta/.msg/.log
├── evidence/                             # 证据中心：本次 Run 的 Evidence JSON, 指标提取卡, 运行日志
└── delivery/                             # 正式交付：可交付 .cae, 独立 HTML 报告, 高清云图, 交付 Manifest
```

**硬性红线**：用户工程项目的正式输入、中间产物和交付物严禁存放在 Agent 核心仓库内。不得将仓库内的 `runs/` 当作用户工程项目的默认工作区。

## 15.4 运行时路径上下文与路径安全防御 (REQ-ISO-003)

### 统一路径上下文契约
Agent 执行器必须具备感知并统一传递完整工程路径上下文的能力：
- `repo_root`：核心仓库根目录（只读引用源码与核心规范）
- `project_root`：用户工程项目根目录
- `input_dir`：原始输入目录（只读保护）
- `working_dir`：工作副本与中间产物目录
- `solver_dir`：Abaqus 求解运行沙箱
- `evidence_dir`：证据与指标提取目录
- `delivery_dir`：正式工程交付目录

### 路径安全红线
1. **禁止内部回退**：用户工程目录配置缺失或解析异常时，系统必须立即抛出异常并阻断执行（Fail-Closed），严禁静默回退到核心仓库根目录或仓库内 `runs/`。
2. **防路径穿越**：严禁通过 `../` 相对路径跨越边界写回核心仓库；执行前严格检查 `resolve()` 真实绝对路径。
3. **输入不可变性**：Agent 操作必须针对 `working/` 下的模型副本展开，禁止原地覆盖或修改 `input/` 下的原始工程文件。
4. **跨项目防污染**：每次运行必须分配全局唯一 `run_id`，多项目或多次运行禁止共享或覆盖相同文件。

## 15.5 清理机制与双向数据保护 (REQ-ISO-004)

清理机制必须同时保护核心产品资产与外部用户工程资产，严格执行《安全契约 v1.0》：
1. **核心资产免疫**：Git 跟踪文件、`machine_validation/`、`validation_assets/`、`test_assets/` 严禁纳入清理候选。
2. **禁止后缀一刀切**：不得仅凭 `.odb`、`.inp`、`.dat`、`.log` 等求解器后缀判断文件可以删除。
3. **清理作用域限制**：核心仓库的清理脚本权限严格限制在授权范围（如仓库内临时缓存），绝对禁止跨目录递归扫描或误删外部工程目录。
4. **正式交付物免疫**：外部工程空间中 `input/`、`evidence/` 和 `delivery/` 下的文件属于受控交付成果，禁止任何自动化清理流程处理。
5. **完整性校验**：所有获授权删除的文件必须在删除前重算 SHA-256 并与清单比对，不匹配时拒绝删除。

## 15.6 CAE 工程执行与交付闭环 (REQ-ISO-005)

目录隔离是基础，Agent 执行用户任务时必须完成真实的工程闭环：

| 执行阶段 | 核心验证与验收要求 |
| :--- | :--- |
| **1. 需求解析与规划** | 解析分析意图，提取几何、材料、边界与工况；发现信息不全时触发交互式澄清 (NEEDS_CLARIFICATION)，不得凭空捏造。 |
| **2. 模型操作与编译** | 从 `input/` 复制到 `working/` 生成工作副本；通过 Intent Compiler 生成 CAE 执行脚本，确保原始模型不被破坏。 |
| **3. 求解监控与自愈** | 在 `solver/` 真实调用 Abaqus 2025 求解；实时监控 `.msg`/`.sta`，若发散则在允许阈值内受控微调步长或接触阻尼自愈。 |
| **4. 结果提取与验收** | 验证 ODB 完整性（检查有效 Step、Frame、S/U/CPRESS 场输出）；经过单一出口 Acceptance 判定，严禁跳过验收。 |
| **5. 离屏渲染与证据** | 启动无头 Abaqus Viewer，从实际求解出的 ODB 渲染云图与历程曲线，生成带会话签名的 Evidence JSON。 |
| **6. 正式交付与检查** | 汇总生成独立单文件 HTML 报告与最终 CAE 模型至 `delivery/`；校验最终 CAE 模型可被重新打开且拓扑完整。 |

### 验收红线
- 求解器退出码为 0 不等于工程验收通过。
- `SKIPPED` 严禁被视为 PASS。
- 关键物理量缺失时严禁伪造数值。
- 未通过验收的中间诊断材料严禁冒充正式工程交付物。

## 15.7 代码整改与分阶段实施状态

- **P0-1：全链路路径审计 (Path Audit)** [✅ **COMPLETED**]：全面追踪输入读取、模型修改、脚本生成、求解、ODB 提取、云图渲染、报告输出与清理工具的读写路径来源。
- **P0-2：资产分类与路径契约 (Contract Design)** [✅ **COMPLETED**]：在 `paths.py` 中落地 `ExternalProjectContext`，建立 `input/`、`working/`、`solver/`、`evidence/`、`delivery/` 严格子目录级约束，增设 `_validate_identifier` 防穿越与 `prepare_working_copy` 防覆盖保护。
- **P0-3：路径安全防御与清理加固 (Security Hardening)** [✅ **COMPLETED**]：在 `analysis_run.py` 强制校验显式 `workdir` 必须在 `solver_dir` 内；在 `agent.py` 实施前置生产隔离门禁 Fail-Closed 拦截向仓库内静默回退；`clean_workspace.py` 已收紧并经过负向测试。
- **P1-1：工程运行链路贯通 (E2E Integration)** [✅ **COMPLETED**]：复用现有 `AnalysisRun`、`agent.py` 求解和报告链路，注入 `evidence_dir` 至运行时环境，测试验证外部目录产物生成。
- **P1-2：交付物验证与可编辑性检查 (Delivery & Model Verification)** [🔄 **PARTIALLY COMPLETED**]：自动化测试验证了模拟环境下的交付产物路径与生成；真实 CAE 模型重新打开完整性待 P2 物理机验证。
- **P2：回归测试与真机验收 (Regression & Live Gate)** [🔄 **AUTOMATION COMPLETED / LIVE GATE PENDING**]：完成 23 项隔离专项测试与 14 项清理契约测试，1142 项自动化回归 100% 通过；待在具备 Abaqus 2025 许可的物理环境中完成实际工程项目的端到端真机闭环。

## 15.8 最终验收准则

只有同时满足以下条件，本项隔离治理才认定为完成：
1. 核心代码与测试资产完整保留在核心仓库内，各项测试与发布门禁无回退；
2. 用户工程项目的输入、中间文件、求解产物与交付成果全部落在仓库外的指定工程目录中；
3. 全链路具备统一、可追溯的项目路径上下文；
4. 路径越界、跨项目覆盖、篡改原始输入及静默回退测试 100% 拦截并抛出异常；
5. 清理工具无法触及或误删核心验证资产和外部工程交付物；
6. 离屏云图、报告指标与交付物均与本次真实运行一一对应并具备防伪追溯；
7. 正式交付的 CAE 模型经真实验证可重新加载；
8. 在真实 Abaqus 2025 环境中至少完成 1 个代表性工程项目的完整外部端到端闭环验证（已在外部独立项目 `D:\AbaqusProjects\Jansen_Mechanism` 完成 MBD-3：IFToMM Planar Jansen 步行机构动力学真机全流程闭环验证并通过验收）。
