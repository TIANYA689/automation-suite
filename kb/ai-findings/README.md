# AI Findings — 可复用发现库

用途：把一次任务里"下次还有用"的发现沉淀成结构化记录，喂回路由与后续任务。

**这里不记命令流水账。** 只记四类内容：

1. 发现了可复用的路径（某个混淆器该怎么破、某类样本的稳定入口）
2. 某工具在某环境下失败，并找到了替代方案
3. 某特征可以稳定触发某个流程
4. 某条路径被证据排除（**这是最有价值的一类**，防止重复走死路）

## 记录格式

`findings.jsonl` 每行一条 JSON：

```json
{
  "time": "2026-09-24T21:30:00+08:00",
  "kind": "path|tool|signal|dead-end",
  "area": "js-reverse|reversing|automation|methodology",
  "title": "一句话结论",
  "trigger": "什么信号出现时该读这条",
  "detail": "具体发现，含命令/参数/版本",
  "evidence": {"path": "证据文件相对路径", "note": "说明"},
  "reuse": "high|medium|low",
  "confidence": "high|medium|low",
  "status": "active|superseded|invalid"
}
```

字段说明：

| 字段 | 作用 |
|---|---|
| `kind` | 四类之一；`dead-end` 用于记录被排除的路径 |
| `trigger` | **最重要**——决定这条记录下次能否被检索到 |
| `evidence` | 证据位置；没有证据的发现只能给 low 置信度 |
| `reuse` | 复用价值，用于排序 |
| `status` | 结论失效后改为 `superseded` 或 `invalid`，不删除 |

## 触发时机

出现下列情况时应当追加一条：

- 解混淆时发现某混淆器的识别特征或还原捷径
- 某工具在 Windows / 某 Node 版本下失败，换用替代方案
- 某个签名特征可以稳定定位到入口
- 某条分析路径被证据明确排除（写明排除依据）
- 某个环境差异反复导致失败

**不记**：单次任务的具体业务参数、临时路径、一次性的调试输出。

## 使用方式

```bash
# 追加一条
python scripts/misc/ai_finding.py add --kind path --area js-reverse \
  --title "..." --trigger "..." --detail "..." --evidence "exports/..." --reuse high

# 检索
python scripts/misc/ai_finding.py search "混淆 字符串数组"

# 列出最近若干条
python scripts/misc/ai_finding.py list --limit 20
```

## 与知识库的关系

- `kb/*/techniques/` 是**成体系的知识**，需要人工整理与审查。
- `kb/ai-findings/` 是**零散但可检索的经验**，允许随时追加。

一条 finding 如果被反复验证且具有普遍性，应当由 `knowledge-architect` 提炼进对应 techniques 文件；提炼后把 finding 的 `status` 改为 `superseded`，并在 `detail` 里指向新技术文件。

## 质量门禁

`scripts/misc/check_kb_quality.py` 是只读门禁，回答两个问题：

- **active 的 finding 有没有证据，证据是不是一条断链？** `evidence.path` 必须至少含
  一个**像路径**的 token（这个字段的语义是「证据文件相对路径」，写成描述文字属字段误用）。
  - 本仓库拥有的文件（`git ls-files` 命中）→ 通过；
  - **本地产物**（`projects/` `exports/` `reports/` `notes/` `tmp/` `.workbuddy-ai/`）
    → **通过**。本文件开头的示例就是 `--evidence "exports/..."`，这些目录是作业产物的
    既定位置，被 gitignore 是设计而非缺陷——门禁**不要求证据搬进仓库**；
  - 像仓库内路径却解析不到（文件被删或路径写错）→ 断链，报 `evidence_broken`。
- **superseded 的 finding 必须指向真实存在的技术条目**——即 `detail` 或 `evidence`
  里点名的 `kb/*/techniques/*.md` 必须能解析到本仓库里的文件，否则「已提炼」无从复核。

**没有证据的发现只能给 `low` 置信度**（见上面的字段说明）——所以 `confidence` 是
`high` / `medium` 而 `evidence.path` 里一个路径 token 都没有时会报 `missing_evidence`；
给了 `low` 就不算缺陷。门禁按它引用的这条规则判，而不是只在文案里提它。

`findings.jsonl` 不存在、解析出 0 条、或 active 一条都没有时**直接报错退出**——
空集不能当作通过（「跳过」与「通过」退出码相同本身就是缺陷）。

```bash
python scripts/misc/check_kb_quality.py            # 只报告，不因 warning 失败
python scripts/misc/check_kb_quality.py --strict   # CI 用：warning 也升级为失败
```

## 维护纪律

- 追加不修改历史记录；结论变化用 `status` 标记，保留原始记录。
- 定期清理：`reuse: low` 且超过 30 天未被检索的记录可以归档。
- 不写入任何凭据、真实账号、私有 URL 或授权样本内容。
