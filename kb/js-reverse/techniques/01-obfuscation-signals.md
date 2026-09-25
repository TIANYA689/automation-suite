# 混淆信号速查

用途：拿到一个 JS 文件，先判断它属于哪一类混淆，再决定工具路径。**类型判断错误是最大的时间浪费来源。**

程序性步骤见 `js-script-deobfuscator` 技能；本页只做"信号 → 类型 → 成本"的映射。

## 信号到类型

| 信号 | 类型 | 还原成本 |
|---|---|---|
| `_0x` 前缀变量、十六进制字符串数组、数组旋转 IIFE | OB 混淆（obfuscator.io 系） | 低 |
| `'1\|4\|2\|0'.split('\|')` + `switch(state)` 循环 | 控制流平坦化 | 中 |
| `eval(function(p,a,c,k,e,d){...})`、`new Function('return ...')` | eval / Function 打包 | 低-中 |
| 全为日文颜文字字符 | AAEncode | 极低 |
| 全为 `$` 与特殊字符 | JJEncode | 极低 |
| 仅使用 `[]()!+` 六种字符 | JSFuck | 极低 |
| 超大数组 + 解释器循环 + 函数查找表 | 自定义 VM | 高（反编译）/ 低（I/O 定位） |
| 200KB+ 单文件、无意义命名、改写原生 API、操作码表 | JSVMP | 高 |
| object helper `{a:function(x,y){...}}` | 代理函数 | 中低 |
| `toString().search('(((.+)+)+)$')` | 自防御（selfDefending） | 中 |

## 三个必须避免的误判

**看到 `switch` 就断定控制流平坦化。** 必须同时满足：存在状态变量、状态变量在循环内被更新、分发依赖该变量。普通的业务 `switch` 遍地都是。

**看到大数组就断定是 VM 字节码。** 很多混淆器会把字符串、查找表、常量池都塞进大数组。判定 VM 需要看到虚拟 PC、寄存器/操作数栈、以及真正的分发执行循环。

**看到 `eval` 就断定是打包器。** `eval` 可能是正常业务代码，也可能是 VM 初始化的一环。看它执行的内容形态。

## 分层识别顺序

```text
第 1 层：文件级形态
  体积、行数、是否单行、是否含非 ASCII 字符集 → 快速排除 AAEncode/JJEncode/JSFuck

第 2 层：命名与结构
  标识符是否语义化、是否存在统一前缀 → OB 混淆

第 3 层：控制流
  是否存在状态机循环 → CFF / VM

第 4 层：数据流
  字符串是否集中在数组、是否加密 → 字符串表保护

第 5 层：环境交互
  是否改写原生 API、是否读取大量环境属性 → JSVMP
```

前两层通常 30 秒内可以完成，能直接排除掉一半以上的可能性。

## 混淆与保护不是一回事

混淆是**结构变换**，保护是**成本管理**。除 VM 化以外，所有常见混淆手段都是可逆的：字符串数组可以执行旋转函数还原，控制流可以按状态转移重排，自防御可以在副本里 stub 掉。

因此判断一个混淆产物"值不值得解"，看的不是"混淆了多少层"，而是"有没有引入 VM 化的成本跃升"。

反向来看，`js-script-obfuscator` 选择保护强度时也应当依据同一张表。

## 相关条目

- 加密算法识别：`kb/js-reverse/techniques/02-crypto-fingerprints.md`
- JSVMP 双路径：`kb/js-reverse/techniques/03-jsvmp-paths.md`
- 环境伪装差异表：`kb/js-reverse/techniques/04-env-emulation-diff.md`
- 改写语义验证：`kb/js-reverse/techniques/05-transform-validation.md`
