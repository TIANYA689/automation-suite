# 环境伪装差异表

用途：脚本读取浏览器环境值时，快速定位"缺什么、补什么、按什么顺序补"。

完整补丁实现见 `js-script-deobfuscator` 技能的 `skills/js-script-deobfuscator/references/env-emulation-jsdom.md`；本页是差异速查。

## 分级

### 致命级——缺失即被拒绝

| 检测项 | 真实浏览器 | 纯 Node/jsdom 默认 | 检测原理 |
|---|---|---|---|
| `Function.prototype.toString` | 含 `[native code]` | 暴露实际 JS 源码 | 原生函数与 JS 函数形态不同 |
| `navigator.plugins.length` | 典型 5 | 0 | 插件数为 0 等价无头 |
| `navigator.webdriver` | `false` | `undefined` | 自动化标志 |
| `document.hasFocus()` | `true` | `false` | 无窗口焦点 |
| DOM 布局尺寸 | 非零 | 0 | 无布局引擎 |

### 高危级——可能参与指纹哈希

| 检测项 | 真实浏览器 | 默认 |
|---|---|---|
| `Object.prototype.toString.call(document)` | `[object HTMLDocument]` | `[object Document]` |
| `window.chrome` | 对象 | `undefined` |
| `navigator.userAgentData` | 对象 | `undefined` |
| `performance.timing` / `navigation` | 完整对象 | 缺失 |
| `Symbol.toStringTag` | 正确标签 | 不正确 |

### 中危级——API 存在性

约 30+ 项：`Notification`、`Worker`、`SharedWorker`、`RTCPeerConnection`、`AudioContext`、`OfflineAudioContext`、`fetch`、`matchMedia`、`indexedDB`、`caches`、`visualViewport`，以及 `navigator.connection`、`getBattery`、`deviceMemory`。

## 补丁顺序（不可颠倒）

```text
1. native 标记三层防御   ← 最高优先级，其他补丁函数也要纳入
2. navigator 补丁
3. window 补丁
4. document + performance 补丁
5. DOM 布局属性
6. Symbol.toStringTag 修复
```

**每一步修完立即验证**，不要一次改完再调。

## native 标记的格式陷阱

`Function.prototype.toString` 的期望输出**随内核不同而不同**：

| 内核 | 格式 |
|---|---|
| Chromium | 单行：`function name() { [native code] }` |
| Firefox | 多行：函数头 + 换行缩进 + `[native code]` + 换行 + 右花括号 |

用 Firefox 内核浏览器采集基准却按 Chromium 单行格式补，**等于没补**。这是本领域最高频的踩坑。

## 采集纪律

- 必须**分批**采集，单次代码太长会报错。建议按 navigator / screen+window / document+performance+toString / DOM+Canvas+WebGL 分四批。
- 通用环境采集工具**不覆盖** `toString` 系列、`Symbol.toStringTag`、DOM 布局等细粒度项，必须手动采集。
- 若目标把函数或状态挂在页面主世界，采集时必须显式进入主世界上下文；先从帧列表确认实际帧。
- 采集的基线决定补丁目标，**基线错了后面全错**。先确认采集浏览器能通过目标站检测。

## 补丁时机

**补丁必须在目标脚本加载之前完成。** 目标脚本常在加载时就读取环境值，补丁打晚了无效。

Hook 的安装顺序同样关键——决定能否截获最终 URL。

## 验证要点

在 jsdom 的 window 上下文内执行验证代码（目标脚本看到的就是这个上下文）。检查项与期望值见上表"真实浏览器"列。

**静默拒绝识别**：HTTP 200 + 空 body。不是网络问题，是环境指纹不匹配。回差异表重查致命级。

**间歇性失败**：检查时间相关环境值（`performance.now` 起始偏移、时区）。

## 相关条目

- JSVMP 双路径：`kb/js-reverse/techniques/03-jsvmp-paths.md`
- 改写验证：`kb/js-reverse/techniques/05-transform-validation.md`
