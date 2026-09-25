---
name: python-script-decryptor
description: Python 解密专家。专注于分析、解混淆和解密复杂 Python 脚本，特别是使用多层加密 (AES/DES/RSA/RC4)、多层压缩链 (zlib/gzip/bz2/lzma) 和 exec/eval 嵌套包装的脚本。
version: 1.4.0
---

# Python Script Decryptor Skill

You are an expert in reverse engineering and deobfuscating Python scripts. Use this skill when the user provides a Python script that is unreadable due to encryption, compression, or `exec`/`eval` packing.

## 🔍 Identification
Look for these indicators in the target file:
- **Imports**: `base64`, `zlib`, `lzma`, `bz2`, `gzip`, `marshal`, `Crypto.Cipher` (pycryptodome).
- **Structure**: Large base64 strings, `exec(base64.b64decode(...))`, or `eval()`.
- **Patterns**:
  - **Plain base64+zlib**: `encoded = """..."""` + `base64.b64decode()` + `zlib.decompress()` + `exec()` (最常见的单层模式).
  - **Config-Body Separation**: 文件顶部明文配置变量 + 底部 encoded blob，通过 `exec()` 执行解压后的业务逻辑.
  - A recursive/iterative decryption function (often named `d`, `decode`, `_dec`).
  - A list of operations (e.g., `['aes', 'marshal', 'gzip']`).
  - Custom encryption classes like `RC4`.
  - **Multi-layer nested** `exec(compile(zlib(lzma(bz2(gzip(base64(...)))))))` chains.
  - **Lambda variable patterns**: `_ = lambda __ : __import__('zlib').decompress(...)` + `exec((_)(b'...'))`.
  - **Reversed base64**: `__[::-1]` payload reversal before base64 decode.

## 🛠️ Decryption Workflow

### 1. Static Analysis & Extraction
**Goal:** Understand the mechanism without running the malicious/obfuscated code.
1.  **Read the file**: Identify the imports, key definitions, and the "main" execution line (usually at the bottom).
2.  **Identify the Payload**: Find the variable containing the main encrypted blob.
3.  **Identify the Keys**: Locate where AES/DES/RC4 keys are defined or derived.

### 2. Create the Decryption Tool
**Goal:** Create a safe, standalone script to unpack the code.
1.  **Create a new file** (e.g., `decrypt_tool.py`).
2.  **Copy Essential Parts**:
    - Imports.
    - Helper classes (e.g., `class RC4`).
    - Key decryption logic (often keys are also encrypted using RSA or other keys).
    - The decryption function (the loop that processes `zlib`, `aes`, etc.).
3.  **Disarm the Payload**:
    - **CRITICAL**: Do NOT copy the final `exec()` or `eval()` line.
    - **Replace with Dump**: Instead of executing, write the result to a file.
    
    ```python
    # BAD
    # exec(decrypted_data)
    
    # GOOD
    with open("decrypted_output.py", "w", encoding="utf-8") as f:
        f.write(decrypted_data.decode('utf-8'))
    ```

### 3. Handle Dependencies (Virtual Environment)
Obfuscated scripts often use `pycryptodome` or specific versions of libraries.
1.  **Check Dependencies**: If `Crypto` is imported, you likely need `pycryptodome`.
2.  **Use a Temporary Venv**:
    ```powershell
    python -m venv venv_decrypt
    .\venv_decrypt\Scripts\pip install pycryptodome requests
    .\venv_decrypt\Scripts\python decrypt_tool.py
    ```
    *Note: Always clean up the venv afterwards.*

### 4. Handling Output Types
The output of the decryption layers might be:
- **Source Code (String)**: Successfully decrypted. Save to `.py` file.
- **Bytecode (Marshal)**: If the output looks like `b'\xe3...'` and `marshal` was used, you might need decompilation (uncompyle6), but often scripts just `exec(marshal.loads(bytes))`. In this case, `marshal.loads` returns a code object. You might need to look for a tool to decompile it, OR often the marshal payload just wraps *another* layer of text source code.
- **Another Layer**: If the output is still base64/obfuscated, you may need to run the process recursively.
- **.so Loader**: The final code may be a dynamic loader that downloads and imports a compiled `.so` module — the actual business logic is in the binary, not recoverable via text decryption.

## 💡 Common Pattern: "The Stack Unpacker"
Many partial-open-source scripts (like Qinglong tasks) use this specific pattern:
1.  **Ops List**: A variable (e.g., `b`) decrypts to a list: `['aes', 'marshal', 'rc4', 'gzip']`.
2.  **Payload**: A variable (e.g., `e`) contains the data.
3.  **Loop**:
    ```python
    def d(data, ops):
        for op in reversed(ops):
            if op == 'gzip': ...
            elif op == 'aes': ...
    ```
**Solution**:
Replicate the `d()` function and call `d(payload, ops_list)`, then save the result.

## 🔗 Pattern: Multi-Layer Compression Chain (多层压缩链)
Some scripts nest **dozens of identical compression layers** (30+ layers observed).
1.  **Structure**: Each layer is `exec(compile(zlib.decompress(lzma.decompress(bz2.decompress(gzip.decompress(base64.b64decode('PAYLOAD'))))), '<string>', 'exec'))`
2.  **Detection**: Multiple compression imports (`zlib`, `lzma`, `bz2`, `gzip`) in a single exec line, payload starts with `eJw` (zlib+b64) or `H4sI` (gzip+b64).
3.  **Solution**: Build the decompression chain from code analysis, loop until no more `exec` patterns found:
    ```python
    def decrypt_chain(code_text):
        payload = find_b64_payload(code_text)
        # Infer chain from imports in the code
        chain = []  # e.g., ['gzip', 'bz2', 'lzma', 'zlib']
        data = base64.b64decode(payload)
        for comp in chain:
            data = decompress(comp, data)
        return data.decode('utf-8')
    ```

## 🔗 Pattern: Reversed Base64 + Zlib (反转b64+zlib Lambda模式)
A stealthier obfuscation using **payload reversal** before encoding.
1.  **Structure**: `_ = lambda __ : __import__('zlib').decompress(__import__('base64').b64decode(__[::-1])); exec((_)(b'PAYLOAD'))`
2.  **Detection**: `[::-1]` reversal + `lambda` + `__import__` dynamic imports.
3.  **Solution**:
    ```python
    reversed_payload = payload[::-1]
    decoded = base64.b64decode(reversed_payload)
    result = zlib.decompress(decoded)
    ```

## 🔗 Pattern: Cross-Layer Variable Persistence (跨层变量持久化)
The lambda function `_` is defined in one layer but **reused across multiple subsequent layers**.
1.  **Structure**: Layer N defines `_ = lambda ...`, Layers N+1 to N+M all use `exec((_)(b'...'))`
2.  **Key Insight**: After decrypting the lambda definition layer, the subsequent layers ONLY contain `exec((_)(b'...'))` — the `_` variable's definition is "lost" but its behavior is known.
3.  **Solution**: Identify what `_` does from its definition, then apply that transform to all subsequent `exec((_)(b'...'))` payloads in a loop.

## 🔗 Pattern: Multi-Phase Recursive Decryption (多阶段递归解密)
When scripts use **multiple different obfuscation techniques** layered together:
1.  **Phase 1**: Process uniform pattern layers (e.g., 31 layers of chain compression)
2.  **Phase 2**: Handle pattern transition (e.g., chain → reversed-b64+zlib)
3.  **Phase 3**: Process new pattern layers (e.g., repeated `exec((_)(b'...'))` calls)
4.  **Phase 4**: Fallback detection (check for any remaining exec/eval patterns)

## 🔗 Pattern: Plain Base64+Zlib Single-Layer (简单 base64+zlib 单层解密)
最基础也是最常见的混淆模式，仅一层 base64 编码 + zlib 压缩。
1.  **Structure**: `encoded = """<large_base64_string>"""` → `base64.b64decode(encoded)` → `zlib.decompress()` → `exec()`.
2.  **Detection**: 仅导入 `base64`, `zlib`, `sys`；文件中有一个大型三引号字符串变量；底部 `exec(zlib.decompress(base64.b64decode(...)))`。
3.  **Solution**: 无需创建解密工具，直接静态提取 payload 并解压：
    ```python
    import base64, zlib
    compressed = base64.b64decode(encoded)
    code = zlib.decompress(compressed).decode('utf-8')
    with open("decrypted_output.py", "w", encoding="utf-8") as f:
        f.write(code)
    ```
4.  **Key Point**: 无额外依赖，无需虚拟环境，Python 标准库即可完成。

## 🔗 Pattern: Config-Body Separation (配置与业务逻辑分离混淆)
一种常见的青龙面板/自动化脚本混淆策略：用户可修改的配置以明文形式暴露在文件顶部，核心业务逻辑则压缩加密后通过 `exec()` 执行。
1.  **Structure**:
    - 文件顶部：注释说明 + `ACCOUNT_PREFIX = "XXX"` / `DELAY_MIN = 30` 等明文配置变量
    - 文件底部：`encoded = """..."""` + `exec(zlib.decompress(base64.b64decode(encoded)))`
    - 加密的业务代码在运行时读取顶部的全局配置变量
2.  **Detection**: 文件前半部分是可读的 Python 赋值语句（全大写变量名），后半部分是 base64 blob。
3.  **Solution**: 解密业务逻辑后，将**原始头部配置**与**解密后的代码**合并输出，保持配置可编辑性。
4.  **Key Point**: 解密时必须保留头部配置块，因为解密后的代码依赖这些全局变量。

## 🔗 Pattern: Recursive Fernet-Marshal Onion (递归 Fernet-Marshal 脱壳)
专门针对类似“套娃”式的嵌套混淆，每一层都包含新的 `_o` 字符串和 `Fernet` 密钥。
1.  **Structure**: `_o = '...'` -> `_b = "".join(chr(ord(c)-1) for c in _o)` -> `base64` -> `Fernet(key)` -> `zlib` -> `marshal.loads()`.
2.  **Detection**: 源码包含 `chr(ord(_c) - 1)` 位移逻辑及 44 字节的 bytes 类型密钥。
3.  **Solution**: 编写递归脚本 `peel_onion.py`，遍历 `code object` 的常量池 (`co_consts`)，提取最长字符串作为下一层载荷，提取 44 字节 bytes 作为密钥，循环执行直至获得源码。

## 🔗 Pattern: Python 3.14+ Bytecode Scavenging (高版本字节码常量探测)
当代码已解密为 `code object` 但因为 Python 版本过新（如 3.14+）导致 `uncompyle6` 等工具失效时，采取“干榨”策略提取信息。
1.  **Principle**: `code object` 的常量池 (`co_consts`) 和名称池 (`co_names`) 仍然包含明文格式的业务逻辑。
2.  **Detection**: `marshal.load` 成功但 `dis.dis` 报错或反编译报错。
3.  **Solution**: 编写 `scan_bytecode.py` 递归遍历所有嵌套的 `code object`，提取：
    -   **co_consts**: 寻找长字符串（通常是源码注释、API 模板、错误提示）。
    -   **co_names**: 寻找函数名、模块名（暗示业务逻辑：`requests`, `login`, `check_in`）。
    -   **co_filename**: 确认原始文件名提示。
4.  **Result**: 即使无法 100% 还原代码流，也能获取到完整的 API 通讯协议和配置变量。

    ```python
    # Main loop structure
    while has_exec(current):
        for pattern in [chain_pattern, reversed_pattern, simple_pattern]:
            result = try_pattern(current)
            if result:
                current = result
                break
        else:
            break  # No pattern matched
    ```

## 🧪 Advanced: exec/compile Interception (exec拦截解密)
When static analysis fails (e.g., code objects, dynamic variable resolution), **hook Python builtins**:
```python
import builtins
original_exec = builtins.exec
captured = []

def intercepted_exec(obj, *args):
    if isinstance(obj, str):
        captured.append(obj)
    original_exec(obj, *args)

builtins.exec = intercepted_exec
original_exec(compile(source_code, '<input>', 'exec'))
builtins.exec = original_exec  # Restore
```
> ⚠️ **Use with extreme caution** — only on scripts you understand. This EXECUTES the code.

## ⚠️ Safety Rules
- **Never Run `exec()`** on unknown payloads during analysis.
- **Isolate**: Use virtual environments to avoid polluting the user's workspace or conflicting with global packages.
- **Clean Up**: Remove the temporary decryption tool and venv when finished.

## Instruction for Agent
When using this skill:

1.  **Safety First**: NEVER directly run the decrypted code if it contains `exec()` or `eval()` without first inspecting the payload.
2.  **Add Standard Header**: The output decrypted script MUST start with a comment block explaining:
    -   Original source (if known).
    -   Methods used for decryption (e.g., "AES key extracted from...").
    -   Disclaimer: "Decrypted for educational/analysis purposes only."
3.  **Dependencies**: Check imports in the decrypted code and list required `pip install` commands in the comments.
4.  **Runnable**: Ensure the decrypted script is syntactically correct and runnable (e.g., unexpected indentation fixed).
5.  **Post-Decryption Cleanup** (必须执行):
    解密完成并确认结果正确后，**必须删除所有中间产物**：
    -   所有解密工具脚本（如 `decrypt_tool.py`、`recursive_decrypt.py`、`full_decrypt.py` 等）
    -   分析/调试脚本（如 `check_payload.py`、`analyze_step.py`、`inspect_bytes.py` 等）
    -   临时虚拟环境（`venv_decrypt/`）
    -   仅保留**最终解密结果文件**和**原始加密文件**
    -   主动询问用户确认后执行批量删除

## 🔗 Related Skills

- **python-obfuscator-pro**: Python 混淆技能（本技能的逆操作）
- **js-script-deobfuscator**: JavaScript 解混淆技能（类似概念，不同语言）
- **automation-script-dev-py**: Python 自动化开发技能
