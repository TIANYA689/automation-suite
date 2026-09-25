# Hook 与反调试

动态观测是解混淆的补充手段：静态看不清时，靠 Hook 把运行时的输入输出捞出来。

**前提纪律**：所有 Hook 都可能改变目标行为。每装一个 Hook，都要能与无 Hook 基线对照。

## 一、Hook 顺序原则

```text
先出口，后入口。
```

1. **Hook 出口**：`XMLHttpRequest` / `fetch` / `document.cookie` / `WebSocket.send`
   → 确定"最终要产生什么"（签名值、Cookie、请求体）。
2. **Hook 入口**：加密原语、字符串构造、字符编码函数
   → 确定"给了什么"（明文、时间戳、随机数、密钥）。
3. **两端夹逼**：出口值 + 入口值 → 推断中间公式。

反过来先 Hook 入口，容易在海量调用里迷失，因为不知道哪个输入对应哪个输出。

## 二、常用 Hook 点

| 目标 | Hook 点 | 说明 |
|---|---|---|
| 请求出口 | `XMLHttpRequest.prototype.open` / `send` / `setRequestHeader` | 分别覆盖 URL 签名与 header 签名 |
| 请求出口 | `window.fetch` | 与 XHR 是**两条独立通道**，必须都 Hook |
| Cookie 写入 | `document.cookie` 的 setter | 区分 JS 写入与 HTTP Set-Cookie 下发 |
| 编码原语 | `btoa` / `atob` / `encodeURIComponent` | VM 高频信号 |
| 字符构造 | `String.fromCharCode` | VM 逐字符拼串的典型痕迹 |
| JSON | `JSON.stringify` | 参与签名的参数序列化 |
| 加密库 | `CryptoJS.MD5` / `CryptoJS.AES.encrypt` 等 | 命中即可判定算法归属 |
| 摘要 | `crypto.subtle.digest` | Web Crypto 路径 |
| 代码执行 | `eval` / `Function` 构造器 | 拦截实际执行的代码 |
| 动态属性 | 目标对象的属性 getter | 观察 VM 读了哪些环境值 |

## 三、日志量控制

**高频函数不设上限会直接打爆日志缓冲。** 每个 Hook 必须设捕获上限，并优先使用轻量序列化。

| 做法 | 原因 |
|---|---|
| 设最大捕获条数 | 每秒数千次调用的函数会瞬间淹没日志 |
| 用"预览"式序列化而非完整 JSON | 完整序列化会触发 getter / `toJSON` 副作用，改变目标行为 |
| 只对目标数据范围做内存/属性追踪 | 全量追踪开销大且噪声高 |
| 用块级 trace 而非指令级 | 指令级只在很小范围、很短窗口内开启 |
| 记录容量与截断状态 | 空日志不能当作"未执行"的证据 |

## 四、模块/资源加载时序

当目标函数所在的模块/脚本**尚未加载**时，直接 Hook 会失败。正确顺序：

1. 先检查目标是否已加载；已加载则直接 Hook。
2. 未加载则 Hook 加载入口（如 `dlopen` / `android_dlopen_ext` 之类），在加载完成回调里再装 Hook。
3. 轮询只作兜底手段，不要作为首选。
4. 按模块基址去重，避免同一模块重复安装 Hook。

**反模式**：不要盲目 Hook 初始化段、构造函数或 `JNI_OnLoad` 之类的一次性初始化入口。理由：

- 坏 Hook 会在目标逻辑跑之前把进程搞崩。
- 过早 Hook 会改变时序，把待研究的行为藏起来。
- 初始化函数常扇出到大量无关 helper，日志全是噪声。

**正确顺序**：① Hook 加载后的稳定导出函数 → ② Hook 注册/绑定类函数或首个真实业务函数 → ③ 仅在确有证据时 Hook 初始化入口 → ④ 有强证据才 Hook 构造函数。

若确实需要早 Hook，必须能回答：为什么普通导出 Hook 不够？精确 Hook 哪个位置？预期失败模式是什么？如何验证没有破坏初始化？

## 五、常见反调试与对抗

| 反调试手段 | 表现 | 对抗方式 |
|---|---|---|
| 无限 `debugger` | `setInterval(() => { debugger }, 100)` 或递归自调用 | 覆写 `Function` 构造器过滤 `debugger`；过滤含 `debugger` 的定时器回调 |
| `Function` 构造器隐藏 | `new Function("debugger")` | 同上，覆写构造器并保留原型链 |
| 窗口尺寸检测 | `outerHeight - innerHeight > 200` 判定开发者工具打开 | 锁定 `outerHeight/outerWidth` 返回 `innerHeight/innerWidth` |
| `console` 计时检测 | `console.log` 前后测时间差 | 把 `console` 方法覆写为空操作 |
| `toString` 检测 | 利用对象 `toString` 只在开发者工具打开时被调用 | 覆写 `console.log` 阻止 `toString` 调用 |
| 函数源码完整性 | 检查 `fn.toString()` 是否含换行或长度是否匹配 | 保存原始 `toString` 结果并返回固定值；或**不修改原函数**，改用加载前收集数据 |
| 时间差检测 | 代码段前后时间差过大判定被断点 | Hook 时间源返回连续递增值（注意这会改变依赖真实时间的逻辑） |
| Node.js 环境检测 | `typeof process !== 'undefined'`、`typeof module !== 'undefined'` | 在沙箱上下文中不暴露这些全局 |
| 指纹检测 | 检查 `window.chrome`、`navigator.webdriver`、`plugins.length` | 补全环境（见 jsdom 环境伪装） |
| 自动化框架检测 | `_Selenium_IDE_Recorder`、`_phantom`、`__webdriver_script_fn` 等 | 逐个清除并 `Object.defineProperty` 覆写 |
| `Object.defineProperty` 篡改 | 目标改写 `defineProperty` 阻止 Cookie Hook | 在注入脚本**最开始**保存原始引用，后续使用保存的引用 |
| Proxy 检测 | 检测对象是否被 Proxy 包装 | 确保 Proxy 行为与原始对象一致（含 `toString` 与原型链） |

## 六、注入时机

反反调试脚本必须在**页面脚本之前**注入，否则目标已经完成了检测。

```text
注入顺序：
1. 保存原始方法引用（defineProperty / setInterval / Function / Date.now 等）
2. 安装 debugger 过滤
3. 安装 console 静默
4. 安装指纹补全
5. 最后才允许页面脚本执行
```

**注意**：某些属性一旦被锁定或已注册初始化脚本，可能无法原位卸载；彻底恢复需要新建上下文或重启浏览器。不要假设"卸载 Hook 就能回到原状"。

## 七、边界声明

- 绕过反调试是**观测手段**，不是交付目标。
- 绕过可能改变目标行为，因此所有结论必须与无 Hook 基线对照。
- 反调试绕过能力不能作为"目标已完全还原"的证据。
- 记录哪些反调试被绕过、用什么方式、是否观察到行为差异。
