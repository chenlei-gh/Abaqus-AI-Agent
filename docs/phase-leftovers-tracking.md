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
| 报告体被掏空但绑定仍匹配 | 同上 `extractions_missing` | `result_ref.counts` 与实际条数不一致即拒绝复用 |
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

### 2.5 测试与回归

| 项 | 结果 |
| :--- | :--- |
| 定向测试（7 个文件） | 89 passed |
| 全量 `pytest -q` | 1889 passed（118 s） |
| 全量 `pytest -W error -q` | 1889 passed（118 s） |
| `tools/check_workspace_pollution.py` | passed |

---

## 变更历史

| 日期 | 变更 |
| :--- | :--- |
| 2026-10-20 | 建立本文件；结转阶段 1 的 4 项遗留（3 项未验证、1 项契约偏差），作为带条件进入阶段 2 的前提记录 |
| 2026-10-21 | 登记阶段 2 验收记录：TC-TOK-01/02/03 单元级通过，新增 5 项遗留（真实 Provider 日志、真实 ODB 往返、真实规模计时、图像链路接入、JPEG 头部校验边界） |
| 2026-10-21 | 契约加固：缓存结构损坏归一为未命中、计数自洽校验、摘要严格 `<1500`、遥测来源降级、Provider usage 有效性校验、基准证据分层。全量 1889 passed（含 `-W error`） |
