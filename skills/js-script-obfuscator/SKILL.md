---
name: js-script-obfuscator
description: JavaScript/Node.js 源码混淆与交付保护。用于用户要求保护自有 JS、青龙脚本、Node 自动化脚本或前端业务逻辑时，按轻度/中度/重度预设执行 javascript-obfuscator 风格混淆，支持配置区明文保留、字符串数组、Base64/RC4、控制流扁平化、死代码、代理函数、自防御、产物验证和可回滚备份。
---

# JavaScript Script Obfuscator

目标：在不破坏运行行为的前提下提高源码阅读成本。参照 open-reverselab 风格：先备份、分离配置、执行验证、产物和说明落盘。

## 启动协议

1. 确认输入是用户要保护的 JS/Node 代码或用户授权修改的脚本。
2. 复制原文件到备份目录，保留源码不覆盖。
3. 判断运行环境：Node.js / 青龙 / Browser / UserScript。
4. 分离可编辑配置区与业务区；配置区默认明文。
5. 按强度预设混淆，运行原版与混淆版的无害自测，比较退出码和关键输出。

## 强度预设

| 等级 | 适用 | 配置 |
|---|---|---|
| light | 体积敏感、只防随手查看 | `stringArray + base64 + identifierNamesGenerator` |
| medium | 常规自动化脚本，推荐默认 | light + `stringArrayRotate + controlFlowFlattening(0.5) + transformObjectKeys` |
| heavy | 商业/分发脚本，接受体积和启动开销 | medium + `rc4 + wrappersCount=2 + deadCode + selfDefending + splitStrings` |

## 还原成本视角（选强度前必读）

保护强度不是越高越好，而是"攻击者成本 / 用户成本"的权衡。下面按**对方要花多少力气才能还原**排序，这是选择强度的依据。

| 手段 | 还原成本 | 代价 | 说明 |
|---|---|---|---|
| 变量名重命名 | 极低 | 几乎无 | 只增加阅读噪音，不构成保护 |
| 字符串数组 + Base64 | 低 | 体积略增 | 纯结构变换，工具化程度高 |
| 字符串数组旋转 | 低 | 无 | 旋转函数可被直接执行得到明文表 |
| 字符串数组 RC4 编码 | 中 | 体积增 | 需先复刻 RC4 或调用 decoder 扫索引 |
| 控制流平坦化 | 中 | 性能下降明显 | 按状态转移重排即可还原，但条件分支需要额外处理 |
| 死代码注入 | 中低 | 体积与启动开销 | 只增加干扰，不影响核心可还原性 |
| 代理函数（object helper） | 中低 | 无 | 可内联还原 |
| 字符串切片拆分 | 低 | 体积增 | 相邻字面量拼接即可还原 |
| 自防御（selfDefending） | 中 | 体积小 | 还原者只需在副本里 stub 掉完整性校验 |
| **JSVMP / 自定义 VM** | **高** | 体积与性能代价大 | 真正的成本跃升点：静态不可读，需运行时观测或环境复现 |

**关键结论**：

1. 除 JSVMP 外，上述手段**都是可逆的结构变换**，能显著提高"随手查看"的门槛，但挡不住有针对性分析。
2. 唯一的成本跃升点是 VM 化。若目标是防止针对性逆向，评估引入 VM 保护的成本收益；若只是防止复制粘贴和随手改动，medium 足够。
3. `selfDefending` 与 `debugger` 类手段会**同时伤害正常用户**（异常栈变差、调试困难、启动变慢），且不阻止决心足够的分析者。谨慎启用。

## 诚实的保护边界声明

交付保护版时必须向用户说明，不要暗示"混淆即安全"：

- 混淆提高**阅读与修改成本**，不提供密码学安全性。
- 只要代码能在目标环境运行，就一定能被还原到可读形式；差别只是成本。
- 真正的秘密（密钥、算法参数）**不应放在被分发的代码里**。混淆不能保护硬编码密钥。
- 自防御类手段可能被误触发，导致正常环境下也运行失败。
- 建议在交付说明中写清：保护等级、使用的技术、已知限制、以及"哪些信息仍可从产物中恢复"。

这些说明与 `js-script-deobfuscator` 的分析能力互为镜像——保护方应当知道分析方会怎么走。完整还原路径见该技能的 [混淆类型识别与还原](../js-script-deobfuscator/references/obfuscation-taxonomy.md) 与 [JSVMP 双路径方法论](../js-script-deobfuscator/references/jsvmp-paths.md)。

## 推荐实现

优先使用 npm 包 `javascript-obfuscator`。若项目已有 `package.json`，在项目内安装；否则在临时工作目录安装并记录版本。

```javascript
const JavaScriptObfuscator = require('javascript-obfuscator');
const result = JavaScriptObfuscator.obfuscate(sourceCode, {
  compact: true,
  target: 'node',
  stringArray: true,
  stringArrayRotate: true,
  stringArrayEncoding: ['base64'],
  stringArrayThreshold: 0.75,
  identifierNamesGenerator: 'hexadecimal',
  renameGlobals: false,
  controlFlowFlattening: true,
  controlFlowFlatteningThreshold: 0.5,
  deadCodeInjection: false,
  transformObjectKeys: true,
  selfDefending: false,
  numbersToExpressions: true,
  splitStrings: true,
  splitStringsChunkLength: 10,
});
```

### heavy 覆盖项

```javascript
{
  stringArrayEncoding: ['rc4'],
  stringArrayWrappersCount: 2,
  controlFlowFlatteningThreshold: 0.75,
  deadCodeInjection: true,
  deadCodeInjectionThreshold: 0.4,
  selfDefending: true
}
```

## 配置区明文保留

自动化脚本默认保留文件顶部用户配置、环境变量说明、cron 注释和公告信息。

```text
[clear header: cron/env/account/config]
[obfuscated business logic IIFE]
```

规则：
- 不混淆 `require()` 模块名、环境变量名、用户需修改的 URL/token 占位符。
- 青龙脚本保留环境变量说明、依赖说明和 README 运行说明。
- 可变账号、代理、通知配置放明文；签名/请求/业务流程可混淆。

## 交付产物

```text
脚本名.obfuscated.js
脚本名.original.backup.js
obfuscation-report.md
```

报告至少包含：源文件、输出文件、强度、保留明文范围、依赖、验证命令、体积变化、已知限制。

## 验证

- `node --check 输出.js` 必须通过。
- 如果原脚本支持 dry-run/help，分别运行原版与混淆版比对关键输出。
- 如果需要网络凭据，使用 mock/dry-run，不在验证中暴露真实 token。
- 失败时降低强度：heavy → medium → light，定位是自防御、控制流还是字符串编码导致。

## Related Skills

- `automation-architect`：上层路由与质量门。
- `automation-script-dev-js`：先开发/整理 JS 自动化脚本，再交给本技能保护。
- `js-script-deobfuscator`：混淆结果审计或逆向验证。
- `python-obfuscator-pro`：Python 脚本保护。
