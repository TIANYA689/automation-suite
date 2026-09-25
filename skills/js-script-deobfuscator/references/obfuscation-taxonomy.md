# 混淆类型识别与还原

按识别难度从低到高排列。每一步都先给"识别特征"，再给"还原步骤"，最后给"还原成本"——成本决定值不值得动手。

## 1. OB 混淆（obfuscator.io 系）

**识别特征**

- 大量 `_0x` 前缀变量名，如 `_0x4a3b2c`
- 顶部有十六进制字符串数组：`var _0xabc = ['...', '...', ...]`
- 字符串数组旋转函数（自执行 IIFE，常与一个整数偏移量搭配）
- 十六进制属性访问：`obj['_0x1234']` 代替 `obj.method`
- 数字被转成表达式：`0x1a2b` 或 `0x3e8 * 0x2`

**还原步骤**

1. 定位字符串数组与旋转函数。
2. 执行旋转函数，得到最终字符串数组。
3. 全局替换十六进制索引为实际字符串。
4. 简化数学表达式与逻辑运算。
5. 变量重命名提高可读性。

**还原成本**：低。这类混淆是可逆的纯结构变换，工具化程度高。

**注意**：如果字符串数组元素本身是加密的（见第 3 节 RC4），先解字符串再替换索引，顺序反了会白做。

## 2. 控制流平坦化（CFF）

**识别特征**

```javascript
var state = initialState;
while (true) {
    switch (state) {
        case 'A': /* ... */ state = 'C'; break;
        case 'B': /* ... */ state = 'D'; break;
        case 'C': /* ... */ state = 'B'; break;
    }
}
```

有时状态用数字，有时用字符串，有时由辅助函数计算。关键特征是**一个状态变量 + 一个分发 switch + 循环**。

**还原步骤**

1. 找到初始状态值（循环前最后一次赋值）。
2. 按状态转移顺序排列代码块。
3. 去掉 switch-case 包装，还原为顺序代码。
4. 简化多余的变量赋值与不透明谓词。

**还原成本**：中。难点在于状态转移可能是条件性的（真分支/假分支），需要同时恢复条件判断本身。若有 `switch` 嵌套 `switch`，先处理内层。

**判据**：不要仅凭"文件里有 switch"就判定 CFF。必须同时看到状态变量在循环内被更新、且分发依赖该变量。

## 3. eval / Function 打包

**识别特征**

```javascript
eval(function(p,a,c,k,e,d){...}('encoded_string',...))
new Function('return ' + decryptedCode)()
```

**还原步骤**

1. Hook `eval` 与 `Function` 构造器，拦截实际执行的代码。
2. 或把 `eval()` 替换为 `console.log()` / 写入文件，直接看解密后代码。
3. 可能有多层嵌套，逐层解包，每层记录 payload 长度与哈希。

**还原成本**：低到中。单层很容易；多层需要自动化循环（反复执行到不再产生新的 eval 调用）。

**安全要求**：**不要直接执行未知 payload**。先静态提取，确认无网络/文件副作用后再在沙箱中执行。

## 4. AAEncode / JJEncode / JSFuck

**识别特征**

| 类型 | 特征 |
|---|---|
| AAEncode | 全为日文颜文字字符（`ﾟωﾟﾉ` 等） |
| JJEncode | 全为 `$` 与特殊字符：`$=~[];$={___:++$,...` |
| JSFuck | 仅使用 `[]()!+` 六种字符 |

**还原步骤**：直接在浏览器或 Node 中执行，或把最外层执行函数改为输出。

**还原成本**：极低。这类混淆只做字符编码，不做逻辑变换，执行即得原文。

## 5. 自定义 VM / 字节码解释器

**识别特征**

- 超大数组作为"字节码"
- 解释器循环，含 `switch` 或函数查找表
- 通常在 IIFE 中，与外部只通过少量接口通信
- 无法通过简单字符串替换还原

**还原策略**

1. **不要尝试反编译字节码**——这是最常见的弯路。
2. 找到解释器的**输入和输出接口**。
3. Hook 解释器的关键操作（函数调用、赋值、返回）来理解行为。
4. 直接在 Node.js 中运行字节码解释器（原样跑，只改 I/O 出口）。

**还原成本**：高（若走反编译）/ 低（若走 I/O 定位）。**优先 I/O 定位**。

## 6. JSVMP（JS 虚拟机保护）

**识别特征**

- 超大 JS 文件（200KB+，常见 380KB 以上）
- 包含自定义解释器与操作码表
- 函数名与变量名完全无意义
- 改写浏览器原生 API（劫持 XHR/fetch/cookie）
- 存在"虚拟 PC"、寄存器数组、操作数栈之类的结构

**与"自定义 VM"的区别**：JSVMP 通常额外具备**环境感知**与**完整性检测**，且常与签名逻辑深度绑定。

**还原策略**：走 [JSVMP 双路径方法论](jsvmp-paths.md)。核心是"不要反编译，通过 I/O 定位"。

**还原成本**：高。这类保护的设计目标就是提高成本，应优先考虑路径 B（环境复现）。

## 通用反混淆骨架（AST）

```javascript
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const generate = require('@babel/generator').default;
const t = require('@babel/types');

function deobfuscate(code) {
    const ast = parser.parse(code);
    traverse(ast, {
        StringLiteral(path) {
            if (/^\\x/.test(path.node.extra?.raw || '')) {
                path.node.extra = undefined;
            }
        },
        MemberExpression(path) {
            if (t.isStringLiteral(path.node.property) && /^[a-zA-Z_$]/.test(path.node.property.value)) {
                path.node.computed = false;
                path.node.property = t.identifier(path.node.property.value);
            }
        },
        BinaryExpression(path) {
            if (t.isNumericLiteral(path.node.left) && t.isNumericLiteral(path.node.right)) {
                const result = eval(`${path.node.left.value} ${path.node.operator} ${path.node.right.value}`);
                if (typeof result === 'number' && isFinite(result)) {
                    path.replaceWith(t.numericLiteral(result));
                }
            }
        }
    });
    return generate(ast, { comments: false }).code;
}
```

**上面这段是骨架，不是可直接交付的成品。** 每一条改写规则都要按 [改写语义验证](transform-validation.md) 逐条验证；`eval` 用于常量折叠只允许在数值字面量上使用。

## 分析工作流顺序

```text
1. 保存原始脚本到工作目录（含 hash）
2. 搜索可能的入口函数与字符串数组
3. 在入口设观察点，记录参数与返回值
4. 读取捕获数据，判断是纯混淆还是 VM
5. 纯混淆 → AST 改写；VM → I/O 定位
6. 逐条改写 + 逐条验证
7. 输出清洁版 + 证据 + 不确定项
```
