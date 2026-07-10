# knowledge-architect

将已验证经验路由到正确知识资产的元技能。它负责判断“是否值得固化、写到哪里、如何避免重复与漂移”，不替代单个 Skill 的创建、优化或精简工具。

## 目录

```text
knowledge-architect/
  SKILL.md
  scripts/inventory_skills.py
  references/knowledge-routing.md
  references/candidate-schema.md
  evals/trigger-evals.json
  evals/output-evals.json
  evals/results.tsv
```

## 动态技能清单

```powershell
python scripts\inventory_skills.py `
  "$HOME\.codex\skills" `
  --output inventory.json
```

扫描器只读取 `SKILL.md` 和资源目录，不导入或执行 Skill。它输出名称、description、版本字段、行数、哈希、资源情况、重复名称和 frontmatter 问题。

## 2026-06-10 优化

- 将静态版本/Pattern 总表替换为运行时动态发现。
- 新增证据驱动的通用性门和单一知识源规则。
- 区分项目文档、Skill 主体、reference、script、新 Skill 与长期记忆。
- 跨项目、跨 Skill、长期记忆和用户级目录修改前增加显式检查点。
- 不再因用户称赞自动修改系统知识。
- 新增失败兜底、反模式黑名单、20 条触发评测和 6 条输出评测。

## 验证

- 隔离 venv 中 3 个扫描器测试全部通过；
- Python 语法编译和 2 个 JSON 评测文件解析通过；
- 真实技能根目录扫描成功：识别 35 个 Skill、1 个重名名称和 7 个结构问题条目；
- 20 条触发边界静态复核通过；
- Darwin 9 维静态/干跑复评：`58.5 -> 93.6`，提升 `35.1` 分。

详细结果见 `evals/results.tsv`。输出场景尚未进行独立子代理盲测，效果维度包含 dry-run。
