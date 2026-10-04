# P1 阶段商业产品化与工程 Agent 需求清单 (Product Requirements Backlog)

**版本:** 2026-10-04  
**基线状态:** 20 L4 / 0 L3 物理工程领域已全部通过真实机全链路合格认证 (Agent Full-Chain Qualified)  
**战略阶段:** Phase P1 — 商业产品化与自主工程智能体 (Commercial Productization & Autonomous Engineering Agent)

---

## 一、背景与战略定位

经过 Phase A 至 Phase M 以及 Post-RC1 关键战役（GA-2A 空间拾取、GA-F4 疲劳全链路、GA-2B 意图落地与 HITL 协议、GA-C4 机构连接器、GA-M4 刚柔耦合系统），**Abaqus-AI-Agent 已全面完成 20 个物理工程领域的 L4 真实机全链路认证**。

当前系统已建立起无可撼动的后端工程内核：
- 单一出口与防伪门禁 (`AnalysisRunner` + `EvidenceManifestV2` + `evaluate_result_acceptance`)；
- 真实 Abaqus 2025 求解器闭环与真实 ODB 张量提取；
- 严密的物理检验与反力平衡验证（例如反力平衡相对误差 $< 10^{-6}$）；
- 负向探测 100% fail-closed（阻断未授权修改、证据篡改、字段缺失与非法状态转换）。

**当前的核心瓶颈与战略重点已彻底从“求解器物理领域数量扩张”，全面转移至“商业级工程产品化与真实工程需求进入内核的能力”。**

真实工程师不会直接以严格的 JSON 字典调用 API。工程师的典型输入是：
> “帮我评估这个支架，Q235 材料，底部四个孔固定，顶部受到约 5 kN 向下的力，计算最大应力和安全系数，并给出是否满足要求的报告。”

或者是一张标注了公差与载荷箭头的**零件工程图纸**、现场手机拍摄的**受力结构照片**、或者包含红圈与文字注释的 **CAD 视口截图**。

因此，**Phase P1 商业产品化**的目标是：**在坚守零伪造、零黑盒猜测、fail-closed 的工程底线前提下，将 20 L4 的硬核物理能力封装为普通工程师触手可及、可信赖交付的商业级工程 Agent 产品。**

---

## 二、P1 产品需求矩阵与执行优先级

Phase P1 严格按照系统层解耦、执行层渐进、真实工程可验证的次序推进：

| 需求代号 | 需求模块名称 | 核心目标 | 优先级 | 当前状态 |
|:---|:---|:---|:---:|:---:|
| **P1.0** | **Agent 产品主入口** | 自然语言/结构化工程需求输入 $\to$ 声明式意图编译 $\to$ 20 域能力解析 $\to$ 真实机全链验证 $\to$ 统一任务结果承载 | **P0 (已收口)** | 🏆 **QUALIFIED (Real Abaqus 2025)** |
| **P1.1** | **真实工程多模态感知** | 真实工程图/照片/截图（PNG/JPG/PDF）OCR 识别、尺寸与载荷提取 $\to$ `VisualCallout` $\to$ HITL 门禁 | **P0 (并重协同)** | 🚧 **READY TO EXECUTE** |
| **P1.2** | **工程参数推理与交互补全** | 缺失参数检测、推荐依据记录、HITL 双向确认、严守 fail-closed（不猜测黑盒参数） | **P0 (并重协同)** | 🚧 **READY TO EXECUTE** |
| **P1.3** | **交付级多维结果可视化** | ODB 应力/位移云图无头渲染提取、历程曲线、能量平衡监测看板、交互式工程报告 | **P1** | 📋 **PLANNED** |
| **P1.4** | **求解故障智能诊断与自愈** | 截获 `.msg`/`.sta` 发散特征 $\to$ 根因诊断 $\to$ 生成受控松弛/网格细化修复策略 $\to$ 自动重算与 Diff 对比 | **P2** | 📋 **PLANNED** |
| **P1.5** | **商业级工程工作台 (UI/UX)** | Web 协同界面、3D 模型与视口交互拾取、HITL 确认卡片、任务历史与审计追溯（前序能力成熟后再做） | **P2** | 📋 **PLANNED** |

---

## 三、P1.0 Agent 产品主入口（已完成）

### 3.1 核心交付与真实机审计收口
P1.0 基础设施与产品主入口已全面完成代码加固、Fail-Closed 防伪门禁与真实 Abaqus 2025 黄金案例闭环认证，项目全量测试达到 **704/704 PASS**：
1. **统一高层调用 API (`AbaqusAIAgent.solve_requirement`)**：
   - 接受自然语言文本字符串或结构化意图对象；
   - 自动完成需求澄清检测；如果缺失关键物理定义或存在歧义，返回 `status=NEEDS_CLARIFICATION`，清晰告知工程师缺失的参数项；
   - 若参数完备，自动完成端到端求解并输出结构化结果。
2. **声明式编译适配层 (`compile_engineering_intent`)**：
   - 将高层 `EngineeringIntent` 转换为经过严格量纲、拓扑检查的 `ActionPlan`；
   - 自动补全模型初始化 (`mdb.Model`) 与网格模块环境，彻底消除手写动作脚本与底层求解器之间的鸿沟。
3. **能力注册与物理配置解耦 (`resolve_capability`)**：
   - 覆盖全部 **20 个 L4 物理工程领域**；
   - 根据意图自动匹配对应的 `PhysicsResultProfile`，提取对应的必需字段（如 S, U, RF, TEMP, CU, CTF 等）与物理验收门禁（Gates 1~14）。
4. **严格防伪与单一出口判定 (Single-Exit Acceptance)**：
   - `TaskStatus.COMPLETED` 判定要求 `run.state == AnalysisRunState.ACCEPTED`、`run.engineering_status in ("ACCEPTED", "RESULT_VALID")` 且 `run.acceptance_passed is True`；
   - 严禁任何 `external_input` 或未通过 ODB 真实凭证验签的运行伪造为 `COMPLETED`。
5. **真实 Abaqus 2025 黄金算例闭环 (`tools/p1_product_solve_golden_e2e.py`)**：
   - 运行链路：自然语言需求 $\to$ `solve_requirement()` $\to$ 意图编译 $\to$ Preflight $\to$ Abaqus 2025 求解 $\to$ ODB 提取 $\to$ Evidence V2 $\to$ Acceptance $\to$ TaskResult $\to$ 工程报告；
   - 真实位移 2.166 mm、Mises 应力 505.03 MPa，全数满足理论解；
   - 完整采集并签署 6 类物理工件（`.inp`, `.odb`, `.sta`, `.msg`, `.dat`, `.log`）SHA-256；
   - 6 项负向探针（模糊提示澄清、不支持物理域拦截、缺几何拦截、缺材料拦截、外部伪造防篡改、Preflight 阻断）100% fail-closed；
   - 凭证已固化于 `machine_validation/p1_product_solve_manifest.json`。

---

## 四、P1.1 真实工程多模态感知与图纸/照片 OCR（下一主线 🎯）

### 4.1 业务与工程背景
- 在 GA-2B 阶段，我们成功打通了 `VisualCallout` $\to$ `GroundingObservation` $\to$ `GroundedRegion` $\to$ HITL 协议确认 $\to$ Abaqus 2025 的全链路。
- 然而，GA-2B 当前使用的是**结构化 Callout Ingestion**（基于规则提取结构化文本中的固定端、载荷与数值）。
- **P1.1 的目标是补齐真正的“视觉输入感知层”**：使系统能够直接读取真实的图像格式（PNG, JPEG, PDF 图纸），提取几何、尺寸、形位公差、载荷箭头、文字说明等工程要素。

### 4.2 核心需求与设计契约
1. **多格式图像/文档摄入 (Ingestion Pipeline)**：
   - 支持机械工程二维图纸（DWG 转 PDF/PNG，正交三视图、局部剖视图、轴测图）；
   - 支持工程师拍摄的现场实物照片、白板草图及带有标记（红圈、手绘箭头）的屏幕截图。
2. **多模态特征识别 (Vision Perception Engine)**：
   - **OCR 文本检测与识别**：技术要求、表面粗糙度、焊接代号、材料标注（如 "Q235-A", "45#", "AL6061-T6"）；
   - **尺寸标注线与公差识别**：长宽高、孔径、跨度、板厚；
   - **工程符号与箭头解析**：载荷作用点、方向矢量（沿轴向、法向、垂直向下）、约束符号（固定端、铰支座、对称面）。
3. **结构化转化 (`VisualCallout` 协议输出)**：
   - 将识别出的每一处视觉信息转换为规范的 `VisualCallout`：
     ```python
     VisualCallout(
         callout_id="callout_01",
         callout_type="load_arrow",
         text_content="5 kN 垂直向下",
         magnitude=5000.0,
         unit="N",
         direction_vector=(0.0, -1.0, 0.0),
         region_box=(0.45, 0.12, 0.55, 0.20),
         confidence=0.92
     )
     ```
4. **绝对防伪红线（Anti-Hallucination & Security Redlines）**：
   - 🛑 **严禁 Vision 模型直接生成 Abaqus CAE/Python 脚本**；
   - 🛑 必须先输出 `GroundingObservation` 并映射到 3D CAD/CAE 几何实体；
   - 🛑 **必须触发强制人机交互门禁 (HITL Gate)**：置信度低于 0.95 或存在多重几何候选时，必须高亮候选区域供工程师点击确认，严禁 Agent “替用户决定”载荷作用位置。

---

## 五、P1.2 工程参数智能推理与交互补全

### 5.1 业务与工程背景
工程用户常常省略部分建模决策（例如未指定分析步时长、未声明网格类型、未给出泊松比或仅指定了商用材料家族名称）。

### 5.2 核心需求与设计契约
1. **材料本构自动匹配与智能补全**：
   - 识别常见工程材料别名（如“不锈钢”、“304”、“铝合金”、“尼龙66”、“PA66-GF30”）；
   - 调用 Phase K `MaterialResolver`，从受控的 CAMPUS / TDS 材料库中提取准确的物理参数（弹性模量 $E$、泊松比 $\nu$、密度 $\rho$、屈服应力 $\sigma_y$ 等）；
   - 若用户给出的工作温度超出材料测试环境（如在 $150^\circ\text{C}$ 下使用常温数据），触发明确警告并要求确认。
2. **网格策略智能推荐（防黑盒公理）**：
   - 依据模型特征尺寸、分析类型（静力、接触、冲击、弯曲主导）推荐单元类型（如弯曲主导推荐 C3D20R / C3D8I，大变形/接触推荐 C3D8R 配合沙漏控制）；
   - **防伪与透明性原则**：
     > **系统严禁在无依据的情况下“默默赋予 5mm C3D8R”。**
     推荐策略必须输出显式的工程依据（如基于最小壁厚、应力集中区域特征），并在任务摘要与报告中显式记录；若网格尺寸过粗无法捕捉应力梯度，需在 Preflight 中予以警示。
3. **载荷与边界歧义交互消除 (Ambiguity Resolver)**：
   - 当检测到对称性工况、可能产生刚体位移未完全约束（Mechanisms / Singularities）时，主动提示工程师添加必要弱刚度或对称约束。

---

## 六、P1.3 交付级工程成果多维可视化与深度报告

### 6.1 业务与工程背景
CAE 工程师交付给主管或客户的核心成果不是纯文本数字，而是云图、曲线与专业工程报告。

### 6.2 核心需求与设计契约
1. **无头自动化 ODB 云图提取 (Headless Viewport Rendering)**：
   - 通过原生 Abaqus/CAE 或 ODB API 渲染无头图像：
     - Mises 等效应力云图 (S, Mises) 与危险点（Hotspot）自动标注；
     - 位移幅值云图 (U, Magnitude) 与变形放大显示 (Deformed Shape)；
     - 接触状态与接触压力云图 (CPRESS / COPEN)；
     - 温度场分布云图 (TEMP) 与相对热流矢量。
2. **历程曲线与物理守恒监测图表**：
   - 动力学能量平衡曲线：全系统总能量 $E_{\text{total}}$、内能 $\text{ALLIE}$、动能 $\text{ALLKE}$、伪能比 $\text{ALLAE}/\text{ALLIE}$；
   - 载荷-位移历程曲线 (P-u curve)；
   - 铰链/连接器相对角位移历程与反力/反力矩历程。
3. **交付级独立工程报告 (Deliverable Engineering Report)**：
   - 自动生成独立的 HTML 交付文件（内嵌 Base64 图像、交互式图表、收敛指标历史与 Evidence V2 验签徽标）；
   - 包含结论评定：安全系数 ($SF = \sigma_{\text{yield}} / \sigma_{\max}$)、许用变形判定、疲劳累计损伤与预期寿命。

---

## 七、P1.4 求解故障智能诊断与自愈闭环 (Solver Doctor)

### 7.1 业务与工程背景
非线性分析（材料非线性、接触、几何大变形）中，首次计算发散（Cutback、奇异、不收敛）是家常便饭。优秀的工程 Agent 必须具备自愈能力。

### 7.2 核心需求与设计契约
1. **深度求解监视器诊断 (`.msg`, `.sta`, `.dat`)**：
   - 实时解析发散根因：
     - `NUMERICAL_SINGULARITY`：刚体位移未约束、机构运动或局部解耦；
     - `SEVERE_DISCONTINUITY_ITERATION (SDI)`：接触状态剧烈震荡、穿透未闭合；
     - `CUTBACK_EXCEEDED`：时间增量步衰减至极小阈值（如 $< 10^{-5}$）导致求解器 Abort；
     - `PLASTICITY_DRIFT`：塑性迭代无法回到屈服面。
2. **受控自愈与修复策略库 (Bounded Remediation Playbooks)**：
   - 针对接触发散：自动施加接触面初始稳定阻尼（Contact Stabilization），并在收敛后检查稳定能量比（$< 2\%$）；
   - 针对时间步发散：调整初始时间步长、放宽或收紧增量步控制参数 (`*CONTROLS`)；
   - 针对局部奇异：检测未约束自由度，生成辅助软弹簧或修正约束面定义。
3. **自愈审计与对比溯源 (Diff & Auditability)**：
   - 自愈过程不掩盖问题：报告中必须完整呈现 `Run 1 (Failed)` 与 `Run 2 (Healed)` 的对比明细；
   - 严格防伪：自愈引入的数值稳定项必须经验收门禁确认未扭曲主物理响应。

---

## 八、P1.5 商业级工程工作台 (Web / Desktop UI)

### 8.1 核心需求与设计契约
1. **工程师交互式界面**：
   - 基于轻量级 Web 或现代桌面端（提供 3D WebGL / Three.js 视口）；
   - 支持通过鼠标在 3D 模型表面直接点击面/边，实时生成候选并传递给后端 `RegionResolver`。
2. **HITL 确认与协同卡片**：
   - 当多模态视觉或自动推理提出候选意图时，弹出可视化的工程决策卡片（“识别到底部面为固定约束，置信度 94%，是否确认？”）。
3. **企业级调度与资产管理**：
   - 对接 GA-3 的 `JobQueue` 与并发 Worker 池；
   - 集中管理 Abaqus 许可令牌与计算节点分配；
   - 案例记忆库（Case Memory）与历史算例检索对比。

---

## 九、质量与防伪铁律（Engineering Redlines）

在推进 P1 全线产品化任务时，全团队及智能体必须严格坚守以下公理：

1. **零伪造原则 (Zero Fabrication)**：
   严禁使用任何经验公式、假桩或模拟数据冒充求解器结果。所有物理数据必须来自真机 ODB 提取或受控的严格解析理论解。
2. **Fail-Closed 闭环原则**：
   在任何环节（参数缺失、拓扑无法解析、网格不合法、求解器发散未收敛、证据签名损坏），系统必须明确报告失败并进入 `BLOCKED` / `NEEDS_CLARIFICATION` / `RESULT_INVALID`，绝不允许伪装成 `ACCEPTED`。
3. **单一出口原则 (Single-Exit Acceptance)**：
   外部输入、模型修饰、非标准动作脚本严禁直接触碰 `ACCEPTED` 状态。只有经由 `AnalysisRunner` $\to$ `preflight` $\to$ Abaqus 求解 $\to$ ODB 提取 $\to$ `EvidenceManifestV2` 验签 $\to$ `evaluate_result_acceptance`，才是通往工程合格裁决的唯一合法路径。
4. **范围诚实原则 (Stated Scope Precision)**：
   如实陈述已验证的边界。宣称“20 个物理领域 L4 认证”是指在各领域已声明的物理基准和工程契约范围内达到全链路闭环，严禁夸大为“无限制支持 Abaqus 全部几十万个关键词或任意复杂拓扑”。
