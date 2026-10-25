# T-P10–T-P14 联合治理证据（2026-10-26）

本批次按一个治理批次执行、分项验收。T-P10 只做处置分类，不执行删除；T-P11/T-P12 落实边界声明；T-P13 落实仓库产物规则；T-P14 补齐材料适用区域语义核对。

## T-P10：12 个测试/工具模块处置

### 证据基线

- 当前引用审计：`docs/audits/tp10_20261025/ast_verify.txt`，SHA-256 `4DC87005A543AB8A9A862C05ABE2E01822052478DBCB956F9D873AE1F46A20D3`。
- 审计脚本：`docs/audits/tp10_20261025/ast_verify.py`，SHA-256 `442C32C3C7BDFA9B2DC9EDA8C3A25BFF0EE1E2CB0B15874404F098790B2710C7`。
- Jev 定性请求与原始响应：`docs/audits/tp10_20261025/jev_review.json`，模型 `jev-1.14.0`，SHA-256 `2B624DBB62538A9BC1302D712F5C366748BA0F8BF4980125C12A358D29031477`。
- 判断原则：直接生产导入计数属于 A 级证据；模块价值和处置属于 B 级判断。`src=0` 不是删除依据。

### 最终处置表

| 模块 | 当前行数 | 最终处置 | 证据与依赖结论 |
|---|---:|---|---|
| `mesh_audit.py` | 519 | 保留 | 3 个测试模块覆盖 INP 四边形/六面体 Jacobian 审计；它调用 `mesh_gate`，但当前生产 `mesh_quality` 是 `planning/compiler.py -> actions/builders.py -> actions/script.py -> analysis_run.py -> acceptance.py` 的原生 Abaqus 链，二者不可混同。`C3D10M` 四面体明确不受该审计器支持。 |
| `contracts/benchmarks_catalog.py` | 562 | 保留 | 2 个测试和 3 个资格工具使用 22 项官方基准、引用、容差和参数契约，承载基准可复现性。 |
| `perception/image_context.py` | 415 | 保留 | 测试覆盖图片魔数/CRC、元数据对齐、有界切片和整图阻断；按 T-P12 保持感知包 B 级可达性，不据此判断产品已启用。 |
| `results/query_protocol.py` | 377 | 保留 | `results/__init__.py` re-export，导入 `results` 子模块时会加载；测试覆盖标量/热点/证据查询、raw-array 阻断、预算和 token 压缩。`contracts/capability.py` 的 `.results` 是 `contracts.results`，不是根 `results` 包。 |
| `contact_diagnostics.py` | 350 | 接入 | 8 个测试和 5 个工具使用；`contracts/contact.py` 定义结果类型，本模块计算诊断。生产 acceptance 已消费诊断对象，但计算能力尚未进入主生产链，应接入而非删除。 |
| `execution/convergence_loop.py` | 258 | 接入 | 测试覆盖多级细化、收敛、奇异停止、预算耗尽和证据 fail-closed；生产已使用 `execution/convergence.py`，该模块提供尚未接入的多级收敛能力。 |
| `perception/benchmark_evaluator.py` | 216 | 保留 | 测试和绘图资格工具用它计算感知 precision/recall/F1，是感知基准证据支撑。 |
| `adapters/abaqus/locator_validation.py` | 24 | 接入 | 测试覆盖 Face/Edge/Vertex 解析、`findAt` 失败、歧义和实例不匹配；适合作为 Abaqus locator 的生产安全校验。 |
| `grounding/serialization.py` | 20 | 删除候选 | 未发现 src/test/tool/doc/dynamic-load/re-export 消费；仅是通用 dataclass-to-JSON 辅助。 |
| `grounding/scoring.py` | 13 | 整合 | 1 个测试使用，通用加权评分与 `grounding/ranking.py` 重叠，应合并到统一评分层。 |
| `actions/raw.py` | 10 | 删除候选 | 未发现模块导入；`actions/builders.py::python_action` 已承担该能力。历史 test/tool 计数是同名符号文本命中，不是模块消费者。 |
| `contracts/input.py` | 17 | 删除候选 | 未发现模块消费者；`ExperimentInput` 无调用，历史计数是同名符号文本命中。 |

“明确不支持”没有整模块归属；`mesh_audit` 保留的同时，`C3D10M` 路径必须写成明确能力边界，不能用该模块证明 C3D10M 网格质量。三个删除候选均未删除，后续必须逐文件单独批准。

### 名单口径差异

`src/abaqus_ai_agent/benchmark_catalog.py` 为 48 行、3 个简单 `BenchmarkCase`，当前审计标为 TEST-ONLY，但它不是 562 行的 `contracts/benchmarks_catalog.py`。本次维持 12 项正式范围，将它记录为 scope discrepancy，处置为 `exclude_with_note`，不并入第 13 项。

### Jev 与人工复核

Jev 对 `mesh_audit`、`benchmarks_catalog`、`image_context`、`query_protocol`、`benchmark_evaluator` 的 keep 概率为 0.92–1.00；对 `contact_diagnostics`、`convergence_loop`、`locator_validation` 也建议 keep。人工复核依据生产职责缺口，将后三项定为“接入”。`grounding/scoring.py` 的 keep/merge 各为 0.49、选择置信度仅 0.36，人工按重叠关系定为“整合”。三个删除候选与 Jev 结论一致，其中 `actions/raw.py` 的 delete 概率仅 0.69，因此仍保留独立审批门槛。

## T-P11 / T-P12：未启用与 B 级边界

- `tools/__init__.py` 已声明工具注册表未接入 Agent 主求解循环。
- `workflow/__init__.py` 已声明 workflow 步骤名（含 `mesh_quality`）不构成执行证据。
- `workflow/mbd.py` 已标记 `build_mbd_plan` 为零调用候选，并保留“不得仅据此删除”的边界。
- `context/__init__.py`、`llm/__init__.py`、`perception/__init__.py` 已声明未接入 solve path，同时保留动态可达性和 re-export 的 B 级不确定性。

处置保持“标注、保留、不接入、不删除”；静态零引用不升级为运行时不可达结论。

## T-P13：仓库产物治理

`docs/repository-artifact-governance.md` 固化六个治理目录的规则。`.gitignore` 已删除 `machine_validation/*` 及其反向白名单，以及 `runs/` 整目录规则；只保留具体临时输出：

- `/runs/live_environment_gate.json`
- `/runs/h6_grounding_validation/h6_grounding_live_result.json`
- `/runs/**/*_script.py`
- `/runs/images/slide_*_img_*.png`

`tests/test_repository_artifact_governance.py` 同时验证六个治理目录中的代表性 JSON/HTML/资产不被整目录忽略，以及已知临时件仍被忽略。`tools/check_workspace_pollution.py` 的保护范围扩展到六个目录。

## T-P14：材料证据与最终 `.inp`

`contracts/deck_material.py` 现在解析常见 `*...SECTION` 的 `ELSET + MATERIAL`，生成 `applicable_regions` 和 `section_assignments`。材料声明与 deck 的比较继续覆盖名称、单位、弹性值、密度和塑性数据点，并新增：

- `material_applicable_regions_missing`
- `material_applicable_regions_mismatch`
- `material_unassigned_in_deck`

`reporting/renderer.py` 的材料表新增“适用区域 / Applicable Regions”列。报告材料行仍由 `deck_material_table()` 从实际求解 deck 生成，调用者/LLM 材料表只作为待核对声明，不能改写报告事实。

验证：`tests/test_deck_material_applicable_regions.py` 与 `tests/test_acceptance.py` 定向 18 项通过；纯非真机全量回归 2372 项通过；T-P13 治理与工作区测试 26 项通过。至此正文与汇总表的 T-P14 状态统一为已关闭。
