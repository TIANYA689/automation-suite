# 上游吸收台账

记录本套件从外部仓库吸收了什么、剔除了什么、以及理由。目的是让"某个规则从哪来"可追溯，并防止把不该进来的东西混进来。

## 为什么要写这份台账

吸收外部能力时有三个风险：

1. **来源不可追溯**：半年后没人知道某条规则为什么这么写。
2. **许可不清**：直接复制 GPL 代码会污染本项目许可。
3. **边界模糊**：把"绕过模型安全护栏""主动攻击载荷"之类内容当技术知识吸收进来。

因此本项目的吸收原则是：**吸收设计范式与方法论，不复制实现代码；不吸收任何越界内容。**

## 本轮吸收的来源

| 仓库 | 吸收的部分 | 剔除的部分 |
|---|---|---|
| `WhiteNightShadow/hello_js_reverse_skill` | JS 逆向完整方法论：混淆类型分类、JSVMP 双路径、jsdom 环境伪装差异分级、Hook 与反调试、改写语义验证、反模式清单 | 与特定商业站点绑定的抓包细节；依赖外部浏览器 MCP 的工具调用 |
| `LING71671/open-reverselab` | 工程骨架：kb 信号索引（`kb-index.json`）、可复用发现库（`findings.jsonl`）、长任务三态与恢复点、公开/私有边界、证据闭环纪律 | 攻击性内容（Web 渗透、云提权、DoS、CVE 利用链、免杀与对抗检测）；GPL-3.0 代码；GUI 打包与站点部署 |
| `P4nda0s/reverse-skills` | 静态符号/结构体恢复方法论、算法常量指纹、模拟执行策略与架构调用约定 | 预编译二进制（供应链不可审计）；与真机/越狱设备强绑定的流程（本项目无设备依赖） |
| `Jia-Ethan/codex-keysmith` | 评测工程学：对照实验设计（基线臂/外部对照臂/变体臂）、消融实验记录、结果结构化归档、CI 供应链加固、事务化回滚设计 | **全部越狱载荷与判分口径**：绕过模型安全护栏的提示词、把拒答判为失败的评测机制、规避安全分类器的部署路径 |
| `JacksonTai2007/cc-unlock` | 记忆包的组织结构（索引 + 类型化条目）、agent 角色定义与职责切分的**结构**、事务式备份/回滚模型、部署脚本的幂等与回滚经验 | **内容层语义**：把攻击性交付重定义为"实验语义"的规则、关闭权限确认的危险默认值、反拒绝洗白内容 |
| `wuyoscar/Internal-Safety-Collapse` | 无（未进入吸收范围） | 全部 |
| `newliver666/apk-reverse` | 文档真实性的四类校验器（命令真实性、交叉引用可达性、索引完备性、体量预算）；长任务纪律与结论分级、验证阶梯、覆盖边界、案例体裁；APK/dex 结构事实与改动审计、加固与虚拟化识别及边界度量、原生层与 JNI 形态、无 schema 协议解码、门禁归属判定、脱敏与交付卫生 | **降低安全机制类内容**：去广告、会员与登录门禁绕过、中和强制升级、签名派生密钥、模块侧投递绕过重打包、内核层绕过、中和自毁路径、反检测与规避、绕过完整性校验、证书固定绕过、运行期替换 Java 实现、脱壳配方；以及上游全部脚本实现（不复制代码） |

## 来源清单与版本记录

上表每个仓库都在 [`docs/upstream-sources.json`](upstream-sources.json) 里有一条登记，记的是**复核时的固定版本与许可证状态**：URL、默认分支 commit、SPDX 标识、复核日期、吸收与剔除范围。

两份文件分工不同，不能互相替代：

- **本台账**回答「吸收了什么、剔除了什么、为什么」——人读，随判断变化。
- **来源清单**回答「当时看的是哪个版本、什么许可证」——机器校验，靠 commit 固定。

`scripts/misc/check_upstream_sources.py` 在 CI 里校验两件事：清单自身的 schema（版本号、commit 非空且非占位、许可证在允许列表、日期格式），以及**台账点名的每个仓库都登记在清单里**。台账加了来源却忘了登记清单会直接失败——否则清单只会安静地少一条，而没有任何东西会报错。

远程状态（仓库是否还在、许可证是否变更、是否归档）**不在 CI 里查**：那需要网络和 API token，会让门禁随外部服务的可用性变化。需要时手工复核，更新 `checked_at` 与 `revision` 并写明依据。

## 逐条吸收记录

### 已吸收

| 落点 | 吸收内容 | 来源 |
|---|---|---|
| `kb/js-reverse/techniques/01-obfuscation-signals.md` | 混淆信号 → 类型 → 还原成本的映射；三个必须避免的误判 | hello_js_reverse_skill |
| `kb/js-reverse/techniques/02-crypto-fingerprints.md` | 密文形态速查、变体识别、签名拼接模式、双语言实现差异 | hello_js_reverse_skill |
| `kb/js-reverse/techniques/03-jsvmp-paths.md` | JSVMP 双路径决策与四板斧分工、反向追踪法、观察者效应纪律 | hello_js_reverse_skill |
| `kb/js-reverse/techniques/04-env-emulation-diff.md` | 环境差异三级分类、native 标记格式陷阱、补丁顺序与时机 | hello_js_reverse_skill |
| `kb/js-reverse/techniques/05-transform-validation.md` | 改写必查反例、验证流程、产物三分类 | hello_js_reverse_skill |
| `skills/js-script-deobfuscator/` | 上列知识的程序化版本 + 6 篇 references | hello_js_reverse_skill |
| `skills/js-script-obfuscator/SKILL.md` | 还原成本视角与诚实的保护边界声明 | hello_js_reverse_skill |
| `kb/reversing/techniques/01-symbol-recovery.md` | 符号恢复三步法、成对调用识别表、置信度纪律 | reverse-skills |
| `kb/reversing/techniques/02-struct-recovery.md` | 访问模式记录格式、字段类型推断规则、大小公式 | reverse-skills |
| `kb/reversing/techniques/03-emulated-execution.md` | 模拟执行五原则、环境模拟对照、迭代调试循环 | reverse-skills |
| `kb/reversing/techniques/04-algorithm-identification.md` | 算法盲识别四层次、关键判据 | open-reverselab + reverse-skills |
| `kb/methodology/techniques/01-evidence-closure.md` | 节点执行口径、证据分层、三态与恢复点、反注水纪律 | open-reverselab |
| `skills/binary-symbol-recovery/` | 符号/结构体恢复技能 + 算法常量指纹 + 报告模板 | reverse-skills |
| `skills/emulated-execution-debug/` | 模拟执行技能 | reverse-skills |
| `kb/ai-findings/` + `scripts/misc/ai_finding.py` | 可复用发现库（含 `dead-end` 类型） | open-reverselab |
| `scripts/automation/routing/kb_index.py` + `scripts/misc/kb_router.py` | 知识库文件级路由（技能路由的第二跳），加权打分沿用其基线 | open-reverselab |
| `templates/case/` + `scripts/misc/validate_case_states.py` | 长任务三态协议与恢复点校验 | open-reverselab |
| `skills/knowledge-architect/SKILL.md` | 三层知识资产与维护责任、漂移红线、反注水 | open-reverselab + codex-keysmith |
| `skills/js-script-deobfuscator/references/anti-patterns.md` | 误判清单按"判定/执行/观测/改写"分类 | hello_js_reverse_skill |
| 评测方法论（写入技能与文档，不单独成文） | 对照实验臂设计、消融记录、结果归档四件套 | codex-keysmith（仅工程学部分） |
| 部署/回滚经验（写入设计约束，未落地为脚本） | 首次备份优先、原本不存在则恢复为删除、幂等复制与显式清理清单 | cc-unlock |
| `scripts/misc/check_commands.py` + `scripts/misc/tests/test_check_commands.py` | 文档命令真实性：静态解析命令行表面（含子命令与选项的扫描式判定），与文档里写的命令逐条对照，豁免项全量打印并计命中 | apk-reverse |
| `scripts/misc/check_doc_refs.py` + `scripts/misc/tests/test_check_doc_refs.py` | 交叉引用可达性：链接目标、`#锚点`（按 Unicode 类别丢标点的 slug 规则）、反引号点名的路径 | apk-reverse |
| `scripts/misc/check_index.py` + `scripts/misc/tests/test_check_index.py` | 索引完备性：每个知识篇目必须被索引点名、索引不许指向空气、技能与脚本不得漏登 | apk-reverse |
| `scripts/misc/check_budget.py` + `scripts/misc/tests/test_check_budget.py` | 体量预算度量（阈值用本仓库实测标定）、单文件体积预算（只增/派生文件与已有专属预算的文件不重复计入）、可导航性提示、含糊词趋势 | apk-reverse |
| `kb/methodology/techniques/02-long-task-discipline.md` | 活记录六段结构、四档结论分级、`RESULT=<token>` 与退出码固定语义、单变量纪律、六个约束轴与"交付物永远不会见到的环境"、给等待设上界、观察窗口洁净、长上下文衰减、交接清单 | apk-reverse |
| `kb/methodology/techniques/03-verification-ladder.md` | 主张阶梯 0–7 与各档适用条件、零改动对照规则、结构/运行/行为三段验证、相邻功能回归清单、报告模板与反模式 | apk-reverse |
| `kb/methodology/techniques/04-coverage-and-limits.md` | 三档强度标签的严格口径、覆盖分栏（已验证机制 vs 有文档但推断）、不分发的依赖、**不覆盖清单**、历史验证记录、能力闭包与"未探测≠不具备" | apk-reverse |
| `kb/methodology/techniques/05-precedent-records.md` | 案例体裁：Metadata / 断言与分级 / 执行链含死胡同 / 坑的代价 / 可复用模式 / 回写清单；与坑点目录、发现库、案例状态的分工 | apk-reverse |
| `kb/android-reverse/techniques/01-apk-and-dex-structure.md` | 容器与 dex 结构事实、校验和写入顺序、验证器硬规则、五类结构校验各自的盲区、改动审计的等长替换盲区与两级审计、重打包与签名流程、split APK 集合规则 | apk-reverse |
| `kb/android-reverse/techniques/02-hardening-identification.md` | 壳与代码虚拟化的识别判据、按方法体清空比例的形态分类、单变量边界度量五步、宿主三条件、完整性证据来源、清空比例的实测校准与双峰结论、静态读数能许可什么、诚实停止点 | apk-reverse |
| `kb/android-reverse/techniques/03-native-layer.md` | `DT_NEEDED` 与 `JNI_OnLoad` 的差异、重定位与页权限约束、活进程映射才是架构事实、JNI 三形态与符号搜索静默失败的两个机制、Java2C 与 JNI sinking 的密度判别、指令级追踪的三条纪律与实测边界、Dart AOT 的偏移空间与 ABI 格式推翻 | apk-reverse |
| `kb/android-reverse/techniques/04-protocol-and-attribution.md` | 无 schema 解码的三条必然后果与往返一致证据、gRPC 帧与 trailers、QUIC 限制、证书固定的三类归因、**门禁归属矩阵**、差分验证闭环与成本判定、退避阶梯 | apk-reverse |
| `kb/android-reverse/techniques/05-analysis-hygiene.md` | 脱敏判据与必须保留清单、泄漏扫描的四态状态与放置位置、自指证据与"发布文档永不引用命中值"、交接边界（交付物形态决定验证方式）、侦察顺序与产出清单、工具不可用条件、设备侧数据一致性 | apk-reverse |
| `skills/apk-reverse-analysis/`（含 `skills/apk-reverse-analysis/references/analysis-report-template.md`） | APK/Android 分析技能：范围边界、强度标签强制、四条路线、交付与验收、失败处理；报告模板与残留声明写法 | apk-reverse |
| `routing.source.json` 的 `R8` 规则与 `apk-reverse-analysis` 信号 | 把上述能力接进三层路由（技能路由 + 知识路由第二跳） | 本项目自定 |
| `kb/android-reverse/techniques/06-dynamic-observation.md` | 附着与启动注入的选择、零事件的六因排查顺序、进程存活与事件投递是两件事、观测能证明与不能证明什么、服务化调用的验收判据与实测失败模式、仿真的适用条件与两击规则、环境桩分级、调用约定、仿真结论的迁移程度、工具版本对齐门槛、诚实停止点 | apk-reverse |
| `kb/android-reverse/techniques/07-failure-signatures-and-tooling.md` | 失败特征 → 原因对照表（二十余条）、环境与设备类坑点、工具类坑点（自研脚本的四道形状检查、解码失同步、静默停止）、构建与打包类坑点（排序守卫、往返损坏、二次序列化、对齐与压缩） | apk-reverse |
| `kb/android-reverse/techniques/08-evidence-and-attribution-pitfalls.md` | 证据与归因类坑点（静态压运行时、内部信号替代可见结果、一次改两处、缓存回写、ABI 不匹配、搜索没找到、分支极性、采样不是观测）与十条通则 | apk-reverse |
| `kb/methodology/techniques/06-symptom-index-and-capability-matrix.md` | 症状索引的设计（查找层、一跳可达、条目粒度、与案例的分工、一致性机器强制）；能力矩阵五列与状态三档、"工具被测量 vs 路线被测量"、证据够不到时的用法；路线清单三段（依赖是栅栏不是提醒）；案例库的回写清单判据；豁免项全量打印并计命中的理由 | apk-reverse |

### 明确剔除

| 剔除内容 | 来源 | 理由 |
|---|---|---|
| 越狱提示词正文（人设契约、unrestricted 声明等） | codex-keysmith | 属于绕过模型安全护栏的载荷 |
| 把拒答判为失败的评测机制 | codex-keysmith | 本质是诱导放弃安全行为，与安全评测的中立性相悖 |
| 规避上游安全分类器的部署路径 | codex-keysmith | 目标即规避安全机制 |
| 攻击性内容（Web 渗透、云提权、DoS、CVE 利用链、免杀、反检测对抗） | open-reverselab | 与"授权范围内分析"的定位不符 |
| 预编译第三方二进制 | reverse-skills | 供应链不可审计 |
| 关闭权限确认的配置默认值 | cc-unlock | 放大破坏面 |
| 把攻击性交付重定义为"实验语义"的规则 | cc-unlock | 属绕过安全对齐的话术 |
| 上游仓库的代码实现 | 全部 | 避免许可污染；只借鉴设计，实现自行编写 |
| 去广告（按层抑制广告投放与展示） | apk-reverse `ad-removal.md` | 绕过变现机制，属"降低安全/商业机制"类 |
| 会员、付费墙与登录门禁的绕过 | apk-reverse `membership-and-limits.md`、`account-gates.md` | 绕过访问控制；本套件只做"门禁归谁所有"的判定 |
| 中和强制升级与服务端配置下发 | apk-reverse `updates-and-forced-upgrade.md`、`server-config-and-updates.md` 的对应部分 | 绕过服务端权威 |
| 重签名后硬编码原证书以派生密钥 | apk-reverse `signature-derived-keys.md` | 绕过签名校验 |
| 模块侧投递以绕过重打包 | apk-reverse `lsposed-and-modules.md` | 绕过完整性校验的替代路径 |
| 内核层绕过与环境加固 | apk-reverse `kernel-and-environment-hardening.md`、`kernelsu_syscall_mask.py` | 伪造进程自述、绕过检测；且涉及内核模块开发 |
| 中和自毁与终止路径 | apk-reverse `native-tamper-and-suicide.md` | 对抗完整性校验 |
| 反检测与规避 | apk-reverse `detection-and-anti-analysis.md`、`anti_detect_probe.js`、`spawn_patch_detach.py`、`hook_patch_only.js` | 目标即规避安全机制；上游自身也声明"不是规避目录" |
| 绕过完整性校验（分离校验方与实现方并令其不生效） | apk-reverse `code-virtualization-and-custom-linkers.md`、`so_constpatch.py` | 直接对抗完整性校验 |
| 证书固定绕过 | apk-reverse `protocol-reverse.md` 的固定绕过段、`tls-and-cert.md` 的宽松 TLS 默认段 | 绕过传输信任控制；本套件只做"失败出在哪一层"的归因 |
| 运行期替换 Java 方法实现 | apk-reverse `native-and-so.md` 的入口改写段 | 运行期篡改，属"降低安全机制"类 |
| 脱壳配方（主动调用、反壳对策、现成脱壳器路线） | apk-reverse `advanced-unpacking.md` | 上游自身即声明"不会把真虚拟化样本交还给你"；只吸收其**度量与停止点** |
| 提权安装与设备侧模块安装流程 | apk-reverse `on-device-tooling.md`、`runtime-data.md` 的对应部分 | 放大破坏面；与本套件的授权范围内定位不符 |
| 上游脚本实现（改写字节、注入、探测、追踪等） | apk-reverse `scripts/` 全部 | 不复制代码；且多数脚本的用途即为上述被剔除项 |
| 反插桩与检测中和（重命名并移动插桩服务端、挂钩检测器并中和、注入式加载方案） | apk-reverse `dynamic-frida.md` 反插桩一节、`spawn_patch_detach.py`、`hook_patch_only.js` | 目标即对抗检测 |
| 伪造进程自述以通过环境自检（用预制映射表满足映射检查、重定向进程信息读取） | apk-reverse `emulation-and-rpc.md` 对应段落 | 伪造环境自述，属对抗检测 |
| 六阶段"定位检查点并中和"管线（阻断终止路径、保活、单点置空） | apk-reverse `detection-and-anti-analysis.md` 的 Stage 4 / Stage 6 | 对抗反分析；上游自身也声明交付产物里不得放只为骗过检测器的东西 |
| 去广告与绕付费墙的具体坑点（抑制广告请求、改共享渲染组件、客户端伪造权限） | apk-reverse `pitfalls.md` P5 / P6 / P7 | 绕过变现与访问控制 |
| 中和终止路径与伪造 ELF 结构（把终止改成永不返回、按重定位表改写 stub、利用刻意崩溃、按伪造段头解析） | apk-reverse `pitfalls.md` P31 / P32 / P34 / P35 / P36 | 对抗完整性校验与反检测 |

**切片说明（可复核切在哪）**：`pitfalls.md` 的 P2（字符串表排序守卫）与 P41（分支极性）
在原书里的示例分别是广告串替换与促销门闸，属去广告；但两条的**教训**是通用的
（容器索引有序性、从控制流而非字段名读极性），故按"搞清楚状态"一侧吸收，
示例一律改为中性表述，操作含义不吸收。同理 P27（签名派生值）只吸收其**诊断**价值
（改包后接口全失败时先怀疑签名派生而非网络层），不吸收"硬编码原证书"的做法。

## 吸收原则（后续沿用）

1. **只吸收"测量、记录、对照、回滚、结构归档、验证"类工程内容**，不吸收"降低安全机制"类内容。
2. **不复制代码**：外部仓库的实现一律重写，避免许可传染与不可审计依赖。
3. **可追溯**：每条吸收记录写清落点与来源，便于日后复核与回退。
4. **不引入预编译二进制**：需要工具时优先可编译源码或自研。
5. **保持定位**：授权范围内的自动化开发、自有代码保护、授权样本分析。任何越出这条线的能力都不进本套件。
6. **"识别 / 度量 / 判定"与"绕过 / 对抗"要分开切**（2026-09-24 补充）：同一个文件里往往两者并存。
   吸收时按"这一步是在**搞清楚**状态，还是在**改变**状态"来切——
   前者（识别判据、边界度量、归属判定、审计方法）吸收；后者（让校验不生效、规避检测、中和防护）剔除。
   切片要记进本台账，便于复核时看出切在哪。
7. **能力越界要显式写进交付物**：吸收来的知识必须自带"不覆盖什么"的声明，
   否则读者会把"识别能力"误用成"绕过能力"（典型形态：把"这不是虚拟化"读成"这没有加固"）。

新来源的登记流程与 PR 勾选项见 [`CONTRIBUTING.md`](../CONTRIBUTING.md) 的「外部来源登记」小节。
