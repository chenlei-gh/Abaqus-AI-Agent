# Phase P0-0.5: Context Telemetry & Baseline Evidence Audit

> **审计状态**: COMPLETED  
> **审计日期**: 2026-10-08  
> **核心原则**: 不将估算当实测，不将设计目标当现状，严格区分 LLM Completion、Renderer Output 与 Physical Artifacts。

---

## 一、系统现状全链路证据审计（五项核心验证）

针对本次 Token 治理体系前置条件，对当前代码库进行了逐行代码与调用链审查，结论如下：

### ① 真正的 LLM Request 是否能拿到？
- **代码库实况**:
  - 当前项目中实际存在且能发起远程 HTTP 调用的仅有 `src/abaqus_ai_agent/typesafe_intent.py`（面向 TypeSafe System One JEV 的自然语言意图分类接口）。
  - 在后续的几何处理、特征识别、CAE 脚本编译、Abaqus 求解、ODB 提取、单出口门禁验证到最终双语报告渲染，**主干全链路均为纯 Python 确定性程序（Deterministic Engineering Plane）**。
  - 当前代码库尚未挂载类似 OpenAI/Claude 等通用 Chat Completions 的多轮 ReAct 交互循环。
- **证据结论**:
  - 之前提出的 `73,020 Tokens Baseline`，并非捕获自当前代码库发往商业大模型的真实网络请求 Payload；
  - 它是**在假定“若采用通用 LLM ReAct Agent 直接驱动 Abaqus（将完整 Tool Schemas、CAD 拓扑、长求解日志、ODB 场数据及报告全文通通直塞 Context）”时的理论膨胀上界（Theoretical Upper Bound Projection）**。

### ② Provider 是否返回 Usage？
- **实况**: TypeSafe System One 接口返回结构化判定答案（`decisions/answers`），未返回 OpenAI 格式的 `usage.prompt_tokens` 与 `completion_tokens`。
- **改进规范**:
  - `ContextTelemetryTracker` 已显式增加 `measurement_source` 细分枚举：
    - `provider_usage`（模型 API 官方回传，最高可信）；
    - `tokenizer`（tiktoken 等本地分词器统计）；
    - `estimated`（字符-Token 启发式换算）；
    - `synthetic_projection`（理论模型仿真推演，非物理网络流量）。
  - 所有非真实 API usage 的记录必须强制标注 `is_estimated=True`。

### ③ Tool Schema 是否真的每轮完整发送？
- **实况**: 
  - 当前代码库没有在每个工步都向外部通用 LLM 实际通过网络发送 24 个 CAE 工具的 JSON Schema。
  - 那 24 个全局工具有对应的方法原型，但每轮消耗 16,395 tokens 的数据是“假定通用 ReAct 框架不做动态过滤”时的静态负载投影。
- **架构建议**:
  - 将此项正名为 `Hypothetical Static Schema Overhead`；
  - 在未来真正接入通用 LLM Agent 时，落实 **P0-2: Dynamic Tool Schema Routing**，确保从第一天起就杜绝全量静态注入。

### ④ 18,113 LLM Output 到底来自哪里？
- **实况**:
  - **这 18,113 tokens 绝不是模型的真实 Completion！**
  - 它完全来自于确定性渲染器 `renderer.py` 生成的 `Case_03_Exhaust_Manifold_Report.md`（70,510 字节）！
  - 之前的模拟脚本将其直接塞入了 `output_text`，造成了“LLM Completion”与“Deterministic Renderer Output”的严重分类混淆。
- **纠偏修正**:
  - 在当前已运行的真实系统中，LLM 实际没有输出这 70KB 报告，报告是 `renderer.py` 在本地离线确切渲染生成的；
  - Telemetry 契约中已正式将 **`deterministic_renderer_bytes`（70KB MD + 281KB HTML）** 和 **`data_plane_artifact_bytes`（35MB ODB + 4张高清PNG）** 彻底从 LLM Token 统计中剥离，归入 Data Plane 物理字节流。

### ⑤ 73,020 与 3,043 的真实定位与重新定义
- **73,020 Tokens**:
  - 重新定义为：`Theoretical ReAct Upper Bound (Unmanaged Projection)`；
  - 代表“若不对上下文进行治理，放任工程数据倾倒进入 LLM，单次 Case 3 将面临的严重上下文膨胀风险”。
- **3,043 Tokens**:
  - 重新定义为：`Three-Plane Target Budget (Managed Projection)`；
  - 代表“在严格执行 Artifact Pointer、Result Query、动态 Schema 及确定性渲染约束下，未来接入 LLM 时的目标 Token 预算上限”。

---

## 二、真实性审计后的架构数据矩阵

| 维度 | 未治理推演上界 (Unmanaged Projection) | 三平面设计预算 (Target Budget) | 物理平面剥离归属 |
| :--- | :---: | :---: | :--- |
| **Tool Schemas (工具定义)** | 16,395 tokens (49.2% / 22.4%) | 1,961 tokens | LLM Plane (按阶段 JIT 路由) |
| **Conversation History (多轮累积)** | 21,981 tokens (30.1%) | 93 tokens | LLM Plane (状态机紧凑摘要) |
| **Tool Output Dumps (工具原始返回)** | 14,313 tokens (19.6%) | 171 tokens | Engineering Plane (Query 协议) |
| **LLM Output (模型真实输出)** | 18,113 tokens (24.8% 概念推演) | 255 tokens | LLM Plane (极简工程释义卡片) |
| **System Prompt & User Input** | 2,218 tokens | 563 tokens | LLM Plane (极简契约) |
| **TOTAL CONTEXT FOOTPRINT** | **73,020 tokens** | **3,043 tokens** | **预算控制基线** |
| **Deterministic Renderer Output** | 0 (误塞入 LLM) | **352,224 bytes (352 KB)** | **Data Plane (renderer.py 离线渲染)** |
| **Data Plane Artifacts** | 0 (未受控) | **35,629,000 bytes (~35.6 MB)** | **Data Plane (本地文件系统 / ODB)** |

---

## 三、P0-1 Artifact 契约增强落地

在用户建议下，`ArtifactPointer` 增加了两个核心架构安全与访问控制字段：
1. `storage_scope: str = "run"`
   - 支持 `"run"`, `"case"`, `"global"`, `"ephemeral"`，控制生命周期；
2. `access_policy: str = "llm_pointer_only"`
   - 支持 `"llm_pointer_only"`, `"engineering_internal"`, `"human_downloadable"`, `"machine_internal"`；
   - 彻底从架构上确立：**LLM 只能拿到 Pointer 与极简 Summary，物理二进制与原始文本留在 Data Plane。**

---

## 四、调整后的 P0-2 ~ P0-5 真实施工优先级

采纳审阅指示：**先砍固定开销，再砍状态膨胀，再砍物理数据，最后砍报告。**

```text
[已完成] P0-0     Context Telemetry 观测系统（支持细粒度 measurement_source）
[已完成] P0-1     Artifact Pointer 契约冻结（含 storage_scope & access_policy）
[已完成] P0-0.5   Telemetry Evidence Audit 真实性审计（纠正数据性质与分类混淆）
                         ↓
[施工步 1] P0-2   Tool Schema Dynamic Routing (按阶段动态下发 2~4 个工具，砍掉 49.2% 的固定 Schema 开销)
                         ↓
[施工步 2] P0-3   Context / History State Compaction (状态机紧凑化，砍掉 30.1% 的多轮历史膨胀)
                         ↓
[施工步 3] P0-4   Tool Output Compaction & Result Query (ODB 场数据禁止直塞，改为按需 Hotspot 查询)
                         ↓
[施工步 4] P0-5   Deterministic Report Ingestion (锁定 renderer 确定性注入，LLM 仅消费/产出 ~200 Tokens 释义卡片)
```
