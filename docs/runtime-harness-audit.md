# 运行时 harness 审计（第 4 步 · 只读核查交付物）

日期：2026-10-27
基线：889b8e9（本机工作区与该提交一致）
范围：`tools/runtime_smoke.py`、`execution/runtime_smoke.py`、`execution/watchdog.py`、`execution/batch.py`、tools/ 下 16 个 Golden 脚本的 `_run_code` 模式。
性质：只读核查；本文件是问题清单与最小修改范围，不含代码改动。

## 一、确认的问题清单

### P0-1 watchdog 异常逃逸导致证据缺失

- 事实：`watchdog.run_with_watchdog` 在 stall 时抛出 `SolverProcessStalledError`（watchdog.py:48，`RuntimeError` 子类）；总超时路径同样以异常/返回离开监控循环。
- 事实：`tools/runtime_smoke.py` 的 `except` 只捕获 `(OSError, subprocess.SubprocessError)`；证据 JSON 的写入位于 try/except 之后。
- 后果：stall/超时恰恰是最需要留证据的场景，却跳过 JSON 写入；调用方看到的只是未捕获异常。
- 最小修改：异常分类扩展到全部预期异常并兜底未知异常；证据写入移入 `finally` 且用原子替换；状态文件缺失本身定义为可识别结果。

### P0-2 smoke 标记解析静默吞掉重复与矛盾

- 事实：`classify_smoke_markers`（execution/runtime_smoke.py）用 `{x.get("marker"): x for x in markers}` 建字典；重复标记后者覆盖前者，无任何记录。
- 事实：标记不携带运行身份；`error` 与 `script_completed(passed=True)` 可以同时存在而不被判矛盾。
- 后果：同一输出里两次矛盾的成功标记无法被发现；旧运行的输出片段混入时无法识别。
- 最小修改：解析器严格化——重复标记载荷冲突判 INVALID；`error` + `script_completed(passed=True)` 矛盾判 INVALID；标记携带 `run_id`，解析时校验与本次运行一致。

### P0-3 `.rpy` 回退读取未绑定本次运行

- 事实：`tools/runtime_smoke.py` 在 stdout 标记不完整时回退读取 `workdir/abaqus.rpy*`（按 mtime 排序），不校验标记属于哪次运行。
- 后果：上一次成功运行遗留的 `.rpy` 可以被误当成本次成功（假阳性）。
- 最小修改：smoke 脚本每个标记嵌入本次 `run_id`；`.rpy` 回退只接受 `run_id` 匹配的标记；`.rpy` 匹配失败时降级为诊断材料而非通过依据。

### P1-4 启动器退出 ≠ CAE 完成

- 事实：`BatchExecutor._run` 经 `run_with_watchdog` 监控 `subprocess.Popen` 启动的进程；watchdog 以 `proc.poll()` 为终止依据（watchdog.py:328-330）。
- 实测（本机，2026-10-27）：`abaqus cae noGUI=...` 外层命令约 1.3 秒返回 rc=0，而 CAE 内核继续运行数分钟；`abaqus job=...` 亦观察到 rc=0 先于 ODB 落盘。
- 后果：watchdog 在启动器退出后停止监督，总超时不再约束真实 CAE 进程；调用方可能读到尚未落盘的产物并误判。
- 最小修改：`BatchResult` 增加终态证据标记；`_run` 在启动器 rc=0 退出后轮询工作目录的终态证据（.sta 终态标记/锁文件消失），有界 settle 超时；未收敛则 `settled=False`，`succeeded` 不再仅凭 rc=0。不做 Windows Job Object / psutil 进程树追踪，该限制写入文档。

证据层级（2026-10-28 外部复核后修正，不得混用）：

- **本机实测（已核实）**：`abaqus cae noGUI=...` 外层命令约 1.3 s 返回 rc=0，CAE 内核继续运行数分钟。这是行为观测，不是官方契约。
- **官方文档预期（已核实）**：CAE 执行过程的选项表中没有 `interactive` / `wait` 类关键字；Abaqus Scripting 文档写「脚本跑完，CAE kernel 终止」且「无界面时作业总是 interactive」。即官方预期是 **noGUI 命令自身等到脚本结束**，与本机观测不一致。
- **未核实**：脱离点在 `abaqus.bat`、`SMALauncher.exe` 还是 CAE kernel 内部。本机核实 `abaqus.bat` 仅转调 `abq2025.bat`，后者直接 `"...\SMALauncher.exe" %*`，两份批处理均无 `start`；因此「批处理层无分离」成立，但「SMALauncher 内部脱离」仍属推断。
- **方法学限制**：`psutil` 的 `children(recursive=True)` 与 Windows Job Object 都要求父进程仍存活、且需在创建时或创建后尽早挂接。启动器一旦退出，其 PID 上已无可遍历的子进程树，事后补挂接无法找回内核。因此二者都不能作为「启动器已退出」场景的修复手段；这是能力边界，不是依赖成本问题。

后续修正（2026-10-28，详见 `phase-leftovers-tracking.md` §6.4、§6.5）：

- 求解作业路径此前并未传 `interactive`，所以走的是默认 `background`，即**主动**制造了“启动器先退”这一幕。`BatchExecutor.run_input` 已补 `interactive`，并同步开启证据门控的静默窗口放宽（否则前台化后默认 120 s 会误杀大型隐式算例）。
- CAE noGUI 路径没有 `interactive` 等价关键字，仍完全依赖 `settled` 轮询；`P1-LAUNCHER-01` 的关闭条件不变。
- 二次复核发现 `waitForCompletion(timeOut=N)` 的结果会被传输信封遮蔽（`ABORTED` 读成 `COMPLETED`），且传输超时与内核超时等值会竞态抢占；两处均已修复，见 §6.5。

### P1-5 Golden 脚本共享 globals 命名空间

- 事实：16 个 tools/ 脚本的 `_run_code()` 使用 `exec(..., globals(), globals())` 并读 `globals().get('result')`；其中 4 个脚本已经不得不用 `globals().pop('result', None)` 手动清理泄漏——说明该模式的脆弱性已在仓库内造成过实际困扰。
- 实测（E1，2026-10-27）：`from abaqusConstants import *` 注入的 `LOG` SymbolicConstant 静默覆盖 harness 同名变量，导致结果丢失。
- 跨片段依赖核查：harness → agent 方向的参数全部在脚本生成期以字面量插值，exec 代码不读 harness 变量；agent → harness 方向只有 `result` 一个通道；agent 片段之间需要持久命名空间（后续片段可能引用先前片段定义的名称）。
- 最小修改：在 `src/abaqus_ai_agent/execution/` 新增可复用的内核命名空间组件（持久 agent 命名空间 + stdout 捕获 + result 通道 + 先清后读），离线单测覆盖遮蔽与跨片段持久性；Golden 迁移留给第 5 步分批进行。

## 二、调用面（爆炸半径）

- `parse_smoke_output` / `classify_smoke_markers` / `build_runtime_smoke_script`：仅 `tools/runtime_smoke.py` 与 `tests/test_runtime_smoke.py`。
- `run_with_watchdog`：`batch.py`、`solver.py` 及两个既有测试文件。
- `_run_code` 共享 globals 模式：16 个 Golden 脚本（第 5 步迁移对象）。

## 三、验收标准（第 4 步）

1. stall/超时/启动失败/未知异常都能落出分类明确的 JSON 证据（负例测试驱动）。
2. 重复、缺失、矛盾、串档（run_id 不符）的标记一律不得判 pass。
3. 启动器提前退出时，未收敛的终态证据不得判 succeeded。
4. 离线全量回归无行为变化。
5. 真机：ping + 一个代表性 Golden 算例验证通过。
