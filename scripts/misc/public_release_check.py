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
    ("hardcoded_d_git", re.compile(r"D:[\\/]Git[\\/]", re.I)),
    ("hardcoded_suite_path", re.compile(r"D:[\\/]aaaaa[\\/]automation-suite", re.I)),
]
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


def find_pii(text: str) -> list[tuple[int, str]]:
    """找出「可能是真人信息」的串。当前只有邮箱一类。

    为什么不能只做域名白名单：本仓库的邮箱模块**就是**在讲临时邮箱服务
    （`linshiyou.com` / `chacuo.net`），把非保留域名一律判成 PII 会把文档的
    正当内容全部报红，然后这条规则就会被人关掉——比没有规则更糟。

    所以判据是两条**并列**：域名是文档保留域 **或** 本地部分是明确的非个人名。
    两条都不满足才报。效果：`demo@gmail.com` 放行（本地部分是 `demo`），而真实抓包
    里那种把本地部分打散成点分段、再挂一个 `+` 标记的 gmail 地址会被抓住。

    > 写这段注释时规则先抓到了注释自己：注释里原本抄了那个真实地址当例子。
    > 已改成描述——**规则的第一批用户就是它的作者**，这算一次意外的自证。

    这是**降噪与防误贴，不是安全边界**（同 har_source 的掩码纪律）：
    它挡的是「顺手把抓包里的真值抄进可读文件」，挡不住刻意规避。
    """
    found: list[tuple[int, str]] = []
    for match in EMAIL_PATTERN.finditer(text):
        if not _looks_non_personal_email(match.group("value")):
            found.append((match.start(), match.group(0)))
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
        for name, rx in PATH_PATTERNS:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = text[m.start():m.start()+120]
                issues.append({"file": rel, "line": line, "type": name, "snippet": snippet})
        for start, snippet in find_private_config(text):
            line = text.count("\n", 0, start) + 1
            issues.append({"file": rel, "line": line, "type": "private_config", "snippet": snippet})
        for start, snippet in find_pii(text):
            line = text.count("\n", 0, start) + 1
            issues.append({"file": rel, "line": line, "type": "pii_email", "snippet": snippet})
    # `scanned_files` 是刻意报出来的：这条检查的价值取决于「它看了哪些文件」，
    # 而口径是 git 算的（会发布的那些）。不报出来，口径变了没人会注意到。
    result = {
        "root": "<repo>",
        "ok": not issues,
        "scanned_files": scanned,
        "issue_count": len(issues),
        "issues": issues[:200],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
