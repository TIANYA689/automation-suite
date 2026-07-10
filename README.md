# Automation Suite

Automation Suite 是一套面向 Codex/Claude 的自动化脚本开发、JS/Python 源码保护、解密/解混淆 MCP + Skills 工作区。

> 仅用于授权自动化、安全研究、代码保护和合规逆向分析。请勿用于未授权访问、绕过访问控制、侵犯他人权益或违反适用法律法规的场景。

## 组成

- `skills/`：Agent 工作流与路由说明。
- `tools/skills/mcp/AutomationSuiteMCP/`：MCP 工具服务。
- `kb/`：自动化、混淆、解混淆知识库。
- `exports/`、`reports/`、`notes/`：本地证据、报告和分析笔记目录（默认不提交内容）。
- `.github/`：GitHub Issue/PR 模板与 CI。

## 快速开始

```powershell
git clone <repository-url>
cd automation-suite
python scripts/misc/public_release_check.py
python scripts/misc/mcp_smoke_check.py
```

如果要直接在 Codex 中注册本项目 MCP，请继续执行“安装到 Codex”步骤。

## 安装到 Codex

1. 安装 `uv`：<https://docs.astral.sh/uv/>
2. Clone 本仓库。
3. 在仓库根目录运行：

```powershell
python scripts/misc/install_codex_mcp.py
```

脚本会自动根据当前 clone 路径写入 `~/.codex/config.toml`，不依赖固定盘符或任何个人目录。

4. 重启 Codex 或新开线程，工具列表应出现：

```text
mcp__automation_suite__automation_route
mcp__automation_suite__read_skill
mcp__automation_suite__script_inventory
mcp__automation_suite__py_decrypt_probe
mcp__automation_suite__js_deobfuscate_probe
mcp__automation_suite__py_obfuscate
mcp__automation_suite__js_obfuscate
mcp__automation_suite__validate_script_delivery
```

## 手动 MCP 启动

```powershell
uv run --project tools/skills/mcp/AutomationSuiteMCP python tools/skills/mcp/AutomationSuiteMCP/automation_suite_mcp.py
```

根目录 `.mcp.json` 使用相对路径，适合支持项目级 MCP 配置的客户端。

## 常用工具

- `automation_route`：按需求文本路由到技能和工具。
- `read_skill`：读取套件内指定 skill。
- `script_inventory`：扫描脚本并分类可读/混淆/vendor。
- `py_decrypt_probe` / `js_deobfuscate_probe`：静态识别加密/混淆信号。
- `py_obfuscate` / `js_obfuscate`：生成保护版本。
- `validate_script_delivery`：检查交付文件、README、依赖说明。

## 发布检查

提交前运行：

```powershell
python scripts/misc/public_release_check.py
python scripts/misc/mcp_smoke_check.py
```

检查重点：

- 是否缺少开源必需文件（`LICENSE`、`CONTRIBUTING.md`、`SECURITY.md`、GitHub 模板等）。
- 是否存在本地绝对路径、疑似密钥、密码或私有配置。
- MCP Python 模块是否可编译，核心路由、探测、保护和交付校验是否能跑通。

## 贡献

欢迎提交 Issue 和 Pull Request。贡献前请阅读：

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 许可证

本项目使用 MIT License，见 [LICENSE](LICENSE)。

## knowledge-architect

本项目只把 `knowledge-architect` 作为经验固化协同技能保留在 `skills/knowledge-architect/`，不合并到自动化叶子技能。只有用户明确要求“沉淀/固化/同步知识”时才调用。
