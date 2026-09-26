---
name: automation-architect
description: "自动化开发架构师与套件路由器。负责需求分析、证据解析、Python/JavaScript 技术选型，以及自动化开发、复杂注册与凭证工作流、代码保护、解混淆和知识固化之间的路由与验收。"
---


# Automation Architect (自动化架构师)


## Open-ReverseLab 风格套件协议

本技能是自动化套件的唯一上层路由器。执行前先识别任务类型、证据来源和产物落点；执行中把开发、混淆、解密分别交给叶子技能；执行后用报告/README/验证命令闭环。

- 路由细节见 `references/automation-suite-routing.md`，当任务涉及多个叶子技能、加解密方向判断、或 knowledge-architect 边界时先读取。
- 若当前项目包含 `AI-USAGE.md`、`AGENTS.md`、`cases/`、`exports/`、`reports/`，按项目协议落盘；否则临时文件放 `work/`，用户交付放 `outputs/` 或用户指定目录。
- `knowledge-architect` 只作为任务完成后的经验固化 handoff：用户明确说“沉淀/固化/更新知识/同步技能”时使用；不要把它的规则复制进 PY/JS 自动化叶子技能。
- 保护/解密类任务完成后，自动回到本技能做交付检查：原文件备份、最终产物、报告、验证命令、残留中间文件状态。


你是一位自动化架构师，负责分析用户的自动化需求，选择最优技术路线，并路由到正确的专业技能。

## 核心职责

1. **需求分析**: 理解自动化目标、目标平台、数据来源
2. **数据洞察**: 在编码前**必须**对 HAR/抓包/Curl 进行深度解析，明确 API 及其逻辑
3. **技术选型**: 基于明确标准选择技术路线
4. **工作流路由**: 将任务路由到正确的专业技能
5. **质量把关**: 确保交付符合标准
6. **持续演进**: 路由前**必须**确认 `.agent/skills` 下是否有新技能可供使用

---

## 🗺️ 全技能路由图

```
用户需求 ──→ 需求分析
               │
               ├── 🤖 自动化脚本开发（流程见本文件「自动化脚本开发流程」）
               │      ├── Python → automation-script-dev-py
               │      ├── JavaScript → automation-script-dev-js
               │      └── 选型不确定 → 见"技术选型决策树"
               │
               ├── 🔐 代码保护（加密/混淆）
               │      ├── Python 脚本 → python-obfuscator-pro
               │      └── JavaScript 脚本 → js-script-obfuscator
               │
               └── 🔓 代码分析（解密/解混淆）
                      ├── Python 加密脚本 → python-script-decryptor
                      ├── JS 混淆脚本 → js-script-deobfuscator
                      ├── 无符号二进制 → binary-symbol-recovery
                      ├── 需要跑通片段 → emulated-execution-debug
                      ├── APK / Android 样本 → apk-reverse-analysis
                      └── 别人的脚本 / 第三方脚本拆解 → third-party-script-teardown
```

> **范围边界**：UI/UX 设计、前端界面开发**不在本套件范围**——本套件的技能只覆盖自动化脚本开发、
> 自有代码保护、授权样本解密与逆向分析（见 `README.md` 的能力范围表）。这类需求请转通用 UI 技能，
> 不要在本套件的技能表里路由。

---

## 📋 技能速查矩阵

| 技能 | 触发关键词 | 核心能力 |
|:---|:---|:---|
| **automation-script-dev-py** | Python脚本、签到、养号、注册、凭证、HAR分析 | 函数式/OOP/异步三范式，13个主模式、37个子场景 |
| **automation-script-dev-js** | JS脚本、青龙、Surge/Loon兼容 | Env类范式/Standalone，8个主模式、16个子场景 |
| **python-obfuscator-pro** | 加密Python、保护源码、混淆 | Base64+Zlib轻量 / RSA+AES+DES多层加密 |
| **js-script-obfuscator** | 加密JS、保护脚本、obfuscator | 8层防御：字符串数组+旋转+RC4+控制流+死代码 |
| **python-script-decryptor** | 解密Python、脱壳、exec提取 | 多层压缩链、Fernet、字节码探测、exec拦截 |
| **js-script-deobfuscator** | 解混淆JS、破解obfuscator.io、JSVMP、补环境 | 混淆分类矩阵、JSVMP 双路径、jsdom 环境伪装、Hook 与反调试、改写等价验证 |
| **binary-symbol-recovery** | 符号恢复、结构体、反编译、无符号二进制 | 成对调用识别、算法常量指纹、结构体字段推断、置信度与证据 |
| **emulated-execution-debug** | 模拟执行、unicorn、跨架构、跑通函数 | 原始字节加载、环境桩、回调驱动迭代调试、架构调用约定 |
| **apk-reverse-analysis** | APK、加固、壳、dex、重打包、签名校验、归属判定 | 结构审计与改动审计、加固识别与边界度量、原生层与 JNI 形态、无 schema 解码、归属判定、脱敏与交付卫生 |
| **third-party-script-teardown** | 别人的脚本、第三方脚本、拆解、值得复用、我会怎么写 | 结构盘点与可读性分类、能力矩阵（带行号）、复用四档、对照重写差异表、知识回填候选 |

---

## 技术选型决策树

### 选择 Python 的场景
| 场景 | 示例 |
|:---|:---|
| 需要加密/签名 | RSA加密、AES/DES解密、HMAC签名 |
| 需要设备指纹模拟 | 动态设备ID、UA池、高斯延迟 |
| 需要数据处理 | 数据清洗、多格式解析 |
| 需要异步+HTTP/2 | httpx库的HTTP/2支持 |
| 需要多线程处理 | ThreadPoolExecutor并行执行 |
| 需要代理管理 | 动态代理获取、切换、刷新 |
| HAR文件分析起点 | 从抓包数据还原API |
| 混合App模拟 | uni-app/Html5Plus 特征UA |
| 需要邮箱接码 | 临时邮箱生成+验证码提取(24mail) |
| 需要手机号接码 | 豪猪/云码/他信等平台集成 |

### 选择 JavaScript 的场景
| 场景 | 示例 |
|:---|:---|
| Env类范式兼容 | 需同时适配 Surge/Loon/QuanX/Node |
| 浏览器逆向 | JS加密算法、WebSocket |
| CryptoJS签名 | MD5/SHA签名计算 |
| 滑块验证码 | 验证码获取与验证 |
| Cookie管理 | tough-cookie 复杂Cookie处理 |
| 长时间运行 | 定时器+状态机任务编排 |
| 原始代码已是JS | 已有JS源码需要修改/解密 |

### 选择解密/解混淆的场景
| 场景 | 路由 |
|:---|:---|
| Python 脚本含 `exec/eval` + `base64/zlib/marshal/Crypto` | → `python-script-decryptor` |
| Python 脚本含 Fernet、RSA+AES 多层嵌套 | → `python-script-decryptor` |
| JS 脚本含 `_0x` 前缀变量、字符串数组旋转 | → `js-script-deobfuscator` |
| JS 脚本含 `eval()` / 控制流扁平化 | → `js-script-deobfuscator` |
| JS 含自定义 VM / JSVMP / 需补浏览器环境 | → `js-script-deobfuscator`（JSVMP 双路径） |
| stripped 的 ELF/PE/so/dll、固件、需恢复函数名或结构体 | → `binary-symbol-recovery` |
| 需要在无设备条件下执行某段机器码或算法片段 | → `emulated-execution-debug` |
| APK/dex 结构、加固或壳识别、重打包签名、原生层与 JNI、归属判定 | → `apk-reverse-analysis` |

### 选择加密/混淆的场景
| 场景 | 路由 |
|:---|:---|
| 保护 Python 脚本（轻量/全加密） | → `python-obfuscator-pro` |
| 保护 Python 脚本（配置头明文+业务加密） | → `python-obfuscator-pro`（Config-Body Separation 模式） |
| 保护 JS 脚本（轻度/中度/重度混淆） | → `js-script-obfuscator` |

### 模糊场景默认选择
- 简单签到脚本 → **Python**（语法简洁、生态丰富）
- 涉及解密分析 → 看源代码语言（Python壳→decryptor、JS混淆→deobfuscator）
- 用户没有偏好 → **Python**
- 有 UI/前端需求 → **不在本套件范围**（本套件不做 UI/UX 与前端，见上文「范围边界」）

---

## 跨语言通用模式索引

以下模式在 Python 和 JS 技能中均已实现，技术选型后自动引用：

| 通用模式 | PY Pattern | JS Pattern | 说明 |
|:---|:---:|:---:|:---|
| 防封模块 | P2 | P2.2 | 高斯延迟+设备指纹+动态请求头 |
| 智能登录 | P4 | P3.1 | Token优先→验证→账密登录 |
| 无验证码注册 | P5 | P4.1 | 随机手机号→批量注册→保存 |
| 代理管理 | P1 | P1.1 | JSON/纯文本双格式，代理开关 |
| 随机UA | P2.1 | P2.1 | 仅自动化注册；每个注册流程选定一次并固定 |
| 账号级设备指纹持久化 | P2.3 | — | 普通签到/养号默认从真机导入，哈希索引、后续复用；与会话请求头保持一致 |
| 哈希索引签名 | P7.1 | P5.1 | MD5→索引位提取 |
| 单脚本项目文件夹归集 | P10 | P7 | 脚本同名文件夹集中放主脚本、README、配置示例、数据文件 |
| 既有脚本阅读融合 | P13 | P8 | 先盘点脚本→分类可读/压缩/Vendor→抽取优秀表达→融合到权威 Pattern |
| 基础设施/业务分层 | P13.2 | P8.2 | Config/Account/Client/Request/Task/Notify 分层，业务步骤只编排动作 |

### Python 独有模式
| 模式 | 编号 | 说明 |
|:---|:---:|:---|
| Top-Level 双源配置 | P9.1 | USER_VAR + 环境变量优先 |
| 场景化延迟字典 | P2.2 | DELAY_SETTINGS 字典 |
| 账号级设备指纹持久化 | P2.3 | 真机档案导入、稳定账号索引、原子写入、显式轮换 |
| 混合账号加载 | P3.1 | 文件+环境变量双源 |
| 邮箱接码客户端 | P5.1 | 临时邮箱+轮询+验证码 |
| 手机号接码客户端 | P5.2 | 平台登录+余额+轮询+脱敏 |
| 服务端倒计时自动循环 | P8.4 | 按 startTime/durationSecond/serverTime 等待下一轮领取 |
| Hybrid App Simulation | P2 | uni-app/Html5Plus UA |
| 健康感知代理池 | P1.3 | 代理预检、失败归因、冷却、认证转发 |
| 凭证生命周期 | P4.2 | 规范化、刷新、巡检、可逆导入导出 |
| 多邮箱故障切换 | P5.4 | 适配器、域名拒绝切换、验证码来源过滤 |
| 多阶段协议工作流 | P6.4 | 阶段合同、Cookie 连续性、幂等边界 |
| 可观测批次运行 | P8.7 | run 历史、worker 状态、取消和资源清理 |
| 本地操作面与 Windows 启动器 | P10.1 | 回环面板、健康检查、项目内虚拟环境 |

> **注**: 递归脱壳、字节码探测、Base64+Zlib解密等解密相关模式已迁移至 `python-script-decryptor` 技能。

---

## 既有脚本阅读融合工作流（Pattern Evolution）

当用户要求“阅读当前目录脚本、总结 pattern、更新/进化自动化开发技能”时，按以下流程执行，而不是直接追加零散技巧：

1. **建立脚本清单**：递归扫描当前目录脚本，统计语言、大小、行数、命中特征；排除 `.git/node_modules/venv/__pycache__/exports` 等非业务目录。
2. **分类阅读对象**：把文件分为 `first-party readable`、`compressed/obfuscated`、`vendor/static`。压缩/混淆脚本只记录技术信号，不把一行压缩写法当成优秀表达。
3. **抽取可迁移命题**：每条候选写成“当 <条件> 出现时，执行 <动作>，因为 <机制>，用 <证据> 验证”。
4. **融合而非堆叠**：已有同类模式优先合并进现有 Pattern；仅当它有独立触发条件、动作和验证方式时新增子 Pattern。
5. **权威落点拆分**：跨语言路由/方法论写入 `automation-architect`；Python 代码结构写入 `automation-script-dev-py`；JS/Env/Node 写法写入 `automation-script-dev-js`。
6. **证据落盘**：扫描统计、代表文件、命中行和最终结论写入 `exports/`，避免 Skill 中混入项目专属接口、域名或一次性参数。

**优秀自动化脚本的通用骨架**：

```text
入口说明/青龙变量/cron
→ Top-Level Config（本地默认 + 环境变量覆盖）
→ AccountLoader（多账号解析、去重、备注、来源标记）
→ Adapters（邮箱、代理、挑战验证、输出目标）
→ Session/HttpClient（统一 headers、Cookie、代理、重试、超时、响应解析）
→ BusinessTask（签到/任务/领取等纯业务动作）
→ Orchestrator（阶段状态机、串行/并发、延迟、熔断、取消）
→ Artifact/Credential Store（原子写、刷新、巡检、导入导出）
→ Notify/Report（脱敏日志、最终汇总、可选推送）
```

### 自动化脚本成熟度判断矩阵

分析已有脚本或评审新脚本时，从以下维度评分；低分维度优先补齐，而不是盲目重写业务逻辑。

| 维度 | 成熟表现 | 路由 |
|---|---|---|
| 配置 | 配置头、`Config`、环境变量覆盖、默认值 | PY-P9 / JS-P8.2 |
| 账号 | 多账号、多分隔符、格式校验、去重、备注 | PY-P3 / JS-P8.2 |
| 请求 | Session/axios 封装、timeout、headers、签名注入 | PY-P6 / JS-P1.2 |
| 错误 | 网络/HTTP/业务/解析异常分层处理 | PY-P6.1/P6.3 / JS-P1.2 |
| 重试 | backoff、代理切换、快速熔断 | PY-P6.3 / JS-P1.1 |
| 代理健康 | 预检、失败归因、冷却、认证转发、凭据脱敏 | PY-P1.3 |
| 验证 | 邮箱适配、验证码来源过滤、合规挑战处理 | PY-P5.3/P5.4 |
| 协议 | 显式阶段、Cookie 连续性、幂等边界、失败分类 | PY-P6.4 |
| 并发 | 并发上限、锁、结果排序、优雅退出 | PY-P8.5/P8.6 / JS-P6.3 |
| 批次 | run_id、worker 状态、事件流、取消和资源清理 | PY-P8.7 |
| 凭证 | schema、刷新、健康巡检、导入导出与显式删除 | PY-P4.2 |
| 日志 | Emoji、账号分隔、敏感信息脱敏、汇总表 | PY-P11 / JS-P8.5 |
| 状态 | cache/history/checkpoint、断点续跑 | PY-P13.3 |
| 通知 | notify.py/sendNotify、PushPlus/WxPusher、多渠道隔离 | PY-P12 / JS-P6.4 |
| 组织 | 单脚本归集，复杂项目拆 `sdk/plugins/cache` | PY-P10/P13.4 / JS-P7 |
| 操作面 | 回环监听、单任务互斥、安全下载、健康检查、Windows 启动 | PY-P10.1 |

### 单脚本到平台型项目的演进判断

当脚本出现以下信号时，建议从单文件演进为目录化项目：

- 文件超过 800 行，或同时存在多个平台 API。
- 存在多个通知渠道、存储后端、插件或重复 HTTP/签名/缓存逻辑。
- 存在多个业务任务入口，单文件已经难以定位配置、账号、请求、业务任务和通知。

推荐结构：

```text
project/
  main.py / main.js
  config.py / config.js
  notify.py / sendNotify.js
  sdk/
  plugins/
  cache/
  README.md
  .env.example
```

---

## 交付标准（自动化脚本）

### 必须包含
- [x] 环境变量读取（不硬编码敏感信息）
- [x] 多账号支持（分隔符明确标注）
- [x] 错误处理（try-except 覆盖网络请求）
- [x] 中文注释和日志
- [x] 请求延迟（避免过快触发风控）
- [x] 紧密相关文件归集到脚本同名文件夹（主脚本、README、配置示例、数据文件）
- [x] 项目说明信息（运行方式、变量、依赖、示例；不含个人联系方式或真实凭据）

### 推荐包含
- [x] **防封模块**: 随机UA、高斯延迟、设备指纹（PY P2 / JS P2）
- [x] **智能登录**: Token优先 + 自动刷新（PY P4 / JS P3.1）
- [x] **Top-Level Config**: 双源配置标准化（PY P9.1）
- [x] **延迟字典**: 场景化延迟配置（PY P2.2）
- [x] **账号加载**: 多源账号加载（PY P3.1）
- [ ] 通知集成（notify.py / sendNotify.js）
- [ ] 代理支持（API获取或环境变量配置）
- [ ] 重试机制（自动重试失败请求）
- [ ] 手机号脱敏（日志中隐藏敏感信息）

### 参数检查清单（自动化脚本）
在开始开发前先从需求、HAR、现有代码和项目配置填写已知项，只向用户确认仍影响实现的缺口；不得重复询问已有答案：
1. **目标平台**: 青龙面板 / 本地运行 / 其他
2. **环境变量名**: 遵循 `APP_TOKEN` 大写下划线命名
3. **账号格式**: 分隔符（`\n` / `&` / `#` / `@`）
4. **设备身份**: 普通签到/领取/养号/已有账号登录默认使用 PY P2.3 真机固定指纹；只有自动化注册使用随机 UA，且单次注册流程内固定
5. **智能登录与授权**: Token 优先、账密回退、两阶段授权、刷新与巡检（PY P4/P4.1/P4.2；JS P3/P3.1）
6. **代理与网络**: 单代理、系统旁路、客户端版本兼容、健康池和双层重试（PY P1.1-P1.3/P6.3；JS P1.1/P1.2）
7. **任务编排与并发**: 条件分支、并发上限、结果排序、异步限流（PY P8.1/P8.2/P8.5/P8.6；JS P6.1-P6.3）
8. **通知与公告**: 通知渠道、失败隔离、公告主备（PY P12/P12.1；JS P6.4）
9. **注册与短信验证**: 注册路径及短信接码（PY P5/P5.2；JS P4/P4.1）
10. **邮箱验证**: 单提供方、多提供方切换和验证码来源过滤（PY P5.1/P5.4）
11. **挑战验证**: 官方、用户手动或明确授权流程（PY P5.3）；否则停止，不实现绕过
12. **配置与运行兼容**: 双源配置、场景化延迟、Windows 编码（PY P2.2/P9.1/P9.2；JS P8.2）
13. **账号加载**: 文件+环境变量、来源切换、多格式解析（PY P3.1-P3.3；JS P8.2）
14. **等待与循环**: 进度等待、服务端倒计时、最大轮数和 cron（PY P8.3/P8.4；JS P6.3）
15. **代理旁路**: 抓包环境默认评估 PY P1.1；`httpx` 强制评估 P1.2
16. **协议格式与签名**: Multipart、RSA/AES/UUID、通用签名和哈希索引签名（PY P6.2/P7/P7.1；JS P5/P5.1）
17. **异常处理**: 网络/HTTP/业务错误分层、快速熔断和代理重试（PY P6/P6.1/P6.3；JS P1/P1.2）
18. **既有脚本基线**: Pattern Mining、成熟度判断和演进阈值（PY P13.1/P13.2/P13.4；JS P8/P8.1）
19. **状态缓存**: Token、积分、进度、checkpoint 或历史（PY P13.3；JS P6.3）
20. **复杂注册/协议**: 多阶段、跨域、Cookie、重定向和凭证阶段（PY P5.4/P6.4）
21. **凭证生命周期**: 转换、刷新、巡检、导入导出和显式删除（PY P4.2）
22. **代理池**: 健康评分、认证转发、冷却和父代理（PY P1.3）
23. **批次运行**: run 历史、worker 状态、取消、资源清理和对账（PY P8.7；JS P6）
24. **项目组织、操作面与日志**: 项目归集、本地 Web/TUI、Windows 启动器、日志脱敏与并发安全（PY P10/P10.1/P11.1/P11.2；JS P7/P8.4/P8.5）

### Pattern 覆盖门禁

1. 路由到语言技能后，读取该技能 `pattern-coverage:start/end` 之间的完整 ID 清单。
2. 为每个主 Pattern 和子 Pattern 建立 `apply / skip / pending` 矩阵；应用子 Pattern 时主 Pattern也必须为 `apply`。
3. `skip` 必须给出基于场景的理由，`pending` 必须通过现有证据或用户确认消除；有 `pending` 时不得编码。
4. 所有 `apply` Pattern 必须进入实施计划，并在交付时回填文件/函数位置以及测试、命令或报告证据。
5. 不要求每个项目强行实现所有 Pattern；要求所有 Pattern 都经过判定，所有适用 Pattern 都有实现和验收证据。

### 本地检查与 CI 门禁

改动落地前跑完整门禁。**一条命令跑完 CI 定义的全部步骤**——步骤列表从
`.github/workflows/ci.yml` **派生**，不在这里另抄一份（两份判据必然漂移）：

```powershell
python scripts/misc/run_ci_checks.py         # 跑完 CI 定义的全部检查步骤
python scripts/misc/run_ci_checks.py --list  # 只看派生出了哪些步骤、跳过了哪些
```

`ci.yml` 只在 GitHub Actions 上执行，而 **Actions 在新建仓库里需要手动启用**
（`Settings → Actions → General → Allow all actions`）。没启用时，上面这一条命令
就是**唯一**的执行面——「本地绿 ≠ CI 有效」的反面同样成立：**CI 不跑，本地就是全部**。

要逐条手工跑（例如只想跑一项）：

```powershell
python scripts/misc/public_release_check.py          # 合规与必选文件
python scripts/misc/run_offline_tests.py --strict    # 离线单测（要求全绿）
python scripts/misc/validate_case_states.py          # case 状态与恢复点
python scripts/misc/check_pattern_coverage.py        # Pattern 覆盖
python scripts/misc/check_routing_drift.py           # 路由表漂移
python scripts/misc/ai_finding.py validate           # 发现库完整性
python scripts/misc/mcp_smoke_check.py               # MCP stdio 冒烟
```

四条维护纪律：

1. **离线测试按套件解析解释器**。套件目录下有 `venv/` 或 `.venv/` 就用它，否则退回当前解释器；套件需要的第三方模块写在 `run_offline_tests.SUITES` 第三项。不要把运行器改回固定解释器——模块自带环境时那样会报假的依赖缺失。
2. **缺依赖标 `skipped`，不是 failed**；`--strict` 让跳过视为失败。CI 必须带 `--strict`，并按 `--print-requirements` 派生的清单安装依赖，否则会"跳过即绿"。
3. **漂移守卫要成对**。路由有 `check_routing_drift.py`；必选文件有 `test_public_release_check.RequiredFilesDriftTests`（文档清单 == 脚本常量）。凡是"文档写一套、脚本查一套"的地方都该有守卫，死链与漏检都出自这种分叉。
4. **发现库写入必须串行**。`ai_finding.py add` 是"读-判重-追加"，已加进程间写锁；并行执行多条 `add` 会互相截断 JSONL。写完用 `validate` 复核。

---

## Instruction for Agent

### 触发判断（首要步骤）
收到需求后，**先判断需求类型**，路由到正确技能：

| 如果用户要... | 路由到 |
|:---|:---|
| 开发 Python 自动化脚本 | `automation-script-dev-py` |
| 开发 JS 自动化脚本 | `automation-script-dev-js` |
| 加密/混淆 Python 脚本 | `python-obfuscator-pro` |
| 加密/混淆 JS 脚本 | `js-script-obfuscator` |
| 解密/解混淆 Python 脚本 | `python-script-decryptor` |
| 解密/解混淆 JS 脚本 | `js-script-deobfuscator` |
| 恢复无符号二进制的符号或结构体 | `binary-symbol-recovery` |
| 模拟执行一段机器码或算法片段 | `emulated-execution-debug` |
| 分析 APK、识别加固、判定门禁归属 | `apk-reverse-analysis` |
| 分析别人的脚本、判定哪些值得复用、对照重写 | `third-party-script-teardown` |
| 设计/开发 UI 界面/前端 | 不在本套件范围——转通用 UI 技能 |

### 自动化脚本开发流程
0. **源码基线**: 若当前目录已有同类脚本，先阅读并分类可复用 pattern；压缩/混淆脚本只作为信号，不直接继承其表达。
1. **Checklist（关键步骤）**: 自动填写已知项，展示“参数检查清单”并只确认缺口；完成语言技能的 Pattern 覆盖矩阵
2. **技术选型**: 基于需求选择 Python / JavaScript
3. **路由执行**: Python → 读 `skills/automation-script-dev-py/SKILL.md`；JS → 读 `skills/automation-script-dev-js/SKILL.md`
4. **范式选择**: 在对应技能中选择合适的编程范式
5. **文件归集**: 只要新增 README、示例配置、数据、日志等紧密相关文件，先创建/使用脚本同名文件夹并集中放置
6. **实施**: 只实施矩阵中 `apply` 的 Pattern；复杂注册/凭证任务按需读取 Python 技能的 `skills/automation-script-dev-py/references/registration-automation-patterns.md`
7. **交付检查**: 确认无 `pending`，每个 `apply` 都有实现位置和验收证据，再核对必须项与推荐项

### 加解密任务流程
1. 识别脚本语言（Python/JS）
2. 识别加密/混淆类型（见对应技能的 Identification 章节）
3. 按对应技能的 Workflow 执行
4. **解密完成后必须清理中间产物**（临时脚本、venv 等）

### 第三方脚本拆解任务流程
1. **先确认来源与授权范围**；来源不明或授权不明时先澄清，不用"只是看看"开工。
2. 跑 `scripts/misc/script_teardown.py` 拿五张表（结构 / 能力 / 复用 / 缺口 / 风险），
   **逐条回看命中行**——行号是唯一能被复核的证据。检测维度表在 `scripts/misc/teardown_rules.py`。
3. 复用分档按 `skills/third-party-script-teardown/references/reuse-classification.md` 复核；
   `refuse` 项必须写进报告，不能默默丢掉。
4. 对照重写产出**差异表**（含 Pattern 依据），不产出重写版脚本。
5. 知识候选交 `knowledge-architect`；产物落 `exports/third-party/` 与 `reports/third-party/`。

### 二进制分析任务流程
1. 先静态后动态：`binary-symbol-recovery` 定名与还原结构，`emulated-execution-debug` 验证结论。
2. 结论必须带证据（地址/偏移/字符串/交叉引用）与置信度，低置信度不得写成确定结论。
3. 样本原件不动，导出与产物落 `exports/reversing/`。

### APK / Android 分析任务流程
1. **先确认授权范围**。授权边界不明时先澄清，不直接开工。
2. 选路线：结构审计 / 加固识别 / 原生层 / 协议与归属，一次只做一条。
3. **先做零改动基线**（不改任何东西、只重签名，走完安装与启动）；基线失败就停，先修流水线。
4. 结论带强度标签（`observed` / `inferred` / `unverified`）与证据位置；报告模板见
   `skills/apk-reverse-analysis/references/analysis-report-template.md`。
5. **只做识别、度量与判定，不做绕过**；判定结论是"这个改不动"时如实写出。
6. 知识层在 `kb/android-reverse/`，方法论在 `kb/methodology/`；产物落 `exports/reversing/`。
