# Automation Suite AI Usage Guide

## 任务路由

| 任务 | 主入口 | 工具 | 输出 |
|---|---|---|---|
| 自动化脚本开发/重构 | `skills/automation-architect` | `automation_route`, `script_inventory` | `exports/automation/`, `reports/automation/` |
| Python 自动化开发 | `skills/automation-script-dev-py` | `validate_script_delivery` | 脚本同名目录 |
| JS 自动化开发 | `skills/automation-script-dev-js` | `validate_script_delivery` | 脚本同名目录 |
| Python 保护/混淆 | `skills/python-obfuscator-pro` | `py_obfuscate` | `exports/obfuscation/` |
| JS 保护/混淆 | `skills/js-script-obfuscator` | `js_obfuscate` | `exports/obfuscation/` |
| Python 解密/脱壳 | `skills/python-script-decryptor` | `py_decrypt_probe` | `exports/deobfuscation/` |
| JS 解混淆 | `skills/js-script-deobfuscator` | `js_deobfuscate_probe` | `exports/deobfuscation/` |
| 经验固化 | `skills/knowledge-architect` | `read_skill`, `script_inventory` | `kb/` 或 skill reference |

## 默认流程

1. `automation_route` 判断任务语言、方向、推荐 skill。
2. 读取推荐 skill 的 `SKILL.md`。
3. 对输入文件先跑 probe/inventory，不直接执行未知 payload。
4. 执行生成/保护/解密。
5. 写报告并验证。

## 目录约定

- `tmp/`：临时中间文件。
- `exports/`：可复查的机器输出。
- `reports/`：人读报告。
- `cases/`：长任务状态。
- `skills/`：套件内 skill 权威副本。
