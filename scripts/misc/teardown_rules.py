#!/usr/bin/env python3
"""第三方脚本拆解的**规则表**：检测维度、风险规则、配套文件与分类常量。

与 `script_teardown.py` 的分工：本文件是**数据**，那个文件是**引擎**。
拆开的理由不是行数，是变更频率不同——加一个检测维度、加一条"不该照抄的写法"，
只需要改这张表；引擎（扫描、掩码、对齐、渲染）不因此变动。
把两者放一个文件里，每次加维度都要动一个千行文件。

零第三方依赖，只被 `script_teardown.py` 与它的测试导入。

用法（作为库）：
    from teardown_rules import FEATURES, RISKS, TIERS
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---------------------------------------------------------------- 扫描范围

DEFAULT_EXTENSIONS = (".py", ".js", ".ts", ".mjs", ".cjs", ".sh", ".ps1", ".bat")
LANG_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".sh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
}

# 第三方脚本目录里常见的非源码噪声：不是"没材料"，是"本来就不该看"。
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "site-packages",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
    }
)

# 静态库/打包产物目录：能读，但它是"别人交付的成品"，不是可借鉴的写法。
VENDOR_DIR_NAMES = frozenset(
    {"vendor", "vendors", "lib", "libs", "third_party", "third-party", "dist", "build", "min"}
)
BUNDLE_HINT = re.compile(r"\.(min|bundle|chunk|vendor)\.[cm]?js$", re.IGNORECASE)

# 掩码规则：长不透明串、邮箱、手机号。降噪与防误贴，**不是安全边界**。
MASK_RUN = re.compile(r"[A-Za-z0-9_\-]{24,}")
MASK_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MASK_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 混淆判据。
OBFUSCATED_IDENT = re.compile(r"_0x[0-9a-fA-F]{3,}")
BASE64_BLOB = re.compile(r"[\"'][A-Za-z0-9+/=]{200,}[\"']")
ESCAPE_RUN = re.compile(r"(?:\\x[0-9a-fA-F]{2}){8,}")

ALL_LANGS = ("python", "javascript", "shell", "powershell", "batch")
SCRIPT_LANGS = ("python", "javascript")

GROUPS = ("配置与账号", "网络与协议", "编排与并发", "日志与产物", "安全与识别", "运行与交付")

TIERS = ("direct", "adapt", "borrow", "refuse")
TIER_LABELS = {
    "direct": "直接复用",
    "adapt": "改造后复用",
    "borrow": "只可借鉴",
    "refuse": "拒绝吸收",
}

CLASSIFICATION_LABELS = {
    "readable": "可读",
    "minified": "压缩",
    "obfuscated": "混淆",
    "vendor": "静态库",
    "unreadable": "读不出",
}


# ---------------------------------------------------------------- 检测维度


class Feature(NamedTuple):
    """一个可观测的基础设施维度。

    tier 是**默认档位**，不是最终裁定：同一维度在不同语境下可以升降档，
    最终结论由 agent 按 `references/reuse-classification.md` 复核后写入报告。
    """

    id: str
    label: str
    group: str
    tier: str
    pattern_ref: str
    langs: tuple[str, ...]
    regexes: tuple[str, ...]


FEATURES: tuple[Feature, ...] = (
    # ---- 配置与账号 ----
    Feature("config", "配置集中", "配置与账号", "direct", "PY-P9/P9.1 · JS-P8.2", ALL_LANGS, (
        r"\bclass\s+Config\b",
        r"^TASK_CONFIG\s*[:=]",
        r"^USER_[A-Z0-9_]+\s*=",
        r"^\s*(?:const|let|var)\s+CONFIG\s*=",
        # 实测补（雨云脚本 68-71 行）：PY-P9 说的「配置头」就是**成块**的模块级常量，
        # 而上面几条只认 `Config` 类与特定前缀名，一个都不命中。
        # 要求**连续两行**才认：单个 `MAX_RETRIES = 3` 到处都是，
        # 认它等于把「配置集中」变成永远命中，那这个维度就没信息量了。
        r"^(?:[A-Z][A-Z0-9_]{2,}\s*[:=].*\n){2,}",
    )),
    Feature("env", "环境变量读取", "配置与账号", "direct", "PY-P9.1 · JS-P8.2", ALL_LANGS, (
        r"os\.getenv\s*\(",
        r"os\.environ",
        r"process\.env",
        # PowerShell 的环境变量是 `$env:NAME`——`$env:` 这个前缀只在 PowerShell 里成立，
        # 所以它命中必然是环境变量，不是"某个也叫 env 的东西"。
        r"\$env:",
    )),
    Feature("accounts", "多账号加载", "配置与账号", "adapt", "PY-P3/P3.1/P3.3 · JS-P8.2", SCRIPT_LANGS, (
        r"def\s+get_accounts\b",
        r"ACCOUNT_SEP",
        # 必须带 `re.` 前缀：裸 `.split("&")` 在真实代码里绝大多数是拆 URL query
        # （实测 `har_to_fixture.py` 的 `query.split("&")` 被误报成多账号加载）。
        r"re\.split\(\s*r?[\"'][&\\n]",
        r"accounts\.(?:json|txt)",
        # 实测补（雨云脚本）：真脚本更常见的写法是**模块级账号列表 + 遍历**，
        # 而 `ACCOUNT_SEP` 只认分隔符那一种，`ACCOUNTS = [` 一个都不命中。
        # 只认**集合形态**，不认单个 `ACCOUNT = "..."`——后者是"单账号硬编码"，
        # 与"多账号加载"不是一回事，收进来就把这一档的意思搞浑了。
        r"\bACCOUNTS\s*=\s*[\[\(]",
        r"\baccount_?list\b",
        r"多账号",
    )),
    Feature("login", "登录与凭证", "配置与账号", "borrow", "PY-P4/P4.1/P4.2 · JS-P3.1", SCRIPT_LANGS, (
        r"def\s+login\b",
        r"refresh_token",
        r"storage_state",
        r"token_cache",
    )),
    # ---- 网络与协议 ----
    Feature("request", "请求封装", "网络与协议", "adapt", "PY-P6 · JS-P1.2", SCRIPT_LANGS, (
        r"requests\.Session\s*\(",
        r"httpx\.(?:Client|AsyncClient)",
        r"aiohttp\.ClientSession",
        r"axios\.(?:create|get|post)",
        r"\bfetch\s*\(",
    )),
    Feature("timeout", "超时设置", "网络与协议", "direct", "PY-P6", ALL_LANGS, (
        # `timeout=` 是 Python 的赋值，`timeout: 10000` 是 JS 对象字面量 / Python 注解。
        # 两条都要求**冒号或等号后面还有内容**，且用 `[ \t]` 而不是 `\s`——
        # `\s` 会跨行，`if timeout:` 后面那一行会被它吃掉，等于没排除。
        # `(?!=)` 排除 `timeout ==`（比较，不是赋值）。
        r"timeout[ \t]*=(?!=)[ \t]*\S",
        r"timeout[ \t]*:[ \t]*\S",
    )),
    Feature("retry", "重试与熔断", "网络与协议", "adapt", "PY-P6/P6.1/P6.3 · JS-P1.1", SCRIPT_LANGS, (
        r"\bRetry\s*\(",
        r"MAX_RETRIES|maxRetries",
        r"backoff",
        r"for\s+attempt\s+in",
        # 实测补（可读 JS 样本）：重试上限在 JS 里常叫 `maxAttempts`（camelCase）
        # 或 `max_attempts`，上面只认 `MAX_RETRIES|maxRetries`——又是"只认得一种命名"。
        # 同一文件里 `this.maxAttempts = config.maxAttempts || 50` 与
        # `for (let attempt = 1; attempt <= this.maxAttempts; attempt++)` 两条都不命中，
        # 而这两行正是这个脚本的**重试机制本身**。
        r"[Mm]ax_?[Aa]ttempts|MAX_ATTEMPTS",
        # `for\s+attempt\s+in` 是 Python 的重试循环；JS 是 `for (let attempt = 1; ...)`。
        # 要求括号 + 声明关键字，避免把 `for (attempt of xs)` 这类遍历误收进来。
        r"for[ \t]*\([ \t]*(?:let|var|const)[ \t]+attempt\b",
    )),
    Feature("proxy", "代理支持", "网络与协议", "adapt", "PY-P1/P1.1-P1.3", ALL_LANGS, (
        # `proxies=` / `proxy=` 是 Python 的赋值；JS 把代理写在对象字面量里，
        # 是 `proxy: 'http://…'`（冒号）。同 `timeout` 那条：声明覆盖 ALL_LANGS，
        # 实际只写了 Python 的语法形状。
        # 两条都要求**冒号或等号后面还有内容**（`[ \t]` 不跨行），否则会命中
        # `if '@' in proxy:`——那是语句末尾的冒号，不是代理配置（实测在测试夹具里踩到过）。
        r"proxies[ \t]*=(?!=)[ \t]*\S",
        r"proxies[ \t]*:[ \t]*\S",
        r"\bproxy[ \t]*=(?!=)[ \t]*\S",
        r"\bproxy[ \t]*:[ \t]*\S",
        r"def\s+get_proxy\b",
    )),
    Feature("protocol", "多阶段协议", "网络与协议", "borrow", "PY-P6.2/P6.4", SCRIPT_LANGS, (
        r"multipart/form-data",
        r"boundary\s*=",
        r"WebKitFormBoundary",
        r"def\s+\w*stage\w*\(",
    )),
    # ---- 编排与并发 ----
    Feature("concurrency", "并发执行", "编排与并发", "adapt", "PY-P8.2/P8.6 · JS-P6.3", SCRIPT_LANGS, (
        r"ThreadPoolExecutor",
        r"asyncio\.(?:Semaphore|gather)",
        r"multiprocessing",
        r"Promise\.all",
    )),
    Feature("lock", "并发锁", "编排与并发", "direct", "PY-P11.2", SCRIPT_LANGS, (
        r"threading\.Lock|Lock\s*\(\s*\)",
        r"print_lock",
    )),
    Feature("delay", "节奏控制", "编排与并发", "borrow", "PY-P2.2", ALL_LANGS, (
        r"human_delay|DELAY_SETTINGS",
        r"random\.(?:uniform|randint)\s*\(",
        r"time\.sleep\s*\(",
        # 实测补（可读 JS 样本）：`time.sleep` 是 Python 的等待写法，JS 里是
        # `setTimeout`，或自建一个 `delay(ms)`——实测样本第 22-24 行
        # `delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }`
        # 与第 53 行 `await this.delay(this.retryDelayMs)` 都不命中，
        # 而这个脚本的"失败重试节奏"就靠它。上面三条全是 Python 写法。
        # 只认**调用形态**，不认裸 `delay`——裸词会命中 `delay = 5` 这类配置值。
        r"setTimeout[ \t]*\(",
        r"\bdelay[ \t]*\(",
        # shell 的等待是 `sleep 5`（无括号、直接跟秒数），上面三条一条都不命中。
        # 要求跟数字，避免把 `sleep()` 这类调用或散文里的 "sleep" 收进来。
        r"\bsleep[ \t]+\d",
    )),
    Feature("cycle", "等待与循环", "编排与并发", "adapt", "PY-P8.3/P8.4", ALL_LANGS, (
        r"MAX_CYCLES|max_cycles",
        # Python 的 `while True` 不带括号，JS / C 系是 `while (true)`。
        r"while[ \t]+True",
        r"while[ \t]*\([ \t]*true[ \t]*\)",
        r"progress|进度",
    )),
    Feature("batch", "批次可观测", "编排与并发", "adapt", "PY-P8.7", SCRIPT_LANGS, (
        r"run_id|runId",
        r"worker_?status",
        # 原为裸 `batch`，实测误报：`batch_size = random.randint(2, 3)` 是
        # **并发批量大小**，与 PY-P8.7 要的"run 历史 / worker 状态 / 取消与清理"
        # 是两回事。在 17 个真实样本里裸 `batch` 命中 1 次，**真命中 0 次**。
        # 改成要求"批次身份 / 批次报告"这种可观测语境。
        r"batch_?(?:id|index|report|summary|history)\b",
        r"run_?history|run_?record",
    )),
    # ---- 日志与产物 ----
    Feature("logging", "日志输出", "日志与产物", "adapt", "PY-P11 · JS-P8.5", ALL_LANGS, (
        r"logging\.(?:getLogger|basicConfig)",
        r"\blogger\.(?:info|warning|error)",
        r"console\.(?:log|info)",
        r"Write-Host",
        # 实测补（雨云脚本 L105）：这类脚本跑在面板里，输出被面板捕获，
        # 所以它们**不用 `logging` 模块**，而是自己写一个 `def log(msg)`。
        # 上面四条只认标准库/浏览器写法，一个都不命中——同一个脚本里
        # `ACCOUNTS = [...]` 与配置头也这样被漏掉。这是同一类系统性偏差：
        # **只认得标准库写法，认不出自建同名设施**。
        r"^def\s+log\w*\s*\(",
    )),
    Feature("mask", "敏感信息脱敏", "日志与产物", "direct", "PY-P11.1", ALL_LANGS, (
        # 命名习惯不止 `mask`。实测 `har_probe.py` 的 `def redact(...)`（第 104 行）
        # 一个都不命中，**却命中了第 599 行那句 `"输出已脱敏（--no-redact 可关闭）"`**
        # ——真证据漏了、提示语反被采信。与 `logging` 那条是同一类偏差的另一半：
        # 只认得一种命名，认不出同一件事的其它叫法。
        r"def\s+(?:mask|redact|hide|scrub|sanitize|anonymi[sz]e)\w*",
        # 中文函数名（`def 脱敏(...)`）算证据；**裸 `脱敏` 不算**——
        # 它是描述性词，出现在"给人看的字符串"里的概率远高于出现在实现里。
        # 注意散文过滤管不到这里：`"输出已脱敏"` 是**字符串字面量**，不是注释，
        # 而字符串字面量按纪律不剔（`"User-Agent"` 就是实打实的协议证据）。
        r"def\s+\w*(?:脱敏|打码)",
        # JS 的脱敏函数没有 `def`：`function mask(v) {` 或类方法 `mask(v) {`。
        # 两条都要求**函数头形态**（`)` 紧跟 `{`），所以不会命中普通调用 `mask(x)`；
        # Python 里 `mask(x) {` 语法非法，这条只会落在 JS / shell 上。
        r"(?:function[ \t]+)?(?:mask|redact|hide|scrub|sanitize|anonymi[sz]e)\w*[ \t]*\([^)]*\)[ \t]*\{",
        # 原为裸 `\*\*\*\*`，实测误报：雨云脚本的 `"ocr_f315317b2ee2ec****"` 是
        # **作者自己打码后的配置字面量**，脚本里连一个脱敏函数都没有，
        # 却被报成「敏感信息脱敏」并落进「直接复用」——四档里最不该出错的一档。
        # 改成只认**拼接形态**（`token[:4] + "****"`、`"*" * len(x)`），
        # 那才是脱敏函数在做的事；夹在字符串中段的星号不再算证据。
        r"[\"']\*{2,}[\"']",
        r"[\"']\*[\"']\s*\*\s*len\(",
    )),
    Feature("cache", "状态缓存", "日志与产物", "adapt", "PY-P13.3", ALL_LANGS, (
        r"CacheManager",
        r"checkpoint|断点",
        r"\.tmp\b",
    )),
    Feature("notify", "通知推送", "日志与产物", "adapt", "PY-P12/P12.1 · JS-P6.4", ALL_LANGS, (
        r"\bnotify\b|sendNotify",
        r"pushplus|wxpusher|serverchan|Server酱",
        r"telegram|bark",
    )),
    # ---- 安全与识别 ----
    Feature("device", "设备身份", "安全与识别", "borrow", "PY-P2/P2.1/P2.3", SCRIPT_LANGS, (
        r"user_?agent|User-Agent",
        # 不收裸 `fingerprint`：实测 `build_routing_index.py` 的 `{"fingerprint": hash}`
        # 是**内容指纹**，不是设备指纹。宁可漏（漏了会进"缺口"被人看到），
        # 不可误报——误报会直接进复用候选，而候选是给人照着做的。
        r"device_?id|deviceUuid|device_?fingerprint|getDeviceInfo",
    )),
    Feature("sign", "签名与加密", "安全与识别", "borrow", "PY-P7/P7.1 · JS-P5/P5.1", ALL_LANGS, (
        r"hashlib\.|hmac\.",
        r"Crypto\.(?:Cipher|Util)",
        r"crypto-js|CryptoJS",
        r"def\s+\w*sign\w*\(",
        # Node 内置 `crypto` 的签名 API。注意 `hmac\.` 那条要求点号，
        # 而 Node 的写法是 `crypto.createHmac('sha256', key)`——**不命中**。
        r"createHmac|createHash|createCipheriv",
    )),
    Feature("captcha", "验证码处理", "安全与识别", "adapt", "PY-P5.3 · JS-P4.1", ALL_LANGS, (
        r"captcha",
        r"slider|滑块",
        r"geetest|hcaptcha|recaptcha",
    )),
    Feature("mail", "邮箱接入", "安全与识别", "adapt", "PY-P5.1/P5.4", ALL_LANGS, (
        r"imaplib|smtplib",
        r"mailbox|temp_?mail|临时邮箱",
        # Node 侧的事实标准：`nodemailer` 发信、`imapflow` / `mailparser` 收信。
        # 上面两条是 Python 标准库，JS 里一个都不命中。
        r"nodemailer|imapflow|mailparser",
    )),
    Feature("sms", "接码接入", "安全与识别", "adapt", "PY-P5.2", ALL_LANGS, (
        r"\bsms\b|短信",
        r"get_phone|wait_code|接码",
    )),
    # ---- 运行与交付 ----
    Feature("cli", "命令行入口", "运行与交付", "borrow", "PY-P10", ALL_LANGS, (
        r"argparse\.ArgumentParser",
        r"sys\.argv",
        r"commander|yargs",
    )),
    Feature("schedule", "定时任务", "运行与交付", "adapt", "PY-P10.1", ALL_LANGS, (
        r"\bcron\b|Cron",
        r"schedule\.every",
        r"New-ScheduledTask",
    )),
)

FEATURE_BY_ID = {feature.id: feature for feature in FEATURES}


class DeliverySpec(NamedTuple):
    """配套文件维度：按**目录里有没有这个文件**判定，不按源码正则。

    早先把它写成 `^#\\s+\\S` 的源码正则，结果是每个带注释的 Python 文件
    都命中"随附文档"——一条把注释误认成交付物的假阳性。配套文件是**交付形态**，
    它的证据在目录清单里，不在代码文本里。
    """

    id: str
    label: str
    names: tuple[str, ...]
    pattern_ref: str


DELIVERY_SPECS: tuple[DeliverySpec, ...] = (
    DeliverySpec("readme", "随附文档", ("readme.md", "readme.txt"), "PY-P10 · JS-P7"),
    DeliverySpec("env_example", "配置示例", (".env.example", ".env.sample"), "PY-P9.1 · JS-P8.2"),
    DeliverySpec("deps", "依赖清单", ("requirements.txt", "package.json"), "PY-P10 · JS-P7"),
)


# ---------------------------------------------------------------- 风险规则


class Risk(NamedTuple):
    """一条"不该照抄的写法"。

    tier=refuse 的项**不进复用候选**，只进风险清单——这是"降低安全机制不吸收"的落点。
    """

    id: str
    label: str
    tier: str
    why: str
    regexes: tuple[str, ...]
    redact: bool


RISKS: tuple[Risk, ...] = (
    Risk(
        "hardcoded_secret",
        "硬编码凭据",
        "refuse",
        "凭据写死在源码里（含写成环境变量默认值）：不吸收，且不得抄进任何交付物",
        (
            r"(?i)\b(?:password|passwd|pwd|token|secret|api_?key|access_?key)\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']",
            r"(?i)authorization\s*[:=]\s*[\"']bearer\s+[A-Za-z0-9._\-]{16,}",
            # 实测补（雨云脚本 L77）：`os.environ.get("OCR_TOKEN", "ocr_...")`
            # ——**默认值就是真凭据**，等于没走环境变量，而且比直接写死更容易被忽略：
            # 肉眼扫一眼看到 `os.environ.get` 就以为是合规写法了。
            # 两个条件同时要求，避免 `os.getenv("X", "0")` 这类默认值满天飞：
            # 变量名要像凭据，默认值要非空且够长。
            r"(?i)(?:environ\.get|getenv)\(\s*[\"'][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|PWD|KEY|CREDENTIAL)[A-Z0-9_]*[\"']\s*,\s*[\"'][^\"'\s]{8,}[\"']",
        ),
        True,
    ),
    Risk(
        "captcha_bypass",
        "风控绕过",
        "refuse",
        "验证码/风控绕过或伪造：属于降低安全机制，不吸收；需要时走合规挑战（PY-P5.3）",
        (r"(?i)bypass|crack_?captcha|fake_?captcha|绕过(?:验证|风控)",),
        False,
    ),
    Risk(
        "anti_debug",
        "反调试与自防御",
        "refuse",
        "反调试/自防御属于**保护侧**能力，不由拆解流程吸收；读懂即可，不复制",
        (r"(?i)\bdebugger\b", r"sys\.settrace|ptrace", r"(?i)anti[_-]?debug"),
        False,
    ),
    Risk(
        "proxy_credential_in_url",
        "代理凭据明文",
        "refuse",
        "代理账号密码拼进 URL 并可能进日志：不吸收，凭据必须与日志隔离",
        (
            # 负向先行断言排除**作者自己打的码**：实测三个样本里
            # `display = f"http://***:***@{parts[-1]}"` 全被报成"凭据明文"，
            # 而它恰恰是作者**主动打码后**才打印的——把「已经做了隔离」读成
            # 「没有隔离」，还落进 refuse 档（最不该出错的一档）。
            # 这与 `"ocr_...****"` 是同一类：**星号是打码，不是泄漏**。
            # 只排除「凭据段整段都是 `*` 与 `:`」这一**无歧义**形态：
            # `realuser:***@` 仍然会被报出来——它毕竟把用户名拼进了 URL。
            r"(?i)https?://(?![\*:]+@)[^/\s\"']+:[^/\s\"']+@",
        ),
        True,
    ),
    Risk(
        "credential_egress",
        "会话凭据离开 CookieJar",
        "refuse",
        "把整个 cookie jar 掏成 dict（常紧接着 POST 给打码/接码平台，或落盘）："
        "等于把账号会话交给陌生服务器，不吸收；要过验证走本项目的人工交接（PY-P5.3）",
        (
            # 实测原形（雨云脚本 L1812-1821）：先 `{c.name: c.value for c in sess.s.cookies}`
            # 把 cookie jar 掏空成 dict，再 `json={"cookies": ..., "token": ...}`
            # POST 到 `{CAPTCHA_API_URL}/solve`——而那个域名是别人的动态 DNS。
            # 这类写法在同类脚本里很常见，且比"硬编码凭据"更隐蔽：
            # 源码里看不到任何密钥，秘密是在**运行时**被送出去的。
            #
            # 掏 jar 的那条**不限定变量名**：实测叫 `cookies_dict`、`jar` 的都有，
            # 绑死 `cookies\s*=` 等于只认一种写法（第一版就是这么写错的）。
            r"\{[^\n}]*for\s+\w+\s+in\s+[^\n]*\.cookies\b",
            r"(?i)[\"']cookies[\"']\s*:",
        ),
        False,
    ),
    Risk(
        "unbounded_loop",
        "`while True` 常驻循环",
        "caution",
        "正则只认 `while True` 本身，**看不出有没有 `break` / 轮数上界**"
        "（实测 `bing_rewards_v2.6.py:2951` 是个带 `break` 的查找循环，"
        "被误报成无界）：必须回原文确认；确属无界才需要补上界（PY-P8.4）",
        (r"while\s+True\s*:",),
        False,
    ),
    Risk(
        "bare_except",
        "裸 except 吞错",
        "caution",
        "裸 `except:` / `except Exception: pass` 会把失败伪装成成功：吸收前补分层错误处理（PY-P6）",
        (r"except\s*:", r"except\s+Exception\s*:\s*pass"),
        False,
    ),
    Risk(
        "tls_verify_off",
        "关闭 TLS 校验",
        "caution",
        "出现 `verify=False` 或 `disable_warnings`：**正则分不清是单次请求还是全局**"
        "（实测多为单个 `requests.get(..., verify=False)`）：吸收前必须限定到授权目标"
        "并说明理由（PY-P1.1）",
        (r"verify\s*=\s*False", r"disable_warnings"),
        False,
    ),
)
