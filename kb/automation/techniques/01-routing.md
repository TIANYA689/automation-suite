# 自动化任务路由

## 信号

| 信号 | 技能 |
|---|---|
| Python / requests / httpx / 青龙 / 多账号 / 签到 / 养号 / 设备指纹持久化 / 协议注册 / 凭证巡检 / 代理健康池 / 本地面板 | `automation-script-dev-py`（账号级设备档案读取 P2.3） |
| JavaScript / Node / axios / Env 类 / Surge / Loon / QuanX / UserScript | `automation-script-dev-js` |
| 需求不清 / 多技能协同 / 技术选型 / HAR 抓包证据分析 / 交付验收 | `automation-architect` |
| 加密 / 混淆 / 保护自有源码（Python） | `python-obfuscator-pro` |
| 加密 / 混淆 / 保护自有源码（JS / Node） | `js-script-obfuscator` |
| 解密 / 脱壳 / 解混淆（Python） | `python-script-decryptor` |
| 解密 / 还原 / 解混淆（JS） | `js-script-deobfuscator` |
| 符号恢复 / 结构体恢复 / 无符号二进制 / 算法常量指纹 | `binary-symbol-recovery` |
| 模拟执行 / 跨架构片段执行 / 跑通单个函数 | `emulated-execution-debug` |
| APK / dex 结构审计 / 加固与壳识别 / 重打包签名 / 原生层与 JNI / 门禁归属判定 | `apk-reverse-analysis` |
| 沉淀经验 / 固化方法 / 更新知识 / 同步技能 | `knowledge-architect`（仅用户明确要求时触发） |

> 机器可读版本见项目根 `routing.index.json`；触发信号单一事实源为 `routing.source.json`。用 `python scripts/misc/check_routing_drift.py` 校验本表与索引是否一致。
>
> 技能层之下还有知识层：各 `kb/<领域>/techniques/kb-index.json` 把需求文本映射到具体知识文件，用 `python scripts/misc/kb_router.py "<需求>"` 查询。

## 设备身份默认规则

- 普通签到、领取、养号、已有账号登录和会话刷新属于长期账号养护：按账号导入并固定真实设备指纹，跨请求、重试、换代理和跨天运行均不得随机 UA。
- 只有自动化注册流程采用随机 UA；每个注册流程开始时选择一次，流程内的请求、重试和重定向保持不变。
- 真实设备档案缺失、损坏或不兼容时明确失败，不得静默生成新指纹。

## 输出

先给推荐 skill、理由、输入证据和下一步工具。
