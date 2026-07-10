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
