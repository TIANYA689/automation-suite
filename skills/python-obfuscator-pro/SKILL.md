---
name: python-obfuscator-pro
description: Python 源码混淆、压缩包装与交付保护。用于用户要求保护自有 Python 自动化脚本、青龙脚本或工具源码时，支持轻量 Base64+zlib、配置区明文保留、marshal 字节码包装、多层压缩、AES/DES/RC4/RSA key wrapping、依赖检查、版本兼容验证和可回滚备份。
---

# Python Obfuscator Pro

目标：保护 Python 源码，同时保持可配置、可运行、可回滚。优先选择“足够用且可维护”的模式，不为炫技堆叠不可调试的壳。

## 启动协议

1. 复制原始 `.py`，保留 hash 和备份路径。
2. 确认目标 Python 版本；若用 `marshal`，版本必须与运行端一致。
3. 判断是否有用户配置区：环境变量说明、全大写配置、账号格式、cron、公告等默认明文保留。
4. 选择模式：light / config-body / advanced。
5. 生成产物后运行语法检查和无害自测。

## 模式选择

| 模式 | 适用 | 依赖 | 特点 |
|---|---|---|---|
| light | 普通脚本保护、青龙分发 | 标准库 | `zlib + base64 + exec`，兼容性最好 |
| config-body | 自动化脚本、需要用户改配置 | 标准库 | 顶部配置明文，业务体压缩包装 |
| marshal | 同版本 Python 内部分发 | 标准库 | `compile + marshal`，版本敏感 |
| advanced | 高保护需求 | pycryptodome | AES/DES/RC4/RSA + 多层压缩 |

## light 模板

```python
import base64, zlib, sys
encoded = """..."""
if __name__ == "__main__":
    try:
        exec(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"), globals())
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        sys.exit(1)
```

## Config-Body Separation

用于青龙/自动化脚本的默认模式。按行号或标记分割：

```text
# ===== 用户配置区开始 =====
ENV_NAME = "APP_TOKEN"
DELAY_MIN = 3
# ===== 用户配置区结束 =====
<业务代码加密为 encoded blob>
```

规则：
- 加密体通过 `exec(..., globals())` 读取明文配置变量。
- 明文区不得包含真实 token；只保留变量名、默认值、示例。
- 输出文件头写明“从哪一行/哪个标记之后开始包装”。

## Advanced 包装流程

1. `compile(source, '<protected>', 'exec')` 或 source bytes。
2. 可选 `marshal.dumps(code)`。
3. 随机组合 `zlib/gzip/bz2/lzma`。
4. 可选 AES/DES/RC4 加密；密钥用 RSA 或派生函数包装。
5. loader 内置解包函数，缺依赖时输出安装提示。

## 验证

- `python -m py_compile 输出.py` 通过。
- 如果脚本有 `--help`、dry-run 或 mock 模式，运行原版与保护版比对关键输出。
- `marshal` 模式必须在目标 Python 版本上测试。
- 失败时降级：advanced → config-body → light。

## 交付产物

```text
原名.protected.py
原名.original.backup.py
python-obfuscation-report.md
```

报告包含：源文件、SHA256、模式、明文配置范围、依赖、Python 版本、验证命令、限制。

## Related Skills

- `automation-script-dev-py`：先开发/整理 Python 自动化脚本，再交给本技能保护。
- `python-script-decryptor`：审计或还原包装结果。
- `js-script-obfuscator`：JS 保护。
- `automation-architect`：上层路由与交付检查。
