# Abaqus-AI-Agent 用户已有模型输入通道与轻量后处理操作指南 (User Model Input Guide)

> **对应治理契约：** Phase P1.4 任务 35.4 (P2 用户已有数据输入通道规范)  
> **设计原则：** 拒绝原地修改原始输入（Zero In-Place Mutation）、杜绝多余重复建模、只读后处理严禁重新求解。

---

## 1. 核心设计原则与模式分类

Abaqus-AI-Agent 支持用户直接提供工业级 CAE 资产，根据文件类型分为三大标准输入通道：

| 输入类型 | 接口方法 | 行为契约 | 安全边界 |
|---|---|---|---|
| **`.inp` 输入卡片** | `solve_user_inp()` | **仅求解 (Solver-Direct)**：直接调用 Abaqus 批处理求解器，不重新生成 Python 前处理几何与网格。 | 原始 `.inp` 哈希校验锁定，输出严格写入独立求解沙箱 `solver/<run_id>/`。 |
| **`.odb` 结果文件** | `postprocess_user_odb()` | **纯只读后处理 (Read-Only)**：仅执行场输出/历史输出提取、指标计算与云图/动图渲染，**绝不调用求解器**。 | 原始 `.odb` 完全只读，提取产物写入 `evidence/<run_id>/`。 |
| **`.cae` 模型库** | `prepare_user_cae()` | **副本操作 (Working Copy)**：通过 `openMdb` 打开位于 `working/` 的受控工作副本，进行模型检查与增量修改。 | 原始 `.cae` 文件禁止原地修改，杜绝工程数据损坏。 |

---

## 2. 详细使用示例

### 2.1 用户提供 `.inp` 文件的直接求解模式

用户提供经过验证的标准 Abaqus 输入卡片时，跳过意图解析与脚本建模阶段，直接提交作业并捕获 ODB 产物：

```python
from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.paths import ExternalProjectContext

agent = AbaqusAIAgent(executor=batch_executor)
project_ctx = ExternalProjectContext.create(project_root=Path("D:/AbaqusProjects/GearAnalysis"))

# 1. 求解用户 INP，工作目录隔离在 GearAnalysis/solver/<run_id>/
result = agent.solve_user_inp(
    inp_path="D:/AbaqusProjects/GearAnalysis/input/gear_contact.inp",
    job_name="GearContactJob",
    project_context=project_ctx,
)

print("求解状态:", result["status"])
print("生成的 ODB 路径:", result["odb_path"])
```

### 2.2 用户提供 `.odb` 文件的纯只读后处理模式

用户只需要提取结果指标、评估准则或生成报告，无需再次求解：

```python
from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.paths import ExternalProjectContext

agent = AbaqusAIAgent(executor=None)
project_ctx = ExternalProjectContext.create(project_root=Path("D:/AbaqusProjects/PostOnlyDemo"))

# 2. 纯只读提取，严禁启动求解进程
post_res = agent.postprocess_user_odb(
    odb_path="D:/AbaqusProjects/PostOnlyDemo/input/benchmark.odb",
    project_context=project_ctx,
    requirements=[
        {"field_name": "S", "component": "Mises", "position": "INTEGRATION_POINT"},
        {"field_name": "U", "component": "magnitude", "position": "NODAL"},
    ],
)

print("提取报告:", post_res["extraction_report"])
```

### 2.3 用户提供 `.cae` 模型的安全副本检查与操作

用户提供既有 CAE 模型库时，Agent 自动将其安全克隆至 `working/` 目录，并注入 `openMdb` 打开工作副本：

```python
from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.paths import ExternalProjectContext

agent = AbaqusAIAgent(executor=ipc_executor)
project_ctx = ExternalProjectContext.create(project_root=Path("D:/AbaqusProjects/BridgeCae"))

# 3. 在 working/ 下克隆工作副本，原件 BridgeCae/input/bridge.cae 受到只读保护
cae_res = agent.prepare_user_cae(
    cae_path="D:/AbaqusProjects/BridgeCae/input/bridge.cae",
    project_context=project_ctx,
    target_filename="bridge_run01.cae",
)

print("工作副本路径:", cae_res["working_cae_path"])
print("自动生成的加载脚本:\n", cae_res["open_script"])
```

---

## 3. 验证与审计门禁

- **原始资产防篡改校验**：操作前后自动比对源文件的 SHA-256 哈希值；发生任何哈希漂移立即抛出 `RuntimeError` 阻断。
- **跨平台路径隔离**：禁止向核心代码仓库静默写入过程产物；生产模式下强制绑定外部工程上下文。
- **自动化测试保证**：在 `tests/test_input_modes.py` 中持续保持 100% 回归覆盖。
