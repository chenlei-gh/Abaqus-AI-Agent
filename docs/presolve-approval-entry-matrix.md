# 求解入口覆盖矩阵（求解前审批 · 第 1 步交付物）

日期：2026-10-27
范围：仅限求解前审批方案列出的调用链与实际提交点，不做全仓库泛化审查。
性质：只读审计结论；本步骤未修改任何代码。
判定口径：每个检查项只允许两种结论 —— "已被现有代码覆盖" 或 "存在明确缺口"。

## 1. 生产求解入口清单

| # | 入口 | 位置 | 说明 |
|---|------|------|------|
| E1 | `AbaqusAIAgent.solve_requirement()` | agent.py:1299 | 产品主入口（自然语言/结构化 intent） |
| E2 | `AbaqusAIAgent.solve_user_inp()` / `edit_and_solve_user_inp()` | agent.py:758 / agent.py:794 | 用户 INP 直接求解/编辑后求解 |
| E3 | `AbaqusAIAgent.analysis_run()` | agent.py:1098 | 显式运行入口，唯一实例化 `AnalysisRunner` 的位置（agent.py:1121） |
| E4 | `AbaqusAIAgent.submit(job_name)` | agent.py:1187 | 裸提交方法，直接调用 `JobController.submit` |
| E5 | 自愈编排器重编译路径 | diagnostics/orchestrator.py:227-251 | 修复重试时 `compile_engineering_intent(submit_job=True)` 并应用计划 |

CLI 现状：无任何求解子命令。`ask` 只路由意图、不求解（cli.py:338 自述 "ask routes intent only; it does not solve"）。worker 与 sensitivity 均通过 `AnalysisRunner` 漏斗（execution/worker.py:56、sensitivity.py:54）。

## 2. 实际提交点（作业真正启动的位置）

| # | 提交点 | 位置 | 触发链路 |
|---|--------|------|----------|
| S1 | CAE 会话内 `mdb.jobs[name].submit(consistencyChecking=ON)` | execution/jobs.py:50（`JobController.submit`），由 analysis_run.py:1171 `_submit_and_time` 调用 | E1/E3/E5 的 AnalysisRunner 段 |
| S2 | 编译计划内嵌 Python 动作 `submit(consistencyChecking=OFF)` + `waitForCompletion()` | planning/compiler.py:1745-1746（`submit_job=True` 时生成，`solve_requirement` 默认 True，agent.py:1310/1586） | 由 `apply_plan_with_evidence` → `actions.runner.execute` → `executor.execute` 执行（agent.py:1696、actions/runner.py:14-21），**先于 S1 触发** |
| S3 | 批处理子进程 `abaqus job=X input=Y` | execution/input_modes.py:394-408（优先 `executor.run_input` 走 BatchExecutor，execution/batch.py:130；否则 `executor.execute` 回退） | E2 |
| S4 | 冒烟工具提交 | execution/runtime_smoke.py:104-107 | 测试工具，非生产 |
| S5 | Golden/E2E 工具脚本直接使用 `BatchExecutor` | tools/*.py（case_07、ga14、各 l4_golden_e2e 等） | CI/真机验证通道，不经生产 agent 路径 |

## 3. 覆盖矩阵

| 检查项 | 核实的事实 | 结论 |
|--------|-----------|------|
| E1 是否经过统一提交边界 | 否。S2 内嵌提交在 `apply_plan_with_evidence` 阶段即执行（CAE 会话内 `waitForCompletion` 阻塞至作业结束），随后 S1 在 AnalysisRunner 中再次提交同一作业。S2 绕过 "Single Canonical Production Outlet"（agent.py:1706 注释）所声明的架构 | 存在明确缺口 |
| E2 是否经过 AnalysisRunner | 否。input_modes 独立提交（S3），不经过 preflight、求解器选择门、装配契约审计或台账 | 存在明确缺口 |
| E3 是否经过统一提交边界 | 是。唯一 `AnalysisRunner(...)` 实例化点，经 preflight 硬门（analysis_run.py:778-800）后由 S1 提交 | 已被现有代码覆盖（指漏斗归一，审批门禁尚不存在） |
| E4 裸提交是否可绕过 | 是。`agent.submit()` 对已有 mdb 作业直接提交，无任何门 | 存在明确缺口 |
| E5 自愈重试是否经过统一提交边界 | 否。重编译 `submit_job=True`，应用计划时 S2 触发 | 存在明确缺口 |
| 直接调用能否绕过 Agent/CLI | 库级 API 即生产入口（E1-E4 均为公开方法）；任何持有 executor 的调用方也可直接 `JobController(executor).submit(...)`。门禁必须落在提交边界本身而非调用方 | 存在明确缺口 |
| 恢复路径：已提交作业是否先核对真实状态 | `reconcile_run_state()`/`resume_from_ledger()` 已实现（reconciliation.py:291/161），含进程/`.lck`/`.sta`/ODB 物理探针；但**未被任何生产入口调用**——无 CLI resume 子命令，`AnalysisRunner.run` 提交前不做 reconcile（仅 analysis_run.py:807 注释提及） | 存在明确缺口（机制已覆盖，接入缺失） |
| CI/Golden 是否走显式受控路径 | S5 工具脚本直接用 BatchExecutor，与生产 agent 路径物理分离；目前无"免人工审批"策略概念，亦无审批可免 | 已被现有代码覆盖（通道隔离），审批豁免策略待第 3 步定义 |
| 现有证据链职责划分 | `run_lifecycle.json`/`RunSnapshot`：运行恢复索引（reconciliation.py，原子 `os.replace` 写入）；`AnalysisProvenance`：model/input/intent/action_plan 哈希（contracts/provenance.py）；`EvidenceManifestV2`：求解后证据完整性（contracts/evidence.py）。三者均无"用户已批准该候选版本"语义 | 存在明确缺口（审批契约整体缺失） |

## 4. 现有可复用的门禁先例（审批门禁的挂点参考）

- preflight 硬门：analysis_run.py:778-800，fail-closed 阻断范式。
- 求解器选择阻断：`SolverSelectionBlocked`（analysis_run.py:1010）+ `solver_selection_confirmation_pending` 元数据——"需要用户确认才能继续"的既有先例。
- 装配契约审计 + INP SHA-256 绑定 + 提交前一致性复检：analysis_run.py:1052-1148。**注意：仅当 `assembly_scope is not None` 时执行**，非装配运行缺少提交前哈希绑定，候选版本契约设计时需覆盖此盲区。
- 台账持久化时点：PREFLIGHTED（analysis_run.py:845）、SOLVING（analysis_run.py:1179）。

## 5. 对第 2/3 步的约束（由本矩阵直接推出）

1. 审批门禁必须同时拦截 S1、S2、S3 三个提交点；仅在 AnalysisRunner 内加门不足以覆盖 E1（S2 先于 S1）与 E2（S3 不经 Runner）。
2. S2 的建议处置：编译计划不再内嵌 submit（`solve_requirement`/orchestrator 改传 `submit_job=False`），使 S1 成为 intent 类求解的唯一提交点；该改动本身需在门禁落地前完成并回归。
3. E2 的处置：input_modes 提交前调用同一审批服务，或将 E2 重路由进 AnalysisRunner。
4. E4 的处置：裸 `agent.submit()` 需接入审批或明确降级为诊断/测试接口。
5. 恢复接入：新增 resume/approve CLI 时调用 `reconcile_run_state()`，不另建恢复逻辑；台账快照需扩展关联 candidate_id 与审批记录。
6. "提交成功但台账未写入"窗口由 reconciliation 物理探针兜底，审批层不得仅凭台账状态决定重提。
## 6. 实施状态（2026-10-27 更新）

第 1 步矩阵中的缺口处置已落地：

| 约束项 | 实施结果 |
|--------|----------|
| S2 内嵌提交 | 已移除：`solve_requirement` 默认 `submit_job=False`、自愈编排器同样改为 False；S1（AnalysisRunner）成为 intent 类求解的唯一提交点 |
| S1 门禁 | `AnalysisRunner.run` 在 `JobController.submit` 前调用 `enforce_pre_solve_approval`；阻断时返回 SUBMISSION_BLOCKED，台账记 `AWAITING_APPROVAL`，并生成 `pre_solve_review.html` |
| S3 门禁 | `input_modes.solve_user_inp` 在批处理提交前过同一门禁；阻断时同样落评审报告，重新执行需复用同一 `run_id`（workdir 由 run_id 决定） |
| E4 门禁 | `agent.submit()` 已接入同一审批服务 |
| 重复提交防护 | runner 在覆盖台账前先核对既有台账相位；SOLVING/RUNNING/COMPLETED 触发 `reconcile_run_state` 物理探针，仅 CLEANUP_AND_RESUBMIT 放行，且阻断时不改写原台账 |
| 审批 CLI | 新增 `approve` 子命令，调用统一审批服务，绑定评审报告哈希 |
| CI/Golden 豁免 | 策略解析顺序：显式参数 > `ABAQUS_AI_AGENT_APPROVAL` 环境变量 > 测试替身识别；真实执行器默认 required；tools/* 批处理通道与生产 agent 路径物理隔离 |
| 审批契约 | `contracts/approval.py`：PROPOSED → APPROVED → SUPERSEDED，漂移即失效，摘要仅为防篡改证据而非身份签名 |

真机验证：E2 批处理路径（`machine_validation/presolve_approval_live_evidence.json`）与 E1 真实 CAE 会话路径（`machine_validation/e1_presolve_approval_live_evidence.json`）均已闭环。E1 结果：Phase A 阻断 → CLI 批准（绑定评审报告哈希）→ Phase B 哈希匹配放行 → Abaqus/Standard 2025 真实求解完成（.sta COMPLETED，ODB 1,739,244 字节）→ 验收 PASS、真实指标提取成功。正式交付层按既有规则 DELIVERY_BLOCKED（与审批门禁无关的独立子系统行为）。E2 细节：：Phase A 阻断并产出候选与评审报告 → 审批 → Phase B 真实 Abaqus/Standard 2025 求解成功（.sta COMPLETED，ODB 182,376 字节，SHA-256 已记录）→ 修改 INP 后再次阻断且旧候选归档为 SUPERSEDED → CLI 审批生效 → 重复审批被拒（exit 2）。

已知边界（诚实披露）：

- 批处理启动器可能在求解器刷新产物前返回 rc=0，导致 `solve_user_inp` 的 API 判定与物理证据（.sta/ODB）短暂不一致；这是既有的 E2 通道行为，不是本门禁引入的问题。真机验证以 .sta/ODB 物理证据为准并已如实记录。
- 候选文件按 workdir 持久化；Phase B 必须复用 Phase A 的 workdir（E1 由 `workdir=` 参数、E2 由同一 `run_id` 保证）。
- 审批摘要证明"内容未被篡改"，不证明审批人身份；有写权限者可以重算摘要。
