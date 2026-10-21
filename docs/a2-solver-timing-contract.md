# A2 计时契约：T4a / T4b 拆分（决策记录）

本文件解决 `docs/cross-phase-task-graph.md` §4 登记的 A2 决策阻塞：**主链路要不要改、改成
哪个口径**。

结论先行：**不需要为测量 T4 修改 `AnalysisRunner`**。T4 拆成 `T4a`（等待）与 `T4b`
（求解器自身运行），`T4b` 可以从**已存在的作业产物**中解析，不需要进入主循环。

本文件只为契约定性，**不含任何实现，也不含任何真实性能结论**。

## 0. 为什么必须拆

`jobs.submit(job_name, wait=True, timeout=...)`（`analysis_run.py:979`）覆盖的是
「提交 → 完成」的整段等待。用真实产物可以拆出这段等待内部到底发生了什么：

`runs/odb_sample_run/AIAgent_ODBSample.log`（真实 Abaqus 2025 运行）：

| 段 | 起 | 止 | 实测 |
| :--- | :--- | :--- | :--- |
| Input File Processor | 09:27:46 | 09:27:53 | **7 s** |
| Standard Analysis | 09:27:53 | 09:28:00 | **7 s** |
| SIM Wrap-up | 09:28:00 | 09:28:01 | **1 s** |

同一作业的等待边界内，只有 **7/15 = 47%** 是 `standard.exe` 的运行时间。另外 8 s 是预制
输入与收尾。把 15 s 记为「求解耗时」会把误差放大到 2 倍以上。

这不是极端个例：单砖模型里 `pre.exe` 固定开销占比天然偏高，但**固定开销在工程规模下不会
按比例增长**，因此两者的比例关系必须实测，不能假设。

## 1. T4a：CAE 作业等待时长

| 项 | 定义 |
| :--- | :--- |
| 边界 | 进入 `jobs.submit(wait=True)` → 返回 `JobStatus` |
| 包含 | License 实际检出、`pre.exe`、`standard.exe`/`explicit.exe`、`SMASimUtility.exe`、轮询开销 |
| 不包含 | 提交前的 `writeInput` + 装配审计（`analysis_run.py:901-977`）、`_collect_artifacts`（`:980`） |
| 测量方式 | `PhaseProfiler.measure(PipelinePhase.SOLVER)`，`strict=False` |
| 是否改主链路 | **不改**。用现有 `with` 语义包住既有调用即可 |
| 允许的用途 | **端到端**性能指标；`numCpus` 的端到端对比 |
| 禁止的用途 | 称为「求解耗时」、用于归因并行加速比 |

**T4a 是可行的**，因为它不需要作业产物，边界就在一行既有调用上。这也意味着 A2 的
「是否改主链路」这一问题，对 T4a 的答案是**否**。

## 2. T4b：求解器实际运行时长

### 2.1 两个候选证据源

真实产物中有两处可解析的求解器自报时间。**两者都已在本机真实 ODB 作业上核实存在**：

| 源 | 位置 | 真实取值 | 精度 | 语义 |
| :--- | :--- | :--- | :--- | :--- |
| `.dat` 的 `JOB TIME SUMMARY` | `AIAgent_ODBSample.dat:126-130`、`:200-204` | `WALLCLOCK TIME (SEC) = 0` | **整秒** | 整个作业的墙钟（含 pre/wrap-up） |
| `.log` 的 `Begin/End Abaqus/Standard Analysis` | `AIAgent_ODBSample.log:12-16` | 7 s | 整秒 | **仅 `standard.exe` 段** |

### 2.2 关键限制：精度只有 1 秒

真实 `.dat` 记录的是：

    WALLCLOCK TIME (SEC) =            0

而 `.log` 时间戳显示该作业实际跑了 15 s（`standard.exe` 段 7 s）。**这不是解析错误**：
Abaqus 把该字段取整到整秒，不足 1 秒的部分被抹掉。手写测试样例
（`tests/test_p1_4_self_healing.py:295` 用的 `= 3`）看不出这个问题，只有真实产物能暴露。

直接后果：

- 对小算例，`WALLCLOCK TIME` **基本无信息量**（长期为 0）；
- 只有在求解时长达到数十秒以上时，1 秒的量化误差才可接受；
- 任何人用单砖算例的 `WALLCLOCK TIME` 做性能结论，得到的是噪声。

### 2.3 因此 T4b 允许的用途是分级的

| 用途 | 是否允许 | 条件 |
| :--- | :--- | :--- |
| 区分「求解」与「预制/收尾」的量级 | 允许 | 用 `.log` 段落，整秒精度已足够判断量级 |
| `numCpus` 加速比归因 | **条件允许** | 每组求解时长须 ≫ 量化误差（建议 ≥ 60 s），且同模型、同收敛标准、同机器 |
| 单砖 / 秒级算例的性能结论 | **不允许** | 量化误差与被测量同一量级 |

### 2.4 为什么不从 T4a 里减去估算值

不能用 `T4a - License估算 - pre估算` 推导 T4b。理由：

1. 减法的误差是**相加**的，两个估算各自的不确定性会叠加；
2. `pre.exe` 时长依赖模型规模与 deck 复杂度，没有稳定的比例关系；
3. 一旦某项为负（缓冲、并发、时钟精度），结果就失去物理意义，而调用方看不出这是伪值。

T4b 必须**直接取自求解器自报证据**，不能是推导量。这条与阶段 1 的「估算不得冒充实测」
是同一原则。

## 3. 实现状态

### 3.1 T4b 解析器（已实现，单元级）

`execution/solver_timing.py` 实现契约 A2-1～A2-7 的解析部分：

| 导出 | 作用 |
| :--- | :--- |
| `parse_log_text(text, source)` | 解析日志文本 → `SolverTiming` |
| `read_solver_timing(path)` | 读文件，带大小上限与编码容错 |
| `summarize_solver_timing(wait, timing)` | 聚合 T4a / T4b，**不互相推导** |

**五种失败状态**（任一都不返回 `0.0`）：

| 状态 | 触发条件 |
| :--- | :--- |
| `INCOMPLETE` | solver 段有 `Begin` 无 `End`、时间戳缺失/倒序、段内多于 2 个时间戳 |
| `AMBIGUOUS` | solver 段区间重叠、时间戳完全重复、多个 job 头 + 多个 solver 段 |
| `NO_SOLVER_SEGMENT` | 日志可解析但无 solver 段 |
| `FILE_MISSING` | 文件不存在或不可读 |
| `UNPARSEABLE` | 无任何 `Begin ... End` 阶段记录 |

**solver 段识别**：先匹配块名（`Abaqus/Standard Analysis`、`Abaqus/Explicit Analysis`），
不中则回退到可执行文件名（`standard.exe`、`explicit.exe`）。
`pre.exe` 与 `SMASimUtility.exe` **不在** solver 集合内。

**多段求和的前置条件**（这是假设，不是已证事实）：仅当各段**时间上不重叠、不重复、
且 job 头数 ≤ 1 或 solver 段数 = 1** 时才求和；否则记 `AMBIGUOUS`。求和时在 `notes`
中明写“假设为同一作业的连续运行（如 restart）”。

### 3.2 真实产物验证（已做，范围有限）

对 `runs/odb_sample_run/AIAgent_ODBSample.log`（真实 Abaqus 2025 单砖作业）：

| 项 | 解析结果 | 手工核对 |
| :--- | :--- | :--- |
| 总段数 | 3 | 3（pre / standard / wrap-up） |
| solver 段 | 1（`standard.exe`） | 1 |
| `solver_seconds` | **7.0** | 7 s |
| `job_headers` | 1 | 1 |
| 解析警告 | 无 | — |

同一作业的 `.dat` 写入 `WALLCLOCK TIME (SEC) = 0`，反向印证 §2.2 的量化限制。

### 3.3 仍未验证的部分（必须保留）

| 项 | 状态 | 为何无法从单样本推断 |
| :--- | :--- | :--- |
| 多步分析是否产生**多个** solver 段 | **未验证** | 本机仅有单步样本；多步/多载荷步的日志结构未知 |
| 多段是否语义上可加 | **未验证** | 解析器不重叠就求和，但“不重叠”不等于“同一次求解的连续阶段” |
| restart 分析的日志结构 | **未验证** | 无样本 |
| `Abaqus/Explicit` 真实日志而非合成 | **未验证** | 仅用构造样本测过分枝 |
| 工程规模下 1 s 量化是否够用 | **未验证** | 需 ≥ 60 s 算例 |
| T4b 是否代表 CPU 纯计算时间 | **不成立** | 该值含 IO、求解器启动与线程同步，属墙钟时间 |

**特别说明**：§2 的多段求和不等于“已支持多步分析”。当前实现是在**结构自洽性检查**
通过后才求和；若真实多步日志出现时间区间重叠或 job 头重复，解析器会拒绝而非猜测。
这是 Fail-Closed，但不等于解析正确。

## 3.4 profiler 接入（已实现，未接主链路）

`attach_solver_timing()` 把 T4a 与 T4b 写入同一个 `PhaseProfiler`，**不修改**
`AnalysisRunner`。调用方自行测量等待时长、读取 `.log`，再调用该函数。

### 与 A2-3 / A2-4 的偏差（必须保留，不擅自改条款）

A2-3 要求 T4b 记为独立的 `record_external()` 调用，A2-4 要求 T4b 缺失时记
`NOT_RUN`。这两条与 `PhaseProfiler` 的实现冲突：`_measured` 按 `PipelinePhase`
唯一（`phase_profile.py:170`），同一阶段第二次写入会**覆盖**第一次并抬高
`attempts`。若 T4a 与 T4b 都写 `SOLVER`，基线会丢失其中一个。

因此实现选择是：

| 条款 | 原要求 | 实际做法 | 原因 |
| :--- | :--- | :--- | :--- |
| A2-2 | T4a 记为 `SOLVER`，`detail` 带 `scope="wait"` | **照做** | 与唯一记录约束兼容 |
| A2-3 | T4b 独立 `record_external()` | **偏离**：T4b 存为该记录的 `detail["t4b"]` | 第二次写入会覆盖 T4a |
| A2-4 | T4b 缺失记 `NOT_RUN` | **偏离**：记 `solver_seconds=None`、`measured=false` | `NOT_RUN` 会覆盖已有的 T4a 记录 |
| A2-5 | 不得由 T4a 减法得到 | **照做** | `derivation="none"` |
| A2-6 | `resolution_s=1` | **照做** | 来自 `timing.to_dict()` |
| A2-7 | < 10 s 标 `precision_limited` | **照做** | `detail["t4b"]["precision_limited"]` |

偏差写入 `detail["t4b"]["contract_note"]`，序列化后可见，不靠口头说明。

保留的硬保证（不受偏差影响）：

* T4a 与 T4b 都出现在序列化结果中，键不同，互不覆盖。
* 失败、缺失、截断的 T4b 是 `None`，**不是 `0.0`**，也不回退成 T4a。
* 无 T4a 时阶段记 `NOT_RUN`，不伪造一个实测的 `SOLVER` 记录。
* 非法等待时长（`NaN`、负数）被拒绝并记入 `internal_errors`，不抛出。

**未完成**：没有任何生产调用方调用 `attach_solver_timing()`。`P3-LEFTOVER-02`
（剖析器未接入执行链路）因此**不因本函数存在而闭合**。

## 4. 契约条款

| # | 条款 |
| :--- | :--- |
| A2-1 | T4 拆为 T4a（等待）与 T4b（求解器运行），**两者不得互相替代** |
| A2-2 | T4a 记为 `PipelinePhase.SOLVER` 的实测值，`detail` 必须带 `scope="wait"` |
| A2-3 | T4b 记为 `record_external()`，`detail` 必须带 `scope="solver_only"` 与 `source=".log"/".dat"` |
| A2-4 | T4b 缺失（无 `.log`、无时间戳、格式不识别）时记 `NOT_RUN`，**不得回退为 T4a** |
| A2-5 | T4b 不得由 T4a 减去任何估算量得到 |
| A2-6 | 精度声明随值一同记录：`.dat`/`.log` 均为 1 s 量化，`detail` 须带 `resolution_s=1` |
| A2-7 | 求解时长 < 10 s 时，T4b 只能用于量级判断，`detail` 须带 `precision_limited=true` |

A2-3 的 `scope` 字段是硬要求：没有它，下游无法判断拿到的是 15 s 还是 7 s。

## 5. 对既定任务的影响

| 任务 | 影响 |
| :--- | :--- |
| A2 本身 | **阻塞解除**：T4a 不改主链路；T4b 读产物。两者均无需改 `AnalysisRunner` 循环 |
| BASE（真实基线） | 可以采到 T4a + T4b，但 T2 仍缺失（见 `phase-timing-boundaries.md` §3）。因此基线**仍是部分基线** |
| C1（`numCpus`） | 端到端可比，但加速比归因**必须**用 T4b，且算例须 ≥ 60 s。单砖不可用 |
| D3（watchdog） | 与 A2 无关，可独立准备 |

**必须保留的诚实标注**：T4b **解析器已实现**（§3.1），并用真实单砖日志验证过。
但它**尚未**在工程规模、多步或 restart 场景下验证。因此「能解释 `numCpus` 加速比」
仍不成立——那是 C1 的实验条件问题，不是解析器问题。

## 6. 仍未验证的部分（汇总）

逐项说明见 §3.3，此处只列结论：

| 项 | 状态 |
| :--- | :--- |
| 多步分析的 `.log` 是否产生多个 solver 段 | **未验证** |
| 多段语义上是否可加 | **未验证** |
| restart 分析的 `.log` 结构 | **未验证** |
| `Abaqus/Explicit` 真实日志 | **未验证**（仅构造样本测过分支） |
| 工程规模下 1 s 量化是否足够 | **未验证** |
| `.dat` 多步 `JOB TIME SUMMARY` 语义 | **待确认**（见两次输出，同为单次运行） |

**不得把「解析器已实现」读作「多步分析已支持」。** 当前实现对多段只做结构自洽性
检查后求和；若真实多步日志出现区间重叠或 job 头重复，它会拒绝而不是猜测。
拒绝不等于正确。

## 变更历史

| 日期 | 变更 |
| :--- | :--- |
| 2026-10-21 | 建立本文件：T4 拆为 T4a/T4b；用真实产物证明等待段仅 47% 是求解；确认 `.dat`/`.log` 均为 1 s 量化且小算例不可用；给出 7 条契约条款；解除 A2 阻塞但不实现 |
| 2026-10-21 | 实现 `execution/solver_timing.py`：五类失败状态（均不返回 0.0）、多段结构自洽性检查后才求和、CRLF/编码容错。真实单砖日志验证得 7.0 s（手算 7 s）。31 项单元测试通过。多步/restart/Explicit 真机结构仍未验证 |
| 2026-10-21 | 新增 `attach_solver_timing()`：T4a/T4b 写入同一 `PhaseProfiler`，**不改** `AnalysisRunner`。因阶段记录唯一，T4b 存为 `detail["t4b"]` 而非独立 `record_external()`——**偏离 A2-3/A2-4**，偏差写入 `contract_note`。无生产调用方，`P3-LEFTOVER-02` 不因此闭合 |
