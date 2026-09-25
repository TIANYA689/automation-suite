# jsdom 环境伪装

当 JS 脚本（尤其是 VM 保护）在解码或签名时读取浏览器环境值，纯 Node 沙箱会失败。本文件给出完整的差异表、补丁优先级与验证方法。

**核心原则**：补丁必须在目标脚本加载**之前**完成。加载顺序决定成败。

## 一、为什么要伪装而不是"提取算法"

当 VM 把环境指纹直接参与哈希时，算法本身没有意义——你必须提供相同的环境值才能得到相同的输出。此时"让 VM 认为自己跑在真实浏览器里"比"读懂 VM 的算法"成本低一个数量级。

适用条件：

- 环境指纹参与签名哈希
- VM 劫持了请求链路，签名在内部完成
- 算法不可直接提取（字节码保护 + 自定义算法）
- jsdom 能成功加载并执行目标脚本

## 二、差异分级

### 致命级——缺失即被拒绝

| 检测项 | 真实浏览器 | jsdom 默认 | 检测原理 |
|---|---|---|---|
| `Function.prototype.toString` | 含 `[native code]` | 暴露 jsdom 实际 JS 代码 | 原生函数与 JS 函数的源码形态不同 |
| `navigator.plugins.length` | 典型 5 | 0 | 插件数为 0 等价于无头环境 |
| `navigator.webdriver` | `false` | `undefined` | 自动化标志 |
| `document.hasFocus()` | `true` | `false` | 无窗口焦点 |
| DOM `offsetHeight/offsetWidth` | 非零 | 0 | 无布局引擎 |

### 高危级——可能参与指纹哈希

| 检测项 | 真实浏览器 | jsdom 默认 |
|---|---|---|
| `Object.prototype.toString.call(document)` | `[object HTMLDocument]` | `[object Document]` |
| `window.chrome` | `{runtime: {...}, ...}` | `undefined` |
| `navigator.userAgentData` | `{brands: [...], ...}` | `undefined` |
| `performance.timing` / `performance.navigation` | 完整对象 | 缺失 |
| `Symbol.toStringTag` | 正确标签 | 不正确 |

### 中危级——API 存在性检测

约 30+ 项，包括 `Notification`、`Worker`、`SharedWorker`、`RTCPeerConnection`、`AudioContext`、`OfflineAudioContext`、`fetch`、`matchMedia`、`indexedDB`、`caches`、`visualViewport`，以及 `navigator.connection`、`navigator.getBattery`、`navigator.deviceMemory`。

## 三、补丁优先级

按顺序修，**每修一项立即验证**，不要一次性全改完再调试。

### ① native 标记三层防御（最高优先级）

**问题**：jsdom 所有 DOM 方法的 `toString()` 会暴露实际 JS 代码，一眼就穿。

**方案**：WeakSet + 源码正则 + 实例覆写 + 原型链扫描。

```text
第一层：WeakSet 记录所有需要伪装的函数引用
第二层：源码模式正则匹配，识别"看起来像原生函数"的形态
第三层：实例级覆写 toString 作为兜底
补充：  扫描常见原型链（Document/Element/EventTarget/Window/Navigator/Screen 等），
        把遗漏的方法也纳入 WeakSet
```

**格式差异必须匹配基准浏览器**：

| 内核 | 输出格式 |
|---|---|
| Chromium | `function createElement() { [native code] }`（单行） |
| Firefox | `function createElement() {` + 换行 + 缩进 + `[native code]` + 换行 + `}` |

**这是最容易踩的坑**：用 Firefox 内核浏览器采集基准，却按 Chromium 单行格式打补丁，等于没补。必须先确认采集基准的内核。

### ② navigator 补丁

- `plugins`：构造完整的 PluginArray / Plugin / MimeType 对象树，`length` 与基准一致。
- `webdriver`：置 `false`。
- `userAgentData`：按基准构造 `{brands, mobile, platform}`（Firefox 不支持，需按基准决定是否补）。
- `connection`：`{effectiveType, downlink, rtt}`。
- 每个属性都要经过 native 标记处理。

### ③ window 补丁

- `chrome` 对象：按基准构造 `{runtime: {}, app: {}, ...}`。
- 30+ API 存根：`Notification` / `Worker` / `SharedWorker` / `RTCPeerConnection` / `AudioContext` / `OfflineAudioContext` / `fetch` / `matchMedia` / `indexedDB` / `caches` / `visualViewport` 等。
- 每个存根同样经过 native 标记处理。

### ④ document + performance 补丁

- `hasFocus()` 恒返回 `true`。
- `readyState` 为 `"complete"`，`visibilityState` 为 `"visible"`，`hidden` 为 `false`。
- `performance.timing` 构造完整对象；`performance.navigation` 为 `{type: 0, redirectCount: 0}`。

### ⑤ DOM 布局属性

- `offsetHeight` / `offsetWidth` / `clientHeight` / `clientWidth` / `scrollHeight` / `scrollWidth` 返回非零值。
- `getBoundingClientRect()` 返回合理矩形。

### ⑥ `Symbol.toStringTag` 修复

- `document` → `"HTMLDocument"`（而非 `"Document"`）
- `screen` → `"Screen"`
- `navigator` → `"Navigator"`
- `window` → `"Window"`

用 `Object.defineProperty` 设置，`configurable: true`。

## 四、内部验证清单

验证代码必须在 jsdom 的 window 上下文内执行。

| 检测项 | 期望值 | 不通过时修哪个模块 |
|---|---|---|
| `document.createElement.toString()` | 含 `[native code]` 且格式匹配基准 | native 标记三层防御 |
| `navigator.plugins.length` | 与基准一致（常见 5） | navigator 补丁 |
| `navigator.webdriver` | `false` | navigator 补丁 |
| `document.hasFocus()` | `true` | document 补丁 |
| `typeof window.chrome` | `'object'` | window 补丁 |
| `Object.prototype.toString.call(document)` | `'[object HTMLDocument]'` | toStringTag 修复 |
| `div.offsetHeight` | `> 0` | DOM 布局属性 |

## 五、端到端验证

```text
1. 在 jsdom 中加载完整目标脚本，触发签名生成
2. 用截获的签名值发起真实接口请求
3. 确认返回有效数据（非空 body、非错误码）
4. 连续多次请求验证稳定性（至少 5 次）
```

**静默拒绝的识别**：HTTP 200 + 空 body。这不是网络问题，而是环境指纹不匹配——签名格式对了但环境值不对。回到差异表重查致命级。

**间歇性失败**：检查是否有时间戳相关的环境值未补齐（如 `performance.now` 起始偏移、`Date` 时区）。

## 六、内核差异对照

| 检测项 | Chromium 格式 | Firefox 格式 |
|---|---|---|
| native `toString` | 单行 | 多行带换行缩进 |
| `navigator.vendor` | `"Google Inc."` | `""` |
| `navigator.productSub` | `"20030107"` | `"20100101"` |
| `window.chrome` | 完整对象 | `undefined`（需按基准决定是否补） |
| `navigator.userAgentData` | 完整对象 | `undefined` |

**原则**：以实际采集基准为准，不要凭"目标站点像是给 Chrome 写的"就补 Chrome 特征。若服务端明确校验 Chrome 特征，再额外补。

## 七、补丁与观测的边界

- 环境伪装会改变运行环境，**必须与真实浏览器基线对照**，确认没有引入新的行为差异。
- 补丁代码本身可能被检测（例如通过 `Function.prototype.toString` 检查补丁函数）。因此补丁函数必须纳入 native 标记处理。
- 不要把"jsdom 里跑通"当作"线上可稳定运行"；必须用真实请求回归。
- 若目标脚本使用了 jsdom 无法提供的引擎特性，停止补丁堆叠，转向路径 A。

## 八、最小可用补丁顺序（速查）

```text
1. 采基准（分批，含 toString 系列）
2. jsdom 加载，跑同一份采集代码
3. diff 并分级
4. 修致命级 → 验证
5. 修高危级 → 验证
6. 修中危级 → 验证
7. 加载目标脚本，触发签名
8. 真实请求回归（≥5 次）
9. 若被静默拒绝 → 回第 3 步
```
