# Automation Suite Routing

本套技能采用 open-reverselab 风格：上层路由、叶子技能执行、证据落盘、结果可复查。

## 权威职责

| 职责 | Skill | 说明 |
|---|---|---|
| 需求分析、语言/方向选择、交付质量门 | automation-architect | 唯一上层路由 |
| Python 自动化脚本开发/重构 | automation-script-dev-py | 业务脚本结构、账号、请求、注册、邮箱/代理适配、凭证、批次运行、通知 |
| JavaScript/Node 自动化脚本开发/重构 | automation-script-dev-js | 青龙/Node/UserScript/Env 类脚本 |
| Python 源码保护 | python-obfuscator-pro | 保护、配置区明文、版本验证 |
| Python 解密/脱壳 | python-script-decryptor | 静态解包、逐层 dump、报告 |
| JS 源码保护 | js-script-obfuscator | javascript-obfuscator 风格保护 |
| JS 解混淆 | js-script-deobfuscator | 字符串数组、RC4/Base64、控制流恢复 |
| 无符号二进制的符号/结构体恢复 | binary-symbol-recovery | 调用图、字段偏移、算法常量指纹 |
| 无设备条件下模拟执行片段 | emulated-execution-debug | 环境桩、调用约定、执行 trace |
| APK/Android 授权样本分析 | apk-reverse-analysis | 结构审计、加固识别、原生层、归属判定；**只识别不绕过** |
| 别人的脚本拆解与复用分档 | third-party-script-teardown | 结构盘点、能力矩阵、复用四档、对照重写；**只读，不执行目标脚本** |
| 经验固化/跨技能知识路由 | knowledge-architect | 只在用户明确要求沉淀/固化/同步时触发 |

## 路由优先级

1. 用户要求“写/改自动化脚本” → 先 `automation-architect`，再 PY/JS leaf。
2. 用户提供 HAR/curl/抓包 → 先做 API 证据分析，再开发脚本。
3. 用户要求“加密/保护/混淆” → 按语言路由到 JS/Python obfuscator。
4. 用户要求“解密/还原/解混淆/脱壳” → 按语言路由到 JS/Python decryptor/deobfuscator。
5. 用户要求“分析别人的脚本/哪些值得复用/我会怎么写” → `third-party-script-teardown`；
   代码不可读时先转对应解密技能，结论固化再转 `knowledge-architect`。
6. 用户要求“把这次经验沉淀进技能/知识库/工作流” → 使用 `knowledge-architect` 形成提案；不把 knowledge-architect 合并进自动化叶子技能。

## 产物约定

- 临时分析：`work/` 或项目 `tmp/`。
- 可交付：当前环境的 `outputs/`、项目 `exports/`、`reports/` 或用户指定目录。
- 自动化脚本项目：脚本同名目录，包含主脚本、README、`.env.example`、示例账号/配置。
- 保护/解密任务：保留原始文件、最终文件、报告；中间层按需保留或清理。

## Pattern 覆盖门禁

自动化开发路由到 Python 或 JavaScript 叶子技能后，必须读取该技能 `pattern-coverage:start/end` 标记间的完整 Pattern ID 清单，并生成应用矩阵：

| Pattern | 状态 | 触发信号或 skip 理由 | 实现位置 | 验收证据 |
|---|---|---|---|---|
| Pn(.n) | apply/skip/pending | 需求、HAR、既有代码或不适用边界 | 文件/函数 | 测试/命令/报告 |

- 编码前消除全部 `pending`。
- `skip` 必须有场景理由；不能因实现成本或遗漏而跳过。
- 所有 `apply` 必须进入实施计划，交付前补齐实现位置和验收证据。
- 不强制每个项目实现所有 Pattern；强制全量判定并应用所有适用 Pattern。
- 使用 `python scripts/misc/check_pattern_coverage.py` 验证叶子技能定义与覆盖清单没有差集。

## knowledge-architect 相融结论

可以“协同”，不建议“合并”。原因：

- automation suite 负责执行开发/加解密任务；knowledge-architect 负责判断经验是否值得固化以及写到哪里。
- 合并会让自动化技能在普通开发时误触发长期知识写入，扩大副作用。
- 正确融合方式是在 automation-architect 中加入 handoff：任务完成后若用户明确要求沉淀，再调用 knowledge-architect。
