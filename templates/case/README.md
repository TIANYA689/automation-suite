# 长任务案例模板

复制本目录到 `cases/<slug>/` 开始一个长任务。两个文件分工不同，不要互相复制内容。

| 文件 | 面向 | 作用 |
|---|---|---|
| `state.json` | 人 | 目标、状态、产物清单、下一步 |
| `ai_manifest.json` | 代理 | 恢复点：已完成步骤、证据、**已排除路径**、下一步动作 |

## 为什么要两个文件

`state.json` 回答"这个任务是什么、产出在哪"；`ai_manifest.json` 回答"现在到哪了、下一步做什么、哪些路已经堵死"。

后者的关键价值在 `dead_ends`：把被证据排除的路径写下来，防止下次（或另一个代理）重复走同一条死路。这比"尝试过但没结果"有价值得多。

## 三态约定

`ai_manifest.json` 的 `status` 只能取三个值：

| 状态 | 含义 | 约束 |
|---|---|---|
| `CONTINUE` | 还有可执行的下一步 | `next_actions` 至少一条 |
| `DONE` | 目标达成，证据齐全 | `evidence` 至少一条 |
| `EXHAUSTED` | 已尝试路径走完，无可行下一步 | `dead_ends` 至少一条并写明原因 |

**不要把"等待人工确认"当作状态。** 无人值守执行失败时，记录证据并切换路径。

## 使用流程

```text
1. 复制 templates/case/ 到 cases/<slug>/
2. 把两个文件里的 case 字段改成目录名 <slug>
3. 每完成一步就更新 steps_done 与 evidence，不要攒到最后
4. 每排除一条路径就写进 dead_ends
5. 每次中断前更新 status 与 next_actions
6. 提交前跑 python scripts/misc/validate_case_states.py
```

## 校验

`scripts/misc/validate_case_states.py` 会同时校验 `cases/*/` 与 `templates/case/`：

- `state.json`：`case` 等于目录名、`goal` 非空、`status` 合法、`next_steps` 为非空字符串列表、`updated_at` 为 `YYYY-MM-DD`。
- `ai_manifest.json`：`schema_version` 为整数、`case` 等于目录名、`goal` 非空、`status` 属于三态、各列表字段类型正确、`updated_at` 合法，以及按状态施加的下限约束。

`cases/` 默认不提交，因此模板是唯一进版本库的样例——模板必须始终可校验通过。
