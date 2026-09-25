"""确定性技能路由打分引擎。

不依赖 LLM、embedding 或网络：只用归一化后的子串/词元匹配与语言线索打分，
返回 primary / complementary / additional 三层候选，并附带命中证据。

分数用于排序，不是概率，也不是质量评分。
"""

from __future__ import annotations

import re
from typing import Any

from .index_builder import normalize

SIGNAL_BASE = 3.0
SIGNAL_LENGTH_BONUS = 0.25
SIGNAL_LENGTH_CAP = 8
NAME_TOKEN_WEIGHT = 2.0
DESC_TOKEN_WEIGHT = 0.5
LANGUAGE_MATCH_BONUS = 2.5
LANGUAGE_CONFLICT_PENALTY = -2.0
RULE_WEIGHT = 1.5
COMPLEMENTARY_RATIO = 0.4
MIN_PRIMARY_SCORE = 1.0

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "is", "are",
    "脚本", "自动化", "的", "和", "与", "及", "我", "要", "想", "帮", "请", "一个", "一下",
}

LANGUAGE_HINTS: dict[str, tuple[str, ...]] = {
    "python": ("python", "py", "pip", "requests", "httpx", "asyncio"),
    "javascript": ("javascript", "js", "node", "nodejs", "npm", "axios", "typescript", "ts"),
}

TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(normalize(text)) if tok not in STOPWORDS]


def detect_languages(query: str) -> set[str]:
    detected: set[str] = set()
    normalized = normalize(query)
    for language, hints in LANGUAGE_HINTS.items():
        for hint in hints:
            if re.search(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9])", normalized):
                detected.add(language)
                break
    return detected


def _signal_hits(signals: list[str], normalized_query: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for signal in signals:
        candidate = normalize(signal)
        if not candidate:
            continue
        if candidate in normalized_query:
            weight = SIGNAL_BASE + min(len(candidate), SIGNAL_LENGTH_CAP) * SIGNAL_LENGTH_BONUS
            hits.append({"type": "signal", "value": signal, "weight": round(weight, 2)})
    return hits


def _token_hits(skill: dict[str, Any], query_tokens: set[str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    name_tokens = {part for part in re.split(r"[-_]", skill["name"]) if len(part) > 2}
    for token in sorted(name_tokens & query_tokens):
        hits.append({"type": "name_token", "value": token, "weight": NAME_TOKEN_WEIGHT})
    desc_tokens = set(tokenize(skill.get("description", ""))) - STOPWORDS
    for token in sorted(desc_tokens & query_tokens):
        hits.append({"type": "description_token", "value": token, "weight": DESC_TOKEN_WEIGHT})
    return hits


def _rule_hits(index: dict[str, Any], normalized_query: str, skill_name: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for rule in index.get("routing_rules", []):
        if skill_name not in rule.get("then", []):
            continue
        matched = [trigger for trigger in rule.get("when", []) if normalize(trigger) in normalized_query]
        if matched:
            hits.append(
                {
                    "type": "routing_rule",
                    "value": rule.get("id", ""),
                    "matched": matched,
                    "weight": RULE_WEIGHT,
                }
            )
    return hits


def _score_skill(skill: dict[str, Any], index: dict[str, Any], normalized_query: str, query_tokens: set[str]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    score = 0.0

    hits = _signal_hits(skill.get("signals", []), normalized_query)
    hits += _token_hits(skill, query_tokens)
    hits += _rule_hits(index, normalized_query, skill["name"])
    for hit in hits:
        score += hit["weight"]
        evidence.append(hit)

    detected = detect_languages(normalized_query)
    languages = set(skill.get("languages") or [])
    if detected and languages:
        if detected & languages:
            score += LANGUAGE_MATCH_BONUS
            evidence.append({"type": "language", "value": sorted(detected & languages)[0], "weight": LANGUAGE_MATCH_BONUS})
        else:
            score += LANGUAGE_CONFLICT_PENALTY
            evidence.append(
                {
                    "type": "language_conflict",
                    "value": sorted(detected)[0],
                    "weight": LANGUAGE_CONFLICT_PENALTY,
                }
            )

    if score > 0:
        score += max(0.0, (100 - int(skill.get("priority", 50))) / 100.0)

    return {"skill": skill["name"], "score": round(score, 3), "evidence": evidence}


def _module_suggestions(index: dict[str, Any], normalized_query: str) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    modules = index.get("modules", [])
    for category, config in (index.get("module_categories") or {}).items():
        matched = [s for s in config.get("signals", []) if normalize(s) in normalized_query]
        if not matched:
            continue
        names = sorted(m["name"] for m in modules if m["category"] == category)
        suggestions.append({"category": category, "matched": matched, "modules": names})
    return suggestions


def route(query: str, index: dict[str, Any], top_k: int = 5) -> dict[str, Any]:
    """对单条查询做确定性路由，返回三层候选与证据。"""
    normalized_query = normalize(query)
    query_tokens = set(tokenize(query))
    scored = [_score_skill(skill, index, normalized_query, query_tokens) for skill in index.get("skills", [])]
    scored = [item for item in scored if item["score"] > 0]
    scored.sort(key=lambda item: (-item["score"], item["skill"]))

    top_score = scored[0]["score"] if scored else 0.0
    primary: list[dict[str, Any]] = []
    complementary: list[dict[str, Any]] = []
    additional: list[dict[str, Any]] = []

    if top_score >= MIN_PRIMARY_SCORE:
        primary = [scored[0]]
        for item in scored[1:]:
            if item["score"] >= top_score * COMPLEMENTARY_RATIO:
                complementary.append(item)
            else:
                additional.append(item)
    else:
        additional = list(scored)

    by_name = {skill["name"]: skill for skill in index.get("skills", [])}
    for group in (primary, complementary, additional):
        for item in group:
            meta = by_name.get(item["skill"], {})
            item["invocation"] = meta.get("invocation", "automatic")
            item["role"] = meta.get("role", "leaf")
            item["path"] = meta.get("path", "")

    primary = primary[:top_k]
    complementary = complementary[:top_k]
    additional = additional[: max(0, top_k - len(primary))]

    next_step = ""
    if primary:
        next_step = f"load_skill('{primary[0]['skill']}')"
        if primary[0]["invocation"] == "manual-only":
            next_step = f"向用户确认后再 load_skill('{primary[0]['skill']}')"

    return {
        "query": query,
        "normalized_query": normalized_query,
        "detected_languages": sorted(detect_languages(query)),
        "primary": primary,
        "complementary": complementary,
        "additional": additional,
        "modules": _module_suggestions(index, normalized_query),
        "next_step": next_step,
        "note": "分数用于排序，不是概率；最终技能选择由 Agent 决定。",
    }


DEFAULT_README_CHARS = 4000


def describe_module(name: str, index: dict[str, Any], root, max_chars: int = DEFAULT_README_CHARS) -> dict[str, Any]:
    """返回单个模块的详情（README 摘要、入口文件、依赖）。只读，不执行。"""
    from pathlib import Path

    root = Path(root)
    for module in index.get("modules", []):
        if module["name"] == name:
            detail = dict(module)
            readme_text = ""
            if module.get("readme"):
                readme_path = root / module["readme"]
                if readme_path.is_file():
                    readme_text = readme_path.read_text(encoding="utf-8", errors="replace")
            detail["readme_excerpt"] = readme_text[:max_chars]
            detail["readme_truncated"] = len(readme_text) > max_chars
            detail["readme_chars"] = len(readme_text)
            detail["executes_anything"] = False
            return detail
    known = ", ".join(sorted(m["name"] for m in index.get("modules", [])))
    raise KeyError(f"未知模块：{name}；可用模块：{known}")


DEFAULT_MAX_CHARS = 24000


def _headings(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.startswith("#")]


INTERPRETER_BY_SUFFIX = {
    ".py": "python",
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".ts": "node",
}
MAX_TIMEOUT_SECONDS = 600


def _append_audit(root, index: dict[str, Any], record: dict[str, Any]) -> str:
    """追加一条审计记录。日志失败不影响主流程，只返回空串。"""
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    config = index.get("execution") or {}
    rel = config.get("audit_log") or "exports/automation/module-audit.jsonl"
    try:
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return rel
    except OSError:
        return ""


def _resolve_entry(module: dict[str, Any], entry: str | None) -> tuple[str | None, str]:
    entries = module.get("entries") or []
    if entry:
        wanted = entry.replace("\\", "/")
        for candidate in entries:
            if candidate == wanted or candidate.endswith("/" + wanted):
                return candidate, ""
        return None, f"入口不在该模块的可执行文件内：{entry}；可选：{', '.join(entries) or '(无)'}"
    if len(entries) == 1:
        return entries[0], ""
    if not entries:
        return None, "该模块没有可执行入口文件"
    return None, f"该模块有多个入口，必须显式指定 entry：{', '.join(entries)}"


def run_module(
    name: str,
    index: dict[str, Any],
    root,
    args: list[str] | None = None,
    entry: str | None = None,
    dry_run: bool | None = None,
    timeout: int | None = None,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """按白名单执行模块脚本。三道护栏：白名单、审计日志、dry-run 默认。

    未在 `execution.allowlist` 中的模块一律拒绝；默认只解析命令不执行。
    始终以 argv 列表调用（不使用 shell），cwd 固定为模块目录，并有超时与输出截断。
    """
    import subprocess
    import sys
    import time
    from pathlib import Path

    root = Path(root)
    config = dict(index.get("execution") or {})
    result: dict[str, Any] = {
        "module": name,
        "allowed": False,
        "executed": False,
        "dry_run": None,
        "entry": None,
        "argv": [],
        "cwd": None,
        "exit_code": None,
        "duration_ms": 0,
        "stdout": "",
        "stderr": "",
        "truncated": False,
        "reason": "",
        "audit_log": "",
    }

    def finish(reason: str) -> dict[str, Any]:
        result["reason"] = reason
        result["audit_log"] = _append_audit(
            root,
            index,
            {
                "module": name,
                "entry": result["entry"],
                "argv": result["argv"],
                "dry_run": result["dry_run"],
                "allowed": result["allowed"],
                "executed": result["executed"],
                "exit_code": result["exit_code"],
                "reason": reason,
            },
        )
        return result

    if not config.get("enabled", True):
        return finish("执行功能已在 routing.source.json 的 execution.enabled 中关闭")

    module = next((m for m in index.get("modules", []) if m["name"] == name), None)
    if module is None:
        known = ", ".join(sorted(m["name"] for m in index.get("modules", [])))
        return finish(f"未知模块：{name}；可用模块：{known}")

    allowlist = list(config.get("allowlist") or [])
    if name not in allowlist:
        return finish(
            f"模块 `{name}` 不在执行白名单中（当前白名单：{', '.join(allowlist) or '空'}）。"
            f"如需启用，请在 routing.source.json 的 execution.allowlist 中加入该模块名并重建索引。"
        )

    resolved_entry, entry_error = _resolve_entry(module, entry)
    if resolved_entry is None:
        return finish(entry_error)

    result["allowed"] = True  # 已通过白名单闸门，后续失败只影响是否执行

    entry_path = root / resolved_entry
    if not entry_path.is_file():
        return finish(f"入口文件不存在：{resolved_entry}")

    suffix = entry_path.suffix.lower()
    interpreter_kind = INTERPRETER_BY_SUFFIX.get(suffix)
    if interpreter_kind is None:
        return finish(f"不支持的入口类型：{suffix}")
    interpreter = (python_executable or sys.executable) if interpreter_kind == "python" else "node"

    argv = [interpreter, str(entry_path)]
    for item in args or []:
        if not isinstance(item, str):
            return finish(f"参数必须是字符串：{item!r}")
        argv.append(item)

    effective_dry_run = config.get("default_dry_run", True) if dry_run is None else bool(dry_run)
    effective_timeout = int(timeout if timeout is not None else config.get("timeout_seconds", 120))
    effective_timeout = max(1, min(effective_timeout, MAX_TIMEOUT_SECONDS))
    max_chars = int(config.get("max_output_chars", 8000))

    result.update(
        {
            "dry_run": effective_dry_run,
            "entry": resolved_entry,
            "argv": argv,
            "cwd": str(entry_path.parent),
        }
    )

    if effective_dry_run:
        return finish("dry-run：仅解析命令，未执行。传 dry_run=false 才真正执行。")

    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(entry_path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        return finish(f"执行超时（>{effective_timeout}s），已终止")
    except OSError as exc:
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        return finish(f"无法启动进程：{exc}")

    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    stdout, stderr = completed.stdout or "", completed.stderr or ""
    result["truncated"] = len(stdout) > max_chars or len(stderr) > max_chars
    result["stdout"] = stdout[:max_chars]
    result["stderr"] = stderr[:max_chars]
    result["exit_code"] = completed.returncode
    result["executed"] = True
    return finish(f"已执行，退出码 {completed.returncode}")


def load_skill(name: str, index: dict[str, Any], root, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """按技能名返回 SKILL.md 正文（渐进式披露）。

    超过 max_chars 时截断，并附章节目录与完整路径，便于按需分段读取，
    避免大技能（如 automation-script-dev-py 约 53 KB）一次性占满上下文。
    """
    from pathlib import Path

    for skill in index.get("skills", []):
        if skill["name"] == name:
            path = Path(root) / skill["path"]
            text = path.read_text(encoding="utf-8")
            if len(text) <= max_chars:
                return text
            outline = "\n".join(f"  {h}" for h in _headings(text)[:40])
            return (
                f"{text[:max_chars]}\n\n"
                f"--- [已截断] 全文 {len(text)} 字符，仅返回前 {max_chars} 字符 ---\n"
                f"完整文件：{skill['path']}\n"
                f"章节目录：\n{outline}\n"
                f"需要后续章节请直接按 offset 读取该文件。\n"
            )
    known = ", ".join(sorted(s["name"] for s in index.get("skills", [])))
    raise KeyError(f"未知技能：{name}；可用技能：{known}")
