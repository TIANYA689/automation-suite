# AGENTS.md — 代理运行时契约

全局入口先读 [`AI-USAGE.md`](AI-USAGE.md)（任务路由与默认流程）。本文件只规定**代理自身的运行方式与硬性约束**。

工作区性质：自动化脚本开发、自有代码保护、授权样本的解密/解混淆。

## 会话启动

1. 查 `cases/<slug>/state.json`：存在则从 `next_steps` 继续；不存在则新建或复用 `cases/ad-hoc/`。
   若本次是**抓包 → 脚本**作业，改查 `projects/`：已有对应作业就从它的 `job.json` 继续，
   没有就 `python scripts/misc/new_project.py <slug> --goal "..."` 新建，产物落在该作业目录里。
2. 声明本次目标：`本次我要拿到 ______`。
3. **路由**：优先调用 `route_task(<需求>)` 拿三层候选与命中证据；未接入 MCP 时用
   `python scripts/automation/route_query.py "<需求>"`，或读 `kb/**/techniques/`。
   技能清单以 `routing.source.json` 为准，不以记忆为准。
4. 声明工具选择理由：优先项目内技能与本地脚本。
5. 按路由结果的 `next_step` 用 `load_skill(<技能名>)` 加载目标技能 `SKILL.md`，再动手。
   需要复用模块时用 `list_modules` / `describe_module` 查目录与依赖。
   执行模块用 `run_module`，受三道护栏约束：**白名单**（`execution.allowlist`，默认空）、
   **dry-run 默认**（只解析命令与工作目录，不执行）、**审计日志**（含被拒绝的调用，落 `exports/`）。

> 路由器只推荐不决策：分数是排序不是概率，最终技能选择由代理结合证据判断。
> 无主选时不硬造结论，交 `automation-architect` 澄清需求。

## 硬性约束（做 / 不做）

| 场景 | 做 | 不做 |
|---|---|---|
| 任务路由 | 先 `route_task` 拿候选与证据，再查 `kb/**/techniques/` 与 [`SKILLS.md`](SKILLS.md) | 凭感觉挑技能 |
| 路由信号维护 | 只改 `routing.source.json`，再重建索引并跑漂移检查 | 直接手改 `routing.index.json` 或四处 Markdown 路由表 |
| 抓包作业 | 先 `new_project.py` 建 `projects/<日期>-<项目名>/`，全过程产物落进该目录，`job.json` 记 `knowledge_returned` | 直接把产物丢 `exports/`——作业不可追溯，知识不回流 |
| 模块执行 | 先 `describe_module` 看依赖，再 `run_module`；默认 dry-run 确认命令后再显式执行 | 绕过白名单执行未授权模块；无审计地批量执行 |
| 脚本盘点 | `rg --files` + 本地检查脚本 | 通读全部文件 |
| Python 解包 | 静态检查后按 `python-script-decryptor` 执行 | 直接运行未知 `exec` |
| JS 解混淆 | 静态检查后按 `js-script-deobfuscator` 执行 | 直接 `eval` |
| Python 保护 | 按 `python-obfuscator-pro` 生成新文件 | 覆盖原文件 |
| JS 保护 | 按 `js-script-obfuscator` 生成并验证 | 无验证交付 |
| 任何改动 | 先备份，改动落在副本 | 就地覆盖原件 |

## 完成标准

- **有实质产物**：脚本、保护版、解密版、报告或路由结论，而非仅对话说明。
- **证据落盘**：写入 `exports/` 或 `reports/`。
- **原件不动**：原始文件不覆盖，修改前先备份。
- **可复查**：每条结论附路径、hash、命中信号或验证命令。
