# T1～T6 计时边界定义（A4）

本文件定义**每个阶段从哪里开始、到哪里结束**，以及失败时记什么。

它**不**接线 `AnalysisRunner`，**不**新增打点调用，**不**产生任何耗时数据。
所有锚点均为 `[已核实]`（读代码确认），但**没有任何真实性证据**——本文件不含一条
真实耗时数字。验收状态仍以 `docs/phase-leftovers-tracking.md` 为准。

## 0. 为什么不直接开始打点

边界不清就打点，得到的是"看起来精确的假数字"。三个已核实的事实决定了本文件的写法：

| # | 事实 | 证据 |
| :--- | :--- | :--- |
| B1 | `audit_inp_mesh_quality` 在生产代码中**零调用**，仅测试引用 | `grep` 全仓库：`src/` 无调用点 |
| B2 | 网格生成与建模 action 在**同一个循环**内执行 | `agent.py:273-278` |
| B3 | `apply_plan` 返回原生执行结果，**不含耗时** | `agent.py:273-278`、`actions/runner.py:14-22` |

直接后果：**T2 在当前链路上没有被独立定义的边界**（细节见 §3）。

## 1. 通用契约

计时一律通过 `telemetry/phase_profile.py` 的 `PhaseProfiler`，遵守已落地的六条契约
（封闭阶段集、单调时钟、失败留痕、未测量≠零、阶段不可重叠、与墙上时钟对账）。
本文件只补充**边界语义**，不改契约。

三条跨阶段的规则：

1. **边界必须能用"进入/退出某函数"描述**。用"大约在建模之后"这种说法，无法写成
   `with profiler.measure(...)`。
2. **一个阶段只包住自己那段代码**。包含上游准备工作的边界会把别人的耗时算进本阶段，
   使分项之和对不上墙钟。
3. **拿不到边界就登记 `NOT_RUN`，不要用近似值填充**。`unattributed_s` 存在的意义
   就是承认"这段没测"，而不是把它摊派到相邻阶段。

## 2. T1 CAD 解析

| 项 | 定义 |
| :--- | :--- |
| 入口函数 | `ingest_cad_file(file_path)` — `geometry/cad_ingestion.py:750` |
| 边界 | 函数进入 → 返回 `GeometryModel` |
| 边界内包含 | 存在性检查、空文件检查、SHA-256 计算、格式探测、STEP/IGES 解析 |
| 边界外 | 能力分级（`classify_cad_model`，`:794`）、编译、建模 |
| 生产调用点 | `planning/compiler.py:1944`（`compile_engineering_intent` 内部） |
| 失败记录 | `FileNotFoundError` / `CadIngestionError` 原样抛出；阶段记 `FAILED` + 已耗时 |
| 旁路语义 | `allow_missing_step_file=True` 时不进入本阶段 → `NOT_RUN`，不是 0.0 |

**为什么边界到此为止**：`classify_cad_model` 是纯规则判定，不读文件；把它算进来会
让"CAD 解析"同时包含"能不能自动建模"的策略判断，混淆测量与决策。

## 3. T2 网格编译 —— **当前无可测边界**

这是本文件唯一没有给出可用边界定义的阶段。

### 3.1 候选边界与不可用原因

| 候选 | 位置 | 为什么不能用 |
| :--- | :--- | :--- |
| `audit_inp_mesh_quality(inp_path, policy)` | `mesh_audit.py:361` | 生产零调用（B1），只在测试里跑。拿它当 T2 等于测一个不存在的生产阶段 |
| `evaluate_mesh_quality_gate(metrics, policy)` | `mesh_gate.py:86` | 纯规则评估，输入是已算好的指标；不含任何网格生成 |
| `generate_mesh` action 的执行 | `actions/script.py:193` | 真实生成点，但混在 `apply_plan` 的循环里（B2），且该循环不返回耗时（B3） |
| `writeInput` 段 | `analysis_run.py:901-912` | 这是**导出 inp 并做装配审计**，不是网格生成；且仅在 `assembly_scope is not None` 时执行 |

### 3.2 一个可能成立的边界（未验证，需决策）

按 `action_type` 过滤 `apply_plan` 中的网格动作，累加其执行耗时：

    seed_part, local_seed_size, local_seed_number,
    mesh_controls, element_type, generate_mesh

**它现在无法落地**，因为：

1. `apply_plan` 逐个 `execute()` 且丢弃返回值耗时（B3），要测量必须改这条循环；
2. 改这条循环属于**主链路语义变更**，与 A2（T4 主链路计时）同一性质，
   已登记为决策阻塞项，不属本轮授权范围。

**结论**：T2 在接入前只能登记 `NOT_RUN`。任何"T2 已可测量"的说法都不成立。
若后续批准主链路改动，上述六个 `action_type` 是既定锚点，`generate_mesh` 是耗时主体，
`seed_*` / `mesh_controls` / `element_type` 是前置配置（通常远小于生成耗时）。

## 4. T3 License 排队

| 项 | 定义 |
| :--- | :--- |
| 边界 A（`_LicenseContext`） | `_LicenseContext.__enter__` 内 `reserve()` 前后 — `license.py:64-73` |
| 边界 B（`QueueItem`） | `QueueItem.enqueued_at` → `process_next()` 授予 handle — `queue.py:419` |
| 测量对象差异 | A 测的是**单次阻塞式 `reserve()` 调用的耗时**（只针对最后一次成功调用）；B 测的是**端到端排队等待时长**（从任务入队到最终授予，包含所有退避重试经历的完整等待） |
| 时钟源差异 | **路径 A 使用 `time.monotonic()`**（单调时钟，不受系统时间调整影响）；**路径 B 使用 `time.time()`**（队列系统状态与时间戳基线，注入 `current_time` 时须同源） |
| 失败记录 | 路径 A 获取超时抛错时保持 `None`；路径 B 在排队中或超限 `FAILED` 时保持 `None`。**失败均不记 0，也不把超时当作成功排队耗时** |
| 重试口径 | 路径 A 不感知重试；路径 B 明确累加跨次尝试的所有退避等待时长 |

两条路径独立存在：`AnalysisRunQueue` 走 `reserve(timeout=0.0)` + 退避重试，
`_LicenseContext` 走阻塞式 `reserve(timeout=...)`，**两者时基不同、测量口径不同，绝对不能混用**。

**代码接线与隔离已闭环**：
已实现 `attach_license_timing()` 函数并在 `_LicenseContext`（source=`<Provider>.reserve`）、`AnalysisRunner.run`（source=`queue_dispatch`）、`AbaqusAIAgent.analysis_run`、`RunWorker.execute_item` 完整接线：
1. 当传入 `None`、`bool` 或非法非有限值时，明确调用 `profiler.mark_not_run(PipelinePhase.LICENSE_QUEUE)` 标记 `NOT_RUN`，绝不留下未决状态，绝不捏造 0.0 秒；
2. 当有合法正浮点耗时时，通过 `profiler.record_external(PipelinePhase.LICENSE_QUEUE, float(wait_seconds), source=source, derivation="none")` 记录为 `MEASURED`；
3. 观测异常全流程隔离至 `profiler.internal_errors`，绝不向求解业务链路抛出任何异常；
4. 真实 FlexNet/DSLS 许可排队数据与端到端高并发争抢验证，统一保留在真机清单 **MV-09**，在此之前禁止关闭真机排队遗留项。

**硬隔离红线（严禁推导）**：
`AnalysisRunner` 主链路在 CAE 会话内直接通过 `mdb.jobs.submit()` 运行，未经过 `_LicenseContext` 或 `AnalysisRunQueue`。在物理运行中，License 检出排队被包含在 T4a（`waitForCompletion` 作业总等待）内，而**不包含**在 T4b（`.log` 中求解器纯运行时长）内。
**严禁将 `T4a - T4b` 算作 License 排队时间**！因为 `T4a - T4b` 差额中不仅包含可能的许可排队，还包含 `pre.exe`（前处理/输入解析）、`package.exe`（Explicit packager）、`SMASimUtility.exe`（收尾工具）、进程拉起、磁盘 IO 与 IPC 开销。真实的 License 耗时必须由独立许可探针/日志导出，绝不可通过算术差额推导。

## 5. T4 物理求解 —— T4a 等待与 T4b 求解器

| 项 | 定义 |
| :--- | :--- |
| T4a 可用边界 | `jobs.submit(job_name, wait=True, timeout=...)` — `analysis_run.py:979` |
| T4a 边界内包含 | `mdb.jobs[...].submit()` + `waitForCompletion()` / `monitor_job()` 宿主总等待 |
| T4a **不包含** | 提交前的 `writeInput` + 装配审计（`:901-977`）、提交后的 `_collect_artifacts`（`:980`） |
| T4b 可用边界 | 求解器 `.log` 中自报的时长（`execution/solver_timing.py::parse_log_file`） |
| T4b 计入二进制 | `standard.exe`、`standard_dp.exe`、`explicit.exe`、`explicit_dp.exe` |
| T4b **显式排除** | `pre.exe`（前处理）、`package.exe`（Explicit Packager）、`SMASimUtility.exe`（收尾工具） |

**必须如实标注**：
1. T4a 测的是"提交到完成的等待时间"，包含求解器启动、潜在 License 排队与辅助进程耗时，**不是纯刚度矩阵分解或求解器积分时间**。
2. T4b 是从 `.log` 中解析的求解器执行耗时，量化精度受 Abaqus 日志 1 s 粒度限制；多段日志仅在结构自洽时求和。
3. 生产入口当前将 T4a 作为主阶段耗时，T4b 存放在 `detail["t4b"]` 中，暂未改动主链路以避免语义破坏。两者语义严格独立，禁止混淆。

## 6. T5 数据提取

| 项 | 定义 |
| :--- | :--- |
| 入口函数 | `extract_odb_results(odb_path, requirements, *, run_id, input_hash, ...)` — `odb_extractor.py:1027` |
| 边界 | 函数进入 → 返回 `OdbExtractionReport` |
| 生产调用点 | `analysis_run.py:1146`、`input_modes.py:587`、`input_modes.py:932` |
| 失败记录 | `OdbCorruptOrInvalidError` 等原样抛出；阶段记 `FAILED` |
| **缓存命中** | 命中时耗时反映的是"读缓存 + 还原"，**不是真实提取成本**；须与冷提取分开记录 |

缓存命中与冷提取必须通过 `detail` 区分（如 `cache_hit: bool`），否则性能基线会被
快路径稀释成无意义的平均值。

## 7. T6 报告生成

| 项 | 定义 |
| :--- | :--- |
| 入口方法 | `DeterministicReportPipeline.build_and_render(...)` — `reporting/pipeline.py:81` |
| 边界 | 方法进入 → 返回 `(ReportDeliveryCard, ArtifactPointer, EngineeringReportData)` |
| 边界内包含 | 交付门禁、模型声明对账、HTML/Markdown 渲染、产物登记 |
| 生产调用点 | `agent.py:1578`、`input_modes.py:1039` |
| 失败记录 | `PermissionError`（交付被阻断）同样是 `FAILED`，不是 `NOT_RUN` |
| 旁路语义 | 未走确定性管线的分支 → `NOT_RUN` |

**注意**：`build_and_render` 内含交付授权判定（`:112-150`）。被门禁拒绝的运行会得到
一个很短的 `FAILED` 耗时——这不代表"报告生成很快"，必须在 `detail` 里带上阻断原因。

## 8. 阶段衔接

六个阶段**不在同一条线性链路上**，这一点常被误读：

    T1 ingest_cad_file        ← compile_engineering_intent 内部
    T2 (无边界)               ← apply_plan 内部
    T3 license                ← 与上面三者正交，可能在提交时才发生
    T4 submit(wait=True)      ← AnalysisRunner
    T5 extract_odb_results    ← AnalysisRunner / input_modes
    T6 build_and_render       ← agent / input_modes

因此：

- 不能假设"T1 结束就是 T2 开始"：T1 与 T2 之间还夹着能力分级、求解器选择、输出计划；
- T3 可能同时横跨 T4 的等待窗口（求解器启动期排队），**重叠时必须先扣减再入账**，
  否则 `sum_phase_s` 会超过墙钟，触发 `reconciliation_error`；
- 这种重叠不是打点错误，是真实并发。`unattributed_s` 允许为负——按已有契约
  **不 clamp 为 0**，负值就是需要解释的信号。

## 9. 未验证声明

本文件中的全部锚点都是**静态代码事实**（行号 + 符号名）。以下**全部未验证**：

- 没有任何真实 Abaqus 运行产生过这些阶段的耗时；
- 边界划分是否合理（各阶段耗时量级是否如预期）没有数据支撑；
- T2 的候选边界（§3.2）从未被执行过，可行性未经检验；
- T4 的"等待 ≠ 求解"偏差幅度未知。

因此本文件**不能**用于关闭 `P3-LEFTOVER-01`（真实耗时基线），也**不能**用于证明
阶段 3.1 已验收。它只回答一个问题：接入时该在哪里切。

## 变更历史

| 日期 | 变更 |
| :--- | :--- |
| 2026-10-21 | 建立本文件；定义 T1/T3/T4/T5/T6 边界；确认 T2 无可测边界 |
| 2026-10-21 | 明确 T4a（等待）与 T4b（求解器）边界；确认 T4b 支持双精度并排除 package.exe/pre.exe/SMASimUtility.exe；确立严禁 `T4a - T4b` 推导 License 等待的硬隔离红线 |
| 2026-10-21 | 修正 §4 License 计时时钟源与语义：路径 A 使用 time.monotonic() 测单次 reserve() 耗时；路径 B 使用 time.time() 测包含所有退避重试的端到端墙钟等待。严禁混用 |

| 日期 | 变更 |
| :--- | :--- |
| 2026-10-21 | 建立本文件：定义 T1/T3/T5/T6 的可用边界，认定 T2 当前无可测边界（生产零调用 + 主链路无耗时返回），T4 仅有"等待"边界。不接线、不产数据 |
| 2026-10-21 | T4 接入 `AnalysisRunner.run`：新增可选参数 `phase_profiler`，传入时记录 T4a（等待）与 T4b（`.log`）。默认 `None`，不传则零行为变化。T1/T2/T3/T5/T6 未接入 |
| 2026-10-21 | 生产入口 `analysis_run` 默认传入 profiler，并把定稿写入本次运行已有的证据目录。直接调用 `run()` 仍默认关闭。T1/T2/T3/T5/T6 仍未接入，真实耗时仍未采集 |
| 2026-10-21 | 计时落盘失败有独立 logger 出口。真实 Abaqus 读回仍未做 |
