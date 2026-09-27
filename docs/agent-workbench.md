# AI Agent 自动化工作台

工作台专用于 `automation-suite` 自有项目，把本项目已有的路由 MCP、技能、知识库和模块执行护栏串成一个自然语言入口。Agent 只需把用户原话作为 `query` 传入，工作台会创建带 `run_id` 的可恢复运行，并把机器可读证据写到 `exports/automation/workbench/<run_id>/`。

## 快速开始

```powershell
# 只生成计划：路由、知识候选、主技能摘要都会落盘
python scripts/automation/workbench.py plan "把我的 Python 脚本做源码保护并给出验证步骤"

# 自主推进只读发现：还会读取模块 README，不会执行脚本
python scripts/automation/workbench.py run "分析授权样本的 JS 混淆并生成可验证的还原计划"

# 恢复中断的运行
python scripts/automation/workbench.py resume <run_id>

# 查看某次运行
python scripts/automation/workbench.py status <run_id>
```

默认输出是 JSON，适合被 Codex、Claude、Trae 或其他 Agent 直接解析。`run_id` 对应 `state.json` 中的恢复键；`next_action` 是下一个待处理动作。

### MCP 入口

注册路由 MCP 后，Agent 可以直接调用 `workbench_run`、`workbench_plan`、`workbench_resume`、`workbench_status` 和 `workbench_list`。这些工具与 CLI 共用同一运行目录和协议，stdout 之外的 MCP 返回值仍是同一个 JSON 摘要：

```powershell
python scripts/misc/install_router_mcp.py --write all
```

`workbench_run` 和 `workbench_resume` 的 `execute` 默认是 `false`；即使传入 `true`，模块仍必须在 `routing.source.json` 的 `execution.allowlist` 中。

## 动作与证据

每次运行包含：

| 文件 | 作用 |
|---|---|
| `plan.json` | 原始需求、三层技能候选、知识候选、技能摘要、动作清单和策略 |
| `state.json` | `READY/RUNNING/DONE/BLOCKED/FAILED/UNROUTED` 状态与恢复点 |
| 事件日志（JSONL） | 按时间追加的动作事件，不覆盖历史 |
| `modules/*.json` | 模块说明或模块运行结果 |

## 执行护栏

自然语言不会被当作命令执行。模块动作只有在命令行显式提供 `--module NAME` 时才加入；不提供 `--execute` 时即使模块在白名单内也只做 dry-run。真正执行仍由 `automation.routing.router.run_module` 完成，因此同时受 `routing.source.json` 的 `execution.allowlist`、超时、argv 调用和 `exports/automation/module-audit.jsonl` 审计约束。

```powershell
# 只解析命令，不执行模块
python scripts/automation/workbench.py run "检查邮箱模块" --module 24mail

# 只有在模块已加入白名单后，才允许真实执行
python scripts/automation/workbench.py resume <run_id> --module 24mail --execute
```

工作台本身不覆盖原文件；生成和验证产物都在 `exports/automation/workbench/`。如需开发新模块，仍按 `describe_module` → dry-run → 显式执行的顺序操作。

## 给 Agent 的契约

根目录的 [`agent-workbench.json`](../agent-workbench.json) 是稳定入口清单。Agent 应：

1. 调用 `run <自然语言>` 并解析 stdout JSON；
2. 保存 `run_id`，需要继续时调用 `resume`；
3. 以 `state.json.status` 和 `next_action` 驱动循环；遇到 `blocked_actions` 或 `failed_actions` 时读取对应动作的 `reason`；
4. 以 `plan.json`、事件日志和 `modules/*.json` 作为证据，而不是只相信 stdout；
5. 遇到 `BLOCKED` 或 `UNROUTED` 时读取 `plan.json` 的 `route`、`knowledge` 和 `skill_error`，再决定是否补充输入。

## 验证

```powershell
python scripts/misc/tests/test_workbench.py
python scripts/automation/workbench.py run "路由一个 Python 自动化脚本需求"
python scripts/misc/check_doc_refs.py
```
