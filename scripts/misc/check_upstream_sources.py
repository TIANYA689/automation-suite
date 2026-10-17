#!/usr/bin/env python3
"""外部来源清单的离线校验，以及可选的 GitHub 联网核验。

离线（默认，不发起任何网络请求）回答两个问题：

1. `docs/upstream-sources.json` 是否格式良好（schema、revision 是否固定、
   许可证是否在白名单内、日期是否合法）？
2. 台账（`docs/upstream-absorption.md`）是否点名了清单里漏登记的仓库？

两者都在 CI 中运行。只有显式传入 ``--network`` 时，才会逐条访问 GitHub
REST API，核验仓库是否存在、是否归档、许可证是否与清单一致、revision 是否
仍然存在、HEAD 是否漂移，以及 ``checked_at`` 是否陈旧。

联网核验的严重级别：

- ``error``：仓库不存在、revision 不存在、许可证与清单不符（非零退出）
- ``warning``：仓库已归档、台账陈旧
- ``info``：HEAD 已漂移（正常现象，仅提示该复核，不影响退出码）
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "docs" / "upstream-sources.json"
DEFAULT_LEDGER = ROOT / "docs" / "upstream-absorption.md"
ALLOWED_LICENSES = {"LicenseRef-NOASSERTION", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "GPL-3.0-only", "LGPL-3.0-only"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Only the ledger's "sources of this round" table opens a row with `owner/repo`;
# rows in the per-item tables name sources without an owner and do not match.
LEDGER_REPO_RE = re.compile(r"^\|\s*`([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)`", re.MULTILINE)

API_ROOT = "https://api.github.com"
USER_AGENT = "automation-suite-upstream-check/1.0"
DEFAULT_TIMEOUT = 10.0
DEFAULT_STALE_DAYS = 180
# GitHub 的 license.spdx_id 历史上使用简写（GPL-3.0 而非 GPL-3.0-only），
# 归一化后再比较，避免把同一种许可证误报成「许可证变了」。
LICENSE_ALIASES = {
    "gpl-2.0": "gpl-2.0-only",
    "gpl-3.0": "gpl-3.0-only",
    "lgpl-2.1": "lgpl-2.1-only",
    "lgpl-3.0": "lgpl-3.0-only",
    "agpl-3.0": "agpl-3.0-only",
}
SEVERITIES = ("error", "warning", "info")


class FetchError(RuntimeError):
    """取 GitHub API JSON 失败时抛出，携带 HTTP 状态与限流信息。

    测试通过替换 ``_fetch_json`` 来模拟失败，直接抛出本异常即可。
    """

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        status: int | None = None,
        rate_limited: bool = False,
        reset_at: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.rate_limited = rate_limited
        self.reset_at = reset_at


def _fetch_json(url: str, timeout: float) -> object:
    """GET 一个 GitHub API 地址并解析 JSON。

    这是模块里唯一真正发起网络请求的函数，测试整体替换它即可完全离线。
    未认证调用（不读取任何 token），按 GitHub 要求带上 User-Agent。
    出错时抛出 :class:`FetchError`，不打印原始响应体。
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(4096).decode("utf-8", "replace")
        except OSError:
            pass
        headers = exc.headers
        remaining = headers.get("X-RateLimit-Remaining") if headers else None
        reset_at = headers.get("X-RateLimit-Reset") if headers else None
        rate_limited = exc.code in (403, 429) and (
            remaining == "0" or "rate limit" in body.lower()
        )
        if rate_limited:
            raise FetchError(
                f"GitHub API 限流（rate limit），配额重置时间：{_format_reset(reset_at)}",
                url=url,
                status=exc.code,
                rate_limited=True,
                reset_at=reset_at,
            ) from exc
        detail = _api_message(body)
        suffix = f"：{detail}" if detail else ""
        raise FetchError(
            f"GitHub API 返回 HTTP {exc.code}{suffix}",
            url=url,
            status=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"网络不可达或请求超时：{reason}", url=url) from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"GitHub API 返回的不是合法 JSON：{exc}", url=url) from exc


def _api_message(body: str) -> str:
    """从错误响应体里只取 message 字段，避免整段打印原始响应。"""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str):
            return message.strip()[:200]
    return ""


def _format_reset(reset_at: str | None) -> str:
    """把 X-RateLimit-Reset 的 epoch 秒格式化成可读的 UTC 时间。"""
    if not reset_at:
        return "未知"
    try:
        moment = datetime.fromtimestamp(int(reset_at), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return "未知"
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def validate(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": _display_path(path), "sources": 0, "errors": [str(exc)]}
    if payload.get("version") != "1.0":
        errors.append("version must be 1.0")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    seen: set[str] = set()
    for index, item in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in ("id", "url", "revision", "spdx_license", "checked_at", "scope"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(f"{prefix}.{key} is required")
        identifier = item.get("id")
        if isinstance(identifier, str) and identifier in seen:
            errors.append(f"duplicate id: {identifier}")
        if isinstance(identifier, str):
            seen.add(identifier)
        if isinstance(item.get("url"), str) and not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/.*)?", item["url"]):
            errors.append(f"{prefix}.url must be a GitHub HTTPS URL")
        if item.get("revision") == "REVISION_REQUIRED":
            errors.append(f"{prefix}.revision is still a placeholder")
        if item.get("spdx_license") not in ALLOWED_LICENSES:
            errors.append(f"{prefix}.spdx_license is not allowlisted")
        if not isinstance(item.get("checked_at"), str) or not DATE_RE.fullmatch(item.get("checked_at", "")):
            errors.append(f"{prefix}.checked_at must be YYYY-MM-DD")
    return {"ok": not errors, "path": _display_path(path), "sources": len(sources), "errors": errors}


def check_ledger_coverage(
    ledger: Path = DEFAULT_LEDGER, manifest: Path = DEFAULT_MANIFEST
) -> dict[str, object]:
    """Every repository named by the ledger must be registered in the manifest.

    The ledger answers "what was absorbed / excluded"; the manifest answers
    "which revision and license was reviewed". They are two faces of one source
    list, so a repository added to the ledger and forgotten in the manifest
    **fails silently** — the manifest just gets quietly shorter. That gap is
    what this check closes.

    Repository names are compared case-insensitively: GitHub treats them so.
    """
    errors: list[str] = []
    try:
        text = ledger.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "ledger": _display_path(ledger),
            "named": 0,
            "listed": 0,
            "errors": [f"cannot read ledger: {exc}"],
        }

    named = {match.group(1).lower() for match in LEDGER_REPO_RE.finditer(text)}
    if not named:
        # An empty parse means the table shape changed: the check would pass
        # vacuously, which is worse than failing (MEMORY rule 101).
        errors.append(
            f"{_display_path(ledger)}: no `owner/repo` rows parsed, so the coverage check is not running"
        )

    listed: set[str] = set()
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read manifest: {exc}")
        payload = {}
    entries = payload.get("sources") if isinstance(payload, dict) else None
    for item in entries if isinstance(entries, list) else []:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str):
            parts = url.rstrip("/").split("/")
            if len(parts) >= 2:
                listed.add(f"{parts[-2]}/{parts[-1]}".lower())

    for name in sorted(named - listed):
        errors.append(f"ledger names a repository missing from the manifest: {name}")

    return {
        "ok": not errors,
        "ledger": _display_path(ledger),
        "named": len(named),
        "listed": len(listed),
        "errors": errors,
    }


def _normalize_license(value: object) -> str:
    """把清单与 GitHub 的许可证写法归一化到可比较的形式。

    ``LicenseRef-NOASSERTION``、``NOASSERTION``、``None`` 都表示「上游没有
    声明许可证」，必须视为一致，否则每次联网都会误报许可证变化。
    """
    if value is None:
        return "noassertion"
    text = str(value).strip().lower()
    if text in {"", "noassertion", "none", "null", "licenseref-noassertion"}:
        return "noassertion"
    return LICENSE_ALIASES.get(text, text)


def _owner_repo(url: object) -> tuple[str, str] | None:
    """从 GitHub URL 中取出 (owner, repo)，不是 GitHub 地址时返回 None。"""
    if not isinstance(url, str):
        return None
    parts = url.rstrip("/").split("/")
    if len(parts) < 5 or parts[2].lower() != "github.com":
        return None
    owner, repo = parts[3], parts[4]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


def _finding(severity: str, code: str, message: str, *, source_id: str = "", url: str = "") -> dict[str, str]:
    """构造一条带级别的核验结果。"""
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "id": source_id,
        "url": url,
    }


def _counts(findings: list[dict[str, str]]) -> dict[str, int]:
    return {level: sum(1 for item in findings if item["severity"] == level) for level in SEVERITIES}


def check_remote_source(
    source: dict[str, object],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    stale_days: int = DEFAULT_STALE_DAYS,
    today: date | None = None,
) -> dict[str, object]:
    """对单条来源做 GitHub 联网核验，返回该来源的 findings。

    只读取仓库元数据、指定 revision、当前 HEAD 三处信息；任何网络失败都会
    转成 ``error``，绝不会静默当作通过。
    """
    source_id = str(source.get("id") or "?")
    url = str(source.get("url") or "")
    findings: list[dict[str, str]] = []

    def add(severity: str, code: str, message: str) -> None:
        findings.append(_finding(severity, code, message, source_id=source_id, url=url))

    parsed = _owner_repo(url)
    if parsed is None:
        add("error", "invalid-url", f"无法从 URL 解析 owner/repo：{url or '（空）'}")
        return {"id": source_id, "url": url, "findings": findings}
    owner, repo = parsed
    base = f"{API_ROOT}/repos/{owner}/{repo}"

    # 1. 仓库元数据：存在性、归档状态、许可证。
    try:
        meta = _fetch_json(base, timeout)
    except FetchError as exc:
        if exc.status == 404:
            add("error", "repo-missing", f"仓库不存在（HTTP 404）：{owner}/{repo}")
        elif exc.rate_limited:
            add("error", "rate-limited", str(exc))
        else:
            add("error", "repo-unreadable", f"无法读取仓库信息：{exc}")
        return {"id": source_id, "url": url, "findings": findings}

    if not isinstance(meta, dict) or not meta:
        add("error", "empty-response", "GitHub API 返回空结果（0 条），无法核验仓库")
        return {"id": source_id, "url": url, "findings": findings}

    if meta.get("archived") is True:
        add("warning", "archived", "上游仓库已归档（archived=true），应复核是否仍适合借鉴")

    license_obj = meta.get("license")
    api_license = license_obj.get("spdx_id") if isinstance(license_obj, dict) else None
    expected_license = source.get("spdx_license")
    if _normalize_license(expected_license) != _normalize_license(api_license):
        add(
            "error",
            "license-mismatch",
            f"许可证与清单不符：清单为 {expected_license}，GitHub 为 {api_license or 'null'}",
        )

    # 2. revision 是否仍然存在（最低成本的「没写错」验证）。
    revision = str(source.get("revision") or "")
    if not revision:
        add("error", "revision-missing", "清单缺少 revision，无法核验")
    else:
        try:
            _fetch_json(f"{base}/commits/{revision}", timeout)
        except FetchError as exc:
            if exc.status == 404:
                add("error", "revision-missing", f"revision 在 GitHub 上不存在（HTTP 404）：{revision}")
            elif exc.status == 422:
                add("error", "revision-invalid", f"revision 格式无效（HTTP 422）：{revision}")
            elif exc.rate_limited:
                add("error", "rate-limited", str(exc))
            else:
                add("error", "revision-unreadable", f"无法核验 revision：{exc}")

    # 3. 当前 HEAD，与清单 revision 不同只是漂移提示，不是失败。
    try:
        commits = _fetch_json(f"{base}/commits?per_page=1", timeout)
    except FetchError as exc:
        if exc.rate_limited:
            add("error", "rate-limited", str(exc))
        else:
            add("error", "head-unreadable", f"无法读取当前 HEAD：{exc}")
    else:
        if not isinstance(commits, list) or not commits:
            add("error", "empty-commits", "GitHub API 返回 0 条提交，无法判断 HEAD（空结果守卫）")
        else:
            first = commits[0]
            head = first.get("sha") if isinstance(first, dict) else None
            if not isinstance(head, str) or not head:
                add("error", "head-invalid", "GitHub API 返回的提交缺少 sha，无法判断 HEAD")
            elif revision and head.lower() != revision.lower():
                add(
                    "info",
                    "head-drift",
                    f"HEAD 已漂移：清单 revision {revision[:12]}…，当前 HEAD {head[:12]}…，应复核上游变化",
                )

    # 4. 台账是否陈旧。
    checked_at = source.get("checked_at")
    try:
        checked = date.fromisoformat(str(checked_at))
    except (TypeError, ValueError):
        add("error", "checked-at-invalid", f"checked_at 无法解析为日期：{checked_at}")
    else:
        age = ((today or date.today()) - checked).days
        if age > stale_days:
            add(
                "warning",
                "stale",
                f"台账陈旧：checked_at={checked_at}，已 {age} 天未复核（阈值 {stale_days} 天）",
            )

    return {"id": source_id, "url": url, "findings": findings}


def check_remote_manifest(
    path: Path = DEFAULT_MANIFEST,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    stale_days: int = DEFAULT_STALE_DAYS,
    today: date | None = None,
) -> dict[str, object]:
    """逐条联网核验清单中的来源。

    空清单或 API 空结果都必须报错：让检查「什么都没查」却输出全部通过，
    比直接失败更危险。
    """
    findings: list[dict[str, str]] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        findings.append(_finding("error", "manifest-unreadable", f"无法读取清单：{exc}"))
        return {"checked": 0, "sources": [], "findings": findings}

    entries = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        findings.append(
            _finding(
                "error",
                "empty-manifest",
                "清单里 0 条来源，联网核验没有可检查的对象（空解析守卫）",
            )
        )
        return {"checked": 0, "sources": [], "findings": findings}

    results: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            findings.append(_finding("error", "invalid-source", "来源记录不是对象，无法核验"))
            continue
        result = check_remote_source(entry, timeout=timeout, stale_days=stale_days, today=today)
        results.append(result)
        findings.extend(result["findings"])  # type: ignore[arg-type]

    return {"checked": len(results), "sources": results, "findings": findings}


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _print_network_report(
    checked: int, findings: list[dict[str, str]], counts: dict[str, int]
) -> None:
    """联网模式下默认的人类可读输出（``--json`` 时改走结构化输出）。"""
    print(f"上游来源联网核验：{checked} 条")
    for item in findings:
        location = item.get("id") or item.get("url") or "manifest"
        print(f"[{item['severity']}] {location}: {item['message']}")
    print(f"汇总：错误 {counts['error']}，警告 {counts['warning']}，提示 {counts['info']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate upstream source manifest (offline by default; --network verifies GitHub)."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument(
        "--skip-ledger",
        action="store_true",
        help="run only the manifest schema check (the ledger may not exist yet)",
    )
    parser.add_argument(
        "--ledger-only",
        action="store_true",
        help=(
            "run only the ledger-coverage check. CI uses this as its own step so a "
            "coverage failure is located separately from a manifest-schema failure."
        ),
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="query the GitHub API to verify each source (off by default; no network otherwise)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"per-request timeout in seconds (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"warn when checked_at is older than N days (default: {DEFAULT_STALE_DAYS})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON in --network mode (offline output is always JSON)",
    )
    args = parser.parse_args(argv)

    if args.skip_ledger and args.ledger_only:
        print(json.dumps({"ok": False, "errors": ["--skip-ledger 与 --ledger-only 互斥"]}, ensure_ascii=False, indent=2))
        return 1
    if args.network and args.ledger_only:
        print(
            json.dumps(
                {"ok": False, "errors": ["--network 与 --ledger-only 互斥：联网核验针对清单，不是台账"]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    if not args.network:
        # 默认路径保持原样：纯离线，输出与历史版本完全一致。
        if args.ledger_only:
            coverage = check_ledger_coverage(args.ledger, args.manifest)
            report = {"ok": bool(coverage["ok"]), "mode": "ledger-only", "ledger_coverage": coverage}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 1

        report = validate(args.manifest)
        schema_ok = bool(report["ok"])
        coverage = None if args.skip_ledger else check_ledger_coverage(args.ledger, args.manifest)
        ok = schema_ok and (coverage is None or bool(coverage["ok"]))

        report["schema_ok"] = schema_ok
        report["ok"] = ok
        if coverage is not None:
            report["ledger_coverage"] = coverage
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    local = validate(args.manifest)
    coverage = None if args.skip_ledger else check_ledger_coverage(args.ledger, args.manifest)
    remote = check_remote_manifest(
        args.manifest,
        timeout=args.timeout,
        stale_days=args.stale_days,
    )

    findings: list[dict[str, str]] = list(remote["findings"])  # type: ignore[arg-type]
    for error in local["errors"]:  # type: ignore[union-attr]
        findings.append(_finding("error", "schema", str(error)))
    if coverage is not None:
        for error in coverage["errors"]:  # type: ignore[union-attr]
            findings.append(_finding("error", "ledger", str(error)))

    counts = _counts(findings)
    checked = int(remote["checked"])
    ok = counts["error"] == 0 and checked > 0

    if args.json:
        report = {
            "ok": ok,
            "mode": "network",
            "checked": checked,
            "schema_ok": bool(local["ok"]),
            "ledger_ok": None if coverage is None else bool(coverage["ok"]),
            "counts": counts,
            "findings": findings,
            "sources": remote["sources"],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_network_report(checked, findings, counts)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
