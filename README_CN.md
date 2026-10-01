# Abaqus AI Agent

> **面向 Abaqus/CAE 的开源 AI 工程分析 Agent —— 从工程意图，到经过验证的原生 Abaqus 操作，再到求解证据、结果提取与工程验收。**

[English Documentation / 英文文档](README.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## 项目定位

Abaqus AI Agent 面向已有 Abaqus/CAE 模型及原生 Abaqus 能力。它不是新的有限元求解器，也不试图把任意自然语言直接变成未经验证的几何或分析模型。

核心链路是：

**工程需求 → 工程意图 → 模型检查 → 几何 Grounding → 已验证 Action → Abaqus 执行 → Job/ODB 证据 → 结果提取 → 工程验收 → Evidence**

核心原则：

> **Abaqus Python 调用成功 ≠ 模型正确 ≠ Solver 成功 ≠ 所需结果存在 ≠ 工程要求满足。**

每一层都必须保留与其声明相匹配的证据。

## 当前工程能力

### Action 与 Abaqus 执行

当前 Action 层覆盖：

- 材料：弹性、密度、塑性、导热系数、比热、热膨胀；
- Solid Section 与 Section Assignment；
- Static、Explicit Dynamics、Implicit Dynamics、Frequency、Heat Transfer、Coupled Temperature-Displacement；
- Step 控制：time period、增量上下限、time incrementation、stabilization，以及适用的 solution technique / reform kernel；
- Amplitude：Tabular、Smooth Step、Periodic、Equally Spaced；
- 载荷：Gravity、Pressure、Concentrated Force、Body Force、Body Heat Flux、Surface Heat Flux；
- 预定义场：Initial Temperature、Initial Stress；
- 边界条件：Fixed/Encastre、Displacement、Symmetry、Temperature；
- 装配实例：inspection、translation、rotation、linear pattern；
- Tie 与 Contact；
- Job 创建与提交、INP 导出、ODB Field CSV 导出；
- 受控的原生 Abaqus Python Escape Hatch。

执行层包括 `AbaqusExecutor`、JSON/TCP Bridge、InProcess 测试执行、模型/Job/ODB 检查、Viewport 辅助、`.inp` / `cae noGUI` / Abaqus Python 执行、Session/Runtime capability 检查、有限边界的 Job 诊断和产物收集。

### 网格

当前网格能力包括：

- 全局/局部 Seed；
- 按 Size 或 Number 的 Bias Seed；
- Mesh Controls；
- Sweep Path；
- 语义化 Element Strategy；
- Legacy native element-type assignment；
- Mesh Generation；
- 原生 `Part.verifyMeshQuality(...)` 网格质量验证；
- 面向工程 QoI 的网格收敛评价。

Element Strategy 当前只对明确支持的 **Continuum 子集** 做语义到 Abaqus element code 的映射，包括常见 3D Hex/Tet/Wedge 及 2D Plane Stress/Plane Strain Quad/Tri 组合。Shell/Beam/Truss 虽保留为语义枚举，但未完成的组合会 fail closed，不会猜测 element formulation。

网格质量与网格收敛是两种不同的工程声明：质量检查通过不等于 QoI 已经收敛。

原生网格验证的失败/警告 element labels 会作为证据保留，而不是被压缩成一个未经定义的“网格质量分数”。

### 几何 Grounding

项目把几何选择视为证据问题，而不是简单的名称或索引问题。当前包括：

- image/intent contract；
- 实时 Face/Edge descriptor；
- Viewport camera/projection 提取；
- 标定后的平行投影 screen grounding；
- 候选评分与排序；
- confirmation policy；
- JSON-safe evidence serialization；
- 只读 Viewport PNG 探针。

> 图片标注本身不能证明某个 Abaqus Face/Edge index 就是目标区域。

### 工程可信度与数值验证

当前提供：

- explicit acceptance criteria；
- reaction/load balance、energy-ratio 等工程 sanity checks；
- RF / energy / contact ODB evidence；
- successive-change 与 Richardson/GCI 数值验证；
- QoI-aware mesh convergence；
- declarative benchmark；
- sensitivity / uncertainty contract；
- provenance 与 artifact-manifest hashing；
- 显式授权的一次性 correction；
- deterministic calibration / parameter identification；
- bounded reliability analysis；
- bounded、可复现的 uncertainty execution。

这些机制用于建立证据链，并不单独证明物理正确性。

### 疲劳

当前疲劳能力是针对**已有 Abaqus 标量应力历史**的确定性后处理，已经闭合：

- Rainflow cycle counting；
- half/full cycle 权重；
- stress range / amplitude / mean 的明确语义；
- Goodman；
- Gerber；
- Soderberg；
- Walker（含 gamma 边界校验）；
- log-log S-N 插值；
- Palmgren-Miner 损伤。

当前**不宣称**已实现 critical-plane 或 non-proportional multiaxial fatigue。

### 标定与可靠性

- 参数标定：对明确观测、参数边界和模型函数执行有界确定性搜索，不自动修改 Abaqus 模型；
- 可靠性：经验生存率，以及支持右删失数据的两参数 Weibull 最大似然拟合，并提供可靠度、失效概率、危险率和 B-life。

### Planning / Validation / Evidence

项目提供 experiment input contract、engineering plan、blocker/assumption 报告、Action validation、Preflight、static-analysis planning、model snapshot/state diff、Job status classification、ODB metadata normalization、Field/History/Frame extraction、acceptance evaluation、evidence packaging，以及 `AbaqusAIAgent` orchestration facade。

## 工程闭环

```text
验收标准
   ↓
Result Requirements
   ↓
需要的 Abaqus 输出
   ↓
Job 执行
   ↓
Artifacts + ODB
   ↓
结果提取
   ↓
Acceptance
   ↓
Evidence
```

项目明确区分：

```text
Python 返回成功
      ≠
Abaqus 模型正确
      ≠
Solver 成功完成
      ≠
所需结果存在
      ≠
工程要求满足
```

架构核心仍然是：

**Action → Validation → Preflight → Execution → Job/ODB → Result Extraction → Acceptance → Evidence**

不通过增加新的 VerificationService、EvidenceStore 或大型 Autonomous Orchestrator 来制造第二套闭环。

## 当前能力状态

| 能力 | 状态 |
|---|---|
| Core Action Contracts | 已实现 |
| Materials / Sections | 已实现 |
| Static / Explicit / Implicit Dynamics | 已实现 |
| Heat Transfer / Coupled Temperature-Displacement | 已实现 |
| Amplitudes / Loads / Predefined Fields / BCs | 已实现 |
| Assembly Instance Operations | 已实现 |
| INP / ODB CSV Export | 已实现 |
| Result Extraction | 已实现 |
| Mesh Strategy | 已实现：支持的 Continuum 子集 |
| Native Mesh Verification | 已实现 |
| Mesh Convergence | 已实现：带工程 QoI 元数据 |
| Geometry Grounding | 已实现：当前针对标定 Viewport / Projection 路径 |
| Fatigue | 已实现：标量应力历史、Rainflow、Goodman/Gerber/Soderberg/Walker、S-N、Miner |
| Calibration / Reliability | 已实现：有界非真机工作流 |
| Uncertainty / Sensitivity | 已实现：有界、可复现工作流 |
| Controlled One-shot Correction | 已实现：必须显式授权 |
| Arbitrary Native Abaqus API | 已通过 Python Escape Hatch 支持 |
| Critical-plane / Non-proportional Multiaxial Fatigue | 延后 |
| FORM / SORM | 延后 |
| Bayesian Inference | 延后 |
| Full Probabilistic UQ / Distribution Inference | 延后 |
| Adaptive Remeshing | 延后 |
| CAD Part / Sketch / Extrude Authoring | 有意延后 |
| STEP / STL Typed Capability | 延后 |
| Tosca / Topology / Shape Optimization | 有意延后 |
| Future Release-specific Adapters | 延后 |

## 安装与测试

外部 Python 包目标为 **Python 3.9+**：

```bash
git clone https://github.com/chenlei-gh/Abaqus-AI-Agent.git
cd Abaqus-AI-Agent
python -m pip install -e .
python -m pip install -e ".[test]"
python -m pytest -q
```

普通测试不需要 Abaqus License。GitHub Actions 使用 Python 3.11 运行 pytest；CI 覆盖 `main`、`feature/**` push 以及 Pull Request。

## Abaqus V5 R2018 / B28

B28 真机验证当前仍然是**未验证（unverified）**状态，而不是已验证。

最终验证应至少覆盖：

1. generated-script smoke test；
2. 模型创建/检查；
3. `writeInput`；
4. 受控 Solver Job；
5. Job artifact 检查；
6. ODB 打开；
7. Result extraction；
8. CSV / Evidence 生成；
9. failure classification。

尤其不能用 Python process 或 exit code 为 0 单独证明 CNEXT、目标 Abaqus command、Solver Job 或 ODB 结果成功。

## 明确边界

项目不声称：

- 替代 Abaqus Solver；
- 覆盖所有 Abaqus API 的类型化封装；
- 从任意照片自动、无确认地修改 Abaqus 几何；
- 已实现完整疲劳求解器；
- 已实现通用 CAD authoring；
- 已实现拓扑优化自动化；
- 已完成 B28 或其他未来版本的真机兼容验证。

## 当前工程闭合状态

当前非真机范围已经形成稳定的 Action/Validation/Execution/Evidence 链路，覆盖 P1-3 不确定性执行、P1-4 数值 refinement verification、P1-5 显式授权的一次性 correction，以及网格策略/验证/收敛、标定、可靠性和标量疲劳后处理。

刻意延后的能力仍然保持为 deferred，而不是以部分实现冒充完成。

最终剩余的大型验证边界只有目标 Abaqus 安装上的真实执行：生成脚本、模型检查、`writeInput`、受控求解、Job/ODB、结果提取和失败分类。
