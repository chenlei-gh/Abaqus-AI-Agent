# Abaqus AI Agent

把一条分析需求编译成 Abaqus 模型。模型经过审阅才求解。只有求解产物能支撑声明的准则时，才发布报告。

[English](README.md) | [需求与规划](docs/PROJECT_REQUIREMENTS_AND_PLAN.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Abaqus](https://img.shields.io/badge/Abaqus-2025-blue.svg)](https://www.3ds.com/products-services/simulia/products/abaqus/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

本包不安装 Abaqus，不附带许可证，也没有发布到 PyPI。生成的报告不是分析人员的签字。

## 安装

两套运行时分开。代理装进普通 CPython。Abaqus 保留自己的解释器，通过 SIMULIA 启动器调用。不要把本包 `pip install` 进 Abaqus/CAE 自带的 Python。

本包不在 PyPI 上。从这棵源码树安装。PyPA 的安装要求是使用虚拟环境，并用 `python -m pip` 调用 pip，这样装到的就是刚检查过的那个解释器。

Windows，在仓库根目录：

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m abaqus_ai_agent --help
```

`".[test]"` 的引号不能省。在 `cmd` 里，方括号是通配符。

macOS 或 Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m abaqus_ai_agent --help
```

这条命令实际装的是：

| 项 | 值 |
|---|---|
| 分发包 | `abaqus-ai-agent` 0.2.2，setuptools `src` 布局 |
| 声明的 Python | `pyproject.toml` 中 `>=3.9` |
| CI 测过的解释器 | Ubuntu 与 Windows 上的 3.10、3.11、3.12 |
| 运行依赖 | `Pillow>=9` |
| 测试额外依赖 | `pytest>=7` |
| 控制台脚本 | `abaqus-ai-agent`、`abaqus-agent` |
| 安装方式 | 可编辑安装（`-e`），改源码后无需重装即可导入 |

`-e ".[test]"` 是 CI 使用的开发安装。只运行代理、不跑测试时，去掉额外依赖：

```bash
python -m pip install -e .
```

可编辑安装跟踪 `src/` 里的 Python 改动。`pyproject.toml` 里的依赖或入口脚本变了，仍要再执行同一条安装命令。不要用 `python setup.py install`，那条路径已经废弃。

离线检查不需要求解器：

```bash
python -m pytest tests -q -m unit
abaqus-ai-agent inspect --json
```

`inspect` 报告有没有找到启动器。找不到启动器表示这台机器离线，不是本包装失败。

### Abaqus：本包不安装它

真机求解需要一套已经装好、并且有许可证的 Abaqus 2025。安装程序会创建命令目录；在 Windows 上还会把它加到 `PATH` 前面。默认目录是 `C:\SIMULIA\Commands` 和 `/var/DassaultSystemes/SIMULIA/Commands`。2025 的快捷命令是 `abq2025`；`abaqus` 是不带版本号的入口。

本包按这个顺序找启动器：显式路径，`PATH` 上的 `abaqus`，然后是 Windows 上的 `C:\SIMULIA\Commands\abaqus.BAT`。许可证服务器、`custom_v6.env` 和 token 是否空闲，属于 Abaqus 安装本身。本仓库不配置这些。

指望求解之前，先确认外部产品：

```bat
where abaqus
abaqus information=release
```

`abaqus information=release` 打出版本字符串，只说明启动器能用。它不说明 token 有空闲。

## 工程模型

脚本跑过，不是分析做完。作业做完，不是答案可接受。代理把这三件事保持为不同状态。

```text
需求
  -> 有类型的意图
  -> 有序动作
  -> 生成的 Abaqus Python
  -> CAE 内核
  -> 求解作业
  -> ODB 与求解日志
  -> 按声明的准则验收
  -> report.html，或 report.diagnostic.html
```

代理不发明几何。边界或载荷只有在区域来自几何绑定或显式选择之后才可执行。视觉模型不许靠序号挑面。

### 编译

`EngineeringIntent` 是这条分析的闭合陈述：几何、材料、边界、载荷、网格、过程和准则。编译器把它降成有序的 `AbaqusAction`。每个动作写明目标、参数、前置条件和期望状态。脚本从这张表渲染出来。脚本不是模型的来源。

编译器能渲染的动作是 `SUPPORTED`。绕过类型动作的原生 Python 是 `EXECUTABLE`：它可以跑，这次运行不是该工程操作已被验证的证据。没有执行路径的操作，不说成完成。

求解器族是一条记录下来的决定，不是一次静默改写。选择只有 `STANDARD` 或 `EXPLICIT`。声明的运动学要求与请求的求解器冲突时，提交被阻断。频率和传热过程没有 Explicit 替代，那里的偏好不当成这种冲突。

### 执行

生成片段在隔离的内核命名空间里跑，不进调用方的 globals。编译器发出的求解等待是有界的：`waitForCompletion(timeOut=...)`。裸等待会被拒绝。

在 Windows 上，`abaqus cae noGUI` 不给宿主一个可以等待的进程。启动器拉起 `ABQcaeK.exe` 后就返回。完成标记由内核脚本自己写：`completed`、`blocked` 或 `failed`。工作目录变安静只是 `quiescence_only`。它表示目录不再变化，不表示脚本跑完。

求解作业以前台 `interactive` 提交，因为默认批处理在启动器移交后就返回。退出码 0 不证明作业完成。磁盘上有 ODB 也不证明。正面证据是求解器自己的完成记录。

### 证据与验收

每条提取结果都绑到产生它的那次运行：`run_id`、输入哈希、ODB 路径、ODB SHA256。同名、同大小的文件不是同一份结果。损坏、空文件或非二进制 ODB 会被拒绝。缺字段就报错，不用基准常数填上。

验收是固定的门序列，不是一个通过标志：

| 门 | 必须成立的事 |
|---|---|
| execution | 作业确实以求解器自己写下的完成状态结束 |
| odb | ODB 能作为这次运行的 ODB 打开 |
| evidence | 要求的场和历史存在 |
| numerical | 不是一份写满非有限值、却显示完成的作业 |
| engineering | 声明的检查有证据 |
| mesh | 要求网格质量时，用形状指标，而不是只看 `ANALYSIS_CHECKS` |
| convergence | 要求时，有网格收敛证据 |
| fatigue | 要求时，有疲劳证据 |
| contact | 接触状态与所求接触问题一致 |
| procedure | 要求的过程确实跑了 |
| thermal / energy | 该物理在范围内时，热平衡、静力稳定化或瞬态能量成立 |
| criteria | 声明的数值准则通过 |
| connectors / FMBD | 该模型在范围内时，有运动学或刚柔耦合证据 |

未过的门写出 `report.diagnostic.html`。改文件名不会使它变成正式报告。

### 人仍要决定的事

提交前，候选写入 `pre_solve_review.html`，并用默认浏览器打开。这份文件就是评审。没有另一套交互界面。审批只绑定这一份候选；改了模型，审批失效。

代理能拦住明显会失败的启动。它不能决定传力路径、支承或准则是不是正确的工程问题。那仍是审阅者的决定。

## 参照结果

在带许可证的 Abaqus 2025 上，`machine_validation/` 中的官方悬臂梁用 C3D20R 和端部剪切跑过。挠度 6.3330 mm，梁理论 6.4000 mm，相差 1.05%。积分点应力 138.89 MPa，解析值 138.56 MPa，相差 0.23%。这鉴定的是这个算例。它不鉴定编译器里的每一种过程、单元或接触公式。

## 使用

```python
from abaqus_ai_agent import AbaqusAIAgent

agent = AbaqusAIAgent(executor=None)
result = agent.solve_requirement(
    "200 x 20 x 5 mm 钢悬臂梁，根部固定，自由端 100 N 剪切",
    submit_job=False,
)
```

默认不提交作业。这一步生成并检查候选。该候选批准后，同一工作目录才可以求解。任务完成和准则验收是结果上的两个字段。

```bash
abaqus-ai-agent ask "..." --dry-run
abaqus-ai-agent approve --workdir ./run_workdir --by "analyst name"
```

## 布局

```text
src/abaqus_ai_agent/
  contracts/     意图、动作、证据、验收
  planning/      意图编译器，网格与过程规划
  actions/       动作构造与脚本渲染
  execution/     内核、批处理作业、审批、ODB 提取
  validation/    启动前的结构校验
  grounding/     区域来自几何绑定，不来自猜的序号
  reporting/     正式报告与诊断报告
```

`docs/PROJECT_REQUIREMENTS_AND_PLAN.md` 是唯一规划文档。

## 许可证

[Apache License 2.0](LICENSE)。
