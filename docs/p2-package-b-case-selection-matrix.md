# Phase 2 Package B: 10 大真实复杂工程实战案例筛选与评估矩阵（已整合索引）

> **【架构治理与单一权威源 (SSOT) 说明】**  
> 本文件的全部选型背景、五维量化准则、候选池评估分析表、气囊替换为副车架耐久疲劳的论证，以及每个案例的强制交付物规范，已**完全合并至项目单一权威需求规格说明书**：  
> 👉 **[`docs/p1-product-requirements.md` 第 11.2 节（Package B：10 个真实复杂工程项目正式实战）](p1-product-requirements.md#112-package-b10-个真实复杂工程项目正式实战)**。

---

## 快速导航与权威状态总览

当前 10 大案例在系统中的唯一权威注册表为 [`validation_assets/registry.json`](../validation_assets/registry.json)，当前执行状态如下：

```text
Package B: 10 Authentic Complex Engineering Projects (Status: 6/10 QUALIFIED)
├── Case 01: Bolted Pipe Flange Connection with Gasket Sealing [QUALIFIED]
├── Case 02: Reactor Pressure Vessel (RPV) Bolted Closure Joint [QUALIFIED]
├── Case 03: Heavy-Duty Engine Exhaust Manifold Thermo-Mechanical Contact [QUALIFIED]
├── Case 04: Automotive Front Subframe Multi-Axis Durability & Fatigue [QUALIFIED]
├── Case 05: Open-Hole Composite Cylindrical Shell Buckling & Post-Buckling [QUALIFIED]
├── Case 06: Multi-Stage Sheet Metal Assembly with Submodeling [QUALIFIED]
├── Case 07: Automotive Suspension Hyperelastic Jounce Bumper Self-Contact [PENDING - NEXT PRIORITY]
├── Case 08: Axisymmetric Premium Threaded Casing Connection [PRE_RESERVED]
├── Case 09: Engine Cylinder Head Thermo-Mechanical Low-Cycle Fatigue [PRE_RESERVED]
└── Case 10: Thin-Walled Pipe Elbow Elasto-Plastic In-Plane Bending Collapse [PRE_RESERVED]
```

详细工程边界、物理难点、参考来源与验收门槛请直接查阅：
- **需求规格与交付规范**：[`docs/p1-product-requirements.md`](p1-product-requirements.md)
- **工程实施演进与回归测试**：[`docs/engineering-run-evidence-roadmap.md`](engineering-run-evidence-roadmap.md)
- **物理验证自动化测试套件**：[`tests/test_p2_package_b_cases.py`](../tests/test_p2_package_b_cases.py)
