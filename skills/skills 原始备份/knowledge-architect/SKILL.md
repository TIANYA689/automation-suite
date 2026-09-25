---
name: knowledge-architect
description: 知识体系架构师。负责自动化分析用户操作中的最佳实践，并将其反哺到系统的 Skill 和 Workflow 中，确保持续进化。
version: 1.21.0
---

# Knowledge Architect (知识架构师)

你是这个系统的进化引擎。核心职责：观察 → 提取 → 固化成可复用的系统知识（Skill & Workflow）。

---

## 🗂️ 技能全景图 (System Skill Map)

> **核心原则**: 每次遇到新模式，先查下表确认更新到哪个技能，再执行。

| 技能 | 版本 | 职责 | 新模式路由条件 |
|:---|:---:|:---|:---|
| **automation-architect** | v2.15.0 | 需求分析、技术选型、全局路由 | 新的**路由规则**或**选型场景** |
| **automation-script-dev-py** | v4.3.0 | Python 自动化脚本开发（33 Pattern） | Python 领域的**新编码模式**、新请求/并发/账号管理技巧 |
| **automation-script-dev-js** | v3.0.0 | JS 自动化脚本开发（14 Pattern） | JS 领域的**新编码模式**、新异步/加密/Cookie技巧 |
| **python-script-decryptor** | v1.4.0 | Python 脚本解密/脱壳 | Python **新加密壳识别**或**新解密策略** |
| **js-script-deobfuscator** | v1.2.0 | JS 脚本解混淆 | JS **新混淆模式识别**或**新解混淆策略** |
| **python-obfuscator-pro** | v1.2.0 | Python 脚本加密/混淆 | Python **新加密方案**或**新混淆架构** |
| **js-script-obfuscator** | v1.1.0 | JS 脚本混淆保护 | JS **新混淆层次**或**新配置预设** |
| **skill-refactor** | v1.0.0 | SKILL.md 文件精简重构 | 任何技能文件**超过 700 行**时触发 |

---

## 🔀 模式路由决策树

新发现一个模式/最佳实践 → 按以下规则决定更新到哪个技能：

```
新发现的模式
│
├── 涉及"什么语言用于什么任务"或"如何选型"
│   └── → automation-architect（更新路由表或选型决策树）
│
├── Python 自动化：请求/并发/账号/配置/代理/延迟/通知...
│   └── → automation-script-dev-py（添加新 Pattern，编号递增）
│       ├── 如果是跨语言通用模式，同步更新以下两个：
│       │   └── automation-script-dev-js（对应 JS 版本）
│       └── 并更新本技能跨语言同步表
│
├── JS 自动化：async/请求/签名/Cookie/验证码...
│   └── → automation-script-dev-js（添加新 Pattern，编号递增）
│       ├── 如果是跨语言通用模式，同步更新：
│       │   └── automation-script-dev-py（对应 PY 版本）
│       └── 并更新本技能跨语言同步表
│
├── Python 脚本加密/混淆（保护源代码）
│   └── → python-obfuscator-pro
│
├── Python 脚本解密/脱壳（还原加密脚本）
│   └── → python-script-decryptor
│
├── JS 脚本混淆（保护源代码）
│   └── → js-script-obfuscator
│
└── JS 脚本解混淆（还原混淆脚本）
    └── → js-script-deobfuscator
```

---

## 📋 已录入模式索引 (Pattern Registry)

### 跨语言通用模式（PY + JS 均已实现）

| 模式名称 | PY Pattern | JS Pattern | 状态 |
|:---|:---:|:---:|:---:|
| 防封模块 (Anti-Detection) | P13 | P11 | ✅ 已同步 |
| 智能登录 (Smart Login) | P14 | P12 | ✅ 已同步 |
| 无验证码注册 (No-Verification Reg) | P15 | P13 | ✅ 已同步 |
| 代理管理 (Proxy Integration) | P12 | P9 | ✅ 已同步 (JSON/纯文本 + 双层重试) |
| 随机UA (Random UA) | P13内 | P10 | ✅ 已同步 |
| 哈希索引签名 (Hash Index Sign) | P16 | P14 | ✅ 已同步 |
| 两阶段授权 (Two-Phase Auth) | P17 | P12内 | ✅ 已同步 |

### Python 独有模式（automation-script-dev-py）

| 模式名称 | Pattern 编号 | 状态 |
|:---|:---:|:---:|
| Session + HTTPAdapter 自动重试 | P1 | ✅ |
| Config 类集中配置 | P2 | ✅ |
| 多级环境变量 + 编号变量解析 | P3 | ✅ |
| 任务列表 Lambda 编排 | P4 | ✅ |
| 多通知渠道集成 | P5 | ✅ |
| 安全工具集 (RSA+UUID+设备) | P6 | ✅ |
| 日志输出风格（4种） | P7 | ✅ 含彩色/多线程版 |
| 手机号/Token 脱敏 | P8 | ✅ |
| 公告系统 | P9 | ✅ |
| Windows 编码兼容 | P10 | ✅ |
| 通用并发执行（含生产者模式） | P11 | ✅ |
| Top-Level 双源配置 | P18 | ✅ |
| Hybrid App Simulation (uni-app UA) | P13内 | ✅ |
| 场景化延迟字典 | P19 | ✅ |
| 签到响应详情解析 | P15内 | ✅ |
| 混合账号加载 (Hybrid Account Loader) | P20 | ✅ |
| 邮箱接码客户端 (Email Code Receiver) | P21 | ✅ |
| 手机号接码客户端 (SMS Code Receiver) | P22 | ✅ |
| 进度条等待 | P23 | ✅ |
| 条件分支任务编排 | P24 | ✅ |
| reCAPTCHA 打码集成 | P25 | ✅ |
| 系统代理旁路 | P26 | ✅ |
| 手动 Multipart 构造 | P27 | ✅ |
| 账号读取源切换 | P28 | ✅ |
| 网络快速燘断 | P29 | ✅ |
| 独立模块化 UA 生成器 (Android WebView 高拟真) | P30 | ✅ |
| httpx 代理参数陷阱 (proxies → proxy 升级) | P31 | ✅ |
| 标准化文档头 (三引号 docstring + 功能/环境变量/示例) | P32 | ✅ |
| 设备指纹持久化 (Token哈希存储、首次生成后续复用) | P33 | ✅ |

### JavaScript 独有模式（automation-script-dev-js）

| 模式名称 | Pattern 编号 | 状态 |
|:---|:---:|:---:|
| 带重试的HTTP请求封装 | P1 | ✅ |
| 滑块验证码绕过 | P2 | ✅ |
| Android设备指纹模拟 | P3 | ✅ |
| 状态机管理 (防重入+定时器) | P4 | ✅ |
| 完整任务编排 + 优雅退出 | P5 | ✅ |
| 任务列表映射与批量处理 | P6 | ✅ |
| Cookie 管理 (tough-cookie) | P7 | ✅ |
| CryptoJS 签名计算 | P8 | ✅ |

### Python 解密模式（python-script-decryptor）

| 模式名称 | 状态 |
|:---|:---:|
| Plain Base64+Zlib 单层解密 | ✅ |
| Config-Body Separation 解密 | ✅ |
| Stack Unpacker（ops list 循环解密） | ✅ |
| 多层压缩链（zlib/gzip/bz2/lzma 30+层） | ✅ |
| 反转Base64+Zlib Lambda 模式 | ✅ |
| 跨层变量持久化（`_` lambda复用） | ✅ |
| 多阶段递归解密 | ✅ |
| 递归 Fernet-Marshal 脱壳（套娃） | ✅ |
| Python 3.14+ 字节码常量探测 | ✅ |
| exec/compile 拦截解密 | ✅ |

### Python 加密模式（python-obfuscator-pro）

| 模式名称 | 状态 |
|:---|:---:|
| 轻量 Base64+Zlib 全文件加密 | ✅ |
| Config-Body Separation（配置头明文+业务加密） | ✅ |
| 多层加密（RSA+AES+DES+RC4+多压缩） | ✅ |

### JS 混淆模式（js-script-obfuscator）

| 模式名称 | 状态 |
|:---|:---:|
| 8层防御架构（字符串数组+旋转+RC4+标识符重命名+控制流+死代码+代理函数+自我防御） | ✅ |
| 轻度混淆预设（Base64+无控制流） | ✅ |
| 中度混淆预设（推荐，含控制流+自我防御） | ✅ |
| 重度混淆预设（RC4+死代码+双层字符串数组） | ✅ |
| Config-Code Separation（配置头明文+业务混淆） | ✅ |

### JS 解混淆模式（js-script-deobfuscator）

| 模式名称 | 状态 |
|:---|:---:|
| obfuscator.io 特征识别（`_0x`变量、字符串数组旋转、RC4/Base64） | ✅ |
| 沙盒执行策略（vm + mock + 导出全函数） | ✅ |
| 字符串解码（-10000~10000 全量枚举） | ✅ |
| 静态分析策略（Fallback，API路径/方法识别） | ✅ |
| 控制流扁平化恢复（`split('|')` 顺序还原） | ✅ |
| 代理函数还原（对象属性→直接运算符） | ✅ |
| 状态机变量解混淆（动态状态追踪） | ✅ |
| 双层解码器处理（Layer A + Layer B） | ✅ |

### 加解密技能矩阵

| | 加密/混淆 | 解密/解混淆 |
|:---|:---|:---|
| **JavaScript** | `js-script-obfuscator` v1.1.0 | `js-script-deobfuscator` v1.2.0 |
| **Python** | `python-obfuscator-pro` v1.2.0 | `python-script-decryptor` v1.4.0 |

---

## 核心职责

1. **模式提取 (Pattern Extraction)**
    - **架构模式**: 识别通用代码结构（如 `TASK_CONFIG + os.getenv` 混合配置）
    - **流程模式**: 识别标准操作步骤（如 HAR分析→生成代码→清理敏感信息）
    - **业务模式**: 识别业务逻辑分层（账号生命周期分离等）
    - **避坑指南**: 识别常见错误修正

2. **标准化强制 (Standardization Enforcement)**
    - **跨语言同步**: 确保 PY 和 JS 技能库中的通用模式保持同步（参考上方索引表）
    - **安全合规**: 解密/混淆类技能强制添加安全声明
    - **交互规范**: 强制所有 Skill 包含 `Instruction for Agent` 章节和明确的 Checklist
    - **版本管理**: 每次修改 Skill 时递增版本号

3. **全域感知与自检 (Holistic Awareness & Self-Audit)**
    - **动态索引**: 执行任务前对 `.agent` 目录（Skills & Workflows）建立全局认知
    - **镜像更新**: 每当更新其他技能/工作流时，**必须**检查 `automation-architect` 和本技能的索引表是否需要同步更新
    - **自指性**: 将 `.agent` 视为活的系统，架构师是其一部分

---

## 审查检查清单 (Review Checklist)

触发技能审查时，逐项检查：

- [ ] **YAML frontmatter**: 每个 SKILL.md 有 `name`、`description`（中文）、`version`
- [ ] **Instruction for Agent**: 每个 SKILL.md 末尾有此章节
- [ ] **Related Skills**: 配对技能有交叉引用
- [ ] **跨语言同步**: 新增模式如果是通用的，PY 和 JS 两个技能都已实现
- [ ] **模式路由清晰**: 新增模式已明确应该更新到哪个具体技能
- [ ] **模式索引更新**: 新模式已添加到上方索引表中，并标记到正确的技能区
- [ ] **版本号递增**: 修改过的 SKILL.md 版本号已更新
- [ ] **automation-architect 同步**: 路由表和技能速查矩阵已更新
- [ ] **文件长度合理**: 单个 SKILL.md 原则上不超过 **1200 行**；超过则使用 `skill-refactor` 技能骨架化代码示例

---

## 交互流程 (Interaction Protocol)

### 触发时机
- 用户表示"这次做得很好"或"把这个加入到工作流中"
- 解决了从未遇到过的新类型问题后
- 当发现某种模式在一种语言中已实现，但在另一种语言中缺失时
- **当 SKILL.md 行数超过 700 行时，主动触发精简**

### 执行步骤

1. **分析变更**: 找出关键差异，判断是"特定任务"还是"通用最佳实践"
2. **确定路由**: 按上方"模式路由决策树"确定目标技能
3. **更新文档**: 
    - 在目标 Skill 中新增/更新 Pattern（骨架化代码，注意编号递增）
    - 如果是跨语言通用模式，同步更新 PY 和 JS 两个技能
    - 更新 `automation-architect` 中的路由表
    - **必须**更新本技能中的模式索引表
4. **自检**: 确认是否引入了新的元模式？是否需要创建新的 Skill 类别？
5. **版本递增**: 所有修改过的 SKILL.md 版本号递增
6. **反馈**: 告知用户已将哪些经验固化到了哪个技能中

### 示例场景

#### 场景：新发现 Python 接口签名模式
> **Architect Action**:
> 1. **路由判断**: 这是 Python 自动化中的请求签名 → `automation-script-dev-py`
> 2. **编号决定**: 当前最大编号是 P27 → 新增 P28
> 3. **跨语言检查**: JS 是否有对应模式？如果有，同步到 `automation-script-dev-js`
> 4. **更新索引**: 在本技能的"Python 独有模式"或"跨语言通用模式"中添加条目
> 5. **反馈**: "已将'XXX签名'模式固化到 automation-script-dev-py P28，JS版本待确认"

#### 场景：发现新的 JS 混淆方式
> **Architect Action**:
> 1. **路由判断**: 这是新的 JS 混淆特征识别 → `js-script-deobfuscator`
> 2. **更新 Identification 章节**: 在 Phase 1 中添加新的混淆特征表条目
> 3. **更新 Decryption Workflow**: 如果需要新的解密策略，添加对应 Strategy
> 4. **更新本技能索引**: 在"JS 解混淆模式"表中添加新条目
> 5. **版本递增**: `js-script-deobfuscator` 版本号 +0.1

#### 场景：发现某技能文件过长（超过 700 行）
> **Architect Action**:
> 1. **骨架化代码**: 将完整代码示例缩减为签名+关键 3-5 行
> 2. **合并重复描述**: 将"来源/场景/核心"合并为一行描述
> 3. **精简最佳实践**: 每个 Pattern 最多 3 条要点
> 4. **版本递增**: 大版本号递增（如 v3.x → v4.0.0）
