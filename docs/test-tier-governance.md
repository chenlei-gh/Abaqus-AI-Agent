# Abaqus-AI-Agent 测试分级治理与准入规约（Phase 3.4）

## 1. 治理目标与背景

依据《Abaqus-AI-Agent 系统级综合治理与实施规划》阶段 3.4 要求，为杜绝“单元测试通过冒充真机闭环”及“通过粗化网格伪造求解加速”的现象，本规范确立清晰的**三级测试资产体系（Unit / Smoke / Full Acceptance）**，明确各级测试的适用场景、资源预算、准入/准部门禁与证据形式。

---

## 2. 三级测试资产体系定义

| 资产层级 | 标识 (Marker) | 核心目标 | 典型测试资产 | 执行环境要求 | 时间预算 | 验收准入门禁 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Unit**<br/>单元与契约级 | `@pytest.mark.unit` | 纯离线逻辑、契约边界、Fail-Closed 防御、数据结构序列化与状态机校验 | `tests/test_*.py`（如 `test_parallel_experiment.py`, `test_solver_timing.py`, `test_timing_plumbing.py`） | 纯 Python，无任何外部 Abaqus 进程依赖 | 全量套件 ≤ 180 s（单用例 < 1 s） | 每次 Commit 必须 100% 通过且零警告（`pytest -W error -q` 必须通过） |
| **Tier 2: Smoke**<br/>冒烟与连通级 | `@pytest.mark.smoke` | 真实 Abaqus CLI/API 连通性、基本求解链路、进程管理与简单工件生成验证 | `tools/runtime_smoke.py`, `tests/test_runtime_smoke.py`（单砖三维静力分析） | 真实物理宿主 Abaqus 安装环境 | 单次运行 10 ~ 30 s | 作为进入长周期真机实验的前置连通性自检探针 |
| **Tier 3: Full Acceptance**<br/>全量工程验收级 | `@pytest.mark.acceptance`<br/>`@pytest.mark.live` | 复杂非线性物理响应、真实网格收敛、长周期矩阵分解、接触稳定化闭环、正式基准测量 | `tools/case_07_jounce_bumper_e2e.py`（Standard/Explicit 双作业）、MV-01～MV-11 生产验证清单 | 真实物理宿主 Abaqus 2025、完整许可证、受控硬件与电源环境 | 按案例定义（如 5 ~ 90 分钟） | 严禁降低网格精度；所有验收指标与物理准则 100% 达成并生成防篡改证据清单 |

> **Marker 互斥与隔离铁律（P0-01 闭环规约）**：
> - `unit` 与 `smoke`、`acceptance`、`live` **严格互斥**。`conftest.py` 确保任何被归类为 smoke、acceptance 或 live 的用例严禁打上 `unit` marker；
> - `pytest -m unit` 选出的测试集合 100% 为纯离线单元逻辑用例，绝不卷入任何需要外部进程或工程耗时的验收用例；
> - `live` 是 `acceptance` 的实机子集（兼具 live 与 acceptance marker，但绝无 unit marker）。未检测到真实 Abaqus 环境时，live 用例被探针显式判定为 `BLOCKED` 并记入审计跟踪，绝不作为 unit 运行。

---

## 3. 生产测试分级与判定规约

生产环境测试划分为两类完全独立的任务，严禁混淆概念：

### 3.1 生产路径功能验证（Production Functional Verification）
- **目标**：验证 `AbaqusAIAgent.analysis_run`、ODB 结构读取、结果缓存、许可证排队感知与计时落盘等功能在真实 Abaqus 进程中正常工作。
- **特征**：关注**接口正确性、异常隔离性、产物完整性与 Fail-Closed 兜底**。
- **准入条件**：
  1. Tier 1（Unit）离线契约测试 100% 通过；
  2. Tier 2（Smoke）探针确认本地 Abaqus CLI 可用且环境无残留锁。
- **与性能基准解耦**：此类验证不要求单作业运行时间 ≥ 60 s。

### 3.2 正式性能基准测试（Formal Performance Benchmark）
- **目标**：受控测量不同配置（如 `numCpus=1, 2, 4, 8`）下的真实求解耗时（T4b）与端到端耗时（T4a）。
- **硬性门禁（必须满足 MV-07 准入门槛）**：
  1. 算例尺度门槛：真实 Abaqus/Standard 单作业求解总时长必须 **≥ 60 s**（避免 1 s 量化误差失真）；
  2. 求解器与精度隔离：Standard 与 Explicit 必须完全独立测试，记录精确的求解精度（`SINGLE` vs `DOUBLE_PLUS_PACK`）；
  3. 控制变量冻结：模型几何、网格划分、材料非线性、载荷步与收敛准则在所有实验组中严格一致；
  4. 硬件与环境固化：记录宿主硬件元数据（CPU 型号、物理核心数、内存带宽）并保持操作系统高性能模式运行。

### 3.3 bulkDataBlocks 真实工程 ODB 数值等价与性能收益验证（MV-11 准入规约）
- **目标**：在真实工程规模 ODB（全场应力与位移场）上验证 `bulkDataBlocks` 相比 canonical `fo.values` 遍历的数值等价性与提取速度收益。
- **准入与通过标准**：
  1. 标量峰值与均值相对漂移**严格 `< 1e-6`**（相对公差 `abs(a - b) / max(1.0, abs(a), abs(b)) < 1e-6`）；
  2. 三元空间定位器（`instance`, `node_label`, `element_label`）必须严格对称且类型合法；
  3. 耗时收益必须为统计显著的正向加速；若漂移超标或无显著收益，**坚决不并入主生产链路**。

---

## 4. 生产测试状态判定四态标准（Verdict Standards）

生产测试与真机验证清单（MV-01～MV-11）必须采用统一的严格四态标识，严禁使用模糊的“基本通过”或“待定”：

1. **`PASS`（通过）**：
   - 满足该项定义的全部硬性通过标准；
   - 产生可独立审计的物理证据（带 SHA256 哈希的日志、JSON 清单或真实 ODB 提取值）；
   - 无任何契约偏差或未捕获异常。
2. **`FAIL`（失败）**：
   - 违反验收准则、发生异常终止、数值超出公差、或发生非预期误杀；
   - 必须记录关键失败日志、调用栈及初步原因。
3. **`BLOCKED`（阻塞）**：
   - 前置依赖未满足（例如缺少特定许可证特性、硬件核心数不足、或前置测试失败导致流程中断）；
   - 必须指明具体阻塞条件。
4. **`NOT_RUN`（未运行）**：
   - 尚未在真实物理环境下触发执行。

---

## 5. 红线与反模式禁令

1. **严禁粗化网格伪造提速**：正式工程验收与基准测试必须使用预定细化网格，禁止为追求时间指标而降低单元密度或跳过迭代步。
2. **严禁将 Smoke 测试结果作为性能基线**：Smoke 单砖模型仅用于探针连通性，其秒级耗时受启动与 IPC 支配，禁止据此计算加速比。
3. **严禁将 Unit 测试全绿冒充生产验收完成**：离线测试全绿仅证明代码契约自洽，不能关闭任何带有“真机未验证”标签的遗留项。
