# Phase 2 Package B: 10 大真实复杂工程实战案例筛选与评估矩阵

## 一、筛选背景与核心准则

根据用户与架构委员会对 Phase 2 的裁决，Package B 不应作为盲目的功能扩张实验，而必须作为 **Phase 2 最终硬门槛与工程内核冻结基准 (Engineering Kernel Freeze Gate)**。

### 1.1 五维评分准则 (Evaluation Criteria)
每一个入选案例必须经过以下五维指标的严格量化评估：

1. **工程复杂度 (Engineering Complexity, 1~5 星)**：是否具备真实的工业模型复杂度（如接触非线性、预紧力、多步骤加载、材料非线性、多部件装配体等）。
2. **能力覆盖度 (20 L4 Capability Coverage, 1~5 星)**：能否有效覆盖已通过 L4 验收的 20 项核心物理能力。
3. **组合价值 (Multi-Physics Composition Value, 1~5 星)**：是否体现多物理域或多步骤组合（如 Preload $\to$ Static, Contact + Plasticity, Thermal $\to$ Structural $\to$ Fatigue 等）。
4. **公开参考基准可得性 (Reference Benchmark Availability, 1~5 星)**：是否有权威公开出版物、Abaqus 官方 Example Problems、ASME/SAE/ISO 规范解或实验数据作为绝对校准对照。
5. **新物理域风险 (New Domain Risk, 低/中/高)**：**必须为“低”**。严禁为了凑案例而强行引入当前无内核支撑的冷门物理域（如显式多组分气体充气流体腔、粒子流动力学等）。

---

## 二、候选案例池评估与筛选分析表

| 序号 | 候选案例名称 | 工业领域 | 复杂度 | 能力覆盖 | 组合价值 | 参考基准 | 新域风险 | 综合裁决 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **01** | **螺栓管法兰垫片密封分析** | 压力容器/管道 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ✅ **入选 (Case 01, 已完成)** |
| **02** | **反应堆压力容器螺栓闭合结构** | 核电/重型装备 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ✅ **入选 (Case 02, 当前推进)** |
| **03** | **重载发动机排气歧管热机械接触** | 汽车动力总成 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ✅ **入选 (Case 03)** |
| *--* | *侧气帘安全气囊冲击试验* | *汽车被动安全* | *★★★★★* | *★★☆☆☆* | *★★☆☆☆* | *★★★★☆* | **极高** | ❌ **排除 (依赖冷门流体腔充气模型)** |
| **04** | **汽车副车架多轴耐久与疲劳分析** (替换项) | 汽车底盘结构 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ✅ **入选 (Case 04, 替换气囊)** |
| **05** | **开孔层合复合材料圆柱壳屈曲分析** | 航空航天结构 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | ✅ **入选 (Case 05)** |
| **06** | **多层钣金装配体子模型精细化分析** | 车身/通用机械 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | ✅ **入选 (Case 06)** |
| **07** | **悬架超弹性缓冲块大变形自接触** | 汽车底盘工程 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | ✅ **入选 (Case 07)** |
| **08** | **石油套管特殊螺纹接头弹塑性接触** | 油气能源工程 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ✅ **入选 (Case 08)** |
| **09** | **内燃机气缸盖热机械低周疲劳评定** | 发动机工程 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | **低** | ✅ **入选 (Case 09)** |
| **10** | **薄壁管道弯头弹塑性失稳极限承载** | 化工/核电管道 | ★★★★☆ | ★★★★★ | ★★★★☆ | ★★★★★ | **低** | ✅ **入选 (Case 10)** |

### 2.1 关键剔除与替换论证 (Airbag Impactor $\to$ Subframe Fatigue)
- **剔除原因**：Abaqus 官方侧气帘案例 (`simaexa-c-airbag.htm`) 深度依赖 `*AIRBAG INFLATOR`、`*FLUID CAVITY` 与多组分热力学气体状态方程（EOS），且存在高度特异性的薄织物褶皱自接触显式算法。该领域并不属于主流通用结构工程核心，若在此阶段引入会导致大量流体腔特化逻辑侵入核心编译器，违背“基于已有能力组合，不新增物理域”的铁律。
- **替换方案**：**汽车副车架多轴耐久与疲劳分析 (Automotive Front Subframe Multi-Axis Durability & Fatigue)**。完整利用系统已具备的装配体接触、铰接连接器（CONN3D2 / Bushes）、多通道时域工况加载、ASTM E1049 雨流计数法与 Goodman 修正，直接对冲高价值的整车底盘疲劳工程场景。

---

## 三、最终冻结的 10 大复杂工程实战清单

```text
Package B: 10 Authentic Complex Engineering Projects
├── Case 01: Bolted Pipe Flange Connection with Gasket Sealing [QUALIFIED]
├── Case 02: Reactor Pressure Vessel (RPV) Bolted Closure Joint [QUALIFIED]
├── Case 03: Heavy-Duty Engine Exhaust Manifold Thermo-Mechanical Contact [QUALIFIED]
├── Case 04: Automotive Front Subframe Multi-Axis Durability & Fatigue [IN PROGRESS]
├── Case 05: Open-Hole Composite Cylindrical Shell Buckling & Post-Buckling
├── Case 06: Multi-Stage Sheet Metal Assembly with Submodeling
├── Case 07: Automotive Suspension Hyperelastic Jounce Bumper Self-Contact
├── Case 08: Axisymmetric Premium Threaded Casing Connection
├── Case 09: Engine Cylinder Head Thermo-Mechanical Low-Cycle Fatigue
└── Case 10: Thin-Walled Pipe Elbow Elasto-Plastic In-Plane Bending Collapse
```

每个案例必须产出：
1. `test_assets/engineering_cases/case_XX_.../problem_statement.json`（问题输入与标准参数）
2. `tools/p2_case_XX_..._e2e.py`（端到端执行驱动与物理提取）
3. `machine_validation/p2_cases/case_XX_..._manifest.json`（密码学验签清单）
4. 独立的工程交付报告（Markdown 与 HTML 格式，含高清 SVG 矢量可视化图表）
5. 全量回归测试用例加入 `tests/test_p2_package_b_cases.py`。
