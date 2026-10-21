# 跨阶段任务图与执行顺序

本文件把阶段 1～3 的未闭合项整理成**可核对的依赖图**，用于并行实施与统一验收。

它不是验收记录。本文件中的任何"计划""待验证"都不表示已完成。各阶段的实际验收状态以
`docs/phase-leftovers-tracking.md` 为准。

## 0. 标注约定

任务按**证据形态**分为四类，不得混用：

| 标记 | 含义 | 判定依据 |
| :--- | :--- | :--- |
| **[已核实]** | 已读过代码或产物，结论有直接证据 | 文件路径 + 行号 |
| **[待实现]** | 代码尚不存在或能力不完整 | 审计显示无对应实现 |
| **[待真机]** | 需要真实 Abaqus/Provider 运行才能闭合 | 当前证据仅为单元/模拟 |
| **[决策阻塞]** | 需要人工拍板后才能动 | 涉及主链路语义或契约依据 |

一条任务可以同时是 **[待实现]** 与 **[待真机]**：代码写完了但只有单元证据。

## 1. 已核实事实

以下事实由直接读取代码或产物确认，不是推断：

| # | 事实 | 证据 |
| :--- | :--- | :--- |
| F1 | 仓库内真实 `.odb` 样本数为 **0** | `find . -name "*.odb"` 全空 |
| F2 | `*.odb` 被 `.gitignore:28` 忽略，**真实 ODB 无法入库** | `.gitignore` |
| F3 | 本机已安装 Abaqus，`abq2025.bat` 可用 | `/c/SIMULIA/Commands/abaqus.bat`、`EstProducts/2025/` |
| F4 | 曾有一次真实成功运行，产物在 `machine_validation/b28_smoke.json` | `job_completed: true`、`odb_opened: true`、`return_code: 0` |
| F5 | `AnalysisRunner` 经 `JobController` 在 CAE 会话内提交 | `analysis_run.py:782`、`:979`、`jobs.py:49-64` |
| F6 | 主链路**不经过** `run_with_watchdog` | 调用点仅 `batch.py:108`、`solver.py:811` |
| F7 | `BatchExecutor._run` **丢弃** `proc.duration`，`BatchResult` 无耗时字段 | `batch.py:106-114`、`batch.py:33-38` |
| F8 | `_LicenseContext` 不测量排队耗时；`AnalysisRunner` 不引用 license/queue | `license.py:51-71`、`analysis_run.py` 无引用 |
| F9 | `phase_profile.py` 生产调用点为 **0**，仅 `telemetry/__init__.py` 导出 | 全仓库 grep |
| F10 | `bulkDataBlocks` 全仓库 **0 引用** | `grep -rn bulkDataBlocks src/ tools/ tests/` 空 |
| F11 | `numCpus` 仅硬编码为 4，无实验框架 | `tools/case_07_jounce_bumper_e2e.py:381,510` |
| F12 | `tools/runtime_smoke.py` 是单砖三维静力模型，0 处 `time.` 调用 | 文件内容 |
| F13 | `machine_validation/*.json` 入库，`runs/` 与 `machine_validation/*` 默认忽略 | `.gitignore:14-26,49` |

**F2 的直接后果**：真实 ODB 只能留在本机（`runs/` 或 `machine_validation/` 下被忽略的目录）。
可入库的证据只能是对 ODB 的**描述**——大小、SHA256、魔数探测、提取结果 JSON——而不是 ODB 本体。
任何"提交真实 ODB 样本"的计划都不成立。

## 2. 依赖图

```mermaid
graph TD
    B1["B1 生成并留存真实 ODB<br/>runtime_smoke 单砖"]

    B2["B2 真实 ODB 结构级验签<br/>P1-LEFTOVER-02"]
    B3["B3 真实 ODB result_ref 往返<br/>P2-LEFTOVER-02"]
    B4["B4 真机损坏负例<br/>截断 / 全零 / 头部篡改"]
    D2["D2 ODB mtime 契约审查<br/>P1-LEFTOVER-04"]

    A1["A1 BatchResult 携带 duration"]
    A3["A3 License 排队耗时外露<br/>P3-LEFTOVER-03"]
    A5["A5 profile 异常隔离契约"]
    A4["A4 T1/T2/T6 边界定义"]
    A2["A2 主链路 T4 计时<br/>决策阻塞"]

    BASE["真实耗时基线<br/>P3-LEFTOVER-01"]

    C1["C1 numCpus 实验框架<br/>阶段 3.2"]
    C2["C2 bulkDataBlocks 等价性<br/>阶段 3.3"]
    C2S["C2S 数值验收标准与样本"]

    D3["D3 watchdog 大型隐式真机验证<br/>P1-LEFTOVER-01"]
    D1["D1 Provider 计费证据<br/>P2-LEFTOVER-01"]

    B1 --> B2
    B1 --> B3
    B1 --> B4
    B1 --> D2
    C2S --> C2
    B1 --> C2

    A1 --> BASE
    A3 --> BASE
    A5 --> BASE
    A4 --> BASE
    A2 --> BASE

    BASE --> C1
    BASE --> D3

    subgraph 独立于 ODB 与基线
        A1
        A3
        A5
        A4
        D1
        A2
    end
```

**图的两条硬边**：

1. **B1 → {B2, B3, B4, D2, C2}**：没有真实 ODB，这五项全部只能停在合成样本层面。
2. **BASE → {C1, D3}**：没有真实耗时基线，`numCpus` 对比与 watchdog 误杀判定都**无法归因**。
   这不是保守，是数据本身不支持结论。

**明确不成立的边**（避免把任务错误串联）：

- ~~B1 → D1~~：Provider 计费证据与 ODB 无关，可独立推进。
- ~~B1 → A1 / A3 / A5~~：计时基础设施与 ODB 无关，可独立推进。
- ~~B1 → D3~~：小型单砖 ODB **不能**替代大型隐式求解验证。它无法产生长时间刚度矩阵分解，
  因而无法证明看门狗不会误杀。D3 依赖 BASE 与大型算例，不依赖 B1。

## 3. 任务清单

### 第 1 批：可立即并行（无前置）

| ID | 任务 | 类型 | 写范围 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| B1 | 用 `runtime_smoke.py` 生成并留存真实 ODB | [待真机] | `runs/`（不入库）、`machine_validation/*.json` | 记录运行环境、输入版本、作业状态、文件校验信息 |
| A1 | `BatchResult` 携带耗时 | [待实现] | `execution/batch.py` | 纯增量字段，默认 `None`，不改变现有语义 |
| A3 | License 排队耗时外露 | [待实现] | `execution/license.py` | 需先确认不改 `_LicenseContext` 的返回形状 |
| A5 | profile 异常隔离契约 | [待实现] | `telemetry/phase_profile.py` + 测试 | 计时失败不得影响任务成功判定 |
| D1 | Provider 计费证据采集 | [待真机] | `tools/live_token_benchmark.py` | 与 ODB 无关；需真实 Key，费用自负 |

### 第 2 批：依赖第 1 批

| ID | 任务 | 类型 | 前置 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| A4 | T1/T2/T6 阶段边界定义 | [待实现] | 无（可与第 1 批并行） | 需先明确起止边界，否则打点是假的 |
| B2 | 真实 ODB 结构级验签 | [待真机] | B1 | `verify_authentic_odb_structure` 的 `odbAccess.openOdb()` 路径从未对真实 ODB 执行 |
| B3 | 真实 ODB `result_ref` 往返 | [待真机] | B1 | 关闭 `P2-LEFTOVER-02` |
| B4 | 真机损坏负例 | [待真机] | B1 | 截断/全零/头部篡改，验证 Fail-Closed |
| D2 | ODB mtime 契约审查 | [待真机] | B1 | 关闭或修订 `P1-LEFTOVER-04` |
| C2S | `bulkDataBlocks` 数值验收标准 | [决策阻塞] | 无 | 规划要求浮点公差 `<1e-6`，需确认适用场景 |

### 第 3 批：依赖基线

| ID | 任务 | 类型 | 前置 |
| :--- | :--- | :--- | :--- |
| BASE | 真实耗时基线采集 | [待真机] | 第 1+2 批 |
| A2 | 主链路 T4 计时 | [决策阻塞] | 影响分析先行 |
| C2 | `bulkDataBlocks` 等价性 | [待实现][待真机] | B1 + C2S |

### 第 4 批：依赖 BASE

| ID | 任务 | 类型 | 前置 |
| :--- | :--- | :--- | :--- |
| C1 | `numCpus` = 1/2/4/8 实验框架 | [待实现][待真机] | BASE |
| D3 | watchdog 大型隐式真机验证 | [待真机] | BASE + 大型算例 |

### 不在本批次

阶段 4（声明式建模闭环、分类错误熔断与受控恢复）**不并入**。它与性能测量目标正交，
混做会扩大回归面。等阶段 3 遗留项清完后单独立项。

## 4. 决策阻塞项

### A2：主链路 T4 计时

**为什么阻塞**：`AnalysisRunner.run()` 走 `JobController` 在 CAE 会话内提交（F5），
不经过 `run_with_watchdog`（F6），拿不到 `WatchedProcessResult.duration`。
低侵入测量需要先评估两条路径：

1. 用 `JobController.wait()` 外层包一个 `measure(T4)`——**只测等待时间**，不改提交逻辑；
2. 改 `BatchResult`（A1）后从 batch 路径取，但主链路不走 batch，**覆盖不到**。

选项 1 的风险需要单独评估：它把"等待"当作"求解"计时，在有排队/IO 等待时会计入
不属于求解的时间。这属于定义问题，不是实现问题，因此必须先定性。

**当前决定**：不修改主链路。先做 A1/A3/A4/A5，再回来评估。

### C2S：`bulkDataBlocks` 数值验收标准

规划要求浮点公差 `<1e-6`，但**未定义适用场景**。`bulkDataBlocks` 在 Abaqus 中用于
批量提取全场数据，若无明确场景与容差依据，等价比对会变成伪验收。需先确定：
哪些提取路径可用、哪些因集合语义不同不可等价、公差基于什么物理量级。

## 5. 证据留存规则

| 证据类型 | 存放位置 | 是否入库 |
| :--- | :--- | :--- |
| 真实 `.odb` 本体 | `runs/` 或被忽略的 `machine_validation/` 子目录 | **否**（F2） |
| ODB 描述（大小、SHA256、魔数、mtime） | `machine_validation/*.json` | 是 |
| 提取结果 JSON | `machine_validation/*.json` 或 `.cache/results/` | 结果入库，缓存不入库 |
| 原始运行日志 | `runs/` | 否 |
| 运行环境快照（版本、launcher 路径） | 随证据 JSON 一同记录 | 是 |

任何声称"已用真实 ODB 验证"的记录，必须能指向一个**当时存在**的 ODB 描述文件与校验和；
否则该记录不成立。

## 6. 与遗留项追踪的关系

本文件只负责**排序与依赖**。各遗留项的关闭条件、当前状态、为何未闭合，仍以
`docs/phase-leftovers-tracking.md` 为唯一事实来源。

本文件不新增遗留项编号，也不删除任何遗留项。

## 变更历史

| 日期 | 变更 |
| :--- | :--- |
| 2026-10-21 | 建立本文件：核实 13 条事实（F1～F13），给出四批任务依赖图，登记 2 项决策阻塞（A2 主链路 T4 计时、C2S `bulkDataBlocks` 数值标准）。明确小型 ODB 不能替代大型隐式验证，Provider/计时基础设施不依赖 ODB |
