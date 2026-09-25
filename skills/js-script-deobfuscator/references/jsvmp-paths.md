# JSVMP 双路径方法论

JSVMP（JS 虚拟机保护）的核心特征：把业务逻辑编译成自定义字节码，由一段解释器在运行时执行。因此**静态阅读源码拿不到算法**，必须转向运行时观测或环境复现。

两条路径，选错会浪费数小时。

## 路径选择

| 判断 | 走哪条 |
|---|---|
| 签名通过可 hook 的原语（CryptoJS、atob、标准哈希）走 | 路径 A：算法追踪 |
| 需要精确定位签名函数的输入输出边界 | 路径 A |
| SDK 与环境强绑定（环境指纹参与哈希） | 路径 B：环境复现 |
| VM 劫持了请求链路（XHR/fetch 拦截器），签名在内部完成 | 路径 B |
| 算法不可提取（字节码保护 + 自定义算法） | 路径 B |
| jsdom 能加载并执行目标脚本 | 路径 B（优先） |
| 脚本强依赖真实浏览器引擎特性 | 路径 A |

**经验值**：路径 B 通常比路径 A 快约一个数量级。默认先评估路径 B 的可行性。

---

## 路径 A：算法追踪（四板斧）

核心方法论：**从 I/O 两端夹逼 + 中间层插桩 + 选择性源码 tap**。按当前问题选用所需步骤，不要求四斧全开。

### 四板斧总览

| 板斧 | 名称 | 擅长 | 不擅长 |
|---|---|---|---|
| 第一斧 | Hook I/O | 请求链路、动态 Cookie、加密原语入口 | VM 内部自实现的哈希/AES |
| 第二斧 | 插桩解释器 | 可定位且可访问函数的调用链 | 闭包内部函数不可直接 Hook；高频日志开销大 |
| 第三斧 | 日志分析 | 从已捕获 I/O 推断公式 | 未捕获的数据、预览占位与容量限制 |
| 第四斧 | 源码级插桩 | VM 内部属性与调用位置 | 语法/语义跳过、体积限制、完整性检测 |

前三斧诊断"VM 看外界"（入口）与"外界看 VM"（出口）；第四斧诊断"VM 看自己"——适用于算法全部封装在字节码分发循环里的场景。

### 8 步快速流程

```text
步骤 1：确认是否 VMP
  搜索 switch，核对字节码来源、虚拟 PC / 寄存器 / 操作数栈的变化，
  以及分发循环真实执行的证据。仅凭 case 数量无法区分 VM 与 CFF。

步骤 2：按需装运行时探针
  透明模式的解释器探针，只在当前问题需要时安装。

步骤 3：按需装出口 Hook
  cookie 预设 + XHR 预设（设为持久）。

步骤 4：装源码级插桩（核心）
  按 AST 模式安装，显式限定过滤范围（如只观察字节码对象路径），
  关闭不需要的调用改写。

步骤 5：让所有探针先于 VM 生效
  重新加载；检查运行时标记与业务结果，而不只看"改写文件数 > 0"。

步骤 6：触发目标操作
  翻页、搜索、登录等，等待业务完成信号。

步骤 7：读插桩日志
  属性访问热键按频次倒排 → 告诉你 VM 读了哪些环境属性；
  方法调用热键格式为 类型.方法名 → 提示算法归属；
  函数调用热键 → 找有没有 btoa/atob/encodeURIComponent 之类熟面孔。

步骤 8：交叉印证
  读取页面侧日志 + Cookie 来源分析；对照当前请求与原始结果。
  注意：属性访问不等于参与哈希的证明。
```

### 分层追踪函数调用

```text
粗粒度：追踪解释器主函数         → 看整体调用频次与时机
中粒度：追踪子 handler           → 看操作码分发
细粒度：追踪特定加密函数         → 看具体输入输出
```

**必须设置捕获上限**。高频调用函数每秒数千次，不设上限会直接把日志缓冲打爆。

### 反向追踪法（处理海量日志最高效）

```text
1. 从已知签名值出发（如 sign=abc123）
2. 在所有日志中搜索该值首次出现的位置
3. 从该位置反向追踪：
   - 该值由哪个函数生成？
   - 该函数的输入是什么？
   - 输入又来自哪里？
4. 逐层追踪直到找到原始明文输入
```

### 路径 A 失败诊断

| 失败表现 | 可能原因 | 应对 |
|---|---|---|
| 改写文件数 > 0 但运行时标记为假 | 目标响应、执行世界、加载时序或解析问题 | 核对目标上下文与错误，再对照原始产物 |
| 运行时标记存在但日志为空 | 帧、标签/过滤器、未触发、跳过或容量限制 | 查业务信号与日志诊断，不自动重放操作 |
| 热键很少 | 所选范围有限、未命中关键位置或观测不完整 | 结合源码与容量状态判断，不按数量断言覆盖不足 |
| 签名值不一致 | 输入/编码、时间随机值、状态、实现差异或观察者效应 | 按输入到输出定位首个偏差 |
| 请求反复被拒（如 412） | 挑战流程、鉴权、网络或观测影响 | 对照无 Hook 基线，不直接归因于签名或厂商 |
| AST 失败后回退到保守模式 | 解析依赖、资源限制、复杂语法不在白名单 | 查跳过原因；保留明确跳过记录 |
| 改写触发完整性校验 | 任何源码变化都可能被检测 | 停止该改写，评估不改源码的观测方式 |

---

## 路径 B：环境复现（六步法）

核心思想：**不分析 VM 内部算法，而是在 jsdom 中完整运行原始 JSVMP 字节码**，通过"采集 → 对比 → 补丁"让 VM 认为自己运行在真实浏览器中，直接截获生成的签名值。

### 步骤 0.5：确认签名函数入口（不可跳过）

跳过此步的典型后果：只 Hook 了 XHR 漏掉 fetch 通道、未传必要初始化配置导致拦截器不触发、误以为签名函数不存在而走了更复杂的路径。

搜索以下关键词判断入口类型：

| 搜索目标 | 含义 | 后续策略 |
|---|---|---|
| 导出的签名函数名 | 可直接调用 | 优先直接调用，拦截器作为备选 |
| `XMLHttpRequest.prototype.open` | 劫持 XHR | Hook XHR.open |
| `window.fetch` | 劫持 fetch | 需同时 Hook 两个通道 |
| 初始化配置对象名（如 cacheOpts 之类） | 配置驱动初始化 | 必须传入该配置才能注册业务路径 |

**双通道**（XHR + fetch）必须同时 Hook，只 Hook 一个会漏签名。

### 步骤 1：采集真实浏览器环境基线

用反检测浏览器（或任何能通过目标站检测的浏览器）采集完整环境指纹，作为补丁基准。

采集必须**分批**，单次代码太长会报错。建议分四批：

| 批次 | 内容 | 项数 |
|---|---|---|
| A | `navigator` 属性（userAgent/platform/language/languages/cookieEnabled/webdriver/hardwareConcurrency/plugins.length/userAgentData/connection 等） | 约 24 |
| B | `screen` + `window`（尺寸、availWidth/Height、colorDepth、devicePixelRatio、chrome 对象、30+ API 存在性） | 约 25 |
| C | `document` + `performance` + `toString`（hasFocus/readyState/visibilityState、`Function.prototype.toString` 结果、`Object.prototype.toString.call` 标签、`Symbol.toStringTag`） | 约 28 |
| D | DOM 布局 + Canvas + WebGL + Audio（offsetHeight/Width、getBoundingClientRect、canvas toDataURL 长度、WebGL vendor/renderer） | 指纹类 |

**关键**：批次 C 的 `toString` 系列是环境伪装的第一杀手，必须采集。通用环境采集工具通常不覆盖这些细粒度项。

若 SDK 把函数或状态挂在页面主世界，采集时必须显式进入主世界上下文；先从帧列表确认实际帧，避免把隔离上下文的 `undefined` 当成环境缺项。

### 步骤 2：在 jsdom 中执行相同采集

```javascript
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
  url: '目标URL',
  pretendToBeVisual: true,
  runScripts: 'dangerously'
});
const win = dom.window;
// 在 win.eval() 中运行与步骤 1 完全相同的采集脚本
```

要点：

- `url` 必须设为目标 URL（影响 `document.URL` / `document.domain`）。
- `pretendToBeVisual: true` 使 `requestAnimationFrame` 可用。
- `runScripts: 'dangerously'` 是环境伪装的必要前提。

### 步骤 3：Diff 与严重性分级

| 级别 | 检测项 | 浏览器值 | jsdom 默认值 | 后果 |
|---|---|---|---|---|
| 致命 | `Function.prototype.toString` | 含 `[native code]` | 暴露 jsdom 真实 JS 源码 | 直接暴露非浏览器 |
| 致命 | `navigator.plugins.length` | 通常 5 | 0 | 插件数为 0 = 非浏览器 |
| 致命 | `navigator.webdriver` | `false` | `undefined` | webdriver 检测命中 |
| 致命 | `document.hasFocus()` | `true` | `false` | 焦点检测命中 |
| 致命 | DOM `offsetHeight/Width` | 非零 | 0 | 布局检测命中 |
| 高危 | `Object.prototype.toString.call(document)` | `[object HTMLDocument]` | `[object Document]` | 可能参与指纹哈希 |
| 高危 | `window.chrome` | 对象 | `undefined` | 同上 |
| 高危 | `navigator.userAgentData` | 对象 | `undefined` | 同上 |
| 高危 | `performance.timing/navigation` | 完整对象 | 缺失 | 同上 |
| 中危 | 30+ API 存在性 | 存在 | 缺失 | 存在性检测失败 |

### 步骤 4：补丁优先级

按顺序修，**每修一项立即验证**：

1. **native 标记三层防御**（最高优先级）
   - 第一层：用 WeakSet 记录所有需要伪装的函数引用。
   - 第二层：按源码模式正则匹配 native 形态。
   - 第三层：实例级覆写 `toString` 兜底。
   - **格式必须匹配基准浏览器**：Chromium 单行；Firefox 多行带换行与缩进。
2. **navigator 补丁**：plugins 完整对象树（含 length）、webdriver 置 false、userAgentData、connection；每个属性经 native 标记处理。
3. **window 补丁**：chrome 对象、30+ API 存根（Notification/Worker/SharedWorker/RTCPeerConnection/AudioContext/OfflineAudioContext/fetch/matchMedia/indexedDB/caches/visualViewport 等）。
4. **document + performance 补丁**：hasFocus 恒真、readyState 为 complete、visibilityState 为 visible、hidden 为 false、performance.timing 与 navigation 完整。
5. **DOM 布局属性**：offset/client/scroll 系列返回非零值，`getBoundingClientRect` 返回合理矩形。
6. **`Symbol.toStringTag` 全面修复**：document/screen/navigator/window 的标签逐一设对。

### 步骤 5：内部验证

验证代码必须在 **jsdom 的 window 上下文内**执行，因为目标脚本看到的就是这个上下文。

```javascript
const result = win.eval(`JSON.stringify({
  fnToString: document.createElement.toString(),
  plugins: navigator.plugins.length,
  webdriver: navigator.webdriver,
  hasFocus: document.hasFocus(),
  chromeExists: typeof window.chrome,
  docTag: Object.prototype.toString.call(document),
  offsetTest: (function(){
    var d = document.createElement('div');
    d.style.cssText = 'width:100px;height:100px';
    document.body.appendChild(d);
    var h = d.offsetHeight;
    document.body.removeChild(d);
    return h;
  })()
})`);
```

| 检测项 | 期望 | 不通过时修哪个模块 |
|---|---|---|
| `createElement.toString()` | 含 `[native code]` | native 标记三层防御 |
| `navigator.plugins.length` | 5 | navigator 补丁 |
| `navigator.webdriver` | `false` | navigator 补丁 |
| `document.hasFocus()` | `true` | document 补丁 |
| `typeof window.chrome` | `'object'` | window 补丁 |
| `Object.prototype.toString.call(document)` | `'[object HTMLDocument]'` | toStringTag 修复 |
| `div.offsetHeight` | `> 0` | DOM 布局属性 |

### 步骤 6：端到端验证

```text
1. 在 jsdom 中加载完整 JSVMP 脚本并触发签名生成
2. 用截获的签名值发起真实接口请求
3. 确认返回有效数据（非空 body / 非错误码）
4. 连续多次请求验证稳定性（建议至少 5 次）
```

**服务端可能静默拒绝**：返回 HTTP 200 + 空 body，不报错。这是环境检测失败的典型信号——签名格式对了但环境指纹不匹配。回到步骤 3 重查致命级差异。

### 路径 B 常见坑

| 坑 | 现象 | 解决 |
|---|---|---|
| Canvas 存根不真实 | 指纹哈希不匹配 | 用真实 Canvas 实现，或从真实浏览器采集后硬编码返回值 |
| native 标记格式错 | `toString` 输出格式与基准不符 | 改成与基准浏览器一致的格式 |
| `Symbol.toStringTag` 遗漏 | `[object Document]` 而非 `[object HTMLDocument]` | 用 `Object.defineProperty` 补 |
| 补丁打晚了 | 目标脚本加载时已读取环境值，补丁无效 | 确保补丁在任何脚本执行之前完成；Hook 安装顺序同样关键 |
| 服务端静默拒绝 | HTTP 200 + 空 body | 回差异表重查致命级 |
| 初始化配置未传 | 拦截器不触发，签名不生成 | 检查初始化调用是否包含必需配置项 |

### 路径 B 的还原策略对照

| 情况 | 策略 |
|---|---|
| VM 劫持 XHR，在拦截器中追加签名 | 喂入-截出：在 jsdom 内发请求，拦截器自动追加签名，Hook 截获 |
| VM 导出签名函数到全局 | 直接调用导出函数 |
| VM 需要预热初始化 | 依次加载所有脚本 → 调用初始化 → 再触发签名 |
| VM 需要配置驱动初始化 | 传入配置 → 注册业务路径 → 拦截器才触发 |
| 双签名（URL 参数 + header） | 同时 Hook `open`（URL 签名）与 `setRequestHeader`（header 签名） |

---

## 双路径通用纪律

1. **VM 解释器本身不是目标，签名函数的 I/O 才是目标。**
2. **先 Hook 出口确定"要什么"，再 Hook 入口确定"给了什么"。**
3. **所有探针都需评估观察者效应**：Hook/Proxy 可改变原生性与对象身份；源码改写可被完整性、堆栈与耗时检测。
4. **日志只支持已捕获范围内的结论**：空结果不能当作"未执行"的证据。
5. **本地样本通过不等于线上站点成功**；必须用新输入、新状态回归。
6. **无法完成时记录事实、已尝试路径与剩余依赖，不伪造签名或成功响应。**
