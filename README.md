# Automation Suite

面向 AI 编码代理（Trae / Codex / Claude 等）的自动化工作区：开发自动化脚本、保护自有源码、分析被保护的脚本。

> **授权边界**：本项目仅用于**授权范围内**的自动化、安全研究、自有代码保护和合规逆向分析。
> 禁止用于未授权访问、绕过访问控制、侵犯他人权益或违反适用法律法规的场景。
> 完整条款见 [`DISCLAIMER.zh.md`](DISCLAIMER.zh.md) 与 [`LICENSE`](LICENSE)。

## 能力范围

| 方向 | 说明 | 入口技能 |
|---|---|---|
| 自动化脚本开发 | Python / JS 多账号、登录授权、注册验证、签到养号、青龙面板适配 | `automation-script-dev-py`、`automation-script-dev-js` |
| 代码保护 | 对**自有**源码做混淆、压缩包装与可回滚交付 | `python-obfuscator-pro`、`js-script-obfuscator` |
| 解密与解混淆 | 对授权样本做静态优先的脱壳、去混淆与可审计还原；含 JSVMP 双路径、环境伪装、改写等价验证 | `python-script-decryptor`、`js-script-deobfuscator` |
| 二进制静态分析 | 无符号二进制的符号/结构体恢复、调用图整理、算法常量指纹 | `binary-symbol-recovery` |
| 模拟执行 | 无设备条件下跑通单个函数或代码片段，用于算法复现与跨架构验证 | `emulated-execution-debug` |
| 路由与固化 | 需求路由、技术选型、验收；经验沉淀为项目知识 | `automation-architect`、`knowledge-architect` |

技能明细（路径、触发信号、产物）见 [`SKILLS.md`](SKILLS.md)。

## 知识分层

本套件的知识分三层，各有唯一维护入口：

| 层 | 载体 | 用途 |
|---|---|---|
| 技能层 | `skills/<name>/SKILL.md` 与 `references/` | 流程、契约、判据 |
| 知识层 | `kb/<领域>/techniques/*.md` | 可复用的技术知识，由同目录 `kb-index.json` 的 signals 索引 |
| 经验层 | `kb/ai-findings/findings.jsonl` | 零散可检索的发现与坑点，含被排除的路径 |

技能路由（用哪个技能）由 `routing.source.json` 驱动；知识路由（读哪篇知识）由 `kb-index.json` 驱动，是第二跳。

## 快速开始

1. 读 [`AI-USAGE.md`](AI-USAGE.md) —— 全局入口，含任务路由表与默认流程。
2. 打开路由结论对应的 `skills/<name>/SKILL.md`，按其启动协议执行。
3. 对自然语言需求直接启动 Agent 工作台：

```powershell
python scripts/automation/workbench.py run "开发一个 Python 自动化脚本并给出验证步骤"
python scripts/automation/workbench.py resume <run_id>
```

工作台协议与证据格式见 [`agent-workbench.json`](agent-workbench.json) 和 [`docs/agent-workbench.md`](docs/agent-workbench.md)。

已注册路由 MCP 的 Agent 还可直接调用 `workbench_run`，并用 `workbench_resume`、`workbench_status`、`workbench_list` 管理可恢复运行；默认只做只读发现，模块真实执行仍需显式授权。

4. 提交前跑本地检查：

```powershell
python scripts/misc/public_release_check.py    # 公开前合规检查
python scripts/misc/run_offline_tests.py --strict   # 离线单元测试（要求全绿）
python scripts/misc/validate_case_states.py    # case 状态与长任务恢复点校验
python scripts/misc/check_pattern_coverage.py  # 模式覆盖检查
python scripts/misc/check_routing_drift.py     # 路由表漂移检查
python scripts/misc/check_commands.py          # 文档命令真实性
python scripts/misc/check_doc_refs.py          # 交叉引用可达性
python scripts/misc/check_index.py             # 索引完备性
python scripts/misc/check_budget.py            # 文档与单文件体量预算
python scripts/misc/check_tool_inventory.py    # MCP 工具清单一致性
python scripts/misc/ai_finding.py validate     # 可复用发现库校验
python scripts/misc/check_upstream_sources.py # 外部来源清单离线校验
```

前四项与最后一项是"内容对不对"，中间六项是"文档有没有说谎"：

| 检查 | 回答的问题 | 它看不见什么 |
|---|---|---|
| `check_routing_drift.py` | 4 处 Markdown 路由表与索引是否一致 | 从未入索引的技能 |
| `check_commands.py` | 文档里的命令、子命令、选项是否真实存在 | 参数取值是否合理 |
| `check_doc_refs.py` | 链接、锚点、被点名的路径是否可达 | 目标内容是否还相关 |
| `check_index.py` | 每个技能/知识篇目/脚本是否都被索引点名 | 索引条目本身是否写得好 |
| `check_budget.py` | 始终加载的部分与单个手写文件有没有单向膨胀 | 内容是否有用；只增/派生文件（`*.jsonl`/`*.json`/`*.csv`）与已有专属预算的文件不参与体积度量 |
| `check_tool_inventory.py` | 文档复述的 MCP 工具名与数量是否与实现一致 | 工具本身设计得对不对 |

六者互补且都**只做判定不做修改**：它们不自动改文档，只报出 file:line。

离线测试运行器会为每个套件解析解释器：套件目录下有 `venv/` 或 `.venv/` 就用它，
否则退回当前解释器。套件声明的第三方依赖缺失时标记 `skipped` 而不是失败；
`--strict` 会把跳过视为失败，CI 用的就是这个模式。CI 需要的依赖清单由
`python scripts/misc/run_offline_tests.py --print-requirements` 从套件声明派生，
不在工作流里硬编码。

CI 在 `windows-latest` 上执行以上检查，见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。
Actions 在新建仓库里**需要手动启用**（`Settings → Actions → General → Allow all actions`）。
没启用时用本地等价入口——**步骤列表从 `ci.yml` 派生**，不另抄一份，两份判据不会漂移：

```bash
python scripts/misc/run_ci_checks.py         # 跑完 CI 定义的全部检查步骤
python scripts/misc/run_ci_checks.py --list  # 只看派生出了哪些步骤、跳过了哪些
python scripts/misc/run_ci_checks.py --as-ci # 在 git clone 出来的目录里预演 CI（不应用本地改写）
```

## 文档地图

| 文件 | 职责 |
|---|---|
| [`AI-USAGE.md`](AI-USAGE.md) | 全局入口：任务路由、默认流程、目录约定 |
| [`AGENTS.md`](AGENTS.md) | 代理运行时契约：会话启动、硬性约束、完成标准 |
| [`SKILLS.md`](SKILLS.md) | 技能索引：触发信号与产物 |
| [`docs/upstream-absorption.md`](docs/upstream-absorption.md) | 上游吸收台账：吸收了什么、剔除了什么、理由 |
| [`docs/upstream-sources.json`](docs/upstream-sources.json) | 外部来源固定版本、许可证状态与复核记录 |
| [`docs/public-release.md`](docs/public-release.md) | 公开发布检查清单 |

## 目录结构

```
skills/    技能体系权威副本（明细见 SKILLS.md）
tools/     附属实现：automation-modules/（邮箱/短信/验证码封装）、skills/
kb/        知识库：automation/ js-reverse/ reversing/ methodology/ 下的 techniques/
           各领域 kb-index.json 为知识层路由索引；ai-findings/ 为可复用发现库
scripts/   路由引擎（automation/routing/）与本地检查脚本（misc/）
templates/ 长任务案例模板（case/：state.json + ai_manifest.json）
docs/      公开文档与 tools/ 的模块文档快照
cases/     长任务状态 state.json 与恢复点 ai_manifest.json
exports/   机器可读产物   reports/  人读报告   notes/  分析笔记
.github/   Issue/PR 模板与 CI
```

`cases/`、`exports/`、`reports/`、`notes/`、`tmp/` 为本地内容，默认不提交。

## 参与与合规

- 贡献指南：[`CONTRIBUTING.md`](CONTRIBUTING.md)（提交前务必阅读凭据与本地产物规则）
- 安全与合规：[`DISCLAIMER.zh.md`](DISCLAIMER.zh.md)；漏洞请通过 GitHub 私密安全通告报告，勿开公开 Issue
- 行为准则：[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
- 许可：[`LICENSE`](LICENSE)
