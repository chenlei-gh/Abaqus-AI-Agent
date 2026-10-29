# 求解约定

本文件是产品仓库的编码约定。个人规则仍有效；冲突时以本文件的求解条款为准，其余仍以个人规则为准。本文件是约定，不是锁。

## 入口

建模和提交走 `AbaqusAIAgent.solve_requirement`。默认 `submit_job=False`，不提交。用户已有 INP 走 `solve_user_inp`。两条路都先产出 `execution_candidate.json` 和 `pre_solve_review.html`，等人批准后才求解：

```text
python -m abaqus_ai_agent approve --workdir <run workdir> --by <name>
```

批准绑定候选内容哈希。候选一改，批准失效。CLI `ask` 只路由意图，不求解。

## 禁止自行启动求解

编码会话不得：

- 调用 `abaqus.bat job=` 或 `abaqus job=`
- 调用 `mdb.jobs[...].submit` 或 `mdb.Job.submit`
- 删除 `.lck`
- 手改 INP 绕过评审，包括删除单元
- 设置 `ABAQUS_AI_AGENT_APPROVAL` 来跳过审批

`tools/*.py` 是与生产路径物理隔离的受控通道。不要把仓库外的 scratch 脚本当成这条通道，也不要为了让脚本跑通而关闭审批门。

没有候选哈希绑定的 `.odb`、`.lck` 或直接启动产物，不是 Agent 结果，不得写成通过。求解产物不提交。
