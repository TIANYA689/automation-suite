"""知识库文件级路由（技能路由的第二跳）。

技能路由（`router.route`）回答"用哪个技能"；本模块回答"读哪篇知识"。
索引来源是各 `kb/<领域>/techniques/kb-index.json`，与 `routing.source.json`
是两层关系，互不覆盖。

打分权重沿用 open-reverselab 的 kb_router 基线：
- 命中条目 signals：+10（叠加长度奖励，长信号更具体）
- 命中条目 id：+5
- 命中文件路径词：+3
- priority 只用于同分排序，不参与加分

零第三方依赖，只用标准库；纯只读，不执行任何文件。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

INDEX_NAME = "kb-index.json"
KB_DIR = "kb"

SIGNAL_WEIGHT = 10.0
SIGNAL_LENGTH_BONUS = 0.5
SIGNAL_LENGTH_CAP = 8
ID_WEIGHT = 5.0
PATH_WEIGHT = 3.0
TOP_K = 10

TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}")


def normalize(text: str) -> str:
    """归一化：NFKC 统一全半角、转小写、压缩空白。"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").lower()).strip()


def load_kb_indexes(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """扫描 kb/**/kb-index.json，返回（条目列表, 错误列表）。

    条目的 files 已转换为相对 root 的 POSIX 路径，便于直接读取与校验。
    """
    root = Path(root)
    entries: list[dict[str, Any]] = []
    errors: list[str] = []

    for index_path in sorted((root / KB_DIR).rglob(INDEX_NAME)):
        rel_index = index_path.relative_to(root).as_posix()
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel_index}: {exc}")
            continue
        base = index_path.parent
        for item in payload.get("entries", []):
            files: list[str] = []
            for name in item.get("files", []):
                candidate = (base / name).resolve()
                try:
                    files.append(candidate.relative_to(root).as_posix())
                except ValueError:
                    errors.append(f"{rel_index}: 文件越出仓库范围 {name}")
            entries.append(
                {
                    "id": item.get("id", ""),
                    "signals": item.get("signals", []),
                    "files": files,
                    "priority": int(item.get("priority", 0)),
                    "index": rel_index,
                }
            )
    return entries, errors


def _signal_hits(signals: list[str], normalized_query: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for signal in signals:
        candidate = normalize(signal)
        if not candidate or candidate not in normalized_query:
            continue
        weight = SIGNAL_WEIGHT + min(len(candidate), SIGNAL_LENGTH_CAP) * SIGNAL_LENGTH_BONUS
        hits.append({"type": "signal", "value": signal, "weight": round(weight, 2)})
    return hits


def _id_hits(entry_id: str, normalized_query: str) -> list[dict[str, Any]]:
    candidate = normalize(entry_id)
    if candidate and candidate in normalized_query:
        return [{"type": "id", "value": entry_id, "weight": ID_WEIGHT}]
    return []


def _path_hits(files: list[str], query_tokens: set[str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for path in files:
        stem = Path(path).stem
        tokens = {tok for tok in TOKEN_RE.findall(normalize(stem)) if len(tok) > 2}
        for token in sorted(tokens & query_tokens):
            hits.append({"type": "path_token", "value": f"{token}@{stem}", "weight": PATH_WEIGHT})
    return hits


def route_kb(query: str, entries: list[dict[str, Any]], top_k: int = TOP_K) -> dict[str, Any]:
    """把需求文本映射到知识文件，返回按分数排序的候选与命中证据。"""
    normalized_query = normalize(query)
    query_tokens = set(TOKEN_RE.findall(normalized_query))
    scored: list[dict[str, Any]] = []

    for entry in entries:
        evidence = (
            _signal_hits(entry.get("signals", []), normalized_query)
            + _id_hits(entry.get("id", ""), normalized_query)
            + _path_hits(entry.get("files", []), query_tokens)
        )
        if not evidence:
            continue
        scored.append(
            {
                "id": entry["id"],
                "score": round(sum(hit["weight"] for hit in evidence), 2),
                "priority": entry.get("priority", 0),
                "index": entry.get("index", ""),
                "files": entry.get("files", []),
                "evidence": evidence,
            }
        )

    scored.sort(key=lambda item: (-item["score"], -item["priority"], item["id"]))
    return {
        "query": query,
        "normalized_query": normalized_query,
        "matched": scored[:top_k],
        "total_entries": len(entries),
        "note": "分数用于排序，不是概率；命中文件仍需打开确认适用性。",
    }


def verify_kb_files(result: dict[str, Any], root: Path) -> dict[str, Any]:
    """给路由结果的每个文件附上存在性标记（✓/✗ 的可判定版本）。"""
    root = Path(root)
    for item in result.get("matched", []):
        item["files_exist"] = [
            {"path": path, "exists": (root / path).is_file()} for path in item.get("files", [])
        ]
    return result


def kb_route(query: str, root: Path, top_k: int = TOP_K, verify: bool = False) -> dict[str, Any]:
    """一步完成：加载索引 → 路由 →（可选）校验文件存在。"""
    root = Path(root)
    entries, errors = load_kb_indexes(root)
    result = route_kb(query, entries, top_k=top_k)
    if verify:
        result = verify_kb_files(result, root)
    if errors:
        result["index_errors"] = errors
    return result
