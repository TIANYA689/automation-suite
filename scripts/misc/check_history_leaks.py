#!/usr/bin/env python3
r"""历史泄漏扫描：扫全部 git 历史里的泄漏形态，包括提交元数据与提交信息。

为什么需要它：`public_release_check.py` 只看「当前会进公开仓库的文件」，
一次全仓审计把它明确登记为**已知不覆盖**——「没做 `git log -p` 全历史泄漏扫描」。
被 `git rm` 掉的真实路径、被改写掉的旧凭据，在工作区里已经看不见，但它们
仍在历史里，一旦公开就随 `.git` 一起发布。

扫描面（三个 pass；前两个跑同一套规则表，第三个是独立判据）：

1. **diff 新增行**：`git log -p --all --no-color -U0` 取 `+` 开头、且不是
   `+++` 头的内容。
2. **提交信息**：`git log --all -z --format=%H…%B` 取每个 commit 的 message
   body，逐行套规则表，命中标注 `source="commit_message"`。
3. **作者/提交者身份**：取 `%an` / `%ae` / `%cn` / `%ce`，按邮箱去重，
   kind 为 `identity_email`，命中标注 `source="identity"`。

为什么要补第 2、3 个 pass：只扫 diff 的新增行，等于假设「泄漏只出现在文件
内容里」。这个假设就是盲区——本仓库历史里 4 个提交身份有 3 个是真实个人
邮箱（hotmail / outlook / QQ），它们**一次都没出现在 diff 里**，只存在于
commit 元数据；公开仓库时它们随历史一起暴露。提交信息也是常见载体
（有人把 token、内网地址粘在 message 里）。

diff 补丁按字节取回，统一 `errors="replace"` 解码：老 commit 里可能有非
UTF-8 内容或二进制补丁，不能因为解码失败整跑崩掉。行号来自
`@@ ... +c,d @@` 的新文件侧起始行，逐条新增行递增。全程只读、离线，
不写任何文件。

抓的形态（`kind`）：

- `abs_path_windows` —— `D:/Git/...`、`C:\Users\...`
- `abs_path_posix`   —— `/Users/<name>`、`/home/<name>`
- `email`            —— 常规邮箱形态
- `token`            —— `ghp_` / `github_pat_` / `sk-` / `AKIA` / `xox[baprs]-`
- `private_key`      —— `-----BEGIN ... PRIVATE KEY-----`
- `identity_email`   —— commit 的 author/committer 邮箱，**按身份去重**

`identity_email` 的判据只落在**域名**上：GitHub noreply
（`*.users.noreply.github.com`）与 RFC 2606 保留域（`example.com` 等）
不算泄漏——它们本来就设计成公开的；其余真实域名一律计入。这里故意不套
「本地部分是 test/demo 就豁免」：`test@real-corp.com` 仍是可定位到组织的
真实地址，与 diff 里随手写的 `test@example.com` 不是一回事。

**不抓** IP、手机号、人名：本仓库技术文档里有大量示例路径与示例值，
这三类在历史里只会制造噪音，且当前工作区已有 `public_release_check.py` 管 PII。

**占位识别**（实测数据驱动，不是凭感觉）：

- 首版不带占位判据时，本仓 29 个 commit 的原始命中是 61 条：
  13 条盘符路径**全部**是测试夹具或源码转义（`D:/work/example/...`、
  `C:\tools\someone\python.exe`、`except Exception as e:\n`），
  48 条邮箱**全部**是 `example.*` 保留域或 `test@` / `demo@` / `abc@` 这类占位值。
- 于是路径按「合成标记」排除，邮箱按「保留域 + 非个人本地部分」排除；
  被排除的条数单独计入 `suppressed` 并打印——可审计的排除不是漏洞，沉默的排除才是。
- 判据落在**命中串内容**上，不是「文件是不是测试」：测试里真抄进一条
  `C:\Users\<真名>\...` 照样会被抓住。

输出纪律：

- 计数永远是**完整计数**。`--limit` 只限制打印条数，不限制统计——本仓库
  曾因为在 `tail` 里数条目把 10 条说成 2 条，专门立过规则。
- 命中串一律掩码：token 保留前 4 后 2；路径把用户名段换成 `<user>`；
  邮箱本地部分只留首字母。报告里不出现完整的疑似凭据。
- 身份邮箱**默认也掩码**：这份报告很可能被贴进 issue 或聊天记录，把完整
  邮箱抄进去等于二次泄漏。要原文必须显式加 `--reveal-identities`。
- **空解析守卫**：扫到 0 个 commit（非 git 目录、空仓库、`git log` 失败）
  一律报错并非零退出。跳过与通过不能共用退出码。

退出码：

- `0` —— 扫描完成；`--fail-on` 未触发
- `1` —— 扫描完成，但 `--fail-on` 指定条件命中
- `2` —— 扫描失败（空解析守卫 / git 不可用）

零第三方依赖。

用法：
    python scripts/misc/check_history_leaks.py
    python scripts/misc/check_history_leaks.py --json
    python scripts/misc/check_history_leaks.py --max-commits 5 --limit 5
    python scripts/misc/check_history_leaks.py --fail-on any
    python scripts/misc/check_history_leaks.py --reveal-identities
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]

KINDS = (
    "abs_path_windows",
    "abs_path_posix",
    "email",
    "token",
    "private_key",
    # 身份邮箱放在最后：前五类是按文件内容的命中，这一类的语义完全不同。
    "identity_email",
)

# `commit <sha>` 行。`--no-decorate` 保证后面不会跟 `(HEAD -> main)`，
# 但这里仍只取前 40 位十六进制，装饰内容不会污染 SHA。
COMMIT_RE = re.compile(r"^commit (?P<sha>[0-9a-f]{7,40})\b", re.MULTILINE)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")

# 盘符路径。三处约束都是承重的：
# - `(?<![\w])`：`http://` 里 `p:/` 不是盘符；
# - `(?![\\/])`：同上，协议后面是双斜杠；
# - 排除引号与反引号：避免把 Markdown 行内代码的边界吃进路径。
WINDOWS_PATH_RE = re.compile(r"(?<![\w])[A-Za-z]:[\\/](?![\\/])[^\s\"`<>|]*")
# 前置的 `:` 是为了不吃掉 `C:/Users/x` 里的 `/Users/x`（否则同一条会报两次）。
POSIX_PATH_RE = re.compile(r"(?<![\w:])/(?:Users|home)/[^/\s\"'`<>|]+")
EMAIL_RE = re.compile(
    r"(?<![\w.%+\-])(?P<value>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![\w\-])"
)
TOKEN_PATTERNS = (
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    # `sk-` 是最容易误伤的一类：`(?<![A-Za-z0-9])` 挡住 `task-` 这类词尾。
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")

# 合成路径标记：与 `public_release_check.py` 同一套判据。实测本仓历史里的
# 13 条盘符命中全部落在这里（夹具路径与解释器路径），没有一条是真人路径。
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

# 文档示例专用的保留域名（RFC 2606 / RFC 6761）：这些域名不可能属于真人。
RESERVED_EMAIL_DOMAINS = frozenset(
    {"example.com", "example.net", "example.org", "example.test"}
)
RESERVED_EMAIL_TLDS = (".test", ".invalid", ".localhost", ".local")

# GitHub 给网页/隐私邮箱签发的占位域：`12345+user@users.noreply.github.com`
# 是设计上公开的转发地址，不可能反查到真实信箱，因此不算泄漏。
NOREPLY_EMAIL_DOMAIN = "users.noreply.github.com"

# `git log -z --format=...` 的分隔符：commit 之间用 NUL，字段之间用 US（0x1f）。
# 两者都不可能出现在 commit message 里（NUL 被 git 禁止，US 几乎不会出现）。
META_RECORD_SEPARATOR = "\x00"
META_FIELD_SEPARATOR = "\x1f"
META_FIELDS = 6  # %H %an %ae %cn %ce %B

# 明确不是真人邮箱的本地部分。`abc` 是本仓实测出来的第 2 个夹具值
# （`abc@linshiyou.com` / `abc@googlemail.com`），与 `abc123` 同源。
NON_PERSONAL_LOCAL_PARTS = frozenset(
    {
        "a",
        "abc",
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

MAX_MASKED_PATH = 120


def _mask_token(value: str) -> str:
    """长不透明串保留前 4 后 2，中间用省略号。短串多遮一点。"""
    if len(value) <= 8:
        return value[:2] + "…" + value[-1:]
    return value[:4] + "…" + value[-2:]


def _mask_email(value: str) -> str:
    """本地部分只留首字母，域名保留（域名不是凭据，保留便于判断来源）。"""
    local, separator, domain = value.partition("@")
    if not separator:
        return _mask_token(value)
    head = local[0] if local else ""
    return f"{head}***@{domain}"


def _mask_path(value: str) -> str:
    """保留目录结构，把用户名段替换成 `<user>`。"""
    masked = value.rstrip("'")
    masked = re.sub(r"(?i)([\\/]Users[\\/])[^\\/]+", r"\1<user>", masked)
    masked = re.sub(r"(?i)([\\/]home[\\/])[^\\/]+", r"\1<user>", masked)
    if len(masked) > MAX_MASKED_PATH:
        masked = masked[: MAX_MASKED_PATH - 1] + "…"
    return masked


def _mask_private_key(_value: str) -> str:
    """私钥只报形态，绝不打印 BEGIN 之后的内容（那里才是密钥材料）。"""
    return "-----BEGIN … PRIVATE KEY-----"


def _has_synthetic_marker(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in SYNTHETIC_PATH_MARKERS)


def _is_noise_windows_path(value: str) -> bool:
    """盘符路径的占位/转义判据。"""
    value = value.rstrip("'")
    if _has_synthetic_marker(value):
        return True
    # `except Exception as e:\n` 里的 `e:\n` 是源码转义，不是路径：
    # 盘符后只剩一个字符（或什么都不剩）。
    body = value[3:] if len(value) > 3 else ""
    return len(body) < 2


def _is_noise_posix_path(value: str) -> bool:
    return _has_synthetic_marker(value)


def _is_placeholder_email(value: str) -> bool:
    """保留域，或明确的非个人本地部分——与 `public_release_check.py` 同一套判据。"""
    local, _, domain = value.rpartition("@")
    folded = domain.casefold()
    if folded in RESERVED_EMAIL_DOMAINS or folded.endswith(RESERVED_EMAIL_TLDS):
        return True
    return local.casefold() in NON_PERSONAL_LOCAL_PARTS


def _is_public_identity_email(value: str) -> bool:
    """身份邮箱的豁免判据：只有「设计上就公开」的域名才算安全。

    与 `_is_placeholder_email` 故意不同：这里**不看本地部分**。身份邮箱是
    真实提交者留下的，`test@real-corp.com` 依旧能定位到组织，不能因为本地
    部分长得像夹具就放过。
    """
    _, separator, domain = value.rpartition("@")
    if not separator:
        # 不是邮箱形态（git 允许空或 `(none)`），没有可判定的域名。
        return True
    folded = domain.casefold()
    if folded == NOREPLY_EMAIL_DOMAIN or folded.endswith("." + NOREPLY_EMAIL_DOMAIN):
        return True
    return folded in RESERVED_EMAIL_DOMAINS or folded.endswith(RESERVED_EMAIL_TLDS)


RULE_TABLE: tuple[
    tuple[
        str,
        tuple[re.Pattern[str], ...],
        Callable[[str], str],
        Callable[[str], bool] | None,
    ],
    ...,
] = (
    ("abs_path_windows", (WINDOWS_PATH_RE,), _mask_path, _is_noise_windows_path),
    ("abs_path_posix", (POSIX_PATH_RE,), _mask_path, _is_noise_posix_path),
    ("email", (EMAIL_RE,), _mask_email, _is_placeholder_email),
    ("token", TOKEN_PATTERNS, _mask_token, None),
    ("private_key", (PRIVATE_KEY_RE,), _mask_private_key, None),
)


def _parse_new_path(raw: str) -> str | None:
    """解析 `+++ b/foo` 的新文件路径；`/dev/null` 表示删除，返回 None。"""
    value = raw.rstrip()
    # 引号形式（含特殊字符的路径）先去掉引号再处理，避免把引号内的制表符
    # 当成 git 追加的分隔符。
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    else:
        value = value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if value.startswith("b/"):
        value = value[2:]
    return value or None


def _iter_added_lines(patch: str) -> Iterator[tuple[str, str, int, str]]:
    """逐条产出 `(commit, 文件路径, 新文件行号, 新增行内容)`。

    `-U0` 下正常没有上下文行，但仍按 ` ` 分支递增行号：万一 git 配置或
    版本让上下文行混进来，行号也不会整体错位。
    """
    commit = ""
    current_file: str | None = None
    new_line: int | None = None

    for raw in patch.splitlines():
        if raw.startswith("commit "):
            match = COMMIT_RE.match(raw)
            if match:
                commit = match.group("sha")
            current_file = None
            new_line = None
            continue
        if raw.startswith("+++ "):
            current_file = _parse_new_path(raw[4:])
            continue
        if raw.startswith("@@"):
            match = HUNK_RE.match(raw)
            new_line = int(match.group("start")) if match else None
            continue
        if raw.startswith("+"):
            if current_file is not None and new_line is not None:
                yield commit, current_file, new_line, raw[1:]
                new_line += 1
            continue
        if raw.startswith(" "):
            if new_line is not None:
                new_line += 1
    # `-` 行与 `\ No newline at end of file` 不改变新文件行号。


def _iter_rule_matches(text: str) -> Iterator[tuple[str, str, bool]]:
    """在一段文本上跑规则表，产出 `(kind, 掩码后的值, 是否被占位判据排除)`。

    diff 行与 commit message 行共用这一个入口，保证两边的判据不会漂移。
    """
    for kind, patterns, mask, is_noise in RULE_TABLE:
        for pattern in patterns:
            for match in pattern.finditer(text):
                value = match.group(0)
                excluded = is_noise is not None and is_noise(value)
                yield kind, mask(value), excluded


def _error_report(message: str) -> dict[str, object]:
    """扫描失败的报告。`error` 非空时调用方必须给非零退出码。"""
    return {
        "ok": False,
        "clean": False,
        "error": message,
        "root": "<repo>",
        "commits": 0,
        "total": 0,
        "by_kind": {kind: 0 for kind in KINDS},
        "suppressed": {kind: 0 for kind in KINDS},
        "findings": [],
        "identities": [],
        "identity_total": 0,
        "identity_exposed": 0,
    }


def _git_command(max_commits: int | None) -> list[str]:
    command = [
        "git",
        "--no-pager",
        # 中文路径不要被转成八进制转义，否则文件路径列无法阅读。
        "-c",
        "core.quotepath=false",
        "-c",
        "color.ui=never",
        "log",
        "-p",
        "--all",
        "--no-color",
        "--no-decorate",
        "--no-ext-diff",
        "-U0",
    ]
    if max_commits is not None:
        command.append(f"--max-count={max_commits}")
    return command


def _git_meta_command(max_commits: int | None) -> list[str]:
    """取提交元数据的 `git log`：`-z` 用 NUL 分隔 commit，字段用 US 分隔。

    不用 `--pretty` 的多行输出解析：commit message 本身可以包含任意换行和
    形如 `commit <sha>` 的行，按行解析会被 message 内容伪造。NUL 是 git
    禁止出现在 message 里的字节，所以按 NUL 切分是无歧义的。
    """
    command = [
        "git",
        "--no-pager",
        "-c",
        "core.quotepath=false",
        "-c",
        "color.ui=never",
        "log",
        "--all",
        "--no-color",
        "--no-decorate",
        "-z",
        "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B",
    ]
    if max_commits is not None:
        command.append(f"--max-count={max_commits}")
    return command


def _iter_commit_meta(
    stream: str,
) -> Iterator[tuple[str, str, str, str, str, str]]:
    """解析 `-z` 元数据流，产出 `(sha, 作者名, 作者邮箱, 提交者名, 提交者邮箱, message)`。"""
    for record in stream.split(META_RECORD_SEPARATOR):
        if not record.strip():
            continue
        # 非 `-z` 的 `git log` 会在每条记录前加空行；这里防御性去掉，
        # 否则首字段会变成 `\n<sha>`。
        record = record.lstrip("\n")
        fields = record.split(META_FIELD_SEPARATOR, META_FIELDS - 1)
        if len(fields) < META_FIELDS:
            continue
        sha = fields[0].strip()
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
            continue
        yield sha, fields[1], fields[2], fields[3], fields[4], fields[5]


def _collect_identities(
    meta: list[tuple[str, str, str, str, str, str]],
) -> list[dict[str, object]]:
    """按邮箱去重，汇总每个身份出现过的 commit 数、角色与姓名。

    `email` 字段此时是**原文**，由调用方在输出前决定是否掩码——掩码发生在
    最外层，避免掩码后的值被当成去重键（`a***@x.com` 会让两个人撞成一个人）。
    """
    identities: dict[str, dict[str, object]] = {}
    for sha, author_name, author_email, committer_name, committer_email, _ in meta:
        for role, name, email in (
            ("author", author_name, author_email),
            ("committer", committer_name, committer_email),
        ):
            email = email.strip()
            if not email:
                continue
            key = email.casefold()
            entry = identities.setdefault(
                key,
                {
                    "email": email,
                    "names": [],
                    "commits": set(),
                    "roles": [],
                    "first_commit": sha,
                },
            )
            commits = entry["commits"]
            assert isinstance(commits, set)
            commits.add(sha)
            names = entry["names"]
            assert isinstance(names, list)
            if name.strip() and name.strip() not in names:
                names.append(name.strip())
            roles = entry["roles"]
            assert isinstance(roles, list)
            if role not in roles:
                roles.append(role)
    return list(identities.values())


def scan(
    root: Path | str = ROOT,
    max_commits: int | None = None,
    reveal_identities: bool = False,
) -> dict[str, object]:
    """扫描 `root` 的 git 历史，返回结构化报告（不打印、不写文件）。

    `error` 非空表示扫描本身失败——**包括扫到 0 个 commit**。这是空解析守卫：
    「什么都没扫到」和「扫了但很干净」必须是两种结果。

    `reveal_identities=False`（默认）时，报告里的身份邮箱一律掩码；只有显式
    开启才输出原文。掩码发生在报告组装阶段，内部去重始终用原文。
    """
    root = Path(root)
    try:
        completed = subprocess.run(
            _git_command(max_commits),
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return _error_report(f"无法执行 git：{error}")

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        return _error_report(f"git log 失败（退出码 {completed.returncode}）：{detail}")

    # 非 UTF-8 / 二进制补丁：替换解码，绝不因为解码失败中断。
    patch = completed.stdout.decode("utf-8", "replace")
    commits = len({match.group("sha") for match in COMMIT_RE.finditer(patch)})
    if commits == 0:
        return _error_report(
            "扫描到 0 个 commit——非 git 目录、空仓库或 git log 异常；"
            "此时「没有泄漏」不可信"
        )

    try:
        meta_completed = subprocess.run(
            _git_meta_command(max_commits),
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return _error_report(f"无法执行 git（元数据）：{error}")

    if meta_completed.returncode != 0:
        detail = meta_completed.stderr.decode("utf-8", "replace").strip()
        return _error_report(
            f"git log 元数据失败（退出码 {meta_completed.returncode}）：{detail}"
        )

    meta = list(
        _iter_commit_meta(meta_completed.stdout.decode("utf-8", "replace"))
    )
    if not meta:
        return _error_report(
            "提交元数据解析到 0 条——git log --format 输出异常；"
            "此时「没有身份泄漏」不可信"
        )

    findings: list[dict[str, object]] = []
    by_kind: dict[str, int] = {kind: 0 for kind in KINDS}
    suppressed: dict[str, int] = {kind: 0 for kind in KINDS}

    # pass 1：diff 新增行。
    for commit, file_path, line_number, text in _iter_added_lines(patch):
        if not text:
            continue
        for kind, masked, excluded in _iter_rule_matches(text):
            # 占位/转义命中不计入总数，但单独计数并打印——排除必须可审计。
            if excluded:
                suppressed[kind] += 1
                continue
            by_kind[kind] += 1
            findings.append(
                {
                    "commit": commit[:7],
                    "file": file_path,
                    "line": line_number,
                    "kind": kind,
                    "match": masked,
                    "source": "diff",
                }
            )

    # pass 2：提交信息。行号是 message body 内的行号（1 起）。
    for sha, _, _, _, _, message in meta:
        for line_number, line in enumerate(message.splitlines(), start=1):
            if not line:
                continue
            for kind, masked, excluded in _iter_rule_matches(line):
                if excluded:
                    suppressed[kind] += 1
                    continue
                by_kind[kind] += 1
                findings.append(
                    {
                        "commit": sha[:7],
                        "file": None,
                        "line": line_number,
                        "kind": kind,
                        "match": masked,
                        "source": "commit_message",
                    }
                )

    # pass 3：作者/提交者身份，按邮箱去重。
    identities = _collect_identities(meta)
    exposed: list[dict[str, object]] = []
    for entry in identities:
        email = entry["email"]
        assert isinstance(email, str)
        if _is_public_identity_email(email):
            suppressed["identity_email"] += 1
            continue
        exposed.append(entry)
        commits_seen = entry["commits"]
        assert isinstance(commits_seen, set)
        by_kind["identity_email"] += 1
        findings.append(
            {
                "commit": str(entry["first_commit"])[:7],
                "file": None,
                "line": None,
                "kind": "identity_email",
                "match": email if reveal_identities else _mask_email(email),
                "source": "identity",
                "commits": len(commits_seen),
                "roles": list(entry["roles"]),
            }
        )

    # 明细排序：先暴露的、再按 commit 数多的；同分按邮箱，保证输出稳定。
    def _identity_sort_key(entry: dict[str, object]) -> tuple[int, int, str]:
        commits_seen = entry["commits"]
        assert isinstance(commits_seen, set)
        email = entry["email"]
        assert isinstance(email, str)
        return (
            0 if not _is_public_identity_email(email) else 1,
            -len(commits_seen),
            email.casefold(),
        )

    identity_rows = [
        {
            "email": (
                entry["email"]
                if reveal_identities
                else _mask_email(str(entry["email"]))
            ),
            "names": list(entry["names"]),
            "commits": len(entry["commits"]),
            "roles": list(entry["roles"]),
            "exposed": not _is_public_identity_email(str(entry["email"])),
        }
        for entry in sorted(identities, key=_identity_sort_key)
    ]

    total = len(findings)
    return {
        "ok": True,
        "clean": total == 0,
        "error": None,
        "root": "<repo>",
        "commits": commits,
        "total": total,
        "by_kind": by_kind,
        "suppressed": suppressed,
        "findings": findings,
        "identities": identity_rows,
        "identity_total": len(identity_rows),
        "identity_exposed": len(exposed),
    }


def _format_location(item: dict[str, object]) -> str:
    """把一条命中定位成人读字符串。diff 之外的来源没有文件路径。"""
    source = item.get("source")
    if source == "commit_message":
        return f"提交信息:{item['line']}"
    if source == "identity":
        return "commit 元数据"
    return f"{item['file']}:{item['line']}"


def _print_human(
    report: dict[str, object],
    limit: int,
    stream: object = None,
    reveal_identities: bool = False,
) -> None:
    """人读汇总。`limit` 只截断打印，`total` 与 `by_kind` 始终是完整计数。"""
    out = sys.stdout if stream is None else stream

    error = report.get("error")
    if error:
        print(f"扫描失败：{error}", file=out)
        print("RESULT=ERROR", file=out)
        return

    print(
        f"历史泄漏扫描：{report['commits']} 个 commit，命中 {report['total']} 条",
        file=out,
    )
    print("按 kind：", file=out)
    by_kind = report["by_kind"]
    assert isinstance(by_kind, dict)
    for kind in KINDS:
        print(f"  {kind:<18} {by_kind.get(kind, 0)}", file=out)

    suppressed = report.get("suppressed", {})
    if isinstance(suppressed, dict):
        parts = [f"{kind} {suppressed[kind]}" for kind in KINDS if suppressed.get(kind)]
        if parts:
            print(f"已按占位判据排除（不计入命中）：{'，'.join(parts)}", file=out)

    identity_total = report.get("identity_total", 0)
    identity_exposed = report.get("identity_exposed", 0)
    print(
        f"\n提交身份：共 {identity_total} 个不同身份，"
        f"其中 {identity_exposed} 个真实域名邮箱会随公开暴露",
        file=out,
    )
    exempt = identity_total - identity_exposed
    if exempt:
        print(
            f"  另有 {exempt} 个 GitHub noreply / RFC 2606 保留域身份，按判据豁免",
            file=out,
        )
    if identity_exposed and not reveal_identities:
        print("  邮箱已掩码；需要原文请显式加 --reveal-identities", file=out)

    findings = report["findings"]
    assert isinstance(findings, list)
    shown_total = 0
    for kind in KINDS:
        items = [item for item in findings if item["kind"] == kind]
        if not items:
            continue
        shown = items[:limit]
        shown_total += len(shown)
        print(f"\n[{kind}] 共 {len(items)} 条，显示 {len(shown)} 条", file=out)
        for item in shown:
            suffix = ""
            if item.get("source") == "identity":
                suffix = f"  commits={item.get('commits')}"
            print(
                f"  {item['commit']}  {_format_location(item)}  "
                f"{item['match']}{suffix}",
                file=out,
            )

    total = report["total"]
    if total and shown_total < total:
        print(
            f"\n注意：共 {total} 条，仅打印 {shown_total} 条；"
            "计数为完整计数，--limit 只影响打印条数。",
            file=out,
        )
    elif total == 0:
        print("\n未发现命中。", file=out)
    print(f"RESULT={'CLEAN' if total == 0 else 'FINDINGS'}", file=out)


def _exit_code(report: dict[str, object], fail_on: str) -> int:
    if report.get("error"):
        return 2
    total = report.get("total", 0)
    if fail_on == "none":
        return 0
    if fail_on == "any":
        return 1 if total else 0
    by_kind = report.get("by_kind", {})
    assert isinstance(by_kind, dict)
    return 1 if by_kind.get(fail_on, 0) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="扫描 git 历史新增行中的泄漏形态（只读、离线）。"
    )
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument(
        "--max-commits",
        type=int,
        default=None,
        metavar="N",
        help="只扫最近 N 个 commit（调试用）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="每种 kind 最多打印 N 条（默认 20；计数不受影响）",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "any", *KINDS),
        default="none",
        help="命中到什么程度才非零退出（默认 none：只报告不拦）",
    )
    parser.add_argument(
        "--reveal-identities",
        action="store_true",
        help="在输出里显示完整的身份邮箱（默认掩码；报告常被贴进 issue）",
    )
    args = parser.parse_args(argv)

    if args.limit < 0:
        parser.error("--limit 不能为负数")
    if args.max_commits is not None and args.max_commits <= 0:
        parser.error("--max-commits 必须是正整数")

    report = scan(
        ROOT,
        max_commits=args.max_commits,
        reveal_identities=args.reveal_identities,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(
            report,
            args.limit,
            reveal_identities=args.reveal_identities,
        )
    return _exit_code(report, args.fail_on)


if __name__ == "__main__":
    raise SystemExit(main())
