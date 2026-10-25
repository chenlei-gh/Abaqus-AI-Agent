# 仓库产物治理（T-P13）

## 原则

`deliverables/`、`runs/`、`invalid/`、`machine_validation/`、`validation_assets/`、`test_assets/` 都是治理范围，不是默认垃圾目录。禁止在 `.gitignore` 中使用 `目录/` 或 `目录/*` 形式的一刀切规则。产物是否入库由内容、来源和证据等级决定，不能仅由父目录决定。

| 目录 | 内容与处置 |
|---|---|
| `deliverables/` | 已授权交付、资格报告和交付清单。保留可审计产物；生产运行优先写外部项目空间。 |
| `runs/` | 运行工作目录。报告、证据 JSON、HTML 和非已知临时图片必须对 Git 可见；求解器临时件按扩展名或明确文件模式忽略。 |
| `invalid/` | 失败输入和负向验证资产。保留失败原因、输入和验证结果，不因“无效”整目录隐藏。 |
| `machine_validation/` | 真机和黄金证据。现有跟踪资产保持只读，不得因测试或工具调用重写。 |
| `validation_assets/` | 官方参考、案例注册和受控验证资产。逐项登记来源与使用边界。 |
| `test_assets/` | 受控测试输入、图纸和基准夹具。测试可读取，但不能生成覆盖原件的运行产物。 |

## 忽略边界

允许忽略的是可重建或机器本地的求解器临时件，以及少数已知的开发运行输出：

- 全局求解器扩展：`*.odb`、`*.inp`、`*.sta`、`*.msg`、`*.dat`、`*.log` 等。
- `/runs/live_environment_gate.json`
- `/runs/h6_grounding_validation/h6_grounding_live_result.json`
- `/runs/**/*_script.py`
- `/runs/images/slide_*_img_*.png`

新增忽略规则必须是具体文件或产物模式，并在 `tests/test_repository_artifact_governance.py` 中加入正反例。任何准备进入 `machine_validation/` 的 JSON 都属于证据候选，必须走显式证据生成和审核流程，不能依靠 `.gitignore` 自动过滤。

## 运行保护

`python tools/check_workspace_pollution.py` 会检查六个治理目录是否被测试或工具运行污染。它保护的是仓库状态，不负责删除或归档文件；清理仍需逐项判断。
