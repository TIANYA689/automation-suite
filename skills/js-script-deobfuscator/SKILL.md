---
name: js-script-deobfuscator
description: JavaScript/Node.js 脚本解混淆与可读化。用于分析 obfuscator.io、javascript-obfuscator、JScrambler、自定义 _0x 字符串数组、RC4/Base64、eval/Function 包装、控制流扁平化、死代码注入、代理函数、自防御代码，并输出可审计的解密版 JS、解码表、证据和运行说明。自动化脚本被混淆时优先与 automation-script-dev-js 协同。
---

# JavaScript Script Deobfuscator

目标：把不可读 JS 还原为可审计、可运行、可维护的代码，而不是只“美化缩进”。参照 open-reverselab 风格：先分类、保留证据、工具优先、产物落盘、结论可复查。

## 启动协议

1. 保护原文件：复制到工作目录后再分析；不要覆盖原始脚本。
2. 建立任务上下文：记录原文件路径、大小、哈希、混淆信号、输出目录。
3. 并行两条路径：
   - 静态路径：AST/正则/字符串数组/控制流结构识别。
   - 沙箱路径：Node `vm` 隔离执行解码基础设施，mock I/O。
4. 输出落盘：最终脚本、解码表、证据摘要放到当前项目 `exports/`、`reports/`、`outputs/` 或用户指定目录。

## 识别矩阵

| 信号 | 判断 | 动作 |
|---|---|---|
| `_0x` 前缀变量、数组函数、旋转 IIFE | obfuscator.io/javascript-obfuscator | 提取 array function、rotation、decoder |
| `atob`、Base64 大字符串、`eval()` | eval packer | 静态取 payload，替换执行为 dump |
| RC4 解码函数、缓存对象 | stringArrayEncoding rc4 | 复刻 RC4 或调用 decoder 扫描索引 |
| `'1|4|2|0'.split('|')` + switch | 控制流扁平化 | 按 order 重排 case |
| object helper `{a:function(x,y){...}}` | 代理函数 | 内联为运算符/函数调用 |
| `toString().search('(((.+)+)+)$')` | selfDefending | 在副本中移除或 stub |
| 单行巨大脚本、无语义变量 | 压缩+混淆 | 先 beautify，再识别结构 |

## 工作流

### 1. 结构定位

按顺序标注：

```text
外层定义 → 字符串数组函数 → 数组旋转 IIFE → decoder 函数 → alias → main IIFE → 业务逻辑
```

若存在多层 decoder，分别命名为 `decoder_layer_1`、`decoder_layer_2`，不要混用索引。

### 2. 安全沙箱优先

使用 Node `vm` 只执行“解码基础设施”，mock 掉网络、文件、进程退出和定时器。

```javascript
const vm = require('vm');
const ctx = vm.createContext({
  parseInt, decodeURIComponent, String, Math, RegExp, JSON, Array, Object, Number,
  console: { log(){}, warn(){}, error(){} },
  setTimeout(){ return 0 }, setInterval(){ return 0 }, clearInterval(){},
  process: { env:{}, on(){}, exit(){} },
  require(name){ return new Proxy(function(){}, { get(){ return async()=>({data:{}}) }, apply(){ return {data:{}} } }); }
});
vm.runInContext(modifiedDecoderOnlyCode, ctx, { timeout: 15000 });
```

规则：
- 不运行真实业务入口，例如 `start()`、`main()`、`login()`。
- 把最终 `exec/eval/startFullTask()` 改成 `this.__exported = {...decoderFns}`。
- decoder 扫描用有界范围，例如 `-10000..10000`，记录异常率和有效字符串数。

### 3. 静态回退

沙箱失败时，静态恢复：

1. 拼接显式字符串片段，如 `'https:' + '//api'`。
2. 标记 HTTP 方法、header、path、状态码、中文日志。
3. 展开 proxy object：`helper.eq(a,b)` → `a === b`。
4. 重排 flattening switch。
5. 删除死分支，但保留“不确定分支”注释。

### 4. 重建清洁版

输出 `{原名}_解密版.js`，要求：

- 文件头写明识别到的混淆类型、解码方法、依赖和不确定项。
- 移除 `_0x` 数组、decoder、无效 self-defending 和明显死代码。
- 变量/函数重命名为英文语义名，业务注释用中文。
- 自动化脚本类输出应可继续交给 `automation-script-dev-js` 做结构化改造。

## 证据模板

```markdown
# JS Deobfuscation Report

- Source:
- SHA256:
- Obfuscation:
- Decoder functions:
- Decoded strings:
- Reconstructed files:
- Uncertain points:
- Validation:
```

## 失败处理

| 情况 | 处理 |
|---|---|
| 沙箱超时 | 缩小到 decoder-only，移除 self-defending 后重试 |
| decoder 依赖动态状态 | 记录状态变量初值，模拟线性更新 |
| 输出仍是 eval 包装 | 继续逐层 dump，直到源码或 bytecode |
| 无法完全还原 | 输出 API/配置/控制流证据与人工复核点 |

## Related Skills

- `automation-architect`：上层路由与交付检查。
- `automation-script-dev-js`：把解密版改造成青龙/Node 自动化脚本。
- `js-script-obfuscator`：本技能的逆向配套。
- `python-script-decryptor`：Python 包装/加密脚本解密。
