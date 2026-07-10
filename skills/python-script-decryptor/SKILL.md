---
name: python-script-decryptor
description: Python 脚本解密、脱壳与解混淆。用于分析 Base64/zlib/gzip/bz2/lzma、marshal、pyc、Fernet、AES/DES/RSA/RC4、exec/eval、lambda 包装、反转 payload、配置区明文+业务体加密、多层递归包装，并输出可审计的解密源码、层级证据和依赖说明。
---

# Python Script Decryptor

目标：静态优先、逐层脱壳、只 dump 不直接执行未知载荷。参照 open-reverselab 风格：每层有证据、每个结论可复查、最终产物落盘。

## 启动协议

1. 复制原始脚本，记录路径、大小、SHA256。
2. 静态识别 imports、payload、key、入口 `exec/eval/compile`。
3. 并行两条路径：
   - 静态解包：提取 payload → 解码/解压/解密 → dump。
   - 拦截路径：仅在静态失败且理解风险时，用 hook 捕获 `exec` 参数。
4. 输出最终解密版、层级报告和依赖说明；清理中间工具前保留可复查报告。

## 识别矩阵

| 信号 | 模式 | 动作 |
|---|---|---|
| `base64`, `zlib`, 大三引号字符串 | plain b64+zlib | 直接提取解压 |
| 顶部配置明文 + 底部 encoded | config-body | 保留配置头，合并解密业务体 |
| `gzip/bz2/lzma/zlib` 链 | 多层压缩 | 按出现顺序或代码调用顺序逐层解压 |
| `[::-1]` + b64 | reversed payload | 先反转再解码 |
| `marshal.loads` | bytecode/code object | dump code object，尝试反编译或扫描常量 |
| `Fernet`, `Crypto.Cipher` | 对称/非对称加密 | 提取 key/iv/mode，复刻 decrypt，不执行业务 |
| `_ = lambda __: ...; exec((_)(b"..."))` | lambda 持久变换 | 解析 lambda 后循环处理后续 payload |

## 静态解包骨架

```python
import base64, zlib, gzip, bz2, lzma, marshal

def try_decode(data):
    if isinstance(data, str): data = data.encode()
    # 按识别到的链条逐层处理，不猜测执行
    return data

# BAD: exec(decrypted)
# GOOD:
Path('decrypted_output.py').write_text(decrypted.decode('utf-8'), encoding='utf-8')
```

## 多层递归策略

```text
while current contains exec/eval/compile wrapper:
  identify wrapper pattern
  extract payload and transform chain
  dump layer_N.py or layer_N.bin
  set current = decoded output
stop when readable source, code object, or unknown binary loader
```

规则：
- 每层保留 `layer_N` 摘要：pattern、payload length、输出 hash、下一步判断。
- 输出为 bytes 且无法 UTF-8 解码时，不强行当源码；保存 `.bin` 并检查 marshal/pyc/magic。
- Python 3.14+ bytecode 无法反编译时，扫描 `co_consts/co_names/co_filename` 提取 API、函数名和字符串证据。

## Config-Body 合并

如果原文件顶部是可读配置，解密输出应保持：

```text
原始配置头
# ===== 解密后的业务逻辑 =====
<decrypted body>
```

确保业务体能读取头部全局变量；不要丢失用户可编辑配置说明。

## Exec 拦截兜底

只在静态失败时使用，并把网络/文件/进程危险行为 stub 掉。

```python
import builtins
captured = []
orig_exec = builtins.exec

def intercepted_exec(obj, *args, **kwargs):
    if isinstance(obj, (str, bytes)):
        captured.append(obj)
        return None
    return orig_exec(obj, *args, **kwargs)
```

## 交付产物

```text
原名_decrypted.py
python-decrypt-report.md
layers/layer_01.py|bin ...
```

报告包含：原文件 hash、识别模式、每层转换、最终依赖、未解开部分、验证命令。

## 清理规则

解密完成后删除临时 `decrypt_tool.py`、`inspect_*.py`、临时 venv、缓存目录；保留原始文件、最终解密结果和报告。若用户要求保留中间层用于审计，则把 layers 目录纳入报告。

## Related Skills

- `python-obfuscator-pro`：本技能的逆向配套。
- `automation-script-dev-py`：把解密版改造成可维护自动化脚本。
- `js-script-deobfuscator`：JS 解混淆。
- `automation-architect`：上层路由与质量门。
