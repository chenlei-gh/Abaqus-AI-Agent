# 工业级 CAE 工程分析报告标准规范模板 (Industrial CAE Deliverable Report Standard)

> **版本契约**: `CAE-REPORT-STD-V1`  
> **适用范围**: Abaqus-AI-Agent Phase 2 Package B 真实复杂工程全链路实战 (REQ-P2-006)、Package A 组合验证及后续生产交付  
> **设计原则**: **图文并茂、数据翔实、机理透彻、单一出口、双重契约 (人类可读 Markdown/HTML + 机器可读 JSON Payload)**

---

## 1. 规范背景与工业标准对标

本报告模板参考并吸纳了汽车主机厂（OEM）、航空航天结构咨询机构及特种装备行业通行的 CAE 仿真报告工程规范，对标以下权威工程标准：

1. **VDI 2230 / ASME Section III & VIII**: 螺栓法兰装配、预紧力损失、垫片密封比压演化、应力分类评定规范；
2. **ISO 185 / EN-GJS-SiMo**: 高温蠕变、热疲劳、温变材料力学与导热物理本构规范；
3. **SAE J1397 / ASTM E8**: 结构屈服强度、极限强度、安全裕度与局部应力集中评定准则；
4. **FEA 验证与确认 (V&V 40 / ASME V&V 10)**: 求解器状态、网格收敛性、反力平衡度、能量守恒度与接触无畸变门禁。

---

## 2. 标准报告结构体系 (15 核心章节)

所有由 Agent 生成的最终交付报告均严格遵循以下 15 个层级的模块化工程结构：

```
1. Executive Summary & KPI Banner (执行摘要与核心指标看板)
2. Model Information & Assembly Topology (几何模型与装配拓扑关系)
3. Material Constitutive Specifications (材料本构与温变物性表)
4. Prescribed Boundary Conditions (各分析步约束条件与自由度控制)
5. Operational & Thermal Loading Procedures (多物理场环境与外载步序)
6. Solver Execution & Step Sequencing (求解器步序控制与收敛准则)
7. Finite Element Discretization & Mesh Audit (网格特征与质量门禁表)
8. Multi-Physics Simulation Results (仿真核心数据提取表)
8b. Result Intelligence & Local Hotspots (局部热点坐标/节点、平衡度、FoS/MoS)
9. Figures & Visual Interpretations (图文并茂的核心云图集)
10. Detailed Engineering Verification Checks (工程准则详细验算项)
11. Acceptance Criteria & Gate Audit (Gate 1~14 门禁状态与判决)
12b. Deep Engineering Mechanism Analysis (深度物理机理与失效诱因解析)
13b. Design Recommendations & Countermeasures (工程设计改进方案与对策)
16. Assumptions & Scope of Limitations (工程假设与适用局限性)
17. Evidence Manifest & Cryptographic Signatures (SHA-256 哈希工件可信溯源)
```

---

## 3. 各章节要素与渲染规范

### 3.1 Executive Summary & KPI Banner
- **工程目标**: 清楚阐述被评估组件的核心功能、工况背景与评估目标；
- **核心结论**: 明确给出结构安全性评估结论（PASS / FAIL / MARGINAL）；
- **顶栏 KPI 卡片**:
  - `Overall Acceptance`: 整体门禁状态（通过/阻断）
  - `Peak Temperature`: 核心热区最高温度及发生位置
  - `Operating Sealing CPRESS`: 关键密封面有效压强及安全裕度
  - `Differential Thermal Slip`: 差动热膨胀相对滑移量及孔径间隙比
  - `Peak Mises Stress`: 最大局部等效应力及对应温区屈服比

### 3.2 Model Information & Assembly Topology
- **装配组件清单表**: 标明组件名称（Manifold Casting, MLS Gasket, Cylinder Head, Fasteners 等）、材料归属与装配角色；
- **几何关键尺寸表**: 总体跨距、管径、壁厚、倒角半径、螺栓规格与孔隙配合公差；
- **装配示意图 (Figure 1)**: 必须包含全局三维装配轮廓、各部件空间位置、几何尺寸标注、热流与紧固件分布。

### 3.3 Material Constitutive Specifications
- **材料牌号与状态**: 严格标注标准牌号（如 EN-GJS-SiMo、HT250 / Gray Iron、10.9-Class Fastener）；
- **温变物性数据表**: 必须给出常温与高温工作点下的物性参数：
  - 弹性模量 $E(T)$ (MPa)
  - 泊松比 $\nu$
  - 热膨胀系数 $\alpha(T)$ ($10^{-5}/\text{K}$)
  - 热导率 $k(T)$ ($\text{W}/(\text{m}\cdot\text{K})$)
  - 高温屈服强度 $S_y(T)$ 与抗拉强度 $S_u$ (MPa)

### 3.4 Boundary Conditions & Kinematic Restraints
- **约束区域与自由度**: 明确各步的刚体约束位置（如缸盖底面 6 自由度固定）；
- **接触界面边界**: 明确接触对（Master-Slave 角色、小滑移/有限滑移、罚刚度系数与摩擦系数 $\mu$）。

### 3.5 Operational & Thermal Loading Procedures
- **分析步定义**: 严格区分布序逻辑：
  - Step 0: 稳态/瞬态热传导（燃气对流 $h_{\text{gas}}, T_{\text{gas}}$、外壁对流 $h_{\text{ext}}, T_{\text{ambient}}$、水道导热 $T_{\text{coolant}}$）；
  - Step 1: 常温螺栓预紧加载（Bolt Pretension 载荷施加与垫片压实）；
  - Step 2: 热机耦合运行工况（螺栓锁长 `LOCK_LENGTH`、导入稳态温度场载荷、热膨胀差动滑移）。

### 3.6 Solver Execution & Step Sequencing
- **求解器参数控制**: 几何非线性开关 (`NLGEOM=YES`)、初始时间步长、最小步长、收敛容差与求解器类型（Direct Sparse Solver）。

### 3.7 Finite Element Discretization & Mesh Audit
- **离散网格特征**: 单元类型（热力耦合单元 C3D8RT、高阶四面体 C3D10MT 等）、总节点数、总单元数、关键区域局部网格细化尺寸；
- **网格质量门禁表 (Mesh Quality Audit)**:
  - 最小雅可比矩阵比 (Jacobian Ratio $\ge 0.60$)
  - 最大单元长宽比 (Aspect Ratio $\le 4.5$)
  - 严重畸变单元数 (Worst Distortion Elements = 0)
  - 最大翘曲角 (Warping Angle $\le 15^\circ$)

### 3.8 Multi-Physics Simulation Results & Visual Interpretations
- **结构化结果表格**: 关键物理量实测值、单位、抽取源；
- **矢量高清工程图解集 (SVG/PNG)**:
  - **Figure 1**: 装配几何、紧固件布置与多物理场边界条件示意图；
  - **Figure 2**: 稳态温度场分布云图 (NT11)，标有热流方向向量、高低温测点探针 Callout 及连续色阶标尺；
  - **Figure 3**: 耦合热应力分布云图 (von Mises)，标有中性膨胀轴、外侧差动滑移剪切向量、关键过渡圆角应力集中热点及屈服限值刻度；
  - **Figure 4**: 结构完整性多指标综合评估仪表盘，对比垫片密封压强、螺栓孔滑移量、圆角热应力与门禁限值。

### 3.9 Localized Spatial Field Hotspots & Derived Metrics
- **局部热点 (Top-K Hotspots)**: 标明峰值应力/温度所在的单元编号、节点编号、三维空间坐标 $(X, Y, Z)$；
- **静态平衡与能量守恒**:
  - 反力总和与外载平衡相对误差 ($\le 0.1\%$)；
  - 稳态热传导能量守恒残差 ($\le 0.1\%$)；
- **派生安全指标**: 明确区分事实与结论，计算安全系数 (Factor of Safety, FoS) 与安全裕度 (Margin of Safety, MoS)。

### 3.10 Acceptance Criteria & Gate Audit
- **Deterministic Gate Audit (Gate 1~14)**:
  - Gate 1: 求解器执行状态 (PASS)
  - Gate 2: ODB 存储完整性 (PASS)
  - Gate 7: 非线性收敛性 (PASS)
  - Gate 9: 接触界面非穿透与滑移正规化 (PASS)
  - Gate 10: 步序加载正确性 (PASS)
  - Gate 11: 能量守恒平衡 (PASS)
  - Gate 12: 工程准则限值全量合格 (PASS)

### 3.11 Deep Engineering Mechanism Analysis (深度物理机理分析)
必须针对复杂耦合机理展开深入的物理溯源，例如：
1. **差动热膨胀剪切机理**: 歧管整体热伸长量 $\Delta L = \alpha \cdot L \cdot \Delta T$ 与缸盖在水冷状态下的变形差，导致外侧螺栓承受巨大侧向剪切位移；
2. **汇流过渡倒角热应力集中机理**: 高温排气管与主管交汇处刚度突变，管壁温度梯度导致双向热弯曲力矩自锁，引发局部应力集中；
3. **垫片密封比压衰减机制**: 热负荷膨胀使歧管法兰产生翘曲力矩，螺栓孔间跨距中心密封比压下降，须验证最低接触压强高于燃气冲刷阈值。

### 3.12 Practical Engineering Recommendations & Countermeasures (工程设计改进建议)
提供具有主机厂实战价值的具体工程对策：
1. **外侧螺栓孔长圆孔/腰形孔设计**: 将外侧排气口法兰螺栓孔加工为轴向长圆孔，释放热膨胀自由度，降低螺栓弯剪应力；
2. **汇流过渡倒角结构优化**: 增大两管交汇处过渡圆角半径（如 $R4 \rightarrow R6\,\text{mm}$），改善应力流过渡，预计可降低峰值应力 20%~30%；
3. **分步扭矩-转角拧紧工艺**: 制定合理的螺栓拧紧顺序（由中心向外对称交替打紧），避免冷装配初期法兰翘曲。

### 3.13 Evidence Manifest & Cryptographic Signatures
- **工件指纹**: 输出每个生成文件（INP、ODB、MSG、DAT、SVG、MD、HTML）的字节大小与 SHA-256 签名，保障防篡改合规。

---

## 4. 报告交付质量自检清单 (Checklist)

| 检查维度 | 合格标准 | 状态 |
| :--- | :--- | :---: |
| **可读性** | 具备 Executive Cards、斑马纹表格、悬浮高亮、PASS/FAIL 徽章与打印优化 | [x] |
| **图文完备性** | 包含 4 幅高清晰度矢量图，关键尺寸、载荷、热点、色标全部明确 | [x] |
| **工程深度** | 包含深入的差动膨胀剪切物理机理与 3 条以上具体工业设计对策 | [x] |
| **门禁严谨性** | 严格区分测量事实与工程准则，单出口验签通过，无越权判定 | [x] |
| **安全合规** | 严禁出现主机绝对路径（CHK-02），严禁在 CSS/文本中出现硬编码 "AI" 关键词 | [x] |
