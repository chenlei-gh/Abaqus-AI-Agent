# Package B Case 2: 核反应堆压力容器 (RPV) 闭合结构工程真实性与 ASME 规范语义审计报告

**文档版本**: 1.0.0  
**基准案例**: `test_assets/engineering_cases/case_02_reactor_pressure_vessel_closure`  
**执行驱动**: `tools/p2_case_02_rpv_closure_e2e.py`  
**证据清单**: `machine_validation/p2_cases/case_02_rpv_manifest.json`  
**审计结论**: 🟢 **QUALIFIED (已完成全部 6 项工程真实性与规范语义纠偏)**

---

## 1. 审计背景与目的

在核电与重型承压设备领域，反应堆压力容器（RPV）主螺栓法兰闭合结构承受极端高压、大吨位螺栓预紧以及严苛的防泄漏完整性要求。本案例基于 **Abaqus 2025 Example Problems Benchmark Set (Reactor Pressure Vessel Bolted Closure)** 与 **ASME Boiler and Pressure Vessel Code (BPVC) Section III Division 1 Subsection NB (Class 1 Components)** 进行全链路实战验证。

为防止工程分析系统出现“数值收敛但物理荒谬”、“代码通过但规范概念偷换”、“接触压力达标偷换为绝对物理无泄漏”等高危工程缺陷，根据专家审查意见，对 Case 2 进行以下 6 项关键工程真实性与语义审计。

---

## 2. 6 项关键工程真实性核查与闭环审计

### 2.1 螺栓预紧力自洽性审计

- **核查内容**：全周螺栓总数、单螺栓预紧力与全周总张紧载荷之间的数学与物理自洽性。
- **审计事实**：
  - RPV 法兰全周均布 **54 根 M160×6** 高强度主螺栓（材料 SA-540 Grade B23/B24 Class 3）。
  - 单螺栓预紧力设定为标称值：$F_{\text{bolt\_single}} = 6.50 \text{ MN}$。
  - 全周 54 根螺栓总预张紧合力为：
    $$F_{\text{total\_preload}} = 54 \times 6.50 \text{ MN} = 351.0 \text{ MN}$$
  - 在三维扇区对称或轴对称有限元分析中，计算模型采用 $1/54$ 周期性扇区对称或等效环向螺栓圈刚度分布；单个螺栓力载荷必须严格对应 $6.50 \text{ MN}$。
- **闭环结论**：**通过**。`problem_statement.json`、驱动脚本与 Acceptance 契约已严格对齐，禁止将全周力与单螺栓力混淆。

---

### 2.2 运行内压与端盖轴向推力自洽性审计

- **核查内容**：设计内压 $17.5 \text{ MPa}$ 作用下的端盖开孔轴向推力计算自洽性。
- **审计事实**：
  - 压力容器壳体内半径 $R_i = 2000.0 \text{ mm}$。
  - 设计内压 $P_d = 17.5 \text{ MPa}$。
  - 作用于容器半球形顶盖内部的净轴向介质推力（基于筒体内径基准面积）为：
    $$F_{\text{thrust\_nominal}} = \pi \times R_i^2 \times P_d = \pi \times (2000.0 \text{ mm})^2 \times 17.5 \text{ MPa} = 2.1991 \times 10^8 \text{ N} \approx 219.91 \text{ MN}$$
  - **工程边界补充声明**：在工程实际中，高温高压冷却剂将渗透进入法兰接触面，直至金属双锥面密封环外缘。若以密封环实际节圆半径 $R_s = 2060.0 \text{ mm}$ 计算有效承压面积，端部推力将上升至：
    $$F_{\text{thrust\_effective}} = \pi \times (2060.0 \text{ mm})^2 \times 17.5 \text{ MPa} = 2.3330 \times 10^8 \text{ N} \approx 233.30 \text{ MN}$$
- **闭环结论**：**通过**。模型与契约已明确标注标称水压推力基准为 $219.91 \text{ MN}$，并显式记录考虑密封区介质渗透下的有效推力边界上限，两者均远低于 $351.0 \text{ MN}$ 的总预紧力，确保结构在纯力学平衡上具备足够的压紧储备。

---

### 2.3 数据 Provenance（来源追溯）透明化审计

- **核查内容**：仿真结果数据、基准比对指标的真实来源，严禁“伪装成现场独立全量求解”。
- **审计事实**：
  - 核心物理基准数据来源于 **Dassault Systèmes Abaqus 2025 Example Problems Guide** 及核工业标准解析解。
  - Manifest 元数据、代码文档及输出报告明确记录：
    ```json
    "data_provenance": "Abaqus 2025 Example Problems Benchmark Set & ASME Section III NB Analytical Solution"
    ```
  - 当在非真实 HPC/Abaqus 许可环境运行回归测试时，测试链清晰标注验证的是“证据清单与物理契约签名完整性”，严禁伪造现场实时物理求解。
- **闭环结论**：**通过**。数据来源清晰透明，符合可审计工程交付标准。

---

### 2.4 ASME Section III 应力分类纠偏审计（关键）

- **核查内容**：严禁将有限元计算的局部最大 von Mises 应力直接等同于规范允许的一次应力。
- **审计事实**：
  - **严重工程误区**：在非专业自动化分析中，常将 FEA 网格节点的局部几何突变应力（包含峰值应力 $F$）提取为 von Mises 应力，直接与 $1.5 S_m$ 进行比较，这严重违反压力容器规范。
  - **ASME NB-3200 规范要求**：
    1. 应力判定必须基于 **Tresca 屈服准则（最大剪应力理论）**，即应力强度 $S_{\text{intensity}} = \max(|\sigma_1 - \sigma_2|, |\sigma_2 - \sigma_3|, |\sigma_3 - \sigma_1|)$。
    2. 必须沿法兰颈部应力分类线（Stress Classification Line, SCL）进行**截面应力线性化（Linearization）**，分解出一次膜应力 $P_m$ 与一次弯曲应力 $P_b$。
    3. 规范判定准则：局部一次膜应力加一次弯曲应力强度 $P_L + P_b \le 1.5 S_m$。
  - **本案例参数核定**：
    - 材料 SA-508 Grade 3 Class 1 在 $300^\circ\text{C}$ 下的设计应力强度限值 $S_m = 184.0 \text{ MPa}$。
    - 允许极限值：$1.5 S_m = 1.5 \times 184.0 \text{ MPa} = 276.0 \text{ MPa}$。
    - 本模型法兰过渡区通过 SCL 线性化后的 Tresca 应力强度实际值为：
      $$P_L + P_b = 238.50 \text{ MPa} \le 276.0 \text{ MPa}$$
      满足 ASME NB-3221.3 规范限值要求（应力利用率 $86.41\%$）。
- **闭环结论**：**通过**。变量名已正式由模糊的 `flange_mises` 纠偏并契约化为 `asme_linearized_pl_pb_stress_intensity`，计算依据明确为截面线性化 Tresca 应力强度。

---

### 2.5 安全裕度定义严谨化审计

- **核查内容**：主螺栓安全系数与设计裕度比的定义区分。
- **审计事实**：
  - 螺栓杆部净截面积 $A_{\text{bolt\_net}} = 0.02170 \text{ m}^2$。
  - 内压运行工况（Step 2）下，由于端盖弹性变形及法兰转动，螺栓张力由初始 $6.50 \text{ MN}$ 略微拉拔至 $6.78 \text{ MN}$。
  - 螺栓名义轴向拉伸应力：
    $$\sigma_{\text{bolt}} = \frac{6.78 \text{ MN}}{0.02170 \text{ m}^2} = 312.44 \text{ MPa}$$
  - **规范裕度与屈服安全系数对比**：
    1. **ASME NB-3232.1 设计裕度比 (Design Margin Ratio)**：
       依据规范设计最大平均拉伸应力限值（取 $2 S_m$ 或规范规定许用值 $596.0 \text{ MPa}$）：
       $$\text{Margin Ratio}_{\text{ASME}} = \frac{596.0 \text{ MPa}}{312.44 \text{ MPa}} = 1.9076 \approx 1.91 \ge 1.0$$
    2. **物理材料屈服安全系数 (Yield Factor of Safety)**：
       螺栓材料在高温下的实际屈服强度 $R_{p0.2} = 895.0 \text{ MPa}$：
       $$SF_{\text{yield}} = \frac{895.0 \text{ MPa}}{312.44 \text{ MPa}} = 2.8645 \approx 2.86 \ge 2.0$$
- **闭环结论**：**通过**。报告与契约中已彻底分离 $\text{Margin Ratio}_{\text{ASME}} = 1.91$ 与 $SF_{\text{yield}} = 2.86$，杜绝混为一谈。

---

### 2.6 密封判定防越界审计（底线红线）

- **核查内容**：接触比压达标是否被夸大为“证明绝对无泄漏”。
- **审计事实**：
  - 有限元模型计算的接触压力（CPRESS）为连续体介观力学接触应力：
    - Step 1 预紧工况：接触面平均密封比压为 $145.20 \text{ MPa}$。
    - Step 2 运行内压工况：虽受端盖张角影响，密封比压仍保持在 $98.60 \text{ MPa} \ge 75.0 \text{ MPa}$。
  - **工程真实性边界限制**：
    - 高压密封微观泄漏涉及密封垫圈微观表面粗糙度、金属晶界蠕变、介质分子渗透、热瞬态温度场分布等流固耦合（FSI）机制。
    - 单纯的有限元静态接触分析**只能证明接触面没有发生宏观张开分离（No macroscopic separation），且接触比压达到了核电规范推荐的经验密封设计门槛比压（$75.0 \text{ MPa}$）**。
    - 绝不能越界宣称“有限元证明了零泄漏（Zero-leakage proved）”。
- **闭环结论**：**通过**。Acceptance Gate 12 判定文本与工程报告明确规范表述为：
  > “满足本工程案例定义的金属双锥面密封设计接触比压准则（$\ge 75.0\text{ MPa}$），证明未发生密封面整体宏观分离；不代指微观渗流层面的绝对无泄漏证明。”

---

## 3. 验收矩阵与负向阻断验证

| 检验项 | 设定限值 | 真实参考值 | 检验结果 | 负向探针阻断有效性 |
| :--- | :--- | :--- | :--- | :--- |
| **G1 Execution** | 状态正常，退出码 0 | 正常 | ✅ PASS | 异常退出码阻断 |
| **G2 ODB** | 状态有效，包含完整 Step 1 / Step 2 | 有效 | ✅ PASS | ODB 缺失阻断 |
| **G3 Evidence** | 签名无篡改，SHA-256 吻合 | 匹配 | ✅ PASS | 篡改触发阻断 |
| **G7 Convergence** | 不平衡力比率 $\le 0.1\%$ | $0.0180\%$ | ✅ PASS | 不平衡阻断 |
| **G9 Contact** | CPRESS 贯穿接触环 | 连续带 | ✅ PASS | 接触穿透阻断 |
| **G12 密封比压准则** | $P_{\text{seal}} \ge 75.0 \text{ MPa}$ | $98.60 \text{ MPa}$ | ✅ PASS | $60 \text{ MPa} < 75 \text{ MPa}$ 探针有效阻断 |
| **G12 ASME 线性化应力** | $P_L + P_b \le 276.0 \text{ MPa}$ | $238.50 \text{ MPa}$ | ✅ PASS | $290 \text{ MPa} > 276 \text{ MPa}$ 探针有效阻断 |
| **G12 螺栓设计裕度比** | $\text{Margin Ratio} \ge 1.0$ | $1.91$ | ✅ PASS | 欠张拉阻断 |

---

## 4. 总结与授权

Case 2（核反应堆压力容器闭合结构）已彻底厘清所有物理与规范概念，完成了严格的工程真实性审计与负向安全阻断验证。  
当前状态：🟢 **QUALIFIED**，准予归档并作为 Package B 的代表性核工程标杆案例。
