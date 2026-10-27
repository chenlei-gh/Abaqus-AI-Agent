# Golden 脚本命名空间迁移盘点（第 5 步 · 只读审计）

基线提交：`2778c29`（main，第 4 步运行时加固已合入）。
本文件是第 5.1 步的交付物：16 个 Golden 脚本的全量盘点、逐文件迁移表、
已知风险集中清单与 3 个试点的选择依据。本步不修改任何被盘点的脚本。

## 1. 范围确认

在 `tools/` 下以 `_run_code` / `globals()` 模式执行动态代码的脚本共 16 个，
与计划假设一致。`fmbd6_flexible_to_flexible_golden_e2e.py` 与
`fmbd7_dual_flexible_four_bar_golden_e2e.py` 不含 `exec`/`_run_code`/
`InProcessExecutor`（直接构建并提交，无动态片段），不在本次迁移范围内。

## 2. 总体发现

### 2.1 所有 16 个脚本的 `_run_code` 只有两种变体

- **变体 A（12 个）**：`exec(compile(code, ...), globals(), globals())`，
  执行前**不清理** `result`。上一片段遗留的 `result` 字典可能被误读为
  当前片段的输出 —— 这是跨片段结果串档风险，不只是理论问题：
  变体 B 的 4 个脚本正是为了堵这个洞才手工加了 `globals().pop('result')`。
- **变体 B（4 个）**：p1_2、p1_3、p1_product_solve、run_live_report_gate。
  执行前手工 `globals().pop('result', None)`；整段 CAE 侧脚本以
  f-string/format 模板承载（`_run_code` 体内是 `{{...}}` 双花括号）。

`KernelNamespace.execute()` 每片段前清理 `result`，两种变体迁移后语义统一，
且变体 A 的串档风险随之消除。

### 2.2 12 个脚本各自复制了一份 `CAEInProcessExecutor` 类

定义位置（行号）：static 177 / dynamic 202 / explicit 201 / thermal 163 /
mbd 202 / mbd2 221 / fmbd4 228 / fmbd5 291 / general_contact 262 /
tie_contact 233 / mesh_convergence 182 / production_delivery 193。
变体 B 的 4 个脚本定义的是 `CAEExecutor`（含 `launcher` 参数版本）。
本次迁移只替换 `_run_code` 的实现，不合并这些复制类（避免范围蔓延）；
类去重可作为后续独立改进项。

### 2.3 跨片段变量依赖：只有 mesh_convergence 一处真实存在

对全部 16 个脚本的片段载荷（triple-quoted payload）做了静态扫描：

- 15 个脚本的片段**完全自包含**：所有配置值经 `%r`/`repr()` 以字面量注入，
  没有任何片段以裸标识符读取 harness 模块级配置名。
- **mesh_convergence_e2e** 的第二个片段读取前一片段赋值的
  `model` / `part` / `inst`（`part = model.parts[...]`、
  `fixed_nodes = inst.nodes.getByBoundingBox(...)` 等 9 处）。
  这证明"命名空间必须在同一次运行内持久"是硬需求而非防御性设计，
  每次 `exec` 新建字典会直接破坏该脚本。

### 2.4 4 个 agent 驱动脚本的片段是运行时生成的，静态无法枚举

p1_2、p1_3、p1_product_solve、run_live_report_gate 通过
`AbaqusAIAgent.solve_requirement(...)` 让 agent 规划产生代码片段。
隔离对它们价值最大（agent 代码可能 `from abaqusConstants import *`，
正是 2026-10-27 `LOG` 被 SymbolicConstant 覆盖事故的成因），
同时风险也最高：片段内容不可静态审计，只能靠真机回归验证。

### 2.5 与求解前审批门的交互（试点必须正面处理）

`run_live_report_gate` 调用 `solve_requirement(submit_job=True,
require_production=True)`。在第 4 步之前这会直接求解；现在会被
求解前审批门拦截。试点迁移时**不得**为绕过审批而改脚本语义，
应显式走批准流程（或显式声明受控策略），这本身也是对
"审批门 + 命名空间隔离"两条新防线兼容性的验证。

### 2.6 现有离线测试不执行 `_run_code`

test_static_golden_e2e.py 等离线用例做的是脚本装配的 AST/结构检查，
不会真正 exec 片段。迁移后必须为试点补充"用伪内核驱动迁移后
`_run_code`"的离线负例测试（覆盖：片段异常传播、`result` 隔离、
跨片段持久、star-import 不污染 harness）。

## 3. 逐文件迁移表

| # | 脚本 | 变体 | 行数 | agent 驱动 | 跨片段依赖 | 离线测试 | 迁移风险 | 批次 |
|---|------|------|------|-----------|-----------|---------|---------|------|
| 1 | static_golden_e2e | A | 499 | 否 | 无 | 有（结构级） | 低 | **试点 1** |
| 2 | run_live_report_gate | B | 422 | 是 | 动态 | 无 | 高（叠加审批门） | **试点 2** |
| 3 | production_delivery_e2e | A | 626 | 否 | 无 | 有（契约级，含 fail-closed） | 中 | **试点 3** |
| 4 | mesh_convergence_e2e | A | 583 | 否 | **有（model/part/inst）** | 无 | 中（持久性回归必做） | 批次 1 首个 |
| 5 | thermal_golden_e2e | A | 584 | 否 | 无 | 有（结构级） | 低 | 批次 1 |
| 6 | dynamic_golden_e2e | A | 633 | 否 | 无 | 有（结构级） | 低 | 批次 1 |
| 7 | explicit_golden_e2e | A | 708 | 否 | 无 | 无 | 低 | 批次 1 |
| 8 | mbd_golden_e2e | A | 755 | 否 | 无 | 有（结构级） | 低 | 批次 2 |
| 9 | mbd2_revolute_golden_e2e | A | 740 | 否 | 无 | 有（结构级） | 低 | 批次 2 |
| 10 | fmbd4_rigid_flexible_golden_e2e | A | 705 | 否 | 无 | 有（结构级） | 低 | 批次 2 |
| 11 | fmbd5_crank_slider_golden_e2e | A | 883 | 否 | 无 | 有（结构级） | 低 | 批次 2 |
| 12 | general_contact_e2e | A | 753 | 否 | 无 | 无 | 低 | 批次 2 |
| 13 | tie_contact_e2e | A | 664 | 否 | 无 | 无 | 低 | 批次 2 |
| 14 | p1_product_solve_golden_e2e | B | 439 | 是 | 动态 | 无 | 高 | 批次 3 |
| 15 | p1_2_reasoning_qualification_e2e | B | 682 | 是 | 动态 | 无 | 高 | 批次 3 |
| 16 | p1_3_result_delivery_golden_e2e | B | 388 | 是 | 动态 | 无 | 高 | 批次 3 |

迁移操作本身对每个文件是同一形状：删除脚本内 `_run_code` 的手写实现，
改为持有一个 `KernelNamespace` 实例（CAE 侧以 `build_cae_seed()` 播种），
`_run_code` 变为 `lambda code: _NS.execute(code, '<AIAgent-...>')`。
变更点集中在每个文件的模板内一处，不触碰工程参数与验收标准。

## 4. 已知风险集中清单

| 风险 | 等级 | 说明与对策 |
|------|------|-----------|
| R1 跨片段持久性被破坏 | 高 | 只影响 mesh_convergence（静态可见）与 4 个 agent 脚本（动态不可见）。对策：`KernelNamespace` 单实例贯穿整次运行；试点 2 与批次 1 首个脚本专门回归。 |
| R2 片段读取 harness 配置名 | 低 | 静态扫描未发现（全部字面量注入）。若 agent 动态代码尝试读取，迁移后会 NameError —— 这是期望的显式失败，好过静默读错值。 |
| R3 `result` 串档语义变化 | 中 | 变体 A 今天依赖"残留 result"的行为若存在（未发现证据），迁移后会消失。对策：试点对比迁移前后每个片段的返回序列。 |
| R4 审批门拦截 agent 脚本 | 中 | run_live_report_gate / p1_product_solve 等 `submit_job=True` 路径现在会被审批门拦截。迁移时必须显式走批准流程，不允许为通过测试而禁用门禁。 |
| R5 模板转义破坏 | 低 | 变体 B 的 `_run_code` 在 f-string 模板内，替换时需保持 `{{}}` 平衡；补丁纪律：逐处计数断言 + 写后复读 + AST 解析。 |
| R6 基准证据被覆盖 | — | 新旧证据分开归档：新证据文件名加 `_kn` 后缀（如 `static_golden_e2e_kn.json`），原 `static_golden_e2e.json` 保持不动。 |
| R7 kernel_namespace.py 文档字符串乱码 | 低 | 两处 em-dash 被错误编码（`??`）。随试点提交一并修复为 ASCII。 |

## 5. 试点选择与依据

### 试点 1（静态算例）：static_golden_e2e

- 16 个脚本中最小（499 行）、片段全部自包含、无跨片段依赖，迁移面最小。
- 有真实基准证据（`machine_validation/static_golden_e2e.json` 与
  `static_golden_run_b.json`）可做迁移前后逐项对比。
- 求解量小（C3D8R 悬臂梁），真机回归成本低。

### 试点 2（动态执行算例）：run_live_report_gate

- 唯一完整走 `solve_requirement(require_production=True)` 全链路的脚本，
  agent 动态产生片段 —— 正是命名空间隔离要防的场景。
- 同时覆盖与求解前审批门的集成（R4），一次真机运行验证两条新防线。
- 变体 B 代表：迁移后可拆除手工 `pop('result')`，验证模板转义纪律（R5）。

### 试点 3（异常路径算例）：production_delivery_e2e

- 含交付拒绝/防篡改的 fail-closed 检查（reject 语义），异常传播与
  失败证据写入是其自然流程的一部分。
- 有契约级离线测试（test_production_delivery_contracts.py，含 AST 结构与
  fail-closed 用例）可作为迁移后的第一级回归。
- 变体 A、确定性片段，异常路径可静态推断，便于写负例。

### 明确不进试点但需要点名

- mesh_convergence_e2e：唯一的静态可见跨片段依赖，列为批次 1 首个迁移对象，
  迁移时必须附"片段 2 读取片段 1 变量"的持久性回归。
- p1_product_solve / p1_2 / p1_3：agent 驱动且叠加审批交互，放到批次 3，
  待试点 2 把审批 + 命名空间的组合跑通后再迁移。

## 6. 迁移约束（第 5 步全程有效）

1. 命名空间同一运行内持久存在，禁止每片段新建字典。
2. `result` 只经 `KernelNamespace` 接口读取，禁止 `globals().get('result')`。
3. 不改变任何算例的工程意图、求解参数或验收标准。
4. 不覆盖已有基准证据；新证据以 `_kn` 后缀单独归档。
5. 迁移前后逐项对比：结果数值、退出状态、证据完整性、异常行为。
6. 每个迁移文件配离线负例（片段异常 / result 隔离 / star-import 不污染）；
   需要真机的明确标记，不以静态检查冒充运行证据。

## 7. 试点 1 验证结果（static_golden_e2e，已完成）

前置条件补齐（按复核要求先于迁移完成）：

- `KernelNamespace` 契约测试补齐 4 项：真实星号导入隔离（伪 abaqusConstants
  模块复现 LOG 覆盖机制）、片段异常传播与 stdout 恢复、失败片段不留陈旧
  `result`、seed 不污染调用方。全部通过。
- 片段依赖审计：对 static 全部 13 个片段（11 个库生成 + 2 个字面量 payload）
  做 AST 名称解析，残差名仅 `mdb` 与 abaqusConstants 符号，
  `build_cae_seed()` 完全覆盖；无任何片段引用 harness 配置名。

真机验证（Abaqus 2025，工作目录 D:\AbaqusProjects，仓库外）：

| 阶段 | 结果 | 证据 |
|------|------|------|
| Phase A 拒绝 | 审批门拦截，INP 已编译但未提交求解（无 .sta/.odb），台账 AWAITING_APPROVAL | machine_validation/static_golden_e2e_kn_phase_a.json |
| CLI 批准 | candidate `StaticGoldenJob-cf1c2465724e`，绑定评审报告哈希 | 台账 + execution_candidate.json |
| Phase B 通过 | 真实求解完成，status=pass，验收 PASS | machine_validation/static_golden_e2e_kn.json |
| A/B 对照（迁移前 `_run_code`，同代码库） | status=pass；候选 manifest 逐字节相同（`cf1c2465724e...`） | machine_validation/static_golden_e2e_pre_kn_ab.json |

A/B 逐项对比（612 个报告键）：60 处差异全部为环境字段（run_id、时间戳、
含时间戳的产物 SHA-256、工作目录路径）；18 个数值差异中 17 个是
modified_time，1 个是 .msg 文件 1 字节宽度差（求解耗时字符串位数变化）。
所有物理结果（位移、反力、网格指标、验收判据）逐位一致。

附带验证：COMPLETED 台账下的重复提交防护在迁移前版本上意外触发并正确拦截
（reconcile 物理探针判定作业已完成，拒绝重提）——这是设计的防重复提交行为，
单独取证于本次 A/B 过程。

结论：试点 1 通过。`static_golden_e2e` 的命名空间迁移保持行为不变，
审批门拒绝与批准两条路径均独立取证。

## 8. 集中整改与试点 2/3 验证结果（已完成）

按集中审查意见整改了 5 组阻塞问题并补齐 T1-T8 测试缺口。
**整改过程中发现一个审查清单之外的 P0 级真实缺陷**（试点 2 Phase A 真机暴露）：

### 8.0 新发现：计划内嵌提交绕过审批门（已修复）

试点 2 第一次 Phase A 运行中，审批门正确返回 BLOCKED/AWAITING_APPROVAL，
但 `.sta` 显示求解已完成——`compile_engineering_intent(submit_job=True)`
在 job 创建动作中内嵌 `mdb.jobs[...].submit()`（planning/compiler.py），
该动作经 `apply_plan_with_evidence` 在门介入前就执行了求解。
修复：`agent.py` 调用编译器时硬编码 `submit_job=False`（唯一规范出口
AnalysisRunner 自行完成受门控的提交），并加回归测试
`test_solve_requirement_never_embeds_submit_in_plan_actions`
（已验证该测试在还原 bug 时失败）。修复后 Phase A 复跑：
无 .sta/.odb，只有编译后的 INP——求解确实未被提交。

### 8.1 试点 2（run_live_report_gate）整改项

- P0-1：模板缩进 TabError 修复；模板从 f-string 改为 % 格式化（消除转义雷区）；
  新增 T1 测试对渲染产物做 AST 解析（该 bug 意味着此工具此前从未成功运行过）。
- P0-2：删除无条件 `AIAgent_LIVE_GATE_SUCCESS`；CAE 侧只序列化 facts
  （BEGIN/END 标记包裹），verdict 由宿主侧 `compute_live_gate_verdict` 纯函数计算；
  `[Audit PASS]` 不再无条件输出；退出码按 verdict 区分（PASS=0/AWAITING=2/FAIL=1）。
- P0-3：非空 workdir 拒绝运行（`--reuse-workdir` 仅限 Phase B）；每次运行唯一
  run_id 嵌入 facts 与摘要文件名；rpy/摘要回退均校验 run_id；产物 mtime 必须
  晚于启动时刻。
- P1-4：PASS 需要全部门禁（进程 rc、settled、run 身份、任务状态、求解终态、
  验收、交付落盘、必需产物哈希）；DELIVERY_BLOCKED 单独分类。
- 默认提示词修复（原文件中文已损坏为乱码；英文提示词需显式边界条件措辞才能
  通过意图解析——`missing_boundary_constraints` 为实测结论）。
- 顺带修复：solve_requirement(require_production=True) 需要 ExternalProjectContext
  （REQ-ISO-003），模板已接入；求解异常时 facts 仍兜底输出（task_status=CRASHED）。
- 跨运行批准引入：`approval_service._import_project_approval`——候选 ID 内容寻址，
  仅限 `solver/<run_id>` 同级布局，漂移仍由 assert_submittable 拦截；5 个新测试覆盖。

真机证据：Phase A `machine_validation/live_gate_kn_phase_a.json`
（AWAITING_APPROVAL，无求解产物）；Phase B `live_gate_kn_phase_b.json`
（批准被跨运行采用、求解完成、验收 PASS，终态 DELIVERY_BLOCKED——
E1 已记录的正式交付子系统既有行为，与本次迁移无关，未做扩大处理）。
遗留观察：Phase B 中 agent 对 200N 载荷的规划结果反力为 210435N、
max_mises 提取为 0，属 agent 规划/提取质量问题，已如实记录在证据中。

### 8.2 试点 3（production_delivery_e2e）整改项

- P1-5：宿主终态门禁——`return_code != 0` 或 `settled is not True` 时失败关闭，
  不再读取任何报告；审批拦截有专属标记与可操作错误信息。
- 新增 `--project-dir` 支持两阶段（复用时仅清理本工具拥有的判定文件，
  台账与候选保留）。
- `_run_code` 迁移至 KernelNamespace；T5 伪内核异常注入测试通过
  （异常传播、无陈旧 result、调用方隔离）。

真机证据：Phase A 被拦截（无 ODB）；批准后 Phase B 全量严格契约通过：
deliverable=True、acceptance PASS、RESULT_VALID、反力平衡 0.00% 误差、
位移 2.0686mm（与 static golden 逐位一致）、manifest 签名与 ODB 哈希一致。
证据：`machine_validation/production_delivery_kn.json`。

### 8.3 离线门禁

T1-T8 全部落实为自动化测试；全量离线回归 2478 passed。
