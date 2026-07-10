# Automation Suite Routing

本套技能采用 open-reverselab 风格：上层路由、叶子技能执行、证据落盘、结果可复查。

## 权威职责

| 职责 | Skill | 说明 |
|---|---|---|
| 需求分析、语言/方向选择、交付质量门 | automation-architect | 唯一上层路由 |
| Python 自动化脚本开发/重构 | automation-script-dev-py | 业务脚本结构、账号、请求、并发、通知 |
| JavaScript/Node 自动化脚本开发/重构 | automation-script-dev-js | 青龙/Node/UserScript/Env 类脚本 |
| Python 源码保护 | python-obfuscator-pro | 保护、配置区明文、版本验证 |
| Python 解密/脱壳 | python-script-decryptor | 静态解包、逐层 dump、报告 |
| JS 源码保护 | js-script-obfuscator | javascript-obfuscator 风格保护 |
| JS 解混淆 | js-script-deobfuscator | 字符串数组、RC4/Base64、控制流恢复 |
| 经验固化/跨技能知识路由 | knowledge-architect | 只在用户明确要求沉淀/固化/同步时触发 |

## 路由优先级

1. 用户要求“写/改自动化脚本” → 先 `automation-architect`，再 PY/JS leaf。
2. 用户提供 HAR/curl/抓包 → 先做 API 证据分析，再开发脚本。
3. 用户要求“加密/保护/混淆” → 按语言路由到 JS/Python obfuscator。
4. 用户要求“解密/还原/解混淆/脱壳” → 按语言路由到 JS/Python decryptor/deobfuscator。
5. 用户要求“把这次经验沉淀进技能/知识库/工作流” → 使用 `knowledge-architect` 形成提案；不把 knowledge-architect 合并进自动化叶子技能。

## 产物约定

- 临时分析：`work/` 或项目 `tmp/`。
- 可交付：当前环境的 `outputs/`、项目 `exports/`、`reports/` 或用户指定目录。
- 自动化脚本项目：脚本同名目录，包含主脚本、README、`.env.example`、示例账号/配置。
- 保护/解密任务：保留原始文件、最终文件、报告；中间层按需保留或清理。

## knowledge-architect 相融结论

可以“协同”，不建议“合并”。原因：

- automation suite 负责执行开发/加解密任务；knowledge-architect 负责判断经验是否值得固化以及写到哪里。
- 合并会让自动化技能在普通开发时误触发长期知识写入，扩大副作用。
- 正确融合方式是在 automation-architect 中加入 handoff：任务完成后若用户明确要求沉淀，再调用 knowledge-architect。
