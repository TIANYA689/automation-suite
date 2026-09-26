# AI-USAGE — 全局入口

任何任务先读本文件：这里定义**任务路由、默认流程和落盘约定**。技能自身的执行细节在其 `SKILL.md` 内。

## 任务路由

| 任务类型 | 入口技能 | 产物落点 |
|---|---|---|
| 需求不明确 / 多技能协同 / 技术选型 / 验收 | `automation-architect` | 路由结论 + `reports/automation/` |
| Python 自动化脚本开发与重构 | `automation-script-dev-py` | 脚本同名目录 + `exports/automation/` |
| JS / Node / 青龙脚本开发 | `automation-script-dev-js` | 脚本同名目录 + `exports/automation/` |
| Python 源码保护 | `python-obfuscator-pro` | `exports/obfuscation/` |
| JS 源码保护 | `js-script-obfuscator` | `exports/obfuscation/` |
| Python 解密 / 脱壳 | `python-script-decryptor` | `exports/deobfuscation/` |
| JS 解混淆 | `js-script-deobfuscator` | `exports/deobfuscation/` |
| 无符号二进制符号/结构体恢复 | `binary-symbol-recovery` | `exports/reversing/` |
| 模拟执行单个函数或片段 | `emulated-execution-debug` | `exports/reversing/` |
| APK / Android 授权样本分析、加固识别、归属判定 | `apk-reverse-analysis` | `exports/reversing/` |
| 别人的脚本 / 第三方脚本拆解、复用分档、对照重写 | `third-party-script-teardown` | `exports/third-party/` + `reports/third-party/` |
| 经验固化 / 知识漂移审查 | `knowledge-architect` | `kb/` 或技能 reference |
| 外部模块文档检索 | `automation-architect` | `docs/automation-modules/` |

技能路径统一为 `skills/<name>/SKILL.md`；触发信号与产物明细见 [`SKILLS.md`](SKILLS.md)。

## 路由自动化

路由已从"人工读表"升级为"机器可查"，三层结构：

| 层 | 载体 | 说明 |
|---|---|---|
| 单一事实源 | `routing.source.json` | 12 个技能的触发信号、角色、调用模式、模块分类与路由规则；**唯一需要手工维护的路由文件** |
| 派生索引 | `routing.index.json` | 由事实源 + 磁盘扫描生成，含 SKILL.md 的 hash、模块清单；派生产物，不提交 |
| 路由 MCP | `scripts/automation/routing/mcp_server.py` | 6 个只读工具 `route_task` / `load_skill` / `list_skills` / `kb_route` / `list_modules` / `describe_module`，外加唯一的非只读工具 `run_module`（白名单 + dry-run 默认 + 审计日志） |

```bash
# 重建索引
python scripts/automation/build_routing_index.py
# 校验 4 处 Markdown 路由表与索引是否一致（有漂移则非零退出）
python scripts/misc/check_routing_drift.py
# 人工查询某条需求的路由结果
python scripts/automation/route_query.py "加密我的 python 脚本"
# 知识库第二跳：把需求映射到具体 kb 文件（--verify 校验文件存在）
python scripts/misc/kb_router.py "jsvmp 环境伪装" --verify
# HAR 静态盘点：把抓包文件变成接口地图（只读、离线、不执行、默认脱敏）
python scripts/automation/har_probe.py capture.har --timeline
# HAR 字段溯源：判定请求里的值来自哪条响应（只比哈希，不打印明文）。
# 输入必须是**真实抓包**——降级夹具刻意丢掉了响应体，跑它只会得到空报告。
python scripts/automation/har_origin.py capture.har --from recaptcha.net --to avalonavs
# HAR 内嵌源码检索：把应用自带的前端代码当证据来查（字段生成规则 / 请求包装族的
# 编码方式 / 鉴权拦截器 / 业务失败码 / 完整接口面）。盘点器把 .js 当静态资源折叠，
# 这一层补的就是那个缺口。默认只搜源码类资源，长不透明串已掩码。
# 输入同样必须是**真实抓包**——夹具把响应体压成了形态占位，源码不在里面。
python scripts/automation/har_source.py capture.har
python scripts/automation/har_source.py capture.har --grep deviceUuid
python scripts/automation/har_source.py capture.har --grep keepSignIn --include-data
# 按意图声明生成脚本骨架：先出待填模板，填完 role/动态策略后校验，再生成
python scripts/automation/har_to_script.py --har capture.har --emit-plan plan.json
python scripts/automation/har_to_script.py --har capture.har --plan plan.json --check
# HAR 降级成可进仓库的夹具（保形替换 + 泄漏自检 + 证据保真度）
python scripts/automation/har_to_fixture.py capture.har --out fixture.har
# 桩会话端到端验证（库，不是命令）：把生成的骨架装进假 requests 跑判定逻辑，
# 不发任何网络请求，所以能进 CI、能在没有账号的机器上跑。用法：
#   from automation.stub_session import run_script
#   result = run_script("signin.py", [(200, {"code": 0})], env={"EXAMPLE_ACCOUNT": "phone#pass"})
#   assert result.ok, result.output          # ok 看的是输出里的 [失败] 标记
#   result.calls[0].files                    # 每次请求的实参都记得下来
# 作业特有的用例数据随作业走（projects/<作业>/scripts/ 下的验证脚本）。
# 第三方脚本拆解：只读盘点别人的脚本，产出结构清单 / 能力矩阵（带行号）/
# 复用分档（直接复用 / 改造 / 只借鉴 / 拒绝吸收）/ 缺口 / 风险。**不执行目标文件。**
# 检测维度与风险规则是数据，在 scripts/misc/teardown_rules.py；加维度只改那张表。
# 散文区间（注释 / 文档字符串的识别与等长抹除）在 scripts/misc/text_spans.py。
# 人读版的列宽与按显示宽度截断在 scripts/misc/teardown_render.py（`--ascii` 时退回 ASCII 框线）。
python scripts/misc/script_teardown.py <目标目录> --json --out exports/third-party/teardown.json
python scripts/misc/script_teardown.py <目标目录>            # 人读版（按显示宽度对齐）
python scripts/misc/script_teardown.py <目标目录> --no-snippets
# 抓包作业区：一次「抓包 → 脚本」作业一个目录 projects/<YYYYMMDD>-<slug>/
python scripts/misc/new_project.py avalon-signin --goal "从抓包生成签到脚本"
# 校验作业与索引是否一致；索引是派生产物，漂移时用 --rebuild-index 重建
python scripts/misc/check_projects.py
python scripts/misc/check_projects.py --rebuild-index
# 可复用发现库：追加 / 检索 / 校验
python scripts/misc/ai_finding.py add --kind path --area js-reverse --title "..." --trigger "..." --detail "..."
python scripts/misc/ai_finding.py search "混淆 字符串数组"
python scripts/misc/ai_finding.py validate
# 注册 MCP 到 WorkBuddy / Claude Code / Codex（默认 dry-run，--write 才落盘）
python scripts/misc/install_router_mcp.py
# MCP 服务器 stdio 冒烟检查
python scripts/misc/mcp_smoke_check.py
```

> 改路由信号只改 `routing.source.json`，然后重建索引；`SKILLS.md`、`AI-USAGE.md`、`skills/automation-architect/SKILL.md`、`kb/automation/techniques/01-routing.md` 由漂移检查守住一致性。

## 默认流程

1. **路由** — 读 `kb/**/techniques/`，判断任务方向与推荐技能。
2. **读技能** — 打开推荐技能的 `SKILL.md`，按其启动协议执行。
3. **静态先行** — 输入文件先盘点、探测、记录 hash，不执行未知 payload。
4. **执行** — 生成 / 保护 / 解密，产物落盘到上表目录。
5. **闭环** — 写报告并给出验证命令，结论可复查。

模块文档默认读项目内 `tools/automation-modules/`；目录不可用时回退到 `docs/automation-modules/` 快照。文档检索不执行模块脚本。

## 目录约定

| 目录 | 用途 | 是否提交 |
|---|---|---|
| `tmp/` | 临时中间文件 | 否 |
| `exports/` | 机器可读产物 | 否 |
| `reports/` | 人读报告 | 否 |
| `notes/` | 分析笔记 | 否 |
| `cases/` | 长任务状态 `state.json` | 否 |
| `projects/` | 抓包作业区：一次「抓包 → 脚本」作业一个目录 | 索引与 `_template/` 提交，作业目录否 |
| `kb/` | 知识库 techniques（含各领域 `kb-index.json` 信号索引） | 是 |
| `kb/ai-findings/` | 可复用发现库 `findings.jsonl` | 是 |
| `skills/` | 技能权威副本 | 是 |
| `routing.source.json` | 路由单一事实源 | 是 |
| `routing.index.json` | 派生路由索引 | 否 |
| `scripts/automation/routing/` | 路由引擎与 MCP 服务器 | 是 |
