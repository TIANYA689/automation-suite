---
name: js-script-obfuscator
description: JavaScript 混淆专家。使用 obfuscator.io 技术包括字符串数组旋转、RC4/Base64 编码、控制流扁平化、死代码注入、代理函数和自我防御代码，保护 JS 源代码。
version: 1.1.0
---

# JavaScript Script Obfuscator Skill

You are an expert in JavaScript code protection and obfuscation. Use this skill when the user wants to protect their JavaScript source code from casual inspection or reverse engineering, using techniques similar to **obfuscator.io** / **javascript-obfuscator**.

## 🛡️ Core Features

This obfuscator employs a **"多层防御"(Layered Defense)** strategy, inspired by real-world obfuscation (e.g., the `优步_帐密_签到_刷步_任务.js` case study):

| Layer | Technique | Description |
|-------|-----------|-------------|
| 1 | **String Array** | 所有字符串提取到一个数组函数中 |
| 2 | **Array Rotation** | 使用校验和IIFE将数组元素旋转到正确位置 |
| 3 | **String Encoding** | RC4 或 Base64 加密每个数组元素 |
| 4 | **Identifier Renaming** | 所有变量名替换为 `_0x` 十六进制前缀 |
| 5 | **Control Flow Flattening** | `switch-case` + `split('|')` 打乱执行顺序 |
| 6 | **Dead Code Injection** | 注入永远不执行的分支代码 |
| 7 | **Proxy Functions** | 简单运算包装为对象方法调用 |
| 8 | **Self-Defending** | 防止代码被格式化或篡改 |

## 🏗️ Obfuscation Architecture

### Overall Structure
```
[User Config (Clear Text)]        ← 19行配置（保持可读）
[IIFE Wrapper]                    ← !function(){'use strict'; ... }();
  ├── [String Array Func 1]       ← _0x4cc6() 返回字符串数组
  ├── [Array Rotation IIFE 1]     ← 校验和旋转
  ├── [Decoder Func 1]            ← _0x33c8(index, key) RC4解密
  ├── [String Array Func 2]       ← a() 第二个字符串数组
  ├── [Array Rotation IIFE 2]     ← 第二次校验和旋转
  ├── [Decoder Func 2]            ← b(index, key) 第二个RC4解密
  ├── [Alias Assignment]          ← const E = b;
  ├── [Business Logic]            ← 使用E()解码字符串的业务代码
  └── [Entry Point]               ← startFullTask();
```

## 🔧 Implementation Details

### Layer 1: String Array (字符串数组)

**原理**: 将代码中所有字符串提取到一个集中的数组函数中。

```javascript
// 原始代码
console.log('Hello World');
axios.get('https://api.example.com/data');

// 混淆后 - 字符串被提取到数组
function _0x4cc6() {
    const _0x28818e = [
        'AmkcW4hcKW',   // RC4加密后的 'Hello World'
        'a8kNW7aOta',   // RC4加密后的 'https://api.example.com/data'
        'xZSeWOtcISk1', // RC4加密后的 'log'
        'yCoyWOlcKmkx', // RC4加密后的 'get'
        // ... 数百个加密字符串
    ];
    _0x4cc6 = function() { return _0x28818e; };
    return _0x4cc6();
}
```

**关键特征**：
- 数组函数使用闭包缓存（只计算一次）
- 数组可包含数百个元素
- 每个元素都是 Base64 或 RC4 加密后的字符串
- 支持**双层字符串数组**（如 `_0x4cc6` + `a()`）

### Layer 2: Array Rotation (数组旋转)

**原理**: 通过IIFE将数组元素旋转到正确位置，使得静态分析时索引-字符串对应关系不正确。

```javascript
(function(_0xf18d56, _0xc0fb0c) {
    const _0x462fa4 = _0xf18d56();  // 获取数组
    while (true) {
        try {
            // 使用parseInt和数学运算计算校验和
            const checksum = 
                parseInt(decode(-0xeb, 'mF]S')) / 1 +
                parseInt(decode(-0x11b, 'JDeI')) / 2 +
                // ... 更多项
                ;
            if (checksum === _0xc0fb0c) break;  // 匹配目标校验和
            else _0x462fa4.push(_0x462fa4.shift());  // 旋转数组
        } catch(e) {
            _0x462fa4.push(_0x462fa4.shift());  // 出错也旋转
        }
    }
})(_0x4cc6, 0x3c9224 - 0x19eae1 - 0x14725f);  // 目标校验和
```

**关键特征**：
- 校验和使用大量十六进制数学表达式
- `push(shift())` 实现数组头部元素移到尾部
- 循环直到计算结果匹配目标校验和
- 旋转次数在运行时确定，静态分析无法预知

### Layer 3: String Encoding - RC4 (字符串加密)

**原理**: 使用RC4流密码加密每个字符串，密钥来自数组中的第一个元素。

```javascript
function _0x33c8(_0x43bae8, _0x272ebe) {
    _0x43bae8 = _0x43bae8 - 0x155;  // 索引偏移
    const _0x828f4c = _0x4cc6();     // 获取旋转后的数组
    let _0x4ad7a4 = _0x828f4c[_0x43bae8];  // 取出加密字符串
    
    // 首次调用时初始化RC4解密器
    if (_0x33c8['mVlqxI'] === undefined) {
        // Base64解码函数
        var base64Decode = function(str) {
            const charset = 'abcdefghijklmnopqrstuvwxyz' +
                           'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=';
            let output = '';
            // ... Base64解码逻辑
            return decodeURIComponent(output);
        };
        
        // RC4解密函数
        const rc4Decrypt = function(data, key) {
            let s = [], j = 0, result = '';
            // KSA (Key-Scheduling Algorithm)
            for (let i = 0; i < 256; i++) s[i] = i;
            for (let i = 0; i < 256; i++) {
                j = (j + s[i] + key.charCodeAt(i % key.length)) % 256;
                [s[i], s[j]] = [s[j], s[i]];  // swap
            }
            // PRGA (Pseudo-Random Generation Algorithm)
            let i = 0; j = 0;
            for (let k = 0; k < data.length; k++) {
                i = (i + 1) % 256;
                j = (j + s[i]) % 256;
                [s[i], s[j]] = [s[j], s[i]];
                result += String.fromCharCode(
                    data.charCodeAt(k) ^ s[(s[i] + s[j]) % 256]
                );
            }
            return result;
        };
        
        _0x33c8['JvASjd'] = rc4Decrypt;  // 缓存RC4函数
        _0x33c8['aoCxbm'] = {};           // 结果缓存Map
        _0x33c8['mVlqxI'] = true;         // 标记已初始化
    }
    
    // 使用缓存避免重复解密
    const cacheKey = _0x43bae8 + _0x828f4c[0];  // 数组[0]作为RC4密钥
    const cached = _0x33c8['aoCxbm'][cacheKey];
    if (!cached) {
        _0x4ad7a4 = _0x33c8['JvASjd'](_0x4ad7a4, _0x272ebe);
        _0x33c8['aoCxbm'][cacheKey] = _0x4ad7a4;
    } else {
        _0x4ad7a4 = cached;
    }
    return _0x4ad7a4;
}
```

**关键特征**：
- 先 Base64 解码，再 RC4 解密
- RC4 密钥来源于数组的第 0 个元素（旋转后的位置）
- 解密结果被缓存到 `aoCxbm` 对象中
- 支持**多密钥模式**：每次调用可传入不同的第二参数作为密钥

### Layer 4: Identifier Renaming (标识符重命名)

**原理**: 所有变量、函数、参数名替换为十六进制字符串。

```javascript
// 原始
async function login() {
    const response = await axios.post(url, data);
    return response.data;
}

// 混淆后
async function _0x4ed367() {
    const _0x217523 = await _0x33c8[-0x1519 + -0x215c + 0x3763][
        _0x33c8(-0x1a1 * 0xd + -0xd13 + 0x285e)
    ](_0x43bae8, _0x272ebe);
    return _0x217523[_0x33c8(0x883 + -0x1c79 + 0x1305)];
}
```

**命名规则**：
- 函数名: `_0x` + 6位十六进制 (e.g., `_0x4ed367`)
- 变量名: `_0x` + 6-8位十六进制 (e.g., `_0x217523`)
- 临时变量: 同样格式

### Layer 5: Control Flow Flattening (控制流扁平化)

**原理**: 将线性代码转换为 `while(true) { switch(order[step++]) { ... } }` 结构。

```javascript
// 原始代码（按顺序执行 step1 → step2 → step3 → step4 → step5）
step1();
step2();
step3();
step4();
step5();

// 混淆后
const _0x380853 = '2|0|4|1|3'.split('|');
let _0x3531c9 = 0;
while (true) {
    switch (_0x380853[_0x3531c9++]) {
        case '0': step2(); continue;
        case '1': step4(); continue;
        case '2': step1(); continue;  // 实际第1步
        case '3': step5(); continue;
        case '4': step3(); continue;
        default: break;
    }
    break;
}
```

**关键特征**：
- 顺序字符串如 `'2|0|4|1|3'` 定义执行顺序
- `continue` 确保每个 case 执行后回到循环顶部
- 外层 `break` 在所有 case 执行完后终止循环

### Layer 6: Dead Code Injection (死代码注入)

**原理**: 在条件分支中注入永远不会执行的代码路径。

```javascript
// 混淆后包含死代码
if (_0x4cc0fd['rDpbL']('AMJGt', _0x4e84fd(0x2eb, 'mF]S'))) {
    // 这是死代码 - 字符串比较永远为假
    // 包含看起来合法但无关的逻辑
    _0x55b66e['wztgU'](_0x33d266, _0x5b152e);
} else {
    // 这才是真正执行的代码
    const result = await axios(config);
    return result.data;
}
```

**关键特征**：
- 使用代理函数进行字符串相等比较
- 比较两个运行时才能解密的字符串
- 死分支中包含从其他函数复制来的代码片段
- 增加代码量，误导静态分析

### Layer 7: Proxy Functions (代理函数/对象键变换)

**原理**: 将简单运算和函数调用包装成对象属性方法。

```javascript
// 创建代理对象
const _0x4cc0fd = {
    'rDpbL': function(_0x392d77, _0x78ce98) { 
        return _0x392d77 === _0x78ce98;  // 等于比较
    },
    'vhKqb': function(_0x334e1c, _0x2252d3) { 
        return _0x334e1c(_0x2252d3);      // 函数调用
    },
    'iCoIU': function(_0x206f0e, _0x3f2f76) { 
        return _0x206f0e + _0x3f2f76;     // 加法/字符串拼接
    },
    'rKkYt': function(_0x221e28, _0x537edc) { 
        return _0x221e28 * _0x537edc;     // 乘法
    },
    'CoTYS': '重试次数已用完',              // 字符串常量
};

// 使用代理
_0x4cc0fd['rDpbL'](a, b)        // 实际: a === b
_0x4cc0fd['vhKqb'](parseInt, x) // 实际: parseInt(x)
_0x4cc0fd['iCoIU'](str1, str2)  // 实际: str1 + str2
_0x4cc0fd['rKkYt'](3, 4)        // 实际: 3 * 4
```

**关键特征**：
- 每个函数/代码块都有自己的代理对象
- 代理对象的键名使用随机5位字母字符串 (e.g., `rDpbL`, `cwaZZ`)
- 封装了 `===`, `!==`, `+`, `-`, `*`, `/`, `%`, `&`, `>>`, 函数调用等操作
- 字符串常量也可作为代理对象的属性存储

### Layer 8: Self-Defending (自我防御)

**原理**: 检测代码是否被格式化或修改，如被篡改则进入无限循环。

```javascript
// 自我防御代码模式
const _0x53c574 = (function() {
    let _0x41e43f = true;
    return function(_0x2d269a, _0x953e2f) {
        const fn = _0x41e43f ? function() {
            if (_0x953e2f) {
                const result = _0x953e2f.apply(_0x2d269a, arguments);
                _0x953e2f = null;
                return result;
            }
        } : function() {};
        _0x41e43f = false;
        return fn;
    };
})();

const _0x4b6c99 = _0x53c574(this, function() {
    return _0x4b6c99
        .toString()
        .search('(((.+)+)+)$')  // 检测代码是否被格式化
        .toString()
        .constructor(_0x4b6c99)
        .search('(((.+)+)+)$');
});
_0x4b6c99();  // 如果被格式化，此处触发ReDoS导致挂起
```

**关键特征**：
- 使用 `(((.+)+)+)$` 正则进行 ReDoS 攻击
- 如果 `toString()` 输出与预期不匹配，进入指数级回溯
- 防止使用美化工具（如 Prettier）格式化代码

## 🚀 Obfuscation Workflow

### Step 1: 准备源代码
```
1. 读取目标JS文件
2. 分离配置区域（保持可读）和业务逻辑（需要混淆）
3. 解析AST（抽象语法树）
```

### Step 2: 使用 javascript-obfuscator
推荐使用 `javascript-obfuscator` npm包，配置如下：

```javascript
const JavaScriptObfuscator = require('javascript-obfuscator');

const result = JavaScriptObfuscator.obfuscate(sourceCode, {
    // 基础设置
    compact: true,                          // 压缩为单行
    target: 'node',                         // 目标环境
    
    // 字符串保护 (Layer 1-3)
    stringArray: true,                       // 启用字符串数组
    stringArrayRotate: true,                 // 启用数组旋转
    stringArrayEncoding: ['rc4'],            // RC4加密 (或 'base64')
    stringArrayThreshold: 0.75,              // 75%的字符串被提取
    stringArrayIndexShift: true,             // 索引偏移
    stringArrayWrappersCount: 2,             // 解码包装函数数量
    stringArrayWrappersType: 'function',     // 包装类型
    
    // 标识符重命名 (Layer 4)
    identifierNamesGenerator: 'hexadecimal', // _0x 前缀
    renameGlobals: false,                    // 不重命名全局变量
    
    // 控制流 (Layer 5)
    controlFlowFlattening: true,             // 启用控制流扁平化
    controlFlowFlatteningThreshold: 0.75,    // 75%代码块被扁平化
    
    // 死代码 (Layer 6)
    deadCodeInjection: true,                 // 注入死代码
    deadCodeInjectionThreshold: 0.4,         // 40%的代码块注入死代码
    
    // 代理函数 (Layer 7)
    transformObjectKeys: true,               // 变换对象键名
    
    // 自我防御 (Layer 8)
    selfDefending: true,                     // 启用自我防御
    
    // 其他
    numbersToExpressions: true,              // 数字转为表达式 (0x21 代替 33)
    splitStrings: true,                      // 分割长字符串
    splitStringsChunkLength: 10,             // 分割块长度
    unicodeEscapeSequence: false,            // 不使用unicode转义
});

const obfuscatedCode = result.getObfuscatedCode();
```

### Step 3: 配置与代码分离
```javascript
// 保持配置可读
const clearTextConfig = `
const BASE_URL = 'https://example.com/api/v1';
const PHONE = '';
const PASSWORD = '';
const TASK_CONFIG = { ... };
`;

// 只混淆业务逻辑
const obfuscatedLogic = obfuscate(businessLogic);

// 组合输出
const finalCode = clearTextConfig + '\n' + obfuscatedLogic;
```

### Step 4: 双层字符串数组 (高级)
为增加破解难度，可使用两层不同的字符串数组：
```
Layer A: _0x4cc6() + _0x33c8()  ← 主解码器, 用于基础设施代码
Layer B: a() + b(), alias E     ← 辅助解码器, 用于业务逻辑
```

实现方式：将代码分为两部分分别混淆，然后嵌套组合。

## 📋 Configuration Presets

### 🟢 轻度混淆 (快速，体积小)
适用于：简单的脚本保护，不需要高强度防护

```javascript
{
    compact: true,
    stringArray: true,
    stringArrayEncoding: ['base64'],
    identifierNamesGenerator: 'hexadecimal',
    controlFlowFlattening: false,
    deadCodeInjection: false,
    selfDefending: false,
}
```
**效果**: 代码体积增长 ~30%，初始化延迟 <50ms

### 🟡 中度混淆 (推荐)
适用于：大多数自动化脚本保护

```javascript
{
    compact: true,
    stringArray: true,
    stringArrayEncoding: ['base64'],
    stringArrayRotate: true,
    identifierNamesGenerator: 'hexadecimal',
    controlFlowFlattening: true,
    controlFlowFlatteningThreshold: 0.5,
    deadCodeInjection: false,
    transformObjectKeys: true,
    selfDefending: true,
}
```
**效果**: 代码体积增长 ~100%，初始化延迟 <200ms

### 🔴 重度混淆 (最强保护, 如优步脚本)
适用于：商业脚本，需要最大化防护

```javascript
{
    compact: true,
    stringArray: true,
    stringArrayEncoding: ['rc4'],
    stringArrayRotate: true,
    stringArrayIndexShift: true,
    stringArrayWrappersCount: 2,
    identifierNamesGenerator: 'hexadecimal',
    controlFlowFlattening: true,
    controlFlowFlatteningThreshold: 0.75,
    deadCodeInjection: true,
    deadCodeInjectionThreshold: 0.4,
    transformObjectKeys: true,
    selfDefending: true,
    numbersToExpressions: true,
    splitStrings: true,
    splitStringsChunkLength: 10,
}
```
**效果**: 代码体积增长 ~500%+，初始化延迟 ~500ms

## ⚠️ Limitations & Notes

1. **性能开销**: RC4解密和控制流扁平化会增加运行时开销，尤其在`重度混淆`模式下
2. **代码膨胀**: 死代码注入 + 双层字符串数组可使代码膨胀5-10倍（如优步脚本从~5KB膨胀到~104KB)
3. **调试困难**: 混淆后的代码极难调试，建议保留源码备份
4. **Node.js兼容**: `selfDefending` 在Node.js环境中效果有限，主要针对浏览器
5. **不是加密**: 混淆只增加逆向成本，有足够时间和技术的人仍可还原
6. **配置外置**: 始终将需要用户修改的配置（如账号密码、URL）保持在混淆区域之外
7. **依赖安全**: 不要混淆 `require()` 调用和模块名称

## 🔗 Related Skills

- **js-script-deobfuscator**: 解混淆技能（本技能的逆操作）
- **python-obfuscator-pro**: Python 版混淆技能（类似概念，不同实现）
- **python-script-decryptor**: Python 解密技能

## Instruction for Agent
When using this skill:

1.  **Add Standard Header**: The output script MUST start with a comment block explaining:
    -   That the script is obfuscated.
    -   Any required Node.js version.
    -   Disclaimer about safety/usage.
2.  **Configuration Separation**: Ensure sensitive/changeable data (Tokens, URLs) are kept in a clear-text configuration block at the top, separate from the obfuscated logic (as shown in Step 3).
3.  **Test Locally**: ALWAYS run the obfuscated script locally (`node script.js`) to ensure it executes correctly before delivering.
4.  **Backup**: Remind the user to keep a backup of the original source code.
