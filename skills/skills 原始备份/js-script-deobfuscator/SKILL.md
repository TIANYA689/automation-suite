---
name: js-script-deobfuscator
description: JavaScript 解混淆专家。支持分析和解密由 obfuscator.io、javascript-obfuscator、JScrambler 等工具混淆的 JS 脚本，包含字符串数组旋转、RC4/Base64 解密、控制流恢复、死代码移除。
version: 1.2.0
---

# JavaScript Script Deobfuscator Skill

You are an expert in reverse engineering and deobfuscating JavaScript scripts. Use this skill when the user provides a JS script that is unreadable due to obfuscation by tools like **obfuscator.io**, **javascript-obfuscator**, **JScrambler**, or custom packers.

## 🔍 Phase 1: Identification & Classification

### Step 1.1: Recognize Obfuscation Type
Look for these indicators to classify the obfuscation tool/method:

| Pattern | Indicator | Tool |
|---------|-----------|------|
| `_0x` prefixed variables | `_0x4cc6`, `_0x33c8` | **obfuscator.io** / javascript-obfuscator |
| String array + rotation IIFE | `(function(_0xXXXX, _0xYYYY){...push...shift...})(_0xArrayFunc, checksum)` | **obfuscator.io** |
| RC4 string decryption | Base64 decode → RC4 with key from array element | **obfuscator.io** (stringArrayEncoding: 'rc4') |
| Base64 string decryption | Simple Base64 decode of array elements | **obfuscator.io** (stringArrayEncoding: 'base64') |
| Control flow flattening | `switch(...)` with `'1\|4\|2\|0\|3'.split('\|')` | **obfuscator.io** (controlFlowFlattening) |
| Self-defending code | `(((.+)+)+)$` regex pattern, `toString().search()` | **obfuscator.io** (selfDefending) |
| Dead code injection | Unreachable `if/else` branches with string comparison | **obfuscator.io** (deadCodeInjection) |
| Proxy functions | `{'func': function(a,b){return a+b;}}` wrapper objects | **obfuscator.io** (transformObjectKeys) |
| `!function(){'use strict';...}()` | Top-level IIFE wrapper | Common wrapper pattern |
| `eval(...)` / `Function(...)()` | Packed code execution | **eval-based packers** |
| `_0x` + `atob` | Simple Base64 string hiding | **Lightweight obfuscators** |
| `Bq`, `Ed`, `qX` variables | Dynamic state machine / variables evolution | **Custom logic-heavy obfuscators** |
| `function(Ax){...}(...)` | Nested functional evaluation | **Logic-heavy obfuscators** |

### Step 1.2: Identify Code Structure
Map out the components in this order:
1. **Outer definitions**: String array functions, decoder functions (before the main IIFE)
2. **IIFE wrapper**: `!function(){'use strict'; ... }()`
3. **Array rotation setup**: `(function(array, checksum){ while(true){ ... push(shift) ... } })(arrayFunc, numericChecksum)`
4. **String decoder functions**: Functions that take an index and return a decoded string
5. **Alias assignments**: `const E = b;` — creating aliases for decoders
6. **Business logic**: The actual application code using decoded strings

## 🛠️ Phase 2: Decryption Workflow

### Strategy A: Sandbox Execution (Preferred for obfuscator.io)

**Goal:** Execute the decryption infrastructure in a safe sandboxed environment, then use it to decode all strings.

#### Step 2A.1: Custom Sandbox Strategy (State-Machine Handling)
When variables (like `Bq`, `Ed`) are used to derive values linearly, use a script to simulate the evolution:
```javascript
const state = { Bq: 0, Ed: 0 }; // Initialize from first occurrence
function evaluate(expr) {
    const result = new Function(...Object.keys(state), "return " + expr)(...Object.values(state));
    // Greedy update state: find pattern Bq-=123 or Bq=456
    const matches = expr.match(/([a-zA-Z]+)\s*([+\-*/]?=)\s*(-?\d+)/g);
    if (matches) { /* logic to update local state object */ }
    return result;
}
```

#### Step 2A.2: Build Safe Execution Context
```javascript
const mockAxios = Object.assign(
    async function() { return { data: { code: 0, data: {} } }; },
    {
        get: async () => ({ data: { code: 0, data: {} } }),
        post: async () => ({ data: { code: 0, data: {} } }),
    }
);

const ctx = vm.createContext({
    parseInt, decodeURIComponent, String, Math, RegExp,
    Boolean, Error, Promise, Date, JSON, Array, Object, Number,
    console: { log: () => {}, error: () => {}, warn: () => {} },
    setTimeout: () => 0, setInterval: () => 0, clearInterval: () => {},
    process: { on: () => {}, exit: () => {} },
    require: () => mockAxios,
});
```

#### Step 2A.3: Execute and Extract
```javascript
// Modify the IIFE ending to export all functions instead of calling them
// e.g., replace: startFullTask();}();
// with:   this.__exported = { func1, func2, ... }; }();
vm.runInContext(modifiedCode, ctx, { timeout: 15000 });
```

#### Step 2A.4: Decode All Strings
```javascript
const decoder = ctx.__exported.E; // or b, or whatever the decoder alias is
const allStrings = new Map();
for (let i = -10000; i < 10000; i++) {
    try {
        const r = decoder(i);
        if (r && typeof r === 'string' && r.length > 0) allStrings.set(i, r);
    } catch(e) {}
}
```

### Strategy B: Static Analysis (Fallback)

**When to use:** When sandbox execution fails due to anti-tampering, complex dependencies, or `this` context issues.

#### Step 2B.1: Identify Clear-text Elements
Even in heavily obfuscated code, many elements remain partially readable:
- **String concatenation**: `"https:" + "//yo" + "ub.clu" + 'b/ap'` → `https://youb.club/ap`
- **API paths**: `/captcha/s`, `/signin`, `/steps/sync`, `/tasks`
- **HTTP methods**: `'get'`, `'post'`, `'put'`
- **Headers**: `'Content-Type'`, `'Authorization'`, `'User-Agent'`
- **Status codes**: Numeric comparisons like `=== 0`
- **Chinese log messages**: Often present in clear-text as string constants
- **Known library APIs**: `axios.get()`, `axios.post()`, `JSON.stringify()`

#### Step 2B.2: Trace Function Signatures
Identify functions by their structure even without decoding strings:
```
async function XXX() {
    await axios.get(...)     → likely a data-fetching function
    await axios.post(...)    → likely a submission function  
    setInterval(...)         → likely a task scheduler
    clearInterval(...)       → likely a task stopper
}
```

#### Step 2B.3: Reconstruct Logic
Based on identified API calls, function structures, and partial string decoding, manually reconstruct the readable version.

## 📝 Phase 3: Code Reconstruction

### Step 3.1: Write Clean Version
Create a new file `{original_name}_解密版.js` with:

1. **Header comment block**: Describe the original obfuscation method and what was decoded
2. **Clear imports**: Replace obfuscated require() with readable imports
3. **Configuration section**: Extract all config constants (URLs, timeouts, etc.)
4. **Utility functions**: delay(), request wrapper, ID generators
5. **Business logic**: Each function with clear names and Chinese comments
6. **Main entry point**: Clean startup flow

### Step 3.2: Code Quality Standards
```javascript
// ✅ GOOD: Clear, descriptive, with Chinese comments
/**
 * 执行每日签到
 * @returns {boolean} 签到是否成功
 */
async function doSignin() {
    if (!authToken) {
        console.log('[⚠️] 未获取到Token，无法执行签到');
        return false;
    }
    // ...
}

// ❌ BAD: Still contains obfuscated references
async function doSignin() {
    const _0x12a2b8 = E(-0x478+0xb43+-0x5ce);
    // ...
}
```

### Step 3.3: Cleanup
- Delete all temporary decryption tools (`deobfuscate_*.js`)
- Keep only the final clean version
- The output file should be immediately runnable (after filling in credentials)

## 🔑 Key Patterns Reference

### obfuscator.io String Array + RC4
```
Structure:
  _0x4cc6()     → returns the string array
  _0x33c8(i, k) → RC4 decodes array[i] with key k (from array element 0)
  
Array rotation IIFE:
  (function(arr, checksum) {
      while(true) {
          try {
              if (parseInt(...) + parseInt(...) === checksum) break;
              else arr.push(arr.shift());
          } catch(e) { arr.push(arr.shift()); }
      }
  })(_0x4cc6, 0x12345);
```

### obfuscator.io Dual-Layer Decryption
Some scripts have TWO sets of decoder functions:
```
Layer 1: _0x4cc6 (array) + _0x33c8 (decoder)
Layer 2: a() (array) + b() (decoder), aliased as E
```
Both layers use the same RC4 algorithm but with different arrays and keys.

### Control Flow Flattening
```javascript
// Obfuscated:
const order = '1|4|2|0|3'.split('|');
let step = 0;
while(true) {
    switch(order[step++]) {
        case '0': /* step 4 logic */ continue;
        case '1': /* step 1 logic */ continue;
        // ...
    }
    break;
}

// Decoded: Execute in the order defined by the string
// '1|4|2|0|3' means: case 1 → case 4 → case 2 → case 0 → case 3
```

### Proxy Functions (Object Key Transformation)
```javascript
// Obfuscated:
const helpers = {
    'rKkYt': function(a, b) { return a * b; },
    'cwaZZ': function(a, b) { return a + b; },
    'PEFdx': function(a, b) { return a(b); },
};
// usage: helpers['rKkYt'](3, 4)  // means: 3 * 4

// Decoded: Replace with direct operators
3 * 4
```

## ⚠️ Safety Rules

1. **Never run `eval()`/`exec()`** on unknown payloads during analysis
2. **Use `vm` module** with timeout for sandboxed execution
3. **Mock all I/O**: Replace `axios`, `fetch`, `require`, `process` with safe mocks
4. **Disable network access**: Ensure no real HTTP requests are made during analysis
5. **Handle anti-tampering**: Self-defending code may cause infinite loops — always use timeouts
6. **Clean up**: Remove all temporary analysis/decryption files after generating the clean version

## 📊 Output Deliverables

After deobfuscation, provide the user with:
2. **解密版文件**: `{原始文件名}_解密版.js` — clean, readable, runnable code
3. **注意事项**: Any uncertain decodings, potential errors, or credentials that need filling

## Instruction for Agent
When using this skill:

1.  **Safety First**: Always use the Sandbox Strategy (Strategy A) first. Only use Static Analysis (Strategy B) if sandbox fails.
2.  **Add Standard Header**: The output decrypted script MUST start with a comment block explaining:
    -   Obfuscation type identified (e.g., "obfuscator.io").
    -   Disclaimer: "Decrypted for educational/analysis purposes only."
3.  **No Dead Code**: Remove the `_0x...` arrays and decoder functions from the final output if they are no longer needed.
4.  **Formatting**: Ensure the final code is formatted (beautified) and variables are renamed to readable English where possible (e.g., `_0x123` -> `userToken`).
5.  **Runnable**: The final script must be runnable in Node.js. If specific environment variables are needed, list them in the header.

## 🔗 Related Skills

- **js-script-obfuscator**: JS 混淆技能（本技能的逆操作）
- **python-script-decryptor**: Python 解密技能（类似概念，不同语言）
- **automation-script-dev-js**: JS 自动化开发技能
