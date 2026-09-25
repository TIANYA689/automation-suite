---
name: python-obfuscator-pro
description: Python 混淆加密专家。使用多层加密 (AES、DES、RC4、RSA) 和多种压缩方法保护 Python 源代码。
version: 1.2.0
---

# Python Obfuscator Pro Skill

You are an expert in Python code protection and obfuscation. Use this skill when the user wants to protect their Python source code from casual inspection or reverse engineering.

## ⚡ Lightweight Mode: Plain Base64+Zlib (轻量加密)
最简单的加密方式，适合保护青龙面板/自动化脚本的业务逻辑，无额外依赖。

### 标准模式（全文件加密）
```python
import base64, zlib

with open("source.py", "r", encoding="utf-8") as f:
    source = f.read()

compressed = zlib.compress(source.encode("utf-8"))
encoded = base64.b64encode(compressed).decode("utf-8")

# 输出加密后的 loader 脚本
loader = f'''import base64, zlib, sys
encoded = """{encoded}"""
if __name__ == "__main__":
    try:
        exec(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))
    except Exception as e:
        print(f"❌ 执行失败：{{e}}")
        sys.exit(1)
'''
```

### Config-Body Separation 模式（配置头明文保留）
适用于需要用户自行修改配置变量的脚本。将文件按指定行号分割：
- **配置头**（明文保留）：用户可编辑的全大写变量（如 `ACCOUNT_PREFIX`、`DELAY_MIN`）
- **业务体**（加密）：核心逻辑通过 base64+zlib 压缩

```python
import base64, zlib

with open("source.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

split_line = 42  # 配置头结束行号
header = "".join(lines[:split_line - 1])
body = "".join(lines[split_line - 1:])

compressed = zlib.compress(body.encode("utf-8"))
encoded = base64.b64encode(compressed).decode("utf-8")

# 组装：配置头 + 加密体
output = header + "\nimport base64\nimport zlib\nimport sys\n\n"
output += f'encoded = """{encoded}"""\n\n'
output += 'if __name__ == "__main__":\n'
output += '    try:\n'
output += '        exec(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))\n'
output += '    except Exception as e:\n'
output += '        print(f"❌ 执行失败：{e}")\n'
output += '        sys.exit(1)\n'
```

**关键点**: 加密的业务代码运行时会读取全局作用域中配置头定义的变量，因此配置头必须在 `exec()` 之前执行。

---

## 🛡️ Advanced Mode: Multi-Layer Encryption (多层加密)
This obfuscator employs a "Layered Defense" strategy:
1.  **Multiple Encryption Algorithms**: AES-256 (CBC/ECB), DES, RC4, and RSA for key protection.
2.  **Varied Compression**: zlib, gzip, bz2, lzma to reduce payload size and confuse signature scanners.
3.  **Serialization**: utilizing `marshal` to serialize compiled bytecode, making static analysis harder.
4.  **Dynamic Key Generation**: Keys are derived or decrypted at runtime, never stored in plain text.

## 🏗️ Obfuscation Workflow

### 1. Preparation
**Goal:** Prepare the source code and encryption keys.
1.  **Read Source Code**: Read the target Python script.
2.  **Generate Master Keys**: Create strong random keys for AES, DES, and RC4.
3.  **Encrypt Master Keys**: Use RSA (public key) to encrypt the symmetric keys. The *private key* is embedded in the script (or fetched remotely) to decrypt them at runtime. *Note: Embedding private key is less secure but allows standalone execution.*

### 2. The "Onion" Packaging
**Goal:** Wrap the code in multiple layers of processing.
1.  **Serialize**: `marshal.dumps(compile(source_code, '<string>', 'exec'))`.
2.  **Layer Loop**:
    *   Define a random order of operations (e.g., `['gzip', 'aes', 'rc4', 'lzma']`).
    *   Iteratively apply each operation to the payload.
    *   Store the *reverse* list of operations for the decoder.

### 3. Template Generation
**Goal:** Create the loader script that reverses the process.
1.  **Imports**: standard libs (`base64`, `zlib`, etc.) + `pycryptodome`.
2.  **Key Decryption Block**:
    *   Embed encrypted keys (AES/DES/RC4).
    *   Embed the RSA Private Key (Base64 encoded).
    *   Runtime decrypt the master keys using RSA.
3.  **Decryption Functions**: Include the necessary decryption logic (AES `unpad`, RC4 class, etc.).
4.  **The `d()` Function**: The recursive processor that takes `(payload, ops_list)`.
5.  **Execution Param**:
    *   `e = "BASE64_PAYLOAD"`
    *   `b = "BASE64_OPS_LIST"`
    *   `exec(d(base64.b64decode(e), eval(base64.b64decode(b))))`

## 🚀 Optimization & Best Practices
1.  **Randomization**:
    *   Randomize the *order* and *number* of encryption/compression layers for every build.
    *   Randomize variable names in the loader (e.g., don't use `RAW_AES_KEY`, use `_k1`).
2.  **Anti-Tamper (Optional)**:
    *   Add a checksum verification of the loader code itself.
    *   Add expiry date checks or remote license validation.
3.  **Dependency Check**:
    *   Ensure the output script checks for `pycryptodome` and prompts the user to install if missing.

## ⚠️ Limitations
- **Python Version**: `marshal` format is specific to Python versions. Code obfuscated on Python 3.10 might not run on 3.8. *Recommendation: Use source string encryption instead of marshal if version compatibility is critical.*
- **Performance**: Startup time will be slower due to decryption overhead.
- **False Positives**: Heavily obfuscated scripts may be flagged by antivirus software.

## Instruction for Agent
When using this skill:

1.  **Add Standard Header**: The output script MUST start with a comment block explaining:
    -   That the script is obfuscated/encrypted.
    -   Required dependencies (e.g., `pip install pycryptodome`).
    -   Python version compatibility (ask user if unsure).
    -   Disclaimer about safety/usage.
2.  **Verify Compatibility**: Ask the user for their target Python version before obfuscating (marshal is version-sensitive).
3.  **Test Locally**: ALWAYS run the obfuscated script locally to ensure it decrypts and executes correctly before delivering.
4.  **Config-Body Separation**: 当用户的脚本有可配置变量时，**必须使用** Config-Body Separation 模式，保留配置头明文。在加密前询问用户"从第几行开始加密"。

## 🔗 Related Skills

- **python-script-decryptor**: Python 解密技能（本技能的逆操作）
- **js-script-obfuscator**: JavaScript 混淆技能（类似概念，不同语言）
- **automation-script-dev-py**: Python 自动化开发技能
