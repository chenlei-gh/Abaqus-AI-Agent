# Abaqus AI Agent

位于一条已陈述的分析需求与 Abaqus 之间的工程代理。它把需求编译成可供人审阅的模型，审阅之后才提交求解，并且只有求解器自己的证据能支撑所声明的准则时，才写出正式报告。

[English](README.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/CI-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

脚本跑过、作业做完、答案被接受，是三件分开的事。本包不安装 Abaqus，不附带许可证，也没有发布到 PyPI。生成的报告不是分析人员的签字。

它面向已经持有 Abaqus 许可证、并要求这条路径保持分开的工程师。它不是通用对话程序，也不决定传力路径、支承或准则是不是正确的工程问题。

## 安装

两套解释器分开。本包装进普通 CPython 虚拟环境。Abaqus 保留自己的 Python，通过 SIMULIA 启动器调用。不要把本包装进 Abaqus/CAE 自带的 Python。

本包不在 PyPI 上。从这棵源码树安装。使用虚拟环境，并用 `python -m pip` 调用 pip，这样装到的就是刚检查过的那个解释器。不要用 `python setup.py install`。

Windows，在仓库根目录：

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install .
python -m abaqus_ai_agent --help
```

macOS 或 Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python -m abaqus_ai_agent --help
```

装上的是 `abaqus-ai-agent` 0.2.2。`pyproject.toml` 声明 Python `>=3.9`。持续集成在 Ubuntu 与 Windows 上测试 3.10、3.11、3.12。运行依赖是 `Pillow>=9`。控制台脚本是 `abaqus-ai-agent` 和 `abaqus-agent`。

要改这个仓库，用可编辑方式装上测试额外依赖，再跑离线测试：

```bat
python -m pip install -e ".[test]"
python -m pytest tests -q -m unit
```

在 `cmd` 里，`".[test]"` 的引号不能省。方括号是通配符。可编辑安装跟踪 `src/` 下的 Python 改动。`pyproject.toml` 里的依赖或入口脚本变了，仍要再执行同一条安装命令。

### Abaqus：本包不安装它

真机求解需要一套已经装好、并且有许可证的 Abaqus。本仓库不配置许可证服务器、`custom_v6.env`，也不保证 token 空闲。

Abaqus 安装程序创建命令目录：Windows 上是 `C:\SIMULIA\Commands`，Linux 上是 `/var/DassaultSystemes/SIMULIA/Commands`。2025 的快捷命令是 `abq2025`。`abaqus` 是不带版本号的入口。

本包按这个顺序找启动器：显式路径，`PATH` 上的 `abaqus`，然后是 Windows 上的 `C:\SIMULIA\Commands\abaqus.BAT`。

```bat
where abaqus
abaqus information=release
abaqus-ai-agent inspect --json
```

打出版本字符串，只说明启动器能用。它不说明许可证 token 有空闲。`inspect` 找不到启动器，表示这台机器离线，不是本包装失败。

## 试一次

这一步不启动 Abaqus。它路由需求，然后停止。持续集成跑的是同一条命令。

```bat
abaqus-ai-agent ask "Apply 1000N vertical load to the free end of a 100mm cantilever beam, material steel, fixed root, check deflection <= 2.5mm." --dry-run
```

成功的 dry run 退出码为 0。命令先打印意图路由标题，然后是：

```text
[DRY-RUN] Intent and plan contracts verified successfully. No solver invoked.
Solver invoked:     NO
Report authorized:  NO
```

这两行之间的内容给出推断的物理、单位制、求解器，以及边界、载荷和准则的条数。它们不启动作业，也不授权报告。

同一句话如果没有写明载荷作用位置，退出码为 2，并指出 `missing_load_application_region`。这是预定的停止。它不是求解失败。

建模型和提交作业走 `AbaqusAIAgent.solve_requirement`。默认不提交。提交前，候选写入 `pre_solve_review.html`，并用默认浏览器打开。这份文件就是评审。没有另一套交互界面。审批只记在这一份候选上：

```bat
abaqus-ai-agent approve --workdir ./run_workdir --by "analyst name"
```

改了候选，审批失效。

## 它如何构成

需求被编译成有类型的意图和一张有序动作表。Abaqus Python 从这张表渲染出来。脚本不是模型的来源。几何不被发明。边界或载荷只有在区域来自几何绑定或显式选择之后才可执行。

这三件声明在整次运行里保持分开。脚本跑过，不是作业做完。作业做完，不是答案可接受。正式文件是 `report.html`，并且只有求解器自己写下的证据能支撑所声明的准则时才是。否则文件是 `report.diagnostic.html`。改文件名不会使它变成正式报告。

代理能拒绝一次明显会失败的启动。它不能决定问题本身是不是问对了。

门序列、完成标记和求解器选择规则在[需求与规划](docs/PROJECT_REQUIREMENTS_AND_PLAN.md)。那是唯一的规划文档。

## 一个已鉴定的算例

在带许可证的 Abaqus 2025 上，[`machine_validation/`](machine_validation/) 中的悬臂梁用 C3D20R 和端部剪切跑过。挠度 6.3330 mm，梁理论 6.4000 mm，相差 1.05%。积分点应力 138.89 MPa，解析值 138.56 MPa，相差 0.23%。这鉴定的是这个算例。它不鉴定每一种过程、单元或接触公式。

记录：[`official_cantilever_benchmark_evidence.json`](machine_validation/official_cantilever_benchmark_evidence.json)。

## 帮助

问题和缺陷：[GitHub issues](https://github.com/chenlei-gh/Abaqus-AI-Agent/issues)。

## 许可证

[Apache License 2.0](LICENSE)。
