# 阶段 1（止血）验收记录

对应规划：`docs/Abaqus-AI-Agent-Governance-Plan.md` 第 4 节阶段 1、第 5 节 TC-REC 矩阵。

基线：`main` @ `2d84f728cb0ca18cb3339b857be809bf3d609d89`。

本记录只陈述**已实际执行并观察到结果**的证据。凡未在本机跑过真实 Abaqus 求解的条目，均显式标注为未验证，不得据本文件推断生产恢复能力已闭环。

---

## 1. 实施内容与代码位置

| 规划要求 | 实现位置 | 状态 |
| :--- | :--- | :--- |
| 现场重核验调度器：五重探针 + 冲突阻断 | `src/abaqus_ai_agent/execution/reconciliation.py::reconcile_run_state` | 已实现 |
| 探针 5（ODB）接入真实性初筛 | `reconciliation.py` 调用 `solver.is_authentic_binary_odb` | 已实现 |
| 探针 3（锁活跃度）排他探测 | `recovery.py::_is_held_by_open_handle_windows` | 已实现（修正，见 §1.2） |
| 僵尸锁清理（`CLEANUP_AND_RESUBMIT` 路径） | `reconciliation.py::_release_stale_locks` → `recovery.clean_stale_locks` | 已实现 |
| 快照接入执行链路 | `analysis_run.py::AnalysisRunner.run`（`PREFLIGHTED` → `SOLVING` → `COMPLETED`/`FAILED`） | 已实现 |
| 原子写入防护 | `reconciliation.py::RunSnapshot.save_atomic`（失败即清理临时文件） | 已实现 |
| 看门狗自适应弹性心跳 | `watchdog.py::run_with_watchdog(adaptive_heartbeat=...)` + `_msg_shows_equilibrium_iterations` | 已实现，见 §4 边界 |
| 硬终止后释放 `.lck` | `solver.py::_release_locks_after_kill`、`recovery.py::wait_for_lock_release` | 已实现 |

### 1.1 ODB 校验的依据边界

探针 5 只做 P0-5 规定的轻量初筛，不臆造格式规则：

- 拒绝 `< 1024` 字节的文件（无足够空间容纳 ODB 头）；
- 拒绝明文 `{` `[` `<` `#` `--` 开头（JSON/XML/YAML/注释型伪造）；
- 拒绝首尾采样窗口（各 512 字节）为单一重复字节的文件——依据是结构必然性：任何 ODB 在文件首尾都承载记录结构，恒定填充不可能成立。

**未引入**任何魔数、版本号或 `mtime` 顺序规则。仓库内无真实 `.odb` 样本、无可依据的二进制格式文档，此类规则会误拒合法文件。结构级验签仍由既有的 `verify_authentic_odb_structure`（原生 `odbAccess`）承担。

另修正一处探针开销缺陷：原实现用 `path.read_bytes()[:32]` 取文件头，会整读整个 ODB。对一个 512 MB 伪样本实测，单次调用读取 536 870 912 字节、耗时 0.29 s；而该探针在每次恢复时都会执行。现已改为 `open(...,"rb").read(32)` 的有界读取。

### 1.2 探针 3（锁活跃度）的实测修正

规划原文要求探针 3 「排他性检查 `.lck` 锁」。原实现用 `open(lock_path, "r+b")` 判断：成功打开即认为无人持有。**该判定在 Windows 上不成立**——Python 的 `open()` 请求 `FILE_SHARE_READ|WRITE|DELETE` 共享模式，可成功打开另一个进程正持有的文件，导致活锁被判定为空闲。

实测（真实子进程持有真实句柄，无打桩）：

| 探针方式 | 锁被别的进程持有 | 说明 |
| :--- | :--- | :--- |
| `open(lck, "r+b")` 成功即判空闲 | **False（误判为空闲）** | 原实现，探测形同虚设 |
| `CreateFileW(dwShareMode=0)` | **True（正确识别）** | 现实现，`ERROR_SHARING_VIOLATION=32` |
| 带 `associated_pid` 且 PID 存活 | True | 该分支原本就正确 |

同时确认：Windows 上 `os.remove()` 对被持有的 `.lck` 返回 `PermissionError(errno=13)`，因此旧逻辑**不会**误删活锁——失败模式是「误判为空闲后删除失败、静默跳过」，而非「破坏运行中的求解器」。但这仍违反规划对探针 3 的要求，并使 `CLEANUP_AND_RESUBMIT` 在锁实际存活时给出过度乐观的建议。

现实现仅在 Windows 上使用独占共享模式；POSIX 无强制锁，`open()` 不具备探测能力，已在注释中明确标注为**非证明性**。本记录不声称 POSIX 路径具备验证能力。

---

## 2. TC-REC 验收矩阵核对

| 用例 | 断言要点 | 测试文件 | 层级 |
| :--- | :--- | :--- | :--- |
| TC-REC-01 正常重连 | 活 PID + 活锁 → `RECONNECT_LIVE`，不重复提交 | `tests/test_run_reconciliation.py::test_tc_rec_01_reconnect_live` | 单元（PID/锁探针被 monkeypatch） |
| TC-REC-02 静默完成 | `.sta=COMPLETED` + 有效 ODB → `READ_ONLY_RECOVER` | `::test_tc_rec_02_silent_completion_read_only` | 单元 |
| TC-REC-03 僵尸锁 | 死 PID + 残留 `.lck` → `CLEANUP_AND_RESUBMIT`，**且锁被实际删除**，`metadata` 记录 `lock_released=True` | `::test_tc_rec_03_dead_process_with_stale_lock` | 单元（真实文件系统删除） |
| TC-REC-03 锁探测 | 真实子进程持有真实句柄 → 无 PID 提示也判为活跃；进程退出后判为空闲 | `tests/test_ga3_runtime_infrastructure.py::test_lock_probe_detects_real_open_handle_without_pid` | **真实进程 + 真实句柄**（Windows；无需打桩） |
| TC-REC-03 负例 | 清理时锁被证明存活 → 拒绝删除，升级为 `RECOVERY_REQUIRED` | `::test_tc_rec_03b_live_lock_is_never_deleted` | 单元 |
| TC-REC-04 Git 漂移 | HEAD 变化 → `RECOVERY_REQUIRED` 阻断 | `::test_tc_rec_04_git_commit_drift_blocks` | 单元 |
| TC-REC-05 账本丢失 | 无账本、仅有 `.sta` + ODB → 抢救性 `READ_ONLY_RECOVER` | `::test_tc_rec_05_missing_snapshot_but_valid_sandbox` | 单元 |
| TC-REC-05 损坏 ODB | 全零 ODB 永不授权只读恢复；账本声称 COMPLETED 时判为矛盾并阻断 | `::test_unconfirmable_odb_never_authorizes_read_only_recovery` | 单元 |
| TC-REC-06 原子写 | 正常写入可读回，无临时残留 | `::test_tc_rec_06_atomic_snapshot_persistence` | 单元 |
| TC-REC-06 故障注入 | `os.replace` 抛异常 → 原快照逐字节不变、无 `.tmp_*` 残留 | `::test_tc_rec_06b_failed_replace_preserves_previous_snapshot` | 单元（真实故障注入） |
| ODB 正/负例 | 全零拒、全 `0xFF` 拒、截断拒、结构化二进制通过 | `tests/test_cae_authenticity_enforcement.py::test_is_authentic_binary_odb_rejects_uniform_fill_and_accepts_structured` | 单元 |
| ODB 探针开销 | 8 MB 样本上单次 `read()` ≤ 4 KB，总读取量小于文件大小 | `tests/test_run_reconciliation.py::test_odb_prefilter_does_not_read_whole_file` | 单元（真实 I/O 计数） |
| 账本真实落盘 | 一次真实 `AnalysisRunner.run` 后账本存在、可被 `resume_from_ledger` 读回 | `tests/test_run_lifecycle_ledger.py` | 集成（JobController 打桩，无真实求解） |

TC-REC-06 的故障注入暴露并修复了一个真实缺陷：原 `save_atomic` 在 `os.replace` 抛错时会把临时文件留在 `.state/` 中，该残留与「未完成的半写快照」无法区分。现已在异常路径删除临时文件后重新抛出。

---

## 3. 执行结果

| 命令 | 结果 |
| :--- | :--- |
| `pytest tests/test_run_reconciliation.py -q` | 15 passed |
| 六项定向测试合计 | 103 passed |
| `pytest -q`（全量） | **1817 passed** / 115.38s |
| `pytest -W error -q`（全量） | **1817 passed** / 115.05s |
| `python tools/check_workspace_pollution.py` | passed |

---

## 4. 验证层级与已知缺口（不得扩大解释）

| 项 | 层级 | 说明 |
| :--- | :--- | :--- |
| 1817 passed（含 `-W error`） | 单元 + 集成 | 真实执行，但求解器为桩或合成文件 |
| 锁活跃度探测（真实句柄持有/释放） | **真实进程 + 真实 OS 句柄** | 无打桩，Windows 实测 |
| ODB 探针有界读取 | 单元（真实 I/O 计数） | 验证读取量，不验证 ODB 语义 |
| 自适应心跳门控（有/无 `.msg` 迭代证据双向实验） | 模拟进程 | `time.sleep` 静默，非 Abaqus `standard.exe` |
| 长静默（>620s）不误杀 | 模拟进程 | 同上 |
| 僵尸锁清理 / 活锁拒删 | 真实文件系统 + 模拟 PID | 文件操作真实，进程存活判定被打桩 |
| **真实 Abaqus 大型隐式求解不被误杀** | **未验证** | 本机存在 `C:/SIMULIA/Commands/abaqus.BAT`，但未运行真实算例 |
| **真实 ODB 结构级验签** | **未验证** | 仓库内真实 `.odb` 样本为 0；结构级能力存在但无真实样本佐证 |

### 4.1 明确记录的边界：看门狗尚未进入主链路

`AnalysisRunner.run` 经 `JobController` 在 CAE 会话内提交任务，**不暴露宿主 PID**，其执行路径不经过 `run_with_watchdog`。因此：

> **看门狗自适应弹性心跳目前仅在 `solver.execute_abaqus_batch_job` 这条独立批处理路径生效，尚未在 `AnalysisRunner` 主链路生效。**

本轮按既定决策**不**将看门狗接入 `AnalysisRunner`：该改动会改变主链路的执行、超时与终止语义，超出阶段 1 已确认的最小补齐范围，也不通过修改规划来降低验收标准。

### 4.2 账本 `pid` 恒为 `None`（使探针 3 成为关键路径）

`AnalysisRunner` 无法获得宿主 PID，账本中 `pid` 恒为 `None`。跨会话恢复因此依赖 `.lck` 探针与 `.sta` 判定，而非 PID 探针。

这个约束把探针 3 抬到了关键路径上：`is_lock_active` 拿不到 `associated_pid`，只能靠文件句柄探测判断锁是否存活。§1.2 的缺陷意味着在该路径下，一条活锁会被判为空闲。修复后此路径才真正可用；`test_lock_probe_detects_real_open_handle_without_pid` 正是按这个实际调用形态（不带 PID）构造的。

---

## 5. 结论

阶段 1 的三项补齐（僵尸锁清理、ODB 初筛接入、原子写故障注入）已完成，TC-REC-01～06 均有对应测试且全量回归通过。

**本轮独立审查额外发现并修复了两个实质缺陷**，二者都落在已批准的范围内：

1. **探针 3 在 Windows 上失效**：`open(r+b)` 以共享模式打开，会把活锁误判为空闲。该缺陷直接削弱 TC-REC-01（正常重连）的判定基础。
2. **探针 5 整读 ODB**：`read_bytes()[:32]` 在 512 MB 文件上读满 512 MB。

两者均已有不依赖打桩的回归测试。

**仍不宣布阶段 1 完全验收通过。** 真实 Abaqus 隐式求解的不误杀能力、真实 ODB 的结构级验签，仍属未验证；看门狗尚未进入 `AnalysisRunner` 主链路。在这三项获得证据前，不宣称阶段 1 的「生产恢复能力」已闭环。
