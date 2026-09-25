# SKILLS — 技能索引

权威副本位于 `skills/<name>/`，执行细节读各自 `SKILL.md`；路由决策见 [`AI-USAGE.md`](AI-USAGE.md)。

| 技能 | 何时触发 | 主要产物 |
|---|---|---|
| `automation-architect` | 需求不清、多技能协同、技术选型、验收 | 路由结论、方案与验收报告 |
| `automation-script-dev-py` | Python 自动化：多账号、登录授权、注册验证、签到养号、设备指纹持久化、青龙面板 | 可运行脚本、交付检查清单 |
| `automation-script-dev-js` | JS/Node 自动化：青龙、Surge/Loon/QuanX 多平台适配 | 可运行脚本、平台适配说明 |
| `python-obfuscator-pro` | 保护**自有** Python 源码 | 保护版脚本、备份、验证记录 |
| `js-script-obfuscator` | 保护**自有** JS/Node 源码 | 混淆产物、备份、验证记录 |
| `python-script-decryptor` | 授权样本的 Python 解密 / 脱壳 / 解混淆 | 可审计源码、层级证据 |
| `js-script-deobfuscator` | 授权样本的 JS 解混淆与可读化；OB/CFF/自定义 VM/JSVMP；环境伪装、Hook 与反调试、改写等价验证 | 解密版 JS、解码表、证据、可验证事实清单 |
| `binary-symbol-recovery` | 无符号二进制的符号恢复、结构体重建、调用图整理、算法常量指纹识别 | 建议符号名与置信度、结构体定义、字段访问证据 |
| `emulated-execution-debug` | 无设备条件下模拟执行单个函数或代码片段，用于算法复现与跨架构验证 | 模拟脚本、环境桩定义、执行 trace 与输出证据 |
| `apk-reverse-analysis` | 授权样本的 APK/Android 分析：容器与字节码结构审计、重打包与签名校验、加固与虚拟化识别、校验边界度量、原生层与 JNI 形态、无 schema 协议解码、门禁归属判定 | 识别结论与证据、边界度量、改动审计、带残留声明的分析报告 |
| `knowledge-architect` | 经验固化、方法沉淀、知识漂移审查 | `kb/` 条目或技能 reference |

## 自动路由

本表由 `routing.source.json` 驱动校验，不再手工对账：

- 触发信号维护在 `routing.source.json`（唯一事实源）。
- `python scripts/automation/build_routing_index.py` 生成 `routing.index.json`。
- 只读 MCP 工具：`route_task(query)` 返回三层候选与命中证据，`load_skill(name)` 按需加载技能正文，`list_skills` / `list_modules` 列出技能与模块。
- `python scripts/misc/check_routing_drift.py` 校验本表与索引一致。

## 知识库路由（第二跳）

技能选定后，用知识库索引决定读哪篇知识：

- 每个 `kb/<area>/techniques/kb-index.json` 维护该领域的"信号 → 文件"映射。
- `python scripts/misc/kb_router.py "<需求>"` 按信号命中打分返回候选文件，`--verify` 校验文件是否存在。
- `kb/ai-findings/findings.jsonl` 是可复用发现库，用 `python scripts/misc/ai_finding.py add|search|list` 维护。

## 协同规则

- `automation-architect` 是唯一上层路由器，把开发、保护、解密分别分派给对应叶子技能。
- 被混淆脚本的还原优先与 `automation-script-dev-js` / `automation-script-dev-py` 协同，先看懂业务再动结构。
- `binary-symbol-recovery` 与 `emulated-execution-debug` 是配套：先静态定名与还原结构，再模拟执行验证结论。
- `apk-reverse-analysis` 只做识别、度量与判定，**不做绕过**；需要符号级静态恢复时转 `binary-symbol-recovery`，需要跑片段时转 `emulated-execution-debug`，脚本级还原转对应解密技能。
- `knowledge-architect` 默认只提交变更提案，**不自动合并**到其他技能。
