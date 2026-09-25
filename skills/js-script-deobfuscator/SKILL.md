---
name: js-script-deobfuscator
description: JavaScript/Node.js 脚本解混淆与可读化。用于分析 obfuscator.io、javascript-obfuscator、JScrambler、自定义 _0x 字符串数组、RC4/Base64、eval/Function 包装、控制流扁平化、死代码注入、代理函数、自防御代码、AAEncode/JJEncode/JSFuck、自定义 VM 与 JSVMP 虚拟机保护，并输出可审计的解密版 JS、解码表、证据和运行说明。支持 jsdom/vm 环境伪装、Hook 与反调试对抗、改写语义等价验证。自动化脚本被混淆时优先与 automation-script-dev-js 协同。
---

# JavaScript Script Deobfuscator

目标：把不可读 JS 还原为**可审计、可运行、可维护**的代码，而不是只"美化缩进"。

三条铁律：

1. **先分类，再动手**。混淆类型决定工具路径，走错路径比走得慢更糟。
2. **改写必须验证语义等价**。AST 能定位结构，不保证行为不变。
3. **保留原样本**。原件不动，候选版本另存，diff 与哈希分开保存。

## 启动协议

1. **保护原文件**：复制到工作目录后再分析；记录原文件路径、大小、SHA-256。绝不覆盖原始脚本。
2. **建立任务上下文**：输出目录、混淆信号、已有样本（成功/失败各一份更好）。
3. **判定混淆类型**（见下节），据此选择路径。类型判断错误是最大的时间浪费来源。
4. **双路径并行**：
   - 静态路径：AST / 字符串数组 / 控制流结构 / 常量折叠。
   - 沙箱路径：Node `vm` 只跑解码基础设施，mock 掉网络、文件、进程与定时器。
5. **产物落盘**：解密版脚本、解码表、证据摘要、验证结果、未解决项，落到 `exports/deobfuscation/`、`reports/` 或用户指定目录。

## 混淆类型判定矩阵

| 信号 | 类型 | 首选动作 |
|---|---|---|
| `_0x` 前缀变量、十六进制字符串数组、数组旋转 IIFE | OB 混淆（obfuscator.io 系） | 提取 array function + rotation + decoder |
| `'1\|4\|2\|0'.split('\|')` + `switch(state)` 循环 | 控制流平坦化（CFF） | 按 order 重排 case，恢复顺序 |
| `eval(function(p,a,c,k,e,d){...})`、`new Function('return ...')` | eval / Function 打包 | 拦截执行改为 dump，逐层解包 |
| 全为日文颜文字字符 | AAEncode | 直接执行或把执行改为输出 |
| 全为 `$` 与特殊字符 | JJEncode | 同上 |
| 仅使用 `[]()!+` 六种字符 | JSFuck | 同上 |
| 超大数组当"字节码" + 解释器循环 + 函数查找表 | 自定义 VM | **不要反编译字节码**，走 I/O 定位 |
| 200KB+ 单文件、无意义命名、改写浏览器原生 API、操作码表 | JSVMP | 走双路径决策（见下节） |
| object helper `{a:function(x,y){...}}` | 代理函数 | 内联为运算符/函数调用 |
| `toString().search('(((.+)+)+)$')` | 自防御（selfDefending） | 在副本中移除或 stub |
| 单行巨大脚本、无语义变量 | 压缩 + 混淆 | 先 beautify，再识别结构 |

详细识别特征、还原步骤与工具路径见 [混淆类型识别与还原](references/obfuscation-taxonomy.md)。

## JSVMP 双路径决策

遇到 JSVMP 时，**先选路径再动手**。选错会浪费数小时。

| 路径 | 适用条件 | 思路 | 相对成本 |
|---|---|---|---|
| **路径 A：算法追踪** | 签名通过可 hook 的原语（CryptoJS/atob/MD5）走；需要定位 I/O 边界 | 四板斧：Hook I/O → 插桩解释器 → 日志分析 → 源码级插桩 | 较高 |
| **路径 B：环境复现** | SDK 与环境强绑定、算法不可提取、jsdom 能加载脚本 | 在 jsdom 里跑原始 VM，采集→对比→补丁，直接截获签名 | 较低 |

**路径 B 通常比路径 A 快约一个数量级**，但前提是 jsdom 能加载并执行目标脚本。若脚本强依赖真实浏览器引擎特性（原生 trace、特定 Gecko 行为），路径 B 会卡住，转路径 A。

两条路径的完整方法论、四板斧配置、环境差异分级、补丁优先级见 [JSVMP 双路径方法论](references/jsvmp-paths.md)。

**核心纪律**：VM 解释器本身不是目标，签名函数的输入输出才是目标。不要试图反编译字节码。

## 工作流

### 1. 结构定位

按顺序标注，不要跳步：

```text
外层定义 → 字符串数组函数 → 数组旋转 IIFE → decoder 函数 → alias → main IIFE → 业务逻辑
```

多层 decoder 分别命名 `decoder_layer_1`、`decoder_layer_2`，**不要混用索引**。

### 2. 安全沙箱优先

用 Node `vm` 只执行"解码基础设施"，mock 掉网络、文件、进程退出与定时器。

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

- **不运行真实业务入口**（`start()`、`main()`、`login()`）。
- 把最终 `exec/eval/startFullTask()` 改成 `this.__exported = {...decoderFns}`。
- decoder 扫描用**有界范围**，记录异常率与有效字符串数，不要无限枚举。
- `vm` 不是执行不可信代码的安全边界，只用于已授权的样本。

### 3. 环境伪装（脚本强依赖浏览器环境时）

当解码或签名逻辑读取 `navigator` / `screen` / `document` / `canvas` 等环境值，纯 Node 会失败。此时用 jsdom 补环境：

**核心原则**：补丁必须在目标脚本加载**之前**完成，加载顺序决定成败。

差异分三级，先修致命级：

| 级别 | 典型项 | 后果 |
|---|---|---|
| 致命 | `Function.prototype.toString` 暴露真实源码、`navigator.plugins.length = 0`、`navigator.webdriver` 为 `undefined`、`document.hasFocus()` 为 `false`、DOM 布局尺寸为 0 | 直接暴露非浏览器环境，被拒 |
| 高危 | `Object.prototype.toString.call(document)` 标签错误、缺 `window.chrome`、缺 `navigator.userAgentData`、缺 `performance.timing` | 可能参与指纹哈希 |
| 中危 | 缺失 30+ 浏览器 API（Notification/Worker/RTCPeerConnection/AudioContext/indexedDB 等） | 存在性检测失败 |

**两个高频坑**：

- `markNative` 的格式必须匹配采集基准浏览器。Chromium 单行 `function name() { [native code] }`，Firefox 多行带换行缩进，**格式不匹配等于没补**。
- 服务端可能**静默拒绝**：HTTP 200 + 空 body，不报错。这是环境检测失败的信号，回到差异表重查致命级。

完整差异表、`markNative` 三层防御、各模块补丁优先级与验证清单见 [jsdom 环境伪装](references/env-emulation-jsdom.md)。

### 4. 静态回退

沙箱与环境伪装都失败时，静态恢复：

1. 拼接显式字符串片段，如 `'https:' + '//api'`。
2. 标记 HTTP 方法、header、path、状态码、中文日志。
3. 展开 proxy object：`helper.eq(a,b)` → `a === b`。
4. 重排 flattening switch。
5. 删除死分支，但保留"不确定分支"注释。

### 5. 重建清洁版

输出 `{原名}_解密版.js`，要求：

- 文件头写明：识别到的混淆类型、解码方法、依赖、**不确定项**。
- 移除 `_0x` 数组、decoder、无效 self-defending 与明显死代码。
- 变量/函数重命名为英文语义名，业务注释用中文。
- 自动化脚本类输出应可继续交给 `automation-script-dev-js` 做结构化改造。

## 改写语义等价验证（不可跳过）

任何"看起来更干净"的改写都必须验证。**可读的解码视图只能标为分析副本，不能直接替换生产签名逻辑。**

必查的反例类型：

| 改写 | 必须保留的语义 |
|---|---|
| 常量折叠 | 双精度浮点、负零、NaN/Infinity、字符串拼接与隐式类型转换；不能为好看截短小数 |
| 按函数名替换调用 | 检查词法绑定，局部 `atob`/`parseInt` 等可能遮蔽全局同名函数 |
| 自动解码 Base64/hex 字面量 | 编码字符串可能是实际业务输入；优先加注释或另存候选视图，不直接替换其值 |
| 删除永假分支 | 保留 `var` 声明提升、块作用域与异常时机 |
| 重写成员访问/函数调用 | 保留 `this`、getter/副作用次数、求值顺序、可选链与异常行为 |
| 打印 trace | 区分原函数执行与序列化参数引发的 getter/toString 副作用 |

验证方法：

1. 原脚本、候选脚本、各自 SHA-256 与 diff **分开保存**。
2. 从原脚本的**真实执行结果**构造非空期望值，不要重新生成期望值去迎合候选输出。
3. 一次只改一条有解释的规则，先比返回值/类型/异常，再用实际业务输入确认。
4. 多个样本通过只说明这些样本一致，**不是全程序等价证明**。

详见 [改写语义验证](references/transform-validation.md)。

## 反模式与误判清单

| 误判 | 应做的检查 |
|---|---|
| 看到 `eval` 就断定是打包器 | 可能是正常业务代码或 VM 初始化 |
| 解码字符串全部是单字母乱码就当成功 | 说明字符串是动态加密的，解码路径不对 |
| AST 解析成功就认为改写完成 | 复杂语法（模板串、正则字面量、可选链、`super`、私有成员）可能被整段跳过，需检查跳过原因 |
| 沙箱跑通就认为还原正确 | 沙箱只证明解码基础设施能跑，业务语义需另验证 |
| 一个样本签名对上就交付 | 必须用**新输入**回归，且要在无浏览器环境下验证 |
| 改写后站点请求失败就归因于"环境检测" | 先按"原始输入 → 拼接 → 时间/随机值 → 中间值 → 最终签名"定位**首个偏差** |
| 高频 Hook 不影响目标 | 所有 Hook/Proxy 都可能改变原生性与对象身份，需对照无 Hook 基线 |
| 反调试没触发就认为没有反调试 | 检测可能是条件性的，换环境或换时序才会触发 |

完整清单见 [反模式与误判](references/anti-patterns.md)。

## Hook 与反调试

需要动态观测时，按"先出口、后入口"的顺序 Hook：

- **先 Hook 出口**（XHR/fetch/cookie/document.cookie）确定"要什么"。
- **再 Hook 入口**（加密原语、字符串构造）确定"给了什么"。
- 高频函数必须设**捕获上限**，否则日志量爆炸。
- 优先使用原生 API 的原型级 Hook；避免无理由的裸地址 Hook。

常见反调试（无限 `debugger`、`Function` 构造器检测、`toString` 长度校验、时间差检测、`webdriver` 检测、`Object.defineProperty` 篡改、Proxy 检测）与对抗方式见 [Hook 与反调试](references/hook-and-antidebug.md)。

**注意**：绕过反调试属于观测手段，不是目的。反调试绕过可能改变目标行为，必须与无 Hook 基线对照。

## 证据模板

```markdown
# JS Deobfuscation Report

- Source / SHA256:
- Obfuscation type:
- Detection signals:
- Decoder functions:
- Decoded strings: <数量 + 抽样>
- Reconstructed files:
- Transform validation: <原/候选 hash + diff 摘要 + 验证输入与结果>
- Environment patches: <若用了环境伪装，列出补丁项与验证结果>
- Uncertain points:
- Validation commands:
```

## 失败处理

| 情况 | 处理 |
|---|---|
| 沙箱超时 | 缩小到 decoder-only，移除 self-defending 后重试 |
| decoder 依赖动态状态 | 记录状态变量初值，模拟线性更新 |
| 输出仍是 eval 包装 | 继续逐层 dump，直到源码或字节码 |
| 环境伪装后服务端静默拒绝 | 回差异表重查致命级；HTTP 200 + 空 body 是环境失败的典型信号 |
| AST 改写被整段跳过 | 检查跳过原因；现代语法需本地解析器，复杂节点不做局部正则替换 |
| 自防御触发 | 在副本中 stub 掉完整性校验，不要试图"轻改写"绕过 |
| 无法完全还原 | 输出 API/配置/控制流证据与人工复核点，不编造结论 |

## 可验证事实清单

交付时附一份事实清单，供下次改版或同类样本快速回归：

```markdown
- [ ] <事实1，如：签名参数 X-Bogus 长度固定 28>
- [ ] <事实2，如：解码入口函数偏移 xxx>
- [ ] <事实3，如：navigator.webdriver === false 才会生成签名>
```

全部通过 → 结论仍成立，继续跑回归；部分通过 → 变化的那几条就是今天的工作范围；全部不通过 → 目标大改，但通过过的条目仍是有效不变量。

## Related Skills

- `automation-architect`：上层路由与交付检查。
- `automation-script-dev-js`：把解密版改造成青龙/Node 自动化脚本。
- `js-script-obfuscator`：本技能的逆向配套；了解混淆器的可还原成本有助于判断保护强度。
- `python-script-decryptor`：Python 包装/加密脚本解密。
- `binary-symbol-recovery`：编译后二进制（非脚本）的静态语义恢复。
- `emulated-execution-debug`：跨架构片段模拟执行。
