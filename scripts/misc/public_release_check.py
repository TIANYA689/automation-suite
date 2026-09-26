#!/usr/bin/env python3
"""公开释放检查：扫描「会进公开仓库的文件」，找不该发布的东西。

判据（任何一条命中即失败）：

- `missing_required_file` —— 开源发布必需的文件缺失
- `windows_user_path` / `macos_user_path` / `linux_user_path` —— 用户主目录路径泄漏
- `hardcoded_d_git` / `hardcoded_suite_path` / `generic_drive_path` —— 本机盘符路径泄漏
- `private_config`        —— 密钥/口令赋值、Bearer、私钥块（带占位识别）
- `pii_email`             —— 疑似真人邮箱（保留域与非个人本地部分放行）
- `pii_phone`             —— 疑似真人手机号（**占位号放行**）
- `pii_id_number`         —— 疑似真人身份证号（**校验位不通过的一律放行**）
- `scan_too_small`        —— 扫描面塌了（见 `MIN_SCANNED_FILES`）

**"新增一类规则"必须同时新增"占位识别"**：否则规则的第一批命中就是文档里那些
正当的示例值，报红了然后规则被人关掉——**比没有规则更糟**。
本文件的每类规则都带自己的占位判据，且豁免理由会被打印。

扫描对象由 **git** 算（`ls-files --cached --others --exclude-standard`），
即「已跟踪 ∪ 未跟踪但未被忽略」。**不扫工作区**：`.gitignore` 挡住的东西
（真实抓包、本地记忆、模块目录里的抓取产物）不会进公开仓库。

**不是安全边界**：挡的是「顺手把抓包里的真值抄进可读文件」，挡不住刻意规避
（形近字符、拆行拼接、编码绕过）。别把它当 PII 的唯一防线。

零第三方依赖。

用法：
    python scripts/misc/public_release_check.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IGNORE_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
IGNORE_DIRS_PREFIX = {"tmp", "cases", "exports", "reports", "notes"}
# `projects/` 是**部分提交**的目录：只有索引与模板进版本库，作业目录是本地产物
# （含真实抓包、真实域名、可用脚本）。所以不能整个前缀忽略，要按第二段精确判。
PROJECTS_DIR = "projects"
PROJECTS_TRACKED = {"README.md", "_template"}
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".json",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
    ".gitignore",
    # `.html` 曾经不在表里 —— 实测漏过一次：模块目录下保存的收件箱页
    # （含真实邮箱与一个真实 token）整类不在扫描范围。页面是抓包派生物，
    # 现在由 .gitignore 挡住，但「后缀不在表里」这个缺口本身要补上。
    ".html",
    ".htm",
}
REQUIRED_FILES = [
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    ".github/workflows/ci.yml",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/pull_request_template.md",
]

PATH_PATTERNS = [
    ("windows_user_path", re.compile(r"C:\\Users\\[^\\\s]+", re.I)),
    # 下面两条把首字母写成 `[U]` / `[h]`：**这不是笔误**。
    # 前向斜杠没法像反斜杠那样转义，写成 `/Users/` 的**字面量**会让这两条规则
    # 命中**它们自己的定义行**（实测：首版 5 条自命中里有 2 条就是这里）。
    # `[U]sers` 与 `Users` 等价、`[h]ome` 与 `home` 等价，但源码文本里不含那两个子串
    # ——与 `C:\\Users\\` 用转义规避自命中是同一个手法。
    #
    # **大小写必须照抄**：`[H]ome` 匹配的是 `Home`，而 Linux 主目录是小写 `home`
    # （实测把 `h` 写成 `H` 会让这条规则一次都不命中，且看不出来）。
    ("macos_user_path", re.compile(r"/[U]sers/[^/\s`'\"]+")),
    ("linux_user_path", re.compile(r"/[h]ome/[^/\s`'\"]+")),
    ("hardcoded_d_git", re.compile(r"D:[\\/]Git[\\/]", re.I)),
    ("hardcoded_suite_path", re.compile(r"D:[\\/]aaaaa[\\/]automation-suite", re.I)),
    # 通用盘符。`(?<![\w])` 是承重的：没有它，URL 里协议分隔符前那个字母加冒号
    # 会被当成盘符（那两个斜杠前面的字母，前面紧挨着另一个字母）。
    #
    # 字符类**允许单引号**：撇号出现在路径中间的夹具是真实存在的，
    # 把撇号排除掉会把匹配截断在撇号处，反而更难判定是不是合成值。
    ("generic_drive_path", re.compile(r"(?<![\w])[A-Za-z]:[\\/](?![\\/])[^\s`\"]*")),
]

# 合成路径标记：命中即**不报**。这一条是为**测试夹具**存在的——
# 实测通用盘符规则的全部命中都在 `scripts/misc/tests/` 里，且都是合成值
# （合成项目目录、合成解释器路径、盘符根下的假解释器名）。
#
# 判据是"路径里有没有非真人标记"，不是"文件是不是测试"：**测试里也可能抄进真路径**，
# 而真路径带的是真用户名（由 `windows_user_path` 抓，与这里无关）。
SYNTHETIC_PATH_MARKERS = (
    "example",
    "sample",
    "someone",
    "placeholder",
    "yourname",
    "username",
    "<",
    ">",
    "${",
    "py.exe",
    "python.exe",
    "\\work\\",
    "/work/",
)

SECRET_KEYS = r"api[_-]?key|password|secret|private[_-]?key"
SECRET_ASSIGNMENT_PATTERNS = [
    re.compile(
        rf"(?i)\b(?P<key>{SECRET_KEYS})\b(?:\s*:\s*[^=\n]+)?\s*=\s*(?P<value>\"[^\"\n]*\"|'[^'\n]*')"
    ),
    re.compile(
        rf"(?i)[\"'](?P<key>{SECRET_KEYS})[\"']\s*:\s*(?P<value>\"[^\"\n]*\"|'[^'\n]*')"
    ),
]
BEARER_PATTERN = re.compile(r"(?i)authorization\s*:\s*bearer\s+(?P<value>[^\s`]+)")
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")
PLACEHOLDER_MARKERS = (
    "xxx",
    "example",
    "sample",
    "placeholder",
    "changeme",
    "replace-me",
    "replace_me",
    "your-",
    "your_",
    "api-密码",
    "占位",
    "示例",
)
PLACEHOLDER_EXACT = {"pwd", "pass", "password", "secret", "token"}

# 文档示例专用的保留域名（RFC 2606 / RFC 6761）：这些域名不可能属于真人。
RESERVED_EMAIL_DOMAINS = frozenset(
    {"example.com", "example.net", "example.org", "example.test"}
)
RESERVED_EMAIL_TLDS = (".test", ".invalid", ".localhost", ".local")
# 明确**不是**真人邮箱的本地部分。
#
# 精确匹配，**不做子串**：本地部分里含 "test" 子串、但整体不等于 "test" 的地址
# （真人邮箱很容易长这样）会被子串匹配静默放过——那正是这条规则要防的那类错误。
NON_PERSONAL_LOCAL_PARTS = frozenset(
    {
        "a",
        "abc123",
        "abc12345",
        "admin",
        "demo",
        "example",
        "foo",
        "no-reply",
        "noreply",
        "pass",
        "password",
        "sender",
        "test",
        "test123",
        "user",
        "your-email",
        "your_email",
    }
)
EMAIL_PATTERN = re.compile(
    r"(?<![\w.%+\-])(?P<value>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![\w\-])"
)

# 中国大陆手机号：11 位，1 开头，第二位 3-9。两侧不许再挨着数字
# （否则 `1380000000000` 这类更长的串会被截出一个"手机号"）。
PHONE_PATTERN = re.compile(r"(?<!\d)(?P<value>1[3-9]\d{9})(?!\d)")

# 文档与测试里惯用的**占位手机号**。实测本仓 5 处命中**全部**是前两个（见 F7）。
PLACEHOLDER_PHONES = frozenset(
    {
        "13000000000",
        "13800000000",
        "13800138000",
        "13900139000",
        "15000000000",
        "18888888888",
    }
)

# 18 位身份证：前 17 位数字 + 校验位（数字或 X）。两侧不许再挨着数字或 X。
ID_PATTERN = re.compile(r"(?<![\dXx])(?P<value>\d{17}[\dXx])(?![\dXx])")
ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CHECK_CODES = "10X98765432"

# 扫描面下限。这条检查的价值取决于**它看了多少文件**，而口径是 git 算的
# （会发布的那些）；git 不可用时 `iter_candidate_files` 会退回 rglob，两者可能差很多。
#
# 没有下限守卫时，"只扫到 3 个文件" 与 "扫到 220 个文件" 都报 `ok: true`——
# 而前者意味着**检查其实什么都没看**。实测本仓 223 个；取 150 留出正常增删的余量，
# 只拦灾难性缩水（git 列表失败、后缀表被改小、路径拼错）。
MIN_SCANNED_FILES = 150


def is_ignored(path: Path) -> bool:
    """兜底路径：git 不可用时的近似判断。**它不认识 `.gitignore`。**"""
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & IGNORE_PARTS:
        return True
    if rel.parts and rel.parts[0] in IGNORE_DIRS_PREFIX and path.name != ".gitkeep":
        return True
    # projects/ 只保留索引与模板：README.md 与 _template/ 要照常检查，
    # 其余（各作业目录）是本地产物。整个前缀忽略会连模板一起放过。
    if rel.parts and rel.parts[0] == PROJECTS_DIR:
        if len(rel.parts) < 2 or rel.parts[1] not in PROJECTS_TRACKED:
            return True
    return False


def _git_listed_files() -> list[Path] | None:
    """已跟踪 ∪ 未跟踪但未被忽略——也就是「会进公开仓库的」那一批。

    `-z` 用 NUL 分隔：路径里有中文（本仓库有），行分隔 + 引号转义会读错。
    失败（不是 git 仓库、git 没装）返回 None，由调用方退回 `is_ignored`。
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    found: list[Path] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            candidate = ROOT / raw.decode("utf-8", "surrogateescape")
            if candidate.is_file():
                found.append(candidate)
        except (OSError, UnicodeDecodeError):
            continue
    return found


def iter_candidate_files() -> list[Path]:
    """待检文件 = 会进公开仓库的那些。

    **不扫工作区**。`.gitignore` 挡住的东西（真实抓包、本地记忆、代理配置、
    模块目录里的抓包派生物）不会进公开仓库，把它们当待检对象有两处实测后果：

    1. `tools/automation-modules/邮箱/22do_free_receiver/data/har_summary.json`
       里有一个**真实 gmail**，它被 `.gitignore` 挡住、永远不会发布，
       却一直被本检查当成待检对象——而检查又恰好没有邮箱规则，于是既没报错、
       也没放过，只是**看错了对象**（见 MEMORY 规则 66/67）。
    2. 「忽略前缀」清单与 `.gitignore` 各维护一份，必然分叉：实测 `.trae/`、
       `CLAUDE.md`、`.workbuddy-ai/` 都已进 `.gitignore`，而本文件的
       `IGNORE_DIRS_PREFIX` 完全不知道它们。

    所以判据只有一处：**交给 git 算**。这不是放宽——「公开释放检查」该看的
    本来就只有「会被释放的那些」。
    """
    listed = _git_listed_files()
    if listed is not None:
        return sorted(set(listed))
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and not is_ignored(p))


def _is_placeholder(raw_value: str) -> bool:
    value = raw_value.strip().strip(",;")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    lowered = value.casefold()
    if not lowered or lowered in {"none", "null", "false", "true"} | PLACEHOLDER_EXACT:
        return True
    if (value.startswith("<") and value.endswith(">")) or value.startswith("${"):
        return True
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    return bool(re.fullmatch(r"[xX*_.-]+", value))


def find_private_config(text: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for pattern in SECRET_ASSIGNMENT_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_placeholder(match.group("value")):
                matches.append((match.start(), match.group(0)))
    for match in BEARER_PATTERN.finditer(text):
        if not _is_placeholder(match.group("value")):
            matches.append((match.start(), match.group(0)))
    for match in PRIVATE_KEY_PATTERN.finditer(text):
        matches.append((match.start(), match.group(0)))
    return matches


def _is_reserved_email_domain(domain: str) -> bool:
    """`example.com` 与 `sub.example.com` 都算；`notexample.com` **不算**。

    `endswith("example.com")` 会把 `notexample.com` 一起放过——那是另一个域名，
    不是保留域。所以精确域名走相等，TLD 走「点 + 后缀」。
    """
    return domain in RESERVED_EMAIL_DOMAINS or domain.endswith(RESERVED_EMAIL_TLDS)


def _looks_non_personal_email(address: str) -> bool:
    local, _, domain = address.rpartition("@")
    if _is_reserved_email_domain(domain.casefold()):
        return True
    return local.casefold() in NON_PERSONAL_LOCAL_PARTS


def _is_synthetic_path(value: str) -> bool:
    """路径里带合成标记（`example` / `someone` / `<...>` / `py.exe` …）即放行。

    这是**占位识别**，不是"测试文件豁免"——判据落在**路径内容**上，
    所以 `scripts/misc/tests/` 里真抄进一条 `C:\\Users\\<真名>\\...` 照样会被
    `windows_user_path` 抓住。
    """
    lowered = value.casefold()
    return any(marker in lowered for marker in SYNTHETIC_PATH_MARKERS)


def _is_placeholder_phone(value: str) -> bool:
    """占位手机号：显式表内的，或全同数字的（`11111111111`）。"""
    if value in PLACEHOLDER_PHONES:
        return True
    return len(set(value)) == 1


def _id_checksum_ok(value: str) -> bool:
    """GB 11643 的 mod-11-2 校验位。

    **这是身份证规则的第一道闸**：真实号码按定义必然通过，而随手编的
    （`110101199001011234` 这类）绝大多数通不过——`1/11` 的巧合概率。
    实测本仓 18 位数字串 0 条通过校验，所以这条规则加进来是**零误报**的。
    """
    digits = value[:17]
    if not digits.isdigit():
        return False
    total = sum(int(character) * weight for character, weight in zip(digits, ID_WEIGHTS))
    return ID_CHECK_CODES[total % 11] == value[17].upper()


def _looks_like_real_id(value: str) -> bool:
    """形态对 **且** 校验位对，才当成真身份证。

    校验位放行是**有意的**：宁可漏，不可误报（规则 79）。编造的号段会漏，
    但真实泄漏的号段必然被抓——而那正是这条规则存在的理由。
    """
    return _id_checksum_ok(value)


def find_pii(text: str) -> list[tuple[int, str, str]]:
    """找出「可能是真人信息」的串，返回 `(偏移, 片段, 类型)`。

    三类各有自己的**占位判据**——这是"新增一类规则必须同时新增占位识别"的落地：

    - `pii_email`：域名是文档保留域 **或** 本地部分是明确的非个人名，两条都不满足才报。
      为什么不能只做域名白名单：本仓库的邮箱模块**就是**在讲临时邮箱服务
      （`linshiyou.com` / `chacuo.net`），把非保留域名一律判成 PII 会把文档的
      正当内容全部报红，然后这条规则就会被人关掉——比没有规则更糟。
      效果：`demo@gmail.com` 放行（本地部分是 `demo`），而真实抓包里那种把本地部分
      打散成点分段、再挂一个 `+` 标记的 gmail 地址会被抓住。
    - `pii_phone`：`PLACEHOLDER_PHONES` 表内或全同数字的放行。
    - `pii_id_number`：**校验位不通过的一律放行**。

    > 写这段注释时规则先抓到了注释自己：注释里原本抄了那个真实地址当例子。
    > 已改成描述——**规则的第一批用户就是它的作者**，这算一次意外的自证。

    这是**降噪与防误贴，不是安全边界**（同 har_source 的掩码纪律）：
    它挡的是「顺手把抓包里的真值抄进可读文件」，挡不住刻意规避。
    """
    found: list[tuple[int, str, str]] = []
    for match in EMAIL_PATTERN.finditer(text):
        if not _looks_non_personal_email(match.group("value")):
            found.append((match.start(), match.group(0), "pii_email"))
    for match in PHONE_PATTERN.finditer(text):
        if not _is_placeholder_phone(match.group("value")):
            found.append((match.start(), match.group(0), "pii_phone"))
    for match in ID_PATTERN.finditer(text):
        if _looks_like_real_id(match.group("value")):
            found.append((match.start(), match.group(0), "pii_id_number"))
    return found


def main() -> int:
    issues = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            issues.append({"file": rel, "line": 0, "type": "missing_required_file", "snippet": "required for public GitHub release"})

    scanned = 0
    for p in iter_candidate_files():
        rel = p.relative_to(ROOT).as_posix()
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        # 路径规则按**起始偏移**去重，先到先得：`PATH_PATTERNS` 是"具体 → 通用"排的，
        # 所以作者本机路径只会以它那条**具体**规则报一次，不会被通用盘符规则再报一次
        # （同一条命中报两遍，是把噪音当成覆盖）。
        path_hits: dict[int, tuple[str, str]] = {}
        for name, rx in PATH_PATTERNS:
            for m in rx.finditer(text):
                if _is_synthetic_path(m.group(0)):
                    continue
                path_hits.setdefault(m.start(), (name, m.group(0)))
        for start in sorted(path_hits):
            name, value = path_hits[start]
            line = text.count("\n", 0, start) + 1
            issues.append({"file": rel, "line": line, "type": name, "snippet": value[:120]})
        for start, snippet in find_private_config(text):
            line = text.count("\n", 0, start) + 1
            issues.append({"file": rel, "line": line, "type": "private_config", "snippet": snippet})
        for start, snippet, kind in find_pii(text):
            line = text.count("\n", 0, start) + 1
            issues.append({"file": rel, "line": line, "type": kind, "snippet": snippet})
    # `scanned_files` 是刻意报出来的：这条检查的价值取决于「它看了哪些文件」，
    # 而口径是 git 算的（会发布的那些）。不报出来，口径变了没人会注意到。
    if scanned < MIN_SCANNED_FILES:
        issues.append({
            "file": "-",
            "line": 0,
            "type": "scan_too_small",
            "snippet": (
                f"只扫描到 {scanned} 个文本文件，低于下限 {MIN_SCANNED_FILES}"
                "——扫描面塌了（git 列表失败？后缀表被改小？路径拼错？），"
                "此时 ok=true 不可信"
            ),
        })
    result = {
        "root": "<repo>",
        "ok": not issues,
        "scanned_files": scanned,
        "scan_floor": MIN_SCANNED_FILES,
        "issue_count": len(issues),
        "issues": issues[:200],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
