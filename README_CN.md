# Abaqus AI Agent

把一条分析需求收成 Abaqus 模型、一次求解，以及一份能用证据答辩的报告。

[English](README.md) | [需求与规划](docs/PROJECT_REQUIREMENTS_AND_PLAN.md)

[![CI](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chenlei-gh/Abaqus-AI-Agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Abaqus](https://img.shields.io/badge/Abaqus-2025-blue.svg)](https://www.3ds.com/products-services/simulia/products/abaqus/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

求解器仍是 Abaqus。本仓库不提供许可证。生成的报告也不能代替分析人员签字。

## 问题

自动 CAE 流程里，大头时间通常不在求解器。时间花在发现脚本无法解析、区域是猜的、单位对不上、作业其实没跑完，或者报告里的结论 ODB 并不支持。

语言模型可以起草 Abaqus Python。它自己区分不了三件事：脚本跑过、分析做完、工程答案可接受。这个项目的存在，就是不让这三件事混成一句“完成了”。

## 它是什么

代理站在需求和 Abaqus/CAE 之间。它不替代前处理器，也不重新解释求解器。

```text
需求
  -> 有类型的意图
  -> 动作计划
  -> Abaqus Python
  -> CAE 内核
  -> 求解器
  -> ODB 与日志
  -> 按声明的准则验收
  -> 一份报告，或一份诊断
```

求解前，人要审模型、网格、边界和载荷。审的是默认浏览器打开的静态 HTML，不是另一套交互界面。审批只对这一份候选有效。模型一改，审批作废。

## 设计

五条规则决定架构。

**语言不是权限。** 模型可以解释需求、提议建模选择、起草原生 Python。它不能绕过有类型的动作路径去改分析。模型能写出某项操作，不表示这项能力已被系统支持。

**动作是建模单位。** 几何、材料、网格、分析步、边界、载荷和接触，都从有类型的动作编译出来。生成的脚本是计划的结果，不是计划本身。自由 Python 保留为显式逃生口，它的结果只是执行证据。

**证据分层。** 调了 API，不是模型状态。模型状态，不是作业完成。作业完成，不是 ODB。ODB，不是验收。上一层不成立，下一句结论不许出现。

**失败保持失败。** 输入不全，停在澄清。计划非法，停在启动前。候选未审，停在求解前。验收不过，只出诊断报告。这些都不会被改写成一次完成的分析。

**求解器和代理都不被盲信。** 响应由 Abaqus 计算。代理检查的是：要求的问题是否真的跑了，产物是否属于这次运行，声明的准则是否满足。它不会给出一个比求解器返回值“更好”的物理答案。

## 范围

目标分析面，是能写成闭合需求的结构与传热问题：线性和非线性静力、接触、连接器、隐式与显式动力、刚柔耦合、传热，以及这些分析依赖的网格和材料选择。

这是系统的方向，不是一份合格证书。不是每种过程、单元、接触公式和材料模型都已经鉴定过。一项能力要同时有类型动作、校验路径、结果语义和测试，才算被支持。真机证据只鉴定被点名的算例，不自动推广到相邻算例。

已有的参照算例是 `machine_validation/` 下的官方悬臂梁：C3D20R，端部剪切，挠度与梁理论相差 1.05%，积分点应力与解析值相差 0.23%。同一主机上还跑过接触、审批阻断和损坏 ODB 拒绝。更宽的结论留在需求文档里，直到有同等证据。

## 时间实际耗在哪里

贵的失败并不神秘。

| 失败 | 停在哪里 | 仍要人做什么 |
|---|---|---|
| 需求不闭合 | 计划形成前 | 补几何、材料、支承、载荷或准则 |
| 模型结构非法 | 脚本启动前 | 改分析定义 |
| Python 无法解析 | CAE 启动前 | 改生成源码；这不证明 Abaqus API 有效 |
| 模型未经审阅 | 求解提交前 | 读求解前评审，并批准这一份候选 |
| 作业并未真正完成 | 读取结果前 | 查内核和求解器产物 |
| 结果不满足准则 | 正式交付前 | 接受诊断，或改模型后重跑 |

语法拒绝只去掉一类白跑。它去不掉错误区域、错误单位和被误解的传力路径。这些是建模错误，要到验收路径才变得可见。目前没有前后对照，不能说总纠错时间已经下降。

## 使用

Python 3.10 及以上。只有真正求解时才需要带许可证的 Abaqus 2025。

```bash
git clone https://github.com/chenlei-gh/Abaqus-AI-Agent.git
cd Abaqus-AI-Agent
python -m pip install -e ".[test]"
python -m pytest tests -q -m unit
```

```python
from abaqus_ai_agent import AbaqusAIAgent

agent = AbaqusAIAgent(executor=None)
result = agent.solve_requirement(
    "200 x 20 x 5 mm 钢悬臂梁，根部固定，自由端 100 N 剪切",
    submit_job=False,
)
```

默认不提交作业。这一步生成并检查分析候选，不求解。评审文件批准后，同一工作目录可以继续跑。任务完成和准则验收是两件事。

```bash
abaqus-ai-agent ask "..." --dry-run
abaqus-ai-agent approve --workdir ./run_workdir --by "analyst name"
```

## 布局

```text
src/abaqus_ai_agent/
  contracts/     意图、动作、证据、验收的类型
  planning/      网格与分析规划
  actions/       动作构造与脚本生成
  execution/     CAE 内核、批处理作业、审批
  validation/    启动前的结构校验
  evidence/      产物与 ODB 证据
  reporting/     正式报告与诊断报告
  materials/     模型使用的材料记录
  telemetry/     纠错与计时记录
```

`docs/PROJECT_REQUIREMENTS_AND_PLAN.md` 是唯一规划文档。新需求写在那里。

## 许可证

[Apache License 2.0](LICENSE)。
