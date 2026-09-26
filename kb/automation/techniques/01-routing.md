# 自动化任务路由

## 信号

| 信号 | 技能 |
|---|---|
| Python / requests / httpx / 青龙 / 多账号 / 签到 / 养号 / 设备指纹持久化 / 协议注册 / 凭证巡检 / 代理池 / 本地面板 | `automation-script-dev-py`（账号级设备档案读取 P2.3） |
| JavaScript / Node / axios / env类 / Surge / Loon / QuanX / UserScript | `automation-script-dev-js` |
| 需求不清 / 多技能协同 / 技术选型 / HAR 抓包证据分析 / 交付验收 | `automation-architect` |
| 加密 / 混淆 / 保护自有源码（Python） | `python-obfuscator-pro` |
| 加密 / 混淆 / 保护自有源码（JS / Node） | `js-script-obfuscator` |
| 解密 / 脱壳 / 解混淆（Python） | `python-script-decryptor` |
| 解密 / 还原 / 解混淆（JS） | `js-script-deobfuscator` |
| 符号恢复 / 结构体恢复 / 无符号二进制 / 算法常量指纹 | `binary-symbol-recovery` |
| 模拟执行 / 跨架构片段执行 / 跑通函数 | `emulated-execution-debug` |
| APK / dex 结构审计 / 加固与壳识别 / 重打包签名 / 原生层与 JNI / 门禁归属判定 | `apk-reverse-analysis` |
| 别人的脚本 / 第三方脚本拆解 / 值得复用 / 我会怎么写 / 对照重写 | `third-party-script-teardown`（只读，不执行目标脚本） |
| 沉淀经验 / 固化方法 / 更新知识 / 同步技能 | `knowledge-architect`（仅用户明确要求时触发） |

> 机器可读版本见项目根 `routing.index.json`；触发信号单一事实源为 `routing.source.json`。用 `python scripts/misc/check_routing_drift.py` 校验本表与索引是否一致。
>
> 上表的「信号」列是 `routing.source.json` 的**复述**，不是第二份定义——写词时**照抄 signals 的原文**。
> 这一列由 `check_routing_drift.py` 的 `signal_recall` 判据**逐词**校验：把消歧符当上下文拼进查询后，
> `route(词)` 的主选必须是本行技能；表里漏了哪个技能、或整张表解析不到行，都会报 drift。
>
> 括号里的 `（Python）` / `（JS）` 是**语言消歧符**，不是信号：`加密` / `混淆` / `解密` / `脱壳` 四个词
> 在保护与解密技能里各有一份，靠语言线索分派。**它不是装饰**——去掉消歧符后这六个词会全部翻红。
>
> 已知不覆盖：`normalize()` 会压缩空白但**不删除**它，所以 ASCII 与中文之间的空格会断开信号——
> `env类` 命中而 `env 类` **返回「无匹配」**。写词时不要在 ASCII 与中文之间加空格。
>
> 唯一登记的归属之争是裸语言词 `Python`：它归 `python-obfuscator-pro`，因为该技能**名字里**含
> `python`（`name_token` +2.0 压过 dev-py 的语言加成）。登记在 `check_routing_drift.py` 的
> `KNOWN_SIGNAL_CROSS` 里，**该词一旦恢复正确路由，判据会反过来报「登记已失效」**。
>
> 技能层之下还有知识层：各 `kb/<领域>/techniques/kb-index.json` 把需求文本映射到具体知识文件，用 `python scripts/misc/kb_router.py "<需求>"` 查询。

## 设备身份默认规则

- 普通签到、领取、养号、已有账号登录和会话刷新属于长期账号养护：按账号导入并固定真实设备指纹，跨请求、重试、换代理和跨天运行均不得随机 UA。
- 只有自动化注册流程采用随机 UA；每个注册流程开始时选择一次，流程内的请求、重试和重定向保持不变。
- 真实设备档案缺失、损坏或不兼容时明确失败，不得静默生成新指纹。

## 输出

先给推荐 skill、理由、输入证据和下一步工具。
