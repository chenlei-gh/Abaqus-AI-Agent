# 阶段遗留项追踪

本文件登记各阶段**未闭合**的验收项与契约偏差，供后续统一处置。目的只有一个：让未验证能力保持"未验证"的可读状态，避免在后续开发中被默认为已实现。

登记规则：

- 进入下一阶段**不**清除登记项；只有取得对应证据后才移出。
- 每项必须写明：缺口、当前状态、为何未闭合、关闭条件、追踪位置。
- 任何阶段宣布"验收通过"前，必须先核对该阶段登记项是否为空。

---

## 阶段 1 遗留项（进入阶段 2 时结转）

阶段 1 按「有遗留项、带条件进入阶段 2」处理，**未**宣布全部验收通过。

| ID | 缺口 | 当前状态 | 为何未闭合 | 关闭条件 |
| :--- | :--- | :--- | :--- | :--- |
| P1-LEFTOVER-01 | 真实 Abaqus 大型隐式求解不被看门狗误杀 | **未验证** | 现有证据均为模拟进程（`time.sleep` 静默）与合成文件；无真实 `standard.exe` 刚度矩阵分解阶段的运行记录 | 一次真实大型隐式算例中，求解阶段识别、自适应心跳放宽、正常完成三条均有运行日志佐证 |
| P1-LEFTOVER-02 | 真实 ODB 结构级验签 | **未验证** | 仓库内真实 `.odb` 样本为 0；`verify_authentic_odb_structure` 的 `odbAccess.openOdb()` 路径从未对真实 ODB 执行过 | 用真实求解产出的 ODB 跑通 `verify_authentic_odb_structure`，并保留正例（有效 ODB）与负例（截断/损坏 ODB）结果 |
| P1-LEFTOVER-03 | 自适应心跳未接入 `AnalysisRunner` 主链路 | **未完成（按决定不做）** | `AnalysisRunner` 经 `JobController` 在 CAE 会话内提交，不暴露宿主 PID，执行路径不经过 `run_with_watchdog`；接入会改变主链路执行/超时/终止语义，超出阶段 1 已确认的最小补齐范围 | 由总体规划决定；若决定接入，需单独评估对主链路语义的影响并补充对应测试 |
| P1-LEFTOVER-04 | 契约 A 要求核验 ODB 修改时间戳，当前未实现 | **验收偏差（未豁免）** | 仓库无真实 ODB 样本、无二进制格式文档，`mtime` 顺序规则缺乏语义依据，贸然实现会误拒合法文件 | 统一审查契约依据后决定：补充有据的 mtime 语义实现，或经批准修订契约。**在得出结论前，该项保持"偏差"状态，不得视为已接受的设计** |

### P1-LEFTOVER-04 的详细记录

规划原文（`docs/Abaqus-AI-Agent-Governance-Plan.md` 契约 A 探针 5）要求：

> **探针 5（ODB 真实性）**：核验 ODB 文件大小、修改时间戳及二进制头。

当前实现（`solver.is_authentic_binary_odb`）实际覆盖：

| 契约要素 | 实现状态 |
| :--- | :--- |
| 文件大小 | 已实现（`< 1024` 字节拒绝） |
| 二进制头 | 已实现（明文前缀拒绝 + 首尾恒定填充拒绝），**非**魔数校验 |
| 修改时间戳 | **未实现** |

差异记录：

1. **未实现的原因**：仓库内无真实 `.odb` 样本，也无 ODB 二进制格式文档。任何"ODB mtime 必须晚于 `.sta`"之类的规则都是臆造语义；一个合法场景即可反驳——例如 `.sta` 在求解结束后的收尾写入晚于 ODB 最后一次写入，按该规则会把正常 Job 判为损坏。
2. **尚未确认的语义**：mtime 究竟能提供什么增量信息？大小与二进制头已能排除空文件、明文伪造、恒定填充；mtime 若要提供价值，必须能区分"结构完整但内容被截断/覆盖"的文件，而这一点需要真实样本验证，不能靠推断。
3. **当前处置**：保留规划原文，不做静默豁免，也不加无依据的比较。该项在阶段 1 验收记录（`docs/phase-1-recovery-acceptance.md` §1.1）中已如实标注为有意偏离。
4. **后续决定点**：统一审查契约依据后，二选一并留档——补充有据的 mtime 实现，或经批准修订契约文本。

---

## 阶段 2 验收记录

对应规划：`docs/Abaqus-AI-Agent-Governance-Plan.md` 第 3 节契约 B、第 4 节阶段 2、第 5 节 TC-TOK 矩阵。

阶段 2 **未**宣布全部验收通过。TC-TOK-01/02/03 的自动化契约均有测试佐证，但「真实 Provider 计费日志」与「真实 ODB 提取」两项证据仍缺。

### 2.1 实施内容

| 规划要求 | 实现位置 | 状态 |
| :--- | :--- | :--- |
| `TokenCountSource` 四级分类含 `UNMEASURED` | `telemetry/contracts.py` | 已实现 |
| 汇总报表按来源分桶、禁止混算 KPI | `telemetry/tracker.py::finalize` | 已实现 |
| 估算组件不得冒充实测来源 | `telemetry/tracker.py::record_call`（来源降级 + `source_downgrade_reason`） | 已实现 |
| Provider 未返回 usage 时不得填 0 | `llm/client.py::chat_completion`（`usage_measured` 门控） | 已实现 |
| Provider usage 字段有效性校验 | `llm/client.py::_is_valid_token_count`（拒绝 `bool`/负数/非整数/总量不一致） | 已实现 |
| 离线/未配置基准标 `UNMEASURED` | `tools/live_token_benchmark.py::run_benchmark` | 已实现 |
| 基准证据分层（响应用量 ≠ 计费对账） | `tools/live_token_benchmark.py`（`evidence_scope`、`billing_reconciled`） | 已实现 |
| `result_ref` + 5 条件强校验缓存 | `execution/result_cache.py`、`odb_extractor.extract_odb_results` | 已实现 |
| 不可信缓存不得复用 | `result_cache.py::report_from_payload`（结构错误归一为 `ResultCacheError` + 计数自洽校验） | 已实现 |
| 模型侧摘要 < 1500 字符 | `OdbExtractionReport.to_llm_summary` / `ResultRef.to_llm_json`（严格 `<`） | 已实现 |
| 测试/工具返回结构化切片 | `execution/output_slicing.py` + `HeadlessAbaqusPythonExecutor.execute` | 已实现 |
| 图像分层核验（校验→对齐→切片） | `perception/image_context.py` | 已实现 |

### 2.2 TC-TOK 验收矩阵核对

| 用例 | 断言要点 | 测试文件 | 层级 |
| :--- | :--- | :--- | :--- |
| TC-TOK-01 | 单一已验证来源可产生 KPI；`provider_usage` + `estimated` 混入时 `kpi_eligible=False`、无 KPI；每来源独立分桶 | `tests/test_context_telemetry.py::test_tc_tok_01_*` | 单元 |
| TC-TOK-02 | 外部会话记录 `source=unmeasured`（`is_estimated=False`），落盘 JSON 同样标记；Provider 缺 `usage` 时 token 为 `None` 而非 0 | `tests/test_context_telemetry.py::test_tc_tok_02_*`、`tests/test_live_llm_client.py::test_live_llm_client_missing_usage_is_unmeasured_not_zero` | 单元 |
| TC-TOK-03 | 60 指标摘要 < 1500 字符且不含原始数组；凭 `result_ref` 在磁盘上还原全部浮点数组与因果证据；实测耗时 < 10 ms | `tests/test_result_cache_contract.py::test_tc_tok_03_*` | 单元（合成 ODB + mock runner） |

5 条件绑定的负例覆盖：`input_hash`、`odb_sha256` 对应缓存键变化、`extraction_spec`、`units`、`extractor_version` 任一不符即重新提取（`test_any_binding_mismatch_forces_fresh_extraction`、`test_extractor_version_mismatch_rejects_cache`）。

契约加固负例（本轮补充）：

| 缺口 | 测试 | 行为 |
| :--- | :--- | :--- |
| 合法 JSON、报告结构损坏 | `test_structurally_invalid_but_parseable_cache_is_not_reused`（6 例） | 归一为 `unusable_cache` 并按未命中重新提取，不抛给提取流程 |
| 报告体被掏空但绑定仍匹配 | `test_structurally_invalid_but_parseable_cache_is_not_reused`（`extractions_missing`） | `result_ref.counts` 与实际条数不一致即拒绝复用 |
| 计数元数据本身损坏 | `test_damaged_count_metadata_is_treated_as_unusable_cache`（6 例）、`test_damaged_evidence_count_is_also_refused`、`test_damaged_count_is_refused_by_result_ref_reader` | 非整数/`bool`/负数/缺失/非数字一律 `unusable_cache`；不做 `int()` 截断 |
| 结构错误异常类型不统一 | `test_report_from_payload_normalizes_structural_errors`、`test_result_ref_from_payload_normalizes_structural_errors` | 一律 `ResultCacheError` |
| 摘要边界 ≥ 1500 | `test_summary_is_strictly_below_the_bound` | 严格 `<`，不可满足时抛错而非超长返回 |
| Provider 来源但组件为估算 | `test_heuristic_components_downgrade_a_verified_source` | 降级为 `estimated` 并记录 `requested_source` |
| usage 字段非法 | `test_malformed_provider_usage_is_rejected_not_claimed`（8 例） | `bool`/负数/非整数/总量不一致 → `UNMEASURED`，字段保持 `None` |

### 2.3 本阶段遗留项

| ID | 缺口 | 当前状态 | 为何未闭合 | 关闭条件 |
| :--- | :--- | :--- | :--- | :--- |
| P2-LEFTOVER-01 | 真实 Provider 计费日志采集 | **未验证** | 本机无 Provider 凭据，`live_api=True` 路径从未对真实端点执行；TC-TOK-01/02 全部为单元级，`provider_usage` 仅来自 mock 响应体。基准脚本的 `QUALIFIED_LIVE` 仅表示**响应体 usage 已解析**（`evidence_scope=response_usage_verified`），与账单对账（`billing_reconciled=false`）是两项独立证据 | 用真实 API Key 跑一次 `run_benchmark(live_api=True)`，留下 `machine_validation/live_token_benchmark_evidence.json` 且 `status=QUALIFIED_LIVE`、`claimable=true`；**再**以 Provider 账单/用量记录对账后才可关闭本项 |
| P2-LEFTOVER-02 | 真实 ODB 上的 `result_ref` 往返 | **未验证** | 仓库无真实 `.odb` 样本；缓存往返测试使用合成二进制头 + mock extraction runner，未经过 `odbAccess.openOdb()` | 用真实求解产出的 ODB 执行一次提取，确认缓存命中/失配与磁盘还原在真实数据上成立 |
| P2-LEFTOVER-03 | TC-TOK-03 的 < 10 ms 还原仅在合成负载上实测 | **未验证（规模）** | 测试负载为单需求、200 个浮点；真实工程 ODB 的提取产物更大，10 ms 预算在真实规模下未实测 | 在真实提取产物上重复计时（含证据链完整还原） |
| P2-LEFTOVER-04 | 图像分层核验未接入真实视口捕获链路 | **未接入（按范围决定）** | 本阶段实现的是三层核验能力本身；`render_headless_contour_images` / `capture_viewport` 的产出路径未改造为强制走切片，避免改变既有报告出图语义 | 若决定在交付链路强制切片，需单独评估对 `reporting/pipeline.py` 与图像校验契约的影响 |
| P2-LEFTOVER-05 | PNG/GIF 校验复用了 `odb_rendering` 既有实现，JPEG 仅有头部校验 | **已知边界** | 规划未要求新增格式规则；JPEG 只验证 SOI/SOF/EOI 与声明尺寸，**不**声称像素级完整性 | 若需像素级 JPEG 验签，需补充依据与样本后单独实施 |

### 2.4 验证层级声明

本阶段所有测试均为**单元/集成级**：

- ODB 相关全部使用合成二进制文件与 `custom_runner`，**没有**真实 Abaqus 求解、**没有**真实 `.odb`；
- Provider 相关全部使用 mock HTTP 响应，**没有**真实计费日志；
- 图像相关全部使用 Pillow 合成图像，**没有**真实视口捕获。

因此 TC-TOK 全绿只证明**阶段 2 契约在单元层成立**，不能反向推断阶段 1 的真实环境风险已关闭。

#### 计量的三个层级（不得混用）

| 层级 | 来源 | 可申报范围 |
| :--- | :--- | :--- |
| **请求级 usage** | Provider 响应体 `usage.prompt_tokens` / `completion_tokens` | 单次调用的输入/输出总量，`source=provider_usage` |
| **组件级分布** | 本仓库的分解或启发式估算（`system_tokens`、`tool_schema_tokens` 等） | **仅本地分解结果**，非 Provider 原生计量 |
| **账单对账** | Provider 账单/用量记录 | 尚未采集（`billing_reconciled=false`） |

**组件级 Token 分布属于本地估算或分解结果，不是 Provider 原生提供的独立计量值。** Provider 报的是单次请求的输入与输出总量，并不提供本仓库内部五个上下文组件各自的精确计数。因此请求级 usage 与组件级分布必须分别标识，不得混为同一层级的实测证据；组件占比只能用于内部归因与优化决策参考，不能作为对外的 Provider 实测声明。

`record_call` 的来源降级只解决「启发式估算不得冒充实测来源」，它**不**把组件分布提升为 Provider 原生测量。

### 2.5 测试与回归

| 项 | 结果 |
| :--- | :--- |
| 定向测试（7 个文件） | 89 passed → 后续加固为 62 passed（4 个文件）+ 缓存定向 33 passed |
| 全量 `pytest -q` | 1889 passed → 1897 passed（117 s） |
| 全量 `pytest -W error -q` | 1889 passed → 1897 passed（118 s） |
| `tools/check_workspace_pollution.py` | passed |

---

## 阶段 3 验收记录（进行中）

阶段 2 的实现保持不变；真实 Provider、真实 ODB、真实规模计时统一留到最后一轮集中验证。

### 3.1 全生命周期耗时剖析（T1 ~ T6）

#### 审计结论：当前仓库不具备任何分阶段耗时剖析设施

| T 阶段 | 审计时已有能力 | 结论 |
| :--- | :--- | :--- |
| T1 CAD 解析 | 无 | 缺失 |
| T2 网格编译 | 无 | 缺失 |
| T3 License 排队 | `execution/license.py` 内部算 `elapsed` 但未返回 | 需外部适配 |
| T4 物理求解 | `execution/watchdog.py` 已有 `total_duration` / `WatchedProcessResult.duration` | 可外部登记 |
| T5 数据提取 | `execution/odb_extractor.py` 仅有文件时间戳 | 缺失 |
| T6 报告生成 | 无 | 缺失 |

审计结论：**不存在**统一的分阶段剖析设施，也没有跨阶段一致性校验。

#### 计时契约（`telemetry/phase_profile.py`）

| # | 契约 | 落地方式 |
| :--- | :--- | :--- |
| 1 | 阶段集合封闭为 6 个 | `PipelinePhase` 枚举；`to_dict()` 恒输出全部 6 项 |
| 2 | 单调时钟 | `time.monotonic()`；同时记录 UTC 起止供审计 |
| 3 | 失败是记录结果，不是丢失测量 | `FAILED` + 已耗时 + 异常类型/消息，异常原样重抛 |
| 4 | 未测量 ≠ 零 | 未进入阶段为 `NOT_RUN` 且 `duration_s=None`；`mark_not_run()` 不能覆盖已有实测 |
| 5 | 阶段不可重叠 | 重入另一阶段抛 `PhaseProfileError` |
| 6 | 分解必须与墙上时钟对账 | `unattributed_s` 如实报告；阶段总和超墙上时钟时给出 `reconciliation_error`，**不 clamp 为 0** |

墙上时钟自 `PhaseProfiler` **构造时**起算，而非首次 `measure()`。否则首个阶段之前的初始化耗时会被排除，`unattributed_s` 会低估真实开销。

`record_external()` 用于把既有测量（`WatchedProcessResult.duration`、lmstat 轮询耗时）纳入同一契约，**不改造** `license.py` / `watchdog.py` 的返回语义，也不触碰求解器热路径。

外部耗时的取值校验：非数值、`bool`、负数、以及**非有限值**（`NaN` / `±inf`）一律拒绝。非有限值绕得过 `< 0` 检查（`nan < 0` 与 `inf < 0` 均为 `False`），却能污染 `sum_phase_s` 与 `unattributed_s` 而表面仍像已测量，故单独以 `math.isfinite()` 设闸。

`mark_not_run()` 与 `record_external()` 共用同一条活动阶段冲突规则：任何阶段正在计时时，不得写入 `NOT_RUN`。否则 `NOT_RUN` 会被随后正常结束的计时覆盖，并凭空抬高 `attempts` 计数。

#### 摘要输出的有界化（`to_llm_summary`）

摘要**不再按字符数切割**。截断后的 JSON 不是更短的摘要，而是损坏的输出。实现改为三档物料（全六阶段 / 实测值 + 未运行清单 / 实测值 + 未运行计数），**每档都是完整 JSON**，取第一个满足预算的档位返回；三档均放不下时抛 `PhaseProfileError`，而不是返回不可解析的字符串。`max_chars` 本身也校验为严格正整数。

档位长度并不严格单调（无 `NOT_RUN` 时，较短档位携带空列表而略长），但因「首个适配即返回」且更长档位必定更长，结论不受影响；关键在于任何档位都从未被切割。

#### 本阶段遗留项

| ID | 项 | 状态 | 说明 |
| :--- | :--- | :--- | :--- |
| P3-LEFTOVER-01 | 真实运行耗时基线未采集 | **未验证** | 无任何真实 Abaqus 运行的 T1~T6 数据；现有测试仅用注入的假时钟与合成耗时 |
| P3-LEFTOVER-02 | 剖析器未接入执行链路 | **未接入** | `AnalysisRunner` 主链路按决定不改；当前模块是独立可观测组件，任何「主链路已具备分阶段剖析」的说法都不成立 |
| P3-LEFTOVER-03 | T3 License 排队耗时仍为内部量 | **未导出** | `license.py` 的 `elapsed` 未返回，需在真正接线时再适配，本轮不改动 |

#### 验证层级声明

本项证据全部为**单元级**：

- `tests/test_phase_profile.py`（24 passed）使用 `FakeClock` 注入 `pp.time.monotonic`，断言的是契约行为，不是真实耗时；
- **没有**真实 Abaqus 求解、**没有**真实 License 排队、**没有**真实 ODB 提取；
- 通过本组测试**不能**推断任何真实阶段耗时，也**不能**推断阶段 1/2 的真实环境遗留项已关闭。

#### 测试与回归

| 项 | 结果 |
| :--- | :--- |
| 定向 `tests/test_phase_profile.py` | 44 passed |
| 全量 `pytest -q` | 1921 passed（116 s）→ 1941 passed（契约边界加固后） |
| 全量 `pytest -W error -q` | 1921 passed（108 s）→ 1941 passed（契约边界加固后） |
| `tools/check_workspace_pollution.py` | passed |

#### 未启动项

阶段 3.2（`numCpus` 对比）与 3.3（`bulkDataBlocks`）**未启动**，3.4（测试分级治理）未启动。在真实耗时基线（P3-LEFTOVER-01）取得之前，不具备做并行度对比的依据。

---

## 变更历史

| 日期 | 变更 |
| :--- | :--- |
| 2026-10-20 | 建立本文件；结转阶段 1 的 4 项遗留（3 项未验证、1 项契约偏差），作为带条件进入阶段 2 的前提记录 |
| 2026-10-21 | 登记阶段 2 验收记录：TC-TOK-01/02/03 单元级通过，新增 5 项遗留（真实 Provider 日志、真实 ODB 往返、真实规模计时、图像链路接入、JPEG 头部校验边界） |
| 2026-10-21 | 契约加固：缓存结构损坏归一为未命中、计数自洽校验、摘要严格 `<1500`、遥测来源降级、Provider usage 有效性校验、基准证据分层。全量 1889 passed（含 `-W error`） |
| 2026-10-21 | 补齐计数校验边界：`_coerce_count` 拒绝 `bool`/浮点/负数/缺失（不再依赖会截断的 `int()`），计数校验进入同一归一化块， `result_ref_from_payload` 同口径。全量 1897 passed（含 `-W error`） |
| 2026-10-21 | 在 §2.4 增加计量的三个层级声明：请求级 usage、组件级本地分解、账单对账不得混用（仅文档澄清，无代码变更） |
| 2026-10-21 | 阶段 3.1：新增 `telemetry/phase_profile.py` 及 24 项单元测试，落地 T1~T6 计时契约（封闭阶段集、单调时钟、失败留痕、未测量≠零、不可重叠、与墙上时钟对账）；登记 3 项遗留（真实耗时基线、未接入 `AnalysisRunner`、`license.py` 耗时未导出）。全量 1921 passed（含 `-W error`） |
| 2026-10-21 | 阶段 3.1 契约边界加固（仅 `phase_profile.py` 与对应测试）：摘要改为三档完整 JSON 回退（不再按字符截断，放不下则报错）、外部耗时拒绝 `NaN`/`±inf`、`mark_not_run()` 补活动阶段冲突检查。定向 44 passed |
