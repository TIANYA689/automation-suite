"""拆解器测试的共享夹具与沙箱基类。

三个测试文件（引擎 / 散文区间 / 呈现）共用这里的合成夹具与 `SandboxCase`，
所以它单独成模块。`run_offline_tests.py` 只收集 `test_*.py`，本模块不会被当成用例。

**导入顺序有要求**：本模块在被导入时把 `scripts/misc` 放进 `sys.path`，
所以测试文件必须**先**导入它，再导入被测模块。
"""

from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 与被测脚本同目录（`scripts/misc/`），而不是 `scripts/`：
# `scripts/misc` 不是包（无 `__init__.py`），同级脚本一律按模块名直接导入。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 模块级沙箱：Windows 上每次 rmtree 空目录也要近 1 秒，
# 放进逐用例的临时目录会拖垮整个套件。整模块共用一个，退出时一次性清理。
_SANDBOX = Path(tempfile.mkdtemp(prefix="script_teardown_"))
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)

# ---------------------------------------------------------------- 合成夹具

READABLE_PY = '''#!/usr/bin/env python3
"""合成样本：一个写得还算规整的签到脚本。"""
import os
import re
import time
import logging

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

USER_TARGET_COUNT = 5
TASK_CONFIG = {
    "PROXY_ENABLE": os.getenv("APP_PROXY_ENABLE", "0") == "1",
}
DELAY_SETTINGS = {"ACTION": (3, 6)}
MAX_RETRIES = 3


def mask_token(token):
    return f"{token[:8]}...{token[-8:]}" if token and len(token) > 16 else "****"


def get_accounts():
    raw = os.getenv("APP_AUTH", "")
    return [line.strip() for line in re.split(r"[&\\n]", raw) if line.strip()]


def request_with_retry(session, method, url, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return session.request(method, url, timeout=15, **kwargs)
        except Exception:
            time.sleep(2)
    raise RuntimeError("多次失败，熔断")


def login(session, account):
    return session.post("https://example.com/api/login", data={"u": account}, timeout=15)


def main():
    for account in get_accounts():
        session = requests.Session()
        session.proxies = {}
        logger.info("账号 %s", mask_token(account))
        request_with_retry(session, "GET", "https://example.com/api/checkin")
'''

# 压缩形态：单行超长。
MINIFIED_JS = "var a=1,b=2;" + ",".join(f"v{i}={i}" for i in range(200)) + ";console.log(a,b);"

# 混淆形态：`_0x` 标识符成片出现 + 连续转义串。
OBFUSCATED_JS = (
    'var _0x1a2b=["\\x6c\\x6f\\x67\\x69\\x6e","\\x74\\x6f\\x6b\\x65\\x6e"];'
    "var _0x3c4d=function(_0x5e6f,_0x7a8b){return _0x1a2b[_0x5e6f];};"
    "function _0x9c0d(_0x1e2f){return _0x3c4d(_0x1e2f-0x0);}"
    "var _0xab12=_0x9c0d(0x0),_0xcd34=_0x9c0d(0x1),_0xef56=_0x9c0d(0x2);"
    "var _0x1122=_0x9c0d(0x0),_0x3344=_0x9c0d(0x1),_0x5566=_0x9c0d(0x2);"
    "var _0x7788=_0x9c0d(0x0),_0x99aa=_0x9c0d(0x1),_0xbbcc=_0x9c0d(0x2);"
    "var _0xdd_ee=_0x9c0d(0x0),_0xff00=_0x9c0d(0x1);"
    "console.log(_0xab12,_0xcd34,_0xef56,_0x1122,_0x3344,_0x5566);"
)

# 诱饵：模块级就有副作用，且一旦执行必然抛 SystemExit。
# 拆解器只做 ast.parse，因此这两件事都不该发生——本文件最重要的证伪点。
DECOY_PY = (
    "from pathlib import Path\n"
    'Path(__file__).with_suffix(".executed").write_text("boom", encoding="utf-8")\n'
    'raise SystemExit("若本文件被执行，拆解器就已经越界")\n'
)

# 硬编码凭据形态。值刻意用占位词：公开释放检查会拦下"secret = '<真值>'"
# 这类赋值形态，而它拦得对——真实仓库里那种写法就是事故。
# 名字要如实描述它是什么，而不是它长得像什么。
SECRET_PY = 'API_KEY = "changeme-changeme"\n'

RISKY_PY = (
    "def loop():\n"
    "    while True:\n"
    "        try:\n"
    "            pass\n"
    "        except:\n"
    "            pass\n"
)

SYNTAX_ERROR_PY = "def broken(:\n    pass\n"

# ---------------------------------------------------------------- 散文过滤夹具
# 这四条夹具来自**实测误报**，不是设想：`scripts/automation` 自扫时，
# `route_query.py` 文档字符串里的示例命令「接码注册」被报成"接了接码平台"，
# `har_origin.py` 用法说明里的 `recaptcha.net` 被报成"处理验证码"。
# 关键词最密集的地方恰恰是叙述，不过滤噪声会淹掉真命中。

# 关键词只出现在叙述里：文档字符串（接码 / recaptcha）+ 行注释（User-Agent / deviceUuid）。
PROSE_PY = (
    '"""合成样本：说明文字里提到 接码 与 recaptcha，但代码里两者都没有。"""\n'
    "import time\n"
    "\n"
    "\n"
    "def main():\n"
    "    # 上游用 User-Agent 与 deviceUuid 做设备识别，本脚本没有这一步。\n"
    "    time.sleep(1)\n"
)

# 同样的关键词出现在**代码**里（字符串字面量）。过滤不能连它一起杀掉：
# `"User-Agent"` 是实打实的请求头证据，不是叙述。
EVIDENCE_PY = (
    "import time\n"
    "\n"
    "\n"
    "def main():\n"
    '    header = "User-Agent"\n'
    "    time.sleep(1)\n"
    "    return header\n"
)

# JS 行注释里的关键词是叙述。
PROSE_JS = "// 上游用 slider 处理滑块，这里没做\nconst x = 1;\n"

# JS 块注释里的关键词是叙述。
PROSE_BLOCK_JS = "/*\n * 说明：deviceUuid 由 localStorage 提供\n */\nconst x = 1;\n"

# 字符串里的 `//` **不是**注释开头。逐字符扫描若不跳过引号，
# 这一行后半段的真证据会被整段抹掉——那是静默的假阴性，比误报更难发现。
SLASH_IN_STRING_JS = 'const url = "https://example.com/a"; const h = {"User-Agent": "x"};\n'

# 长不透明串：混合大小写含数字，会被掩码。
OPAQUE = "aB3" * 12


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # name 可能是 `node_modules/x.js` 这类带层级的形式（用来验噪声目录被跳过），
    # 所以父目录要一起建，否则测试会以 FileNotFoundError 而不是断言失败的形式红。
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class SandboxCase(unittest.TestCase):
    """每个用例一个子目录，避免互相污染；目录本身不删（Windows 上 rmtree 很贵）。"""

    def case_dir(self, name: str) -> Path:
        directory = _SANDBOX / f"{self.__class__.__name__}_{name}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

__all__ = [
    "DECOY_PY",
    "EVIDENCE_PY",
    "MINIFIED_JS",
    "OBFUSCATED_JS",
    "OPAQUE",
    "PROSE_BLOCK_JS",
    "PROSE_JS",
    "PROSE_PY",
    "READABLE_PY",
    "RISKY_PY",
    "SECRET_PY",
    "SLASH_IN_STRING_JS",
    "SYNTAX_ERROR_PY",
    "SandboxCase",
    "_write",
]
