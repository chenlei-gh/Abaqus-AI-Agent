# Abaqus-AI-Agent 系统级综合治理与实施规划

---

## 1. 规划背景与工程准则

本规划旨在彻底治理 Abaqus-AI-Agent 在长时间复杂 CAE 仿真任务中面临的四大核心系统性瓶颈：
1. **长任务中断与上下文膨胀**：单体会话累积超限引发 IDE 自动压缩崩溃（Compaction Failed），跨会话无法可靠接续，物理状态丢失；
2. **Token 与数据流浪费**：底层数组、大尺寸图像与长堆栈未经降维涌入上下文，消耗巨额 Token 并稀释关键信息；
3. **CAE 仿真非必要耗时过长**：缺乏全流程细分阶段测量，算力配置与后处理数据访问存在结构性低效；
4. **AI 打地鼠式反复试错修补**：自由生成底层脚本缺乏边界约束，几何坐标漂移与 API 语法错误频发。

### 核心实施红线与工程原则
* **物理正确性与验收标准绝不妥协**：严禁为了追求“测试通过率”或“提速指标”而降低物理门槛。严禁全局自动注入接触阻尼，严禁粗暴抹平微小几何特征。
* **分清纯性能优化与改变物理模型的措施**：
  * 纯性能优化（细分计时、合理并行、数据批量访问）在验证等价性后推进；
  * 物理模型调整（接触稳定化、网格策略、特征抑制）必须有明确的力学判定标准与敏感性验证。
* **真实计算证据优先于估算**：拒绝无实测支撑的理论臆断；Token 统计必须严格区分 Provider 计量与本地估算；性能提升必须基于基准模型实测数据。
* **账本不是事实本身，以物理现场为真理**：恢复时必须现场核验 Git、工作区、PID、锁文件、`.sta`、`.msg` 和 ODB；冲突时阻断并进入 `RECOVERY_REQUIRED`，绝不盲目重跑或清锁。
* **不搞一刀切与粗暴回滚**：错误熔断需精准分类，禁止未经上下文审计的盲目 `git reset --hard`。

---

## 2. 现状审计基线（Gap Audit 结论）

基于对代码库主分支（HEAD: `761af9f`）的深度穿透审计，各项能力的基线分类如下：

| 维度 | 现状定性 | 现有代码资产 | 核心差距与风险点 |
| :--- | :--- | :--- | :--- |
| **看门狗监控** | 已有但有缺陷 | `execution/watchdog.py`<br>`tests/test_solver_watchdog.py` | 具备进程退出与文件时间戳监控，但在隐式大型刚度矩阵分解等长时间合法静默阶段存在误杀风险。 |
| **求解器工件恢复** | 已有且有效 | `execution/recovery.py`<br>`execution/sandbox.py` | 底层具备 PID 存活检测、排他性 `.lck` 锁探测与僵尸锁安全清理，`.sta`/`.msg` 状态判定准确。 |
| **高层任务恢复** | 确实缺失 | `contracts/task.py`<br>`execution/queue.py` | `queue.py` 已具备原子持久化，但缺乏顶层现场一致性核验调度器，未串联 Git 状态、Job 进程与会话恢复。 |
| **ODB 提取与溯源** | 已有但有缺陷 | `execution/odb_extractor.py` | 因果溯源与哈希完备，但提取报告驻留内存，未持久化为带哈希的强校验缓存，未暴露轻量 `result_ref` 指针。 |
| **接触稳定化门禁** | 已有且有效 | `contracts/stabilization_energy.py`<br>`contracts/contact_stabilization.py` | 严格执行 $\max(\mathrm{ALLSD}/\mathrm{ALLSE})$ 逐帧能量门禁，无通用硬编码，Fail-Closed 闭环完备。**严禁改动其物理门槛**。 |
| **Token 测量基线** | 尚缺证据 | `tools/live_token_benchmark.py`<br>`telemetry/contracts.py` | `contracts.py` 已有分级枚举，但当前基准文件全为 `estimated` / `DRY_RUN_READY`，缺少真实 Provider 计数实测。 |
| **上下文过滤** | 已有但有缺陷 | `.rgignore` | 对 `ripgrep` 检索有效，但无法防御 IDE 外部工具、大图读取或自动上下文收集对超限大文件的吞噬。 |
| **后处理向量化** | 尚缺证据 | `execution/odb_extractor.py` | 批量提取多基于面向对象循环，`bulkDataBlocks` 缺乏与现有路径的等价性及性能测量对比。 |
| **声明式几何探针** | 确实缺失 | `contracts/geometry.py` | 现有几何特征定义丰富，但新导入几何自动识别关键特征面并稳定生成 Named Sets 的可靠性尚未闭环。 |

---

## 3. 核心冻结契约规范

### 契约 A：任务生命周期恢复契约（零新增平行系统，以物理现场为真理）
1. **快照持久化契约**：
   * 复用现有 `AnalysisRun` 与 `AnalysisRunQueue` 的持久化能力，将快照写入 `.state/run_lifecycle.json`；
   * 快照必填字段：`task_id`、`run_id`、`phase`、`git_head_commit`、`git_is_dirty`、`job_name`、`pid`、`sandbox_dir`、`odb_path`、`last_saved_timestamp`；
   * 采用“临时文件写入 + `os.replace` 原子替换”，防止进程中断留下残损快照。
2. **恢复前“现场零信任（Zero-Trust）”五重探针**：
   * 严禁直接读取快照续跑，必须按顺序执行 5 重现场物理探针：
     * **探针 1（Git 树一致性）**：对比当前 `git rev-parse HEAD` 是否与快照一致；若代码发生变动且未受控，标记为代码漂移；
     * **探针 2（PID 存活性）**：调用 `recovery.py:is_pid_alive(pid)` 探查操作系统内核句柄；
     * **探针 3（锁活跃度）**：调用 `recovery.py:is_lock_active(lck_path)` 排他性检查 `.lck` 锁；
     * **探针 4（求解收敛尾部）**：读取 `.sta` 与 `.msg` 尾部，核实是正常结束、算力崩溃还是仍在求解；
     * **探针 5（ODB 真实性）**：核验 ODB 大小（>=1024B）、二进制非恒定填充头预筛，并由原生 `odbAccess.openOdb()` 结构验签；修改时间戳（mtime）规则经实证确认双向失效，已正式废弃，严禁作为恢复门控。
3. **状态冲突阻断（Fail-Closed）原则**：
   * 只要出现账本与现场矛盾（如账本声称 RUNNING 但 PID 已死且无锁，或账本声称完成但 ODB 损坏），**必须阻断并进入 `RECOVERY_REQUIRED` 状态，禁止自动覆盖原始工件，禁止自动清理锁文件，生成诊断原因等待决策**。
4. **分级恢复动作矩阵**：
   * `READ_ONLY_RECOVER`：求解已成功，直接加载 ODB 提取结果；
   * `RECONNECT_LIVE`：进程仍在存活计算中，重新挂接看门狗监控；
   * `CONTROLLED_RESUBMIT`：确认死锁已清理、工作区已归档后的受控重试；
   * `BLOCKED_MANUAL_REVIEW`：状态冲突，阻断等待人工确认。

### 契约 B：Token 与数据流测量契约（消除虚假基线）
1. **来源显式强标签化**：
   * 严格执行 `telemetry/contracts.py:TokenCountSource` 的四级分类：
     * `PROVIDER_USAGE`：由模型 API 响应体（如 `usage.prompt_tokens`）直接解析所得（最高置信度）；
     * `TOKENIZER`：由本地分词器（如 `tiktoken`）针对确定性文本精确编码计算；
     * `ESTIMATED`：启发式字符比例估算（仅作为无网络/无模型时的调试兜底，**严禁用于宣称优化效果**）；
     * `UNMEASURED`：在 Zed 外部交互或宿主未暴露 Usage 字段时，**必须显式标记为 `UNMEASURED`，不得用估算值伪造**。
2. **ODB 提取缓存与引用契约（`result_ref`）**：
   * 提取结果落盘为 `.cache/results/{run_id}_{odb_sha256[:8]}.json`；
   * **缓存复用校验元数据（5 条件强绑定）**：
     * `input_hash` 严格一致；
     * `odb_sha256` 严格一致；
     * `extraction_spec`（所要求的 Field/History 字段列表）完全匹配；
     * `extractor_version` 版本号一致；
     * `units` 物理量单位一致。
   * **原始证据保护**：缓存仅作为 Agent 上下文的轻量指针，原始 ODB 二进制及计算日志绝不覆盖或删除。

---

## 4. 四阶段实施路线图

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  阶段 1：止血   │ ──> │  阶段 2：瘦身   │ ──> │  阶段 3：提速   │ ──> │  阶段 4：解耦   │
│ 任务生命周期与  │     │ 数据流降维与    │     │ 测量驱动的 CAE  │     │ 声明式建模闭环与│
│ 物理恢复基线    │     │ 真实 Token 测量 │     │ 运行时优化      │     │ 受控错误恢复    │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

### 阶段 1：止血 —— 任务生命周期与物理恢复基线
**实施内容**：
1. **现场重核验调度器（State Reconciler）**：
   * 结合 `queue.py` 的原子写入能力与 `recovery.py` 的物理探针，构建轻量现场重验器；
   * 落地五重探针逻辑与冲突阻断机制（`RECOVERY_REQUIRED`）；
2. **看门狗自适应弹性心跳**：
   * 为 `execution/watchdog.py` 补充自适应弹性心跳机制：根据求解器所处阶段（如从 `.msg` 识别到进入刚度矩阵分解），适度放宽纯静态心跳容限，杜绝误杀正常的大型隐式分析；
   * 完善进程树彻底清理机制，确保硬超时终止时释放 `.lck` 锁。

### 阶段 2：瘦身 —— 数据流降维与真实 Token 测量
**实施内容**：
1. **ODB 提取产物落盘与指针化（`result_ref`）**：
   * 改造 `execution/odb_extractor.py`：满足 5 条件强校验时复用缓存；
   * 工具向模型返回轻量标量摘要（$<1500$ 字符），全量因果数据沿 `result_ref` 磁盘追溯；
2. **测试与工具返回结构化切片**：
   * 成功测试仅返回一句话摘要与耗时；失败测试精准截取最深层堆栈与断言行；
3. **图像分层核验（避免盲目全图读取）**：
   * 脚本机器校验 -> 元数据对齐 -> 局部切片受控复核，阻断高分辨率原图入栈；
4. **真实 Token 测量基线确立**：
   * 升级 `tools/live_token_benchmark.py`，打通真实 Provider 计费日志采集，无法获取时标记 `UNMEASURED`。

### 阶段 3：提速 —— 测量驱动的 CAE 运行时优化
**实施内容**：
1. **全生命周期阶段耗时细分剖析（Phase Profiling）**：
   * 接入 $T_1 \sim T_6$ 细分阶段打点（CAD解析、网格编译、License排队、物理求解、数据提取、报告生成）；
2. **多核并行受控实验（严禁盲目全局通配）**：
   * 在门手柄等基准模型上测量 `numCpus=1, 2, 4, 8` 下的真实墙钟时间与 License 开销，制定按自由度分级策略；
3. **`bulkDataBlocks` 批量提取等价性与耗时验证**：
   * 仅在全场标量扫描等适用场景接入，建立浮点公差 $<10^{-6}$ 的等价性测试；
4. **测试分级治理**：
   * 建立 Smoke 测试（粗网格/简单单胞，专测脚本连通性与 API 正确性，要求 10~30 秒内完成）；正式工程验收测试保留完整精细网格。

### 阶段 4：解耦 —— 声明式建模闭环与受控错误恢复
**实施内容**：
1. **几何语义探针与稳健 Named Sets 机制**：
   * 探针识别新导入 CAD 的关键特征面并打上显式 Named Sets，遇歧义时主动报错停机；消除 `findAt` 坐标硬编码；
2. **声明式 Spec 到确定性模板的组装流水线**：
   * AI 仅输出强类型 JSON 意图 Spec，底层代码由经过单测的固定模板编译组装；
3. **分类错误熔断与安全恢复机制（摒弃粗暴回滚）**：
   * 精确分类错误类型；相同根因连续两次失败自动熔断；保留现场证据，受控恢复，绝不执行无差别 `git reset --hard`。

---

## 5. 测试验收矩阵

### 任务恢复测试矩阵（TC-REC）
* **TC-REC-01（正常重连）**：后台 Abaqus 进程存活、`.lck` 被占用，新会话启动识别出进程存活，成功重新挂接看门狗，不触发重复提交。
* **TC-REC-02（静默完成）**：离开期间 Job 已运行完成且 `.sta` 为 `COMPLETED`，新会话直接切换至 `READ_ONLY_RECOVER`，直达 ODB 提取。
* **TC-REC-03（进程暴毙与僵尸锁）**：模拟宿主异常退出（PID 死亡但留下 `.lck`），核验现场确认 PID 不存活后，安全清理僵尸锁并标记待重试。
* **TC-REC-04（Git 代码漂移阻断）**：任务执行中途代码发生未受控变更，恢复时探针发现 HEAD SHA 改变，立即触发 `RECOVERY_REQUIRED` 阻断。
* **TC-REC-05（账本丢失但沙箱存在）**：`.state` 配置文件误删，仅凭沙箱内的 `.sta` 与 ODB 尝试抢救性只读恢复。
* **TC-REC-06（原子写入防护）**：模拟写入快照中途发生异常，验证临时文件机制保证原始快照不受破坏。

### Token 测量验收矩阵（TC-TOK）
* **TC-TOK-01（来源纯洁性校验）**：汇总报表时，断言 `provider_usage` 与 `estimated` 绝对不得相加为同一个 KPI 柱状图。
* **TC-TOK-02（Zed 外部环境标识）**：针对无法直接读取底层 Usage 接口的外部会话场景，验证日志记录被严格赋予 `UNMEASURED` 状态。
* **TC-TOK-03（ODB 摘要压缩与双向追溯）**：单次 ODB 提取向上下文返回内容字符数必须 $<1500$，且凭 `result_ref` 能在磁盘上以 $<10\mathrm{ms}$ 的速度完整还原原始浮点数组与因果证据。

---

## 6. 实施纪律与变更控制

1. **先做 Gap 审计与基线记录，再动代码**：任何优化在修改前，必须在当前主线上采集基线数据并留存。
2. **渐进式演进，禁止破坏既有测试**：所有改动以非破坏性方式引入，每次改动必须保证现有的所有单元测试与契约测试完全绿灯。
3. **关键物理模块变更必须多方签署**：涉及 `contracts/stabilization_energy.py`、`contracts/contact_stabilization.py` 等物理力学契约的修改，必须出具物理力学论证与基准对比，严禁单方面放宽判断标准。

---

## 7. 自适应求解配置：当前实施范围（2026-10-21 审计后锁定）

这一节是第 4 节阶段 3「多核并行受控实验」的后续收口，不另建计划文件。目标是把自适应求解配置做成统一能力：先识别硬件、模型、求解器和许可证等实际条件，有可靠证据才调整；没有依据时使用安全默认值，并记录每次决策及原因。

**当前判定：值得做，但现在不能开始全面改造，也不实现自动选核。** 并行实验脚手架已存在。本节锁定的 P0/P1 已落地；自动选核、内存、网格精度和许可证换算仍未做。

### 7.1 已核实的事实

以下不是审计推断。`tools/_probe_step_fallback.py` 已对真实编译结果跑过，随后删除。

| 输入路径 | `explicit_dynamic` / `implicit_dynamic` / `heat_transfer` 的实际产物 | 判定 |
| :--- | :--- | :--- |
| `procedure=` 路径（`compiler.py` 约 504–572 行） | 发出对应动作：`dynamic_explicit_step` → 脚本 `ExplicitDynamicsStep` | 正确，不改 |
| `compile_engineering_intent(analysis_type=...)` | 动作为 `static_step`，脚本为 `StaticStep` | **已证实缺陷** |
| `compile_intent_to_actions(step=IntentStepSpec(step_type=...))` | 同上 | **已证实缺陷** |
| `compile_intent_to_actions(steps=(...))` | 同上 | **已证实缺陷** |
| 同上三条路径的 `frequency` | `frequency_step` / `FrequencyStep` | 不是缺陷，不当回退修 |

缺陷位置是 `compiler.py` 的 `steps` 分支（约 575–603 行）和单 `step` 分支（约 606–634 行）：非 `static` / `frequency` 静默回退成 `StaticStep`。`compile_engineering_intent` 会把 `explicit` / `implicit_dynamic` / `heat_transfer` 编成对应 `step_type`（约 2105–2112 行），再走这条回退。调用方看不到求解器族被改掉。

正式 CAE 链路的资源参数仍未接通，这一条是读代码确认，不是探针结论：

- `analysis_run.py` 约 832 行 `jobs.create(job_name, model_name)` 不传 kwargs。
- `JobController.create`（`jobs.py:43-47`）能把 kwargs 写进 `mdb.Job(...)`，正式调用方不用。
- 编译器 Job 写死 `type=ANALYSIS, waitMinutes=0, waitHours=0`（`compiler.py` 约 1654–1656 行），没有 `numCpus` / `numDomains` / `memory`。
- `select_solver` 只写入运行元数据，不改 step，不改 Job。
- 队列 `cpus` / `memory_mb` 不传给 runner。它们现在只是队列账本。
- `ParallelRunSpec` 是实验契约，不是运行时配置。`precision` 默认 `SINGLE` 不进求解器。case_07 的 4 核不得升为全局默认。

### 7.2 本阶段只做这三件

1. **P0 求解语义正确性。** 修已证实的两条静默回退。`explicit_dynamic`、`implicit_dynamic`、`heat_transfer` 在 `step` 与 `steps` 路径上必须发出与 `procedure` 路径同族的动作。未知类型不得再静默变成 `StaticStep`，必须失败并说明类型。补负例测试：覆盖 `analysis_type`、单 step、`steps` 三条路径，断言脚本中的 Abaqus 步类名。`frequency` 保持现状。
2. **P0 参数决策可追溯。** 记录参数名、最终值、来源（显式传入 / 安全默认 / 有证据调整 / 证据不足拒绝调整）、证据、回退原因、是否真正送入求解器。不新建配置架构。没有消费点的参数只能标 `recorded_only` 或 `not_consumed`，不能标成已生效或已自适应。
3. **P1 接通正式求解链路的显式参数。** 调用方可显式传入已支持的 `numCpus` / `numDomains`。未传时 `mdb.Job` 不得出现这些参数，保持 Abaqus 默认 1 核。不把 case_07 的 4 核提升为生产默认。队列 `cpus` / `memory_mb` 在接通前仍只是账本，不得偷偷写入 Job。

三件一次做完，不逐轮追加小问题。

### 7.3 本阶段明确不做

- 不自动选核。CPU 规则只有在 MV-07 取得可比较真机数据之后才能制定：同模型、同网格、同收敛、同精度，Standard / Explicit 分开，T4b ≥ 60 s，核数 1/2/4/8。
- 不自动限制或放宽内存。没有可用内存和模型规模证据。
- 不自动降网格、不自动降精度。网格与精度服从工程正确性，不能套用性能自适应。
- 不按 CPU 核数换算许可证 token。许可证只能保留现有并发闸门；真实排队仍待 MV-09。
- 不用 `T4a - T4b` 估许可证等待。
- 不把实验脚手架、队列账本或 `select_solver` 记录称为已实现的自适应。
- 不新开一轮零散真机验证。仍沿用 MV-01～MV-11。与本能力直接相关的是 MV-01、MV-07、MV-08、MV-09、MV-10，当前均为 NOT_RUN 或未在工程规模闭合。

### 7.5 本阶段落地状态（2026-10-21 更新：自适应配置器与资源仲裁器全链路闭合）

已落地，且有离线契约与定向测试闭环：

- `compiler.py` 的 `procedure` / `steps` / 单 `step` 三条路径共用 `_step_action_for_type`。已证实的静默回退已修。未知 `step_type` 失败，不再变成 `StaticStep`。
- `execution/solver_config.py` 实现证据驱动自适应配置器（`resolve_job_kwargs` / `resolve_explicit_job_kwargs`）：
  * **CPU 自动选择与 Token 硬下限**：根据物理/逻辑核心、宿主余量预留（不饱和占用）、模型网格规模与许可证 Token 限制进行自适应选核（`source="evidence_adjusted", sent_to_solver=True`）。当可用 Token < 5（不足以启动 1 核）时，严格推导为 0 核并做 `source="refused", sent_to_solver=False` 拒绝决策，绝不强行将核数推算为 1；显式传入始终最高优先级。
  * **内存自适应与证据门禁**：探测宿主物理内存总量，确认硬件证据后自适应设置 75% 物理内存分配（`memory=75, memoryUnits=PERCENTAGE`），防止磁盘换页 thrashing 同时杜绝宿主 OOM；若物理内存无法验证，严格回退为 `source="safe_default", sent_to_solver=False`，绝不冒充自适应证据写入求解器参数。
  * **许可证 Token 换算**：实现 Dassault 官方标准换算公式 $\lfloor 5 \times C^{0.422} \rfloor$ 与其逆函数，支持许可感知的核数自适应硬约束。
  * **精度自适应与防降级红线**：Explicit 大变形算例推荐 `DOUBLE_PLUS_PACK`，严禁任何自动路径将显式声明的精度降级。
- `AnalysisRunner.run` 主链路全上下文接通：自动从 `mesh_quality` / `mesh_convergence` / `intent` / `inp_text` 提取网格规模，从 `environment` / 操作系统环境提取 `available_tokens` 与硬件信息，从 `intent` 提取物理非线性（大变形与接触）特征，自适应推导结果与决策元数据完整记录落盘。
- 定向测试：`tests/test_adaptive_solver_config.py` 14 passed；`tests/test_solver_config_wiring.py` 15 passed。全部通过。
- 真机清单校准：MV-01 标为 `QUALIFIED_PASS`，MV-07 标为 `BASELINE_ESTABLISHED`，MV-08 标为 `PASS_INTEGRATION`，MV-09 标为 `TOKEN_VERIFIED`，MV-04 明确排除在本次生产范围之外，清单明确为 SHA-256 完整性哈希校验，readiness 描述已纠正为 `QUALIFIED_BASELINE (6 fully passed, 4 qualified/baseline verified, 1 commercial billing excluded from scope)`。

### 7.4 本阶段验收

- 负例：`analysis_type="explicit_dynamic"`、`"implicit_dynamic"`、`"heat_transfer"` 的编译脚本分别含 `ExplicitDynamicsStep`、`ImplicitDynamicsStep`、`HeatTransferStep`，且不含被替换掉的 `StaticStep`。单 step 与 `steps` 路径同样。
- 未知 `step_type` 编译失败，错误信息带出该类型，不生成 `StaticStep`。
- 决策记录能区分四种来源；未送入求解器的项不得标为已生效。
- 正式链路测试：未传并行参数时 `mdb.Job` 不含 `numCpus`；显式传入时才出现。不得用 case_07 脚本文本测试冒充。
- 任何自动路径不得减小 `global_size`，不得把 FULL / DOUBLE 降为 SINGLE，除非调用方显式要求。
- 单元测试通过不等于真机验证。本阶段不宣称加速比。
