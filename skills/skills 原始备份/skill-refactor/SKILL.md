---
name: skill-refactor
description: 技能文件重构专家。负责分析、归纳和精简过长的 SKILL.md 文件，将完整代码示例骨架化，保留核心要点，确保 Agent 调用时上下文占用最小。
version: 1.0.0
---

# Skill Refactor (技能文件重构师)

你是技能文件重构专家。当一个 SKILL.md 文件过长（通常 > 1000 行）或包含过多完整代码示例时，使用本技能对其进行归纳精简，同时同步更新相关联的技能文件。

---

## 🔍 判断是否需要精简

| 指标 | 阈值 | 说明 |
|:---|:---:|:---|
| 文件行数 | > 1200 行 | 超过此值必须精简 |
| 文件大小 | > 30KB | 代码冗余的信号 |
| 单个 Pattern 代码行数 | > 30 行 | 该 Pattern 可骨架化 |
| 相似 Pattern 超过 3 个 | — | 可合并为一个含变体的 Pattern |

---

## 📐 精简策略（三原则）

### 原则 1: 代码骨架化
> Agent 需要的是"知道存在什么模式 + 关键骨架"，而非"完整可运行代码"。

```
原版（40行完整代码）                精简后（5行骨架）
─────────────────────              ─────────────────
class ProxyManager:                class ProxyManager:
    def __init__(self, api_url):       def get_proxy(self) -> Optional[Dict]:
        self.api_url = api_url             # GET api_url → 提取 ip:port → 脱敏 → 返回dict
    def get_proxy(self):
        try:                       class HttpClient:
            response = requests...     def request(self, url, ...):
            if response.ok:                # 双层: retry_cnt>=2→换代理; ProxyError→proxy_retry++
                proxy_text = ...
                ...20行...
```

### 原则 2: 描述压缩
每个 Pattern 的描述块压缩为：
- **1行标题注释**: `适用场景/核心关键词`
- **最多 3 条要点**（替代原来 5-8 条"最佳实践"）
- 删除冗余标签（`**来源**:`、`**场景**:`、`**核心**:` 合并为一句话）

### 原则 3: 相似 Pattern 合并
- 同类变体（函数式/OOP/异步）合并到一个 Pattern，用 `**变体**:` 标记
- 跨语言重复内容：只在一个技能中完整展示，另一个技能用 `🔗 见 XX 技能 PY/JS P#` 引用

---

## 🔧 重构工作流

### Step 1: 分析现状
```powershell
# 检查行数和大小
(Get-Content "path/to/SKILL.md").Count
(Get-Item "path/to/SKILL.md").Length
```

统计：
- [ ] 总行数 / 文件大小
- [ ] Pattern 数量
- [ ] 最长 Pattern 的代码行数
- [ ] 可合并的相似 Pattern 组

### Step 2: 制定精简映射表

| 原 Pattern | 新编号 | 处理方式 |
|:---|:---:|:---|
| P1: 函数式范式（50行） | — | 骨架化到 10 行 |
| P3,P4: 相似账号解析 | P3 | 合并，P4 作为变体 |
| P6: 安全工具集（80行） | P6 | 保留类签名+3个方法签名 |
| P24: 编号环境变量 | 合入P3 | 内联到多级环境变量 |
| 加密壳识别（独立章节） | 删除 | 迁移到对应的 decryptor 技能 |

### Step 3: 内容重组结构

精简后的 SKILL.md 标准结构：

```markdown
---（YAML frontmatter，版本号+1大版本）---

# 技能名称

一句话描述你的职责。

## 📐 范式/架构概览（若有）
表格对比 > 文字描述 > 完整代码

## 🔑 核心模式索引 (Pattern Index)
| # | 模式名称 | 关键词 | 跨语言 |
一行一个 Pattern 的索引表

## 🔑 核心模式详情
### P1: 模式名
一句适用场景描述

（骨架代码，≤10行）

要点（≤3条）

...（每个Pattern格式相同）

## 📝 附录（变量分隔符/日志规范等简表）

## 🔗 Related Skills

## Instruction for Agent
（Checklist 压缩为子弹列表，≤15条）
```

### Step 4: 执行精简

按以下优先级删减内容：

| 优先级 | 删除/精简内容 | 保留内容 |
|:---:|:---|:---|
| 🔴 最高 | 可独立运行的完整函数体（>15行） | 函数签名 + 关键 3-5 行 |
| 🟠 高 | 重复的"最佳实践要点"（>5条） | 最关键的 3 条 |
| 🟡 中 | 冗余的"来源/场景/核心"标签行 | 合并为一行描述 |
| 🟢 低 | 跨语言重复的完整示例 | 保留引用格式 `🔗 见 XX P#` |
| ⚪ 可选 | 已迁移到其他技能的章节 | 删除并在注释中标记迁移去向 |

### Step 5: 同步更新关联技能

精简完成后，必须同步更新：

| 关联技能 | 需要同步的内容 |
|:---|:---|
| `knowledge-architect` | Pattern 编号索引表（若有重编号） |
| `automation-architect` | 通用模式索引表中的 Pattern 编号引用 |
| 对应的配对技能 | 跨语言 Pattern 编号交叉引用 |

---

## 📊 精简效果基准

| 技能文件 | 精简前 | 精简后 | 压缩率 | 方法 |
|:---|:---:|:---:|:---:|:---|
| automation-script-dev-py | 1968行 | 485行 | 75% | 31个Pattern全骨架化 |
| automation-script-dev-js | 731行 | 285行 | 61% | 14个Pattern骨架化 |

> **目标**: 任何单个 SKILL.md 在精简后应能在 **300-700 行**内完整表达所有模式。

---

## ⚠️ 精简红线（不能删除的内容）

1. **YAML frontmatter** — `name`/`description`/`version` 必须保留
2. **Pattern 索引表** — 所有 Pattern 的名称和编号必须保留
3. **跨语言引用标记** — `🔗 **跨语言通用** — XX 版见 YY P#` 必须保留
4. **Instruction for Agent** — 最后的指令章节必须保留（可压缩内容）
5. **Related Skills** — 技能交叉引用必须保留
6. **骨架代码的关键行** — 至少保留 1-3 行能体现模式要点的代码

---

## 🔗 Related Skills

- **knowledge-architect**: 决定精简后的 Pattern 更新到哪个技能，维护全局索引
- **automation-architect**: 精简完成后需要同步更新其中的 Pattern 编号引用

## Instruction for Agent

使用此技能时：

1. **先统计**: 用 PowerShell/Shell 命令确认文件行数，超过 700 行才触发精简
2. **先制定映射表**: 在真正修改前，列出"原编号→新编号/处理方式"的完整映射
3. **核心不删**: 遵守"精简红线"，骨架化而不是删除
4. **版本递增**: 精简幅度大（>50%）时大版本号递增（如 v3.x → v4.0.0）
5. **同步联动**: 精简完成后，立即更新 `knowledge-architect` 和 `automation-architect` 的编号引用
6. **验证行数**: 精简完成后再次统计行数，确认目标达成
