# 阶段遗留项追踪

本文件登记各阶段**未闭合**的验收项与契约偏差，供后续统一处置。目的只有一个：让未验证能力保持"未验证"的可读状态，避免在后续开发中被默认为已实现。

登记规则：

- 进入下一阶段**不**清除登记项；只有取得对应证据后才移出。
- 每项必须写明：缺口、当前状态、为何未闭合、关闭条件、追踪位置。
- 任何阶段宣布"验收通过"前，必须先核对该阶段登记项是否为空。

---

## 0. 未完成项总览（一页看全）

本表是**索引**，不新增结论。逐项细节与关闭条件见各自章节。
最后核对：生产入口默认采集并落盘 T4；T1/T2/T3/T5/T6 仍未接入。

### 0.1 代码能力未闭合

| ID | 缺什么 | 状态 |
| :--- | :--- | :--- |
| P1-LEFTOVER-03 | 自适应心跳未接入 `AnalysisRunner` 主链路 | **未完成（按决定不做）** |
| P2-LEFTOVER-04 | 图像分层核验未接入真实视口捕获链路 | **未接入（按范围决定）** |
| P2-LEFTOVER-05 | JPEG 仅有头部校验 | **已知边界** |
| P3-LEFTOVER-02 | 剖析器仅接入 T4，且未经真实运行验证 | **部分接入** |
| P3-LEFTOVER-04 | T4b 多步/restart 日志结构未验证 | **解析器已实现，真机结构未验** |
| T1/T3/T5/T6 打点 | 边界已定义，**无一处接线** | **未接线** |
| T2 | 网格阶段**无可测边界** | **阻塞**（见 `phase-timing-boundaries.md` §3） |

### 0.2 真实环境未验证

| ID | 缺什么 | 状态 |
| :--- | :--- | :--- |
| P1-LEFTOVER-01 | 大型隐式求解不被 watchdog 误杀 | **未验证** |
| P1-LEFTOVER-02 | 真实 ODB 结构验签（工程规模） | **单砖已验，未闭合** |
| P2-LEFTOVER-01 | 真实 Provider 计费日志 | **未验证** |
| P2-LEFTOVER-02 | 真实 ODB `result_ref` 往返（工程规模） | **单砖已验，未闭合** |
| P2-LEFTOVER-03 | `< 10 ms` 还原（工程规模） | **规模未验证** |
| P3-LEFTOVER-01 | 真实耗时基线 | **未验证（数据为零）** |
| P3-LEFTOVER-03 | T3 真实排队耗时 | **字段已可读，无真实数据** |

### 0.3 契约待修订

| ID | 待定内容 | 状态 |
| :--- | :--- | :--- |
| P1-LEFTOVER-04 | 契约 A 探针 5 的 mtime 规则被真实证据双向驳倒 | **待修订** |
| A2 | T4 已拆为 T4a/T4b，解析器已实现；**T4b 多段语义与多步日志结构未验证** | **部分定案** |
| C2S | `bulkDataBlocks` 浮点公差适用场景 | **决策阻塞** |

### 0.4 未启动

| 项 | 状态 |
| :--- | :--- |
| BASE（完整 T1~T6 基线） | **未启动**；T2 缺失使其只能成为部分基线 |
| C1（`numCpus` 正式实验） | **未启动**；需 T4b 落地且算例 ≥ 60 s |
| C2（`bulkDataBlocks` 等价性） | **未启动**；需 C2S 定案 |
| D3（watchdog 大型算例） | **未启动**；可独立准备 |
| 阶段 3.4（测试分级治理） | **未启动** |
| 阶段 4（全部） | **不纳入本批次** |

> 表中任一项被引用时，必须同时引用其状态。
> 「已定义边界」「已实现字段」「已取得单砖证据」均**不等于**该项已闭合。

---

## 阶段 1 遗留项（进入阶段 2 时结转）

阶段 1 按「有遗留项、带条件进入阶段 2」处理，**未**宣布全部验收通过。

| ID | 缺口 | 当前状态 | 为何未闭合 | 关闭条件 |
| :--- | :--- | :--- | :--- | :--- |
| P1-LEFTOVER-01 | 真实 Abaqus 大型隐式求解不被看门狗误杀 | **未验证** | 现有证据均为模拟进程（`time.sleep` 静默）与合成文件；无真实 `standard.exe` 刚度矩阵分解阶段的运行记录 | 一次真实大型隐式算例中，求解阶段识别、自适应心跳放宽、正常完成三条均有运行日志佐证 |
| P1-LEFTOVER-02 | 真实 ODB 结构级验签 | **证据已取得（单砖规模），未闭合** | 已于 2026-10-21 用真实 Abaqus 2025 产出的 ODB 跑通 `verify_authentic_odb_structure`（正例 2 帧/5 场输出，6 个负例全部阻断，其中截断与头部篡改由 `odbAccess.openOdb` 捕获）。**但**样本为单 C3D8R 单元静力作业，无大型隐式 ODB | 用真实大型算例（`case_07_jounce_bumper` 或同等）产出的 ODB 重跑同一验签，保留正例与负例结果 |
| P1-LEFTOVER-03 | 自适应心跳未接入 `AnalysisRunner` 主链路 | **未完成（按决定不做）** | `AnalysisRunner` 经 `JobController` 在 CAE 会话内提交，不暴露宿主 PID，执行路径不经过 `run_with_watchdog`；接入会改变主链路执行/超时/终止语义，超出阶段 1 已确认的最小补齐范围 | 由总体规划决定；若决定接入，需单独评估对主链路语义的影响并补充对应测试 |
| P1-LEFTOVER-04 | 契约 A 要求核验 ODB 修改时间戳，当前未实现 | **已被真机证据驳倒，待契约修订** | 2026-10-21 实证：mtime 规则双向失效——（a）把合法 ODB 的 mtime 改早于 `.sta` 后，规则会拒绝一个 `verified: true` 的可读文件；（b）截断与头部篡改两个真实损坏样本的 mtime 均**晚于** `.sta`，规则会放行。该规则既可误拒合法文件，又不能识别损坏，**不得**作为恢复门控 | 需明确决定修订契约文本（非实现该规则）。修订建议见下方 §P1-LEFTOVER-04 详细记录 |

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
2. **2026-10-21 真机实证（已不再是无样本条件下的推测）**：

   测量环境：Abaqus/Standard 2025，`tools/runtime_smoke.py` 单砖 C3D8R 静力作业，
   证据文件 `machine_validation/real_odb_validation.json`。

   | 实验 | mtime 规则的判定 | 实际情况 | 结论 |
   | :--- | :--- | :--- | :--- |
   | 合法 ODB 副本，mtime 设为早于 `.sta`（09:00 < 09:28） | **拒绝** | `verified: true`，2 帧，5 场输出 | 规则**误拒**合法文件 |
   | 截断 50%（110130 字节） | **放行** | `verified: false` | 规则**漏检**损坏 |
   | 头部篡改 4KB | **放行** | `verified: false` | 规则**漏检**损坏 |

   两个方向都失效：该规则既不能保护合法文件，也不能识别损坏。
3. **mtime 究竟能提供什么增量信息？** 实测回答：没有。真正的判别力来自至少两个已经存在的层次——
   预筛（大小 < 1024、恒定填充、明文前缀）捕获全零/全 `0xFF`/过小/明文伪造；
   `odbAccess.openOdb()` 捕获截断与头部篡改（这两类**能通过**预筛，说明预筛单独不够）。
   mtime 不在这条判别链上。
4. **建议的契约修订方向**（需批准，本文件未自行修改规划）：将探针 5 的"修改时间戳"要素替换为
   "能被 `odbAccess.openOdb()` 打开，且至少含一个非 `initial` 步、该步至少一帧"。
   这是本次实测中唯一具备判别力的结构条件。
5. **当前处置**：保留规划原文，不做静默豁免。该项状态由"验收偏差"更新为"已被反驳、待契约修订"；
   **仍未关闭**，且不得在任何实现中被当作恢复门控使用。
6. **后续决定点**：批准契约修订，或提供 mtime 有效的反例证据（目前不存在）。

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
| P2-LEFTOVER-02 | 真实 ODB 上的 `result_ref` 往返 | **证据已取得（单砖规模），未闭合** | 2026-10-21 已在真实 Abaqus 产出的 ODB 上跑通完整链路：冷提取 0.371 s → 写缓存 → 命中 0.001 s → 磁盘还原，`max_mises=11.6828`/`max_u2=5.2916e-4` 还原后完全一致。**但**仅 2 项需求、8 KB 载荷 | 在真实工程规模提取产物（多需求、大网格）上重跑同一往返 |
| P2-LEFTOVER-03 | TC-TOK-03 的 < 10 ms 还原仅在合成负载上实测 | **仍未闭合（规模未验证）** | 2026-10-21 已在真实 ODB 提取产物上实测 50 次：中位 0.099 ms、P95 0.12 ms、最大 0.153 ms，全部 `< 10 ms`。但这仍不是工程规模 | 在真实工程规模的提取产物上重复计时（含完整证据链还原） |
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

> A4 复核（见 `docs/phase-timing-boundaries.md`）进一步确认：T2「缺失」不是因为没有网格代码，
> 而是网格生成发生在 `apply_plan()` 的混合循环内且不返回耗时；`audit_inp_mesh_quality`
> 在生产代码中零调用。因此 T2 缺少的是**可测边界**，而非缺少网格能力。

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
| P3-LEFTOVER-02 | 剖析器未接入执行链路 | **部分接入** | 生产入口 `AbaqusAIAgent.analysis_run` 默认创建 `PhaseProfiler(strict=False)` 并传入 `AnalysisRunner.run`。该入口覆盖 `solve_requirement` 与自愈重跑。返回后把 `finalize().to_dict()` 写入本次运行已有的 `evidence/<run.id>/phase_profile.json`（不按 job 名另建目录）。无证据目录、`finalize()` 失败或目录不可写时不改变 run，失败记入 `internal_errors`。`AnalysisRunner.run` 直接调用仍默认不计时。落盘内容只有 T4a/T4b；T1/T2/T3/T5/T6 仍为 `NOT_RUN`。**未经真实 Abaqus 运行验证**。「主链路已具备全生命周期剖析」仍不成立 |
| P3-LEFTOVER-03 | T3 License 排队耗时仍为内部量 | **导出能力已实现，仍无真实测量** | A3 已让 `_LicenseContext.wait_seconds` 与 `QueueItem.license_wait_seconds` 可读取并有单元测试；但**没有调用方**把它们交给 `profiler.record_external()`，也没有真实 FlexNet/DSLS 排队数据。关闭条件「取得真实排队耗时」未满足 |
| P3-LEFTOVER-04 | T4b 多步 / restart 日志结构未验证 | **解析器已实现，真机结构未验** | `execution/solver_timing.py` 已能解析真实单砖 `.log`（7.0 s，手算 7 s），且多段仅在结构自洽时求和。但**多步分析是否产生多个 solver 段**、这些段语义上是否可加、restart 与 Explicit 的日志结构，均无真实样本。不得把「解析器已实现」读作「多步分析已支持」 | 用真实多步算例（含至少两个载荷步）与一个 restart 算例的 `.log` 重跑解析器，确认段数与耗时与手工核算一致 |

#### 验证层级声明

本项证据全部为**单元级**：

- `tests/test_phase_profile.py`（24 passed）使用 `FakeClock` 注入 `pp.time.monotonic`，断言的是契约行为，不是真实耗时；
- **没有**真实 Abaqus 求解、**没有**真实 License 排队、**没有**真实 ODB 提取；
- 通过本组测试**不能**推断任何真实阶段耗时，也**不能**推断阶段 1/2 的真实环境遗留项已关闭。

#### 测试与回归

| 项 | 结果 |
| :--- | :--- |
| 定向 `tests/test_phase_profile.py` | 44 passed → **51 passed**（A5 异常隔离后） |
| 定向 `tests/test_timing_plumbing.py` | **9 passed**（A1 / A3 新增） |
| 定向 `tests/test_solver_timing.py` | **38 passed**（T4b 解析器 31 + profiler 接入 7，含真实日志用例） |
| 定向合计（三文件） | **91 passed** |
| 全量 `pytest -q` | **1957 passed**（108.84 s） |
| 全量 `pytest -W error -q` | **1957 passed**（108.24 s） |
| `tools/check_workspace_pollution.py` | 提交后校验 |

#### T4b 解析器的验证层级

| 层面 | 已做 |
| :--- | :--- |
| 单元（构造日志） | 30 项：单段/多段/重叠/重复/多 job 头/截断/缺失时间戳/倒序时间戳/混乱格式/空文件 |
| 真实产物（单步单砖） | 1 项：`runs/odb_sample_run/AIAgent_ODBSample.log` → 7.0 s，与手工核算一致 |
| **真机多步 / restart / Explicit** | **未做**（无样本） |

真实日志用例在该文件不存在时**跳过**而非降级为断言通过；因此 CI 全绿
**不能**证明解析器与真实日志一致，只能证明它在构造样本上符合契约。

#### 3.1.1 计时基础设施补齐（任务图 A1 / A3 / A4 / A5）

这四项是**打点的前置条件**，不是打点本身。完成它们**不产生**任何阶段耗时数据。

| ID | 内容 | 落点 | 验证层级 |
| :--- | :--- | :--- | :--- |
| A1 | `BatchResult.duration` 透传 `WatchedProcessResult.duration` | `execution/batch.py:39-45`、`:118-121` | 单元级 |
| A3 | `_LicenseContext.wait_seconds`、`QueueItem.license_wait_seconds` | `execution/license.py:58-61`、`execution/queue.py:108-113`、`:419` | 单元级 |
| A4 | T1/T2/T6 边界定义（及 T3/T4/T5 边界复核） | `docs/phase-timing-boundaries.md` | **纯静态**，无运行证据 |
| A5 | `PhaseProfiler(strict=False)` 异常隔离 | `telemetry/phase_profile.py:156-176`、`_safe_store` | 单元级 |

**A5 的核心规则**（已核实代码）：`_safe_store()` 捕获记录期异常后，若被测代码已有异常在飞
（`exc is not None`），**永不覆盖**它；仅当 `exc is None and self.strict` 时才抛
`PhaseProfileError`。即「记录失败绝不能掩盖真实异常」。`strict=False` 下契约违例降级写入
`internal_errors`，最终经 `to_dict()` 暴露为 `profiling_errors`——**降级可见，不是静默吞掉**。

**A3 的时基校验**（已核实）：`QueueItem.enqueued_at` 与 `process_next()` 的 `now` **同为
`time.time()`**（`queue.py:96`、`:388`），差值有效；`current_time` 外部注入时必须同源。
`_LicenseContext` 走 `time.monotonic()`，两条路径各自自洽，**不可混用**。

#### 3.1.2 A4 的关键结论：T2 当前没有可测边界

A4 的审计结果比预期严重，必须单独记录（详见 `docs/phase-timing-boundaries.md` §3）：

| 候选锚点 | 不可用原因 |
| :--- | :--- |
| `audit_inp_mesh_quality` | 生产代码**零调用**，仅测试引用 |
| `evaluate_mesh_quality_gate` | 纯规则评估，不含网格生成 |
| `generate_mesh` action | 混在 `apply_plan` 的同一循环内（`agent.py:273-278`） |
| `writeInput` 段 | 是导出 inp + 装配审计，不是网格生成 |

`apply_plan` 逐个 `execute()` 并丢弃返回值耗时，**不暴露任何计时点**。要测 T2 必须改这条
循环，与 A2（T4 主链路计时）同属主链路语义变更，**未获授权**。

因此：**T2 在接入前只能登记 `NOT_RUN`**。任何「T2 已可测量」的说法都不成立。

#### 3.1.3 T4 的语义偏差（必须保留标注）

唯一可用边界是 `jobs.submit(job_name, wait=True, ...)`（`analysis_run.py:979`）。它测的是
**「提交到完成的等待时间」**，可能含求解器启动、License 排队与 IO，**不是纯刚度矩阵分解时间**。
把该值称为「求解耗时」属于扩大解释，验收记录不得这样写。

#### 3.1.4 本子批次未闭合项

| 项 | 状态 |
| :--- | :--- |
| T1 打点接入 | **未接线**（仅有边界定义） |
| T2 打点接入 | **未接线且无可测边界**（见 §3.1.2） |
| T3 打点接入 | **未接线**；字段可读但无调用方送入 profiler |
| T6 打点接入 | **未接线**（仅有边界定义） |
| 真实耗时数据 | **仍为零**，`P3-LEFTOVER-01` 保持未验证 |

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
| 2026-10-21 | 任务图 A1/A3/A4/A5：`BatchResult.duration` 透传、License 排队耗时外露、`PhaseProfiler` 异常隔离（`strict=False` 降级不掩盖真实异常）、T1~T6 边界定义（新增 `docs/phase-timing-boundaries.md`）。**关键发现：T2 无可测边界**（`audit_inp_mesh_quality` 生产零调用，网格生成混在主链路循环内）。定向 60 passed。`P3-LEFTOVER-01/02/03` 全部保持未闭合 |
| 2026-10-21 | A2 契约（`docs/a2-solver-timing-contract.md`）：T4 拆为 T4a 等待 / T4b 求解器；真实日志证明 15 s 等待中仅 7 s 是 `standard.exe`；`.dat`/`.log` 均为 1 s 量化 |
| 2026-10-21 | 新增 §0 未完成项总览表（19 项），并把 A2 契约条款与 T4b 实现状态写入文档 |
| 2026-10-21 | 实现 T4b 解析器 `execution/solver_timing.py` + 31 项测试：五类失败状态均不返回 0.0，多段需结构自洽才求和。真实单砖日志得 7.0 s。新增 `P3-LEFTOVER-04`（多步/restart/Explicit 日志结构未验证） |
| 2026-10-21 | `attach_solver_timing()` 把 T4a/T4b 写入同一 `PhaseProfiler`，不改 `AnalysisRunner`。因阶段记录唯一，T4b 存为 `detail["t4b"]`，**偏离契约 A2-3/A2-4**（偏差见 `a2-solver-timing-contract.md` §3.4）。无生产调用方，`P3-LEFTOVER-02` 保持未接入。定向 38 passed |
| 2026-10-21 | `AnalysisRunner.run` 新增可选参数 `phase_profiler`：传入时记录 T4a/T4b，不传时行为不变。经影响分析确认执行/超时/终止/返回值语义均不变，计时失败不改变 run 状态。T1/T2/T3/T5/T6 未接入，`P3-LEFTOVER-02` 改为**部分接入**。全量 1999 passed（含 `-W error`） |
| 2026-10-21 | 生产入口 `analysis_run` 默认采集 T4，并把 profile 写入本次运行已有的 `evidence/<run.id>/phase_profile.json`。落盘失败不改变 run。直接调用 `AnalysisRunner.run` 仍默认关闭。T1/T2/T3/T5/T6 仍未接入，真实耗时仍未采集，`P3-LEFTOVER-02` 保持部分接入。全量 2004 passed（含 `-W error`） |
