# Automation Suite Agent Instructions

全局入口先读 `AI-USAGE.md`。本项目是自动化脚本开发、代码保护、解密/解混淆的授权实验工作区。

## 会话启动

1. 若存在 `cases/<slug>/state.json`，从 `next_steps` 继续；没有 case 时创建或使用 `cases/ad-hoc/`。
2. 声明目标：`本次我要拿到______`。
3. 声明工具选择理由：优先 MCP 工具，其次本地脚本。
4. 查知识库：先用 `automation_route` 或阅读 `kb/**/techniques/`。

## 工具优先级

| 能做 | 用这个 | 避免 |
|---|---|---|
| 任务路由 | MCP `automation_route` | 手工猜测 |
| 读技能 | MCP `read_skill` | 到处复制 |
| 脚本盘点 | MCP `script_inventory` | 盲目阅读全部文件 |
| Python 解包识别 | MCP `py_decrypt_probe` | 直接运行未知 exec |
| JS 解混淆识别 | MCP `js_deobfuscate_probe` | 直接 eval |
| Python 保护 | MCP `py_obfuscate` | 覆盖原文件 |
| JS 保护 | MCP `js_obfuscate` | 无验证交付 |

## 完成标准

- 拿到实质产物：脚本、保护版、解密版、报告或路由结论。
- 证据落盘到 `exports/` 或 `reports/`。
- 原始文件不覆盖；修改前先备份。
- 每条结论有路径、hash、命中信号或验证命令。
