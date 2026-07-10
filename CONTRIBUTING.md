# Contributing

感谢你愿意改进 Automation Suite。这个项目包含自动化脚本开发、代码保护、解密/解混淆和 MCP 工具，请确保所有贡献都来自授权场景。

## 基本要求

- 不提交真实账号、Cookie、Token、私钥、个人路径或客户数据。
- 不提交 `tmp/`、`cases/`、`exports/`、`reports/`、`notes/` 中的本地分析内容，除非维护者明确要求。
- 新增技能或工具时，同时补充 README、验证命令和必要的 release check。
- 加解密、混淆、探测相关逻辑优先采用静态分析或安全沙盒，不直接执行未知 payload。

## 本地检查

```powershell
python scripts/misc/public_release_check.py
python scripts/misc/mcp_smoke_check.py
```

## Pull Request 建议

- 说明问题、解决方案和验证命令。
- 对安全敏感能力写清楚授权边界。
- 保持变更聚焦，避免把格式化、重命名和功能变更混在一个 PR。
