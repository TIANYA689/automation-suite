#!/usr/bin/env python3
"""第三方脚本静态拆解：把"别人的脚本"读成结构、能力与复用候选。

这是 `har_probe` 在**代码侧**的对应物。HAR 盘点回答"这个站点调了哪些接口"，
本工具回答"这个脚本是怎么写的、哪些值得我复用、哪些坚决不吸收"。

产出四张表：

1. **结构清单** —— 有哪些文件、属于哪一类（可读 / 压缩 / 混淆 / 静态库 / 读不出）、多少行
2. **能力矩阵** —— 命中哪些基础设施维度、在第几行命中、对应本项目哪个 Pattern 编号
3. **复用候选** —— 按 `direct / adapt / borrow / refuse` 四档归位（判据见
   `skills/third-party-script-teardown/references/reuse-classification.md`）
4. **缺口与风险** —— 没命中的维度、以及**明确不吸收**的写法

硬约束（与 har_* 系列同一套纪律）：

- **只解析，不执行**。Python 走 `ast.parse`，JS 走正则；不导入、不 `eval`、不下载。
  目标目录里的脚本可能带副作用，本工具连 `__main__` 都不会碰。
- **片段默认掩码**。长不透明串、邮箱、手机号在输出前被替换；
  凭据类命中（`hardcoded_secret`）**只报行号不报片段**。
- **分类是启发式**。每条结论带 `confidence` 与 `why`，不把猜测写成确定结论。
- **"没命中"与"没材料"分开报**。扫不到脚本、后缀不在表里、解码失败是三件事。

零第三方依赖，可被 `scripts/misc/run_offline_tests.py` 直接发现。

用法：
    python scripts/misc/script_teardown.py <目录或文件> [<目录或文件> ...]
    python scripts/misc/script_teardown.py <目录> --json
    python scripts/misc/script_teardown.py <目录> --no-snippets
    python scripts/misc/script_teardown.py <目录> --ascii --top 5
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

# 散文区间（注释 / 文档字符串的识别与等长抹除）在 `text_spans.py`：
# 那是"文本怎么切"的问题，与"命中什么维度"（`teardown_rules.py`）
# 和"报告长什么样"（`teardown_render.py`）是三件不同的事，变更轴也不同。
from text_spans import blank_spans, prose_spans

# 呈现层（显示宽度对齐、截断、渲染）在 `teardown_render.py`：
# 调排版不该动分析代码，反之亦然。
from teardown_render import render, supports_box

# 规则表（检测维度 / 风险规则 / 配套文件 / 分类常量）在 `teardown_rules.py`：
# 加一个维度只改那张表，本文件是引擎，不随维度数量增长。
from teardown_rules import (
    BASE64_BLOB,
    BUNDLE_HINT,
    DEFAULT_EXTENSIONS,
    DELIVERY_SPECS,
    ESCAPE_RUN,
    FEATURES,
    GROUPS,
    LANG_BY_SUFFIX,
    MASK_EMAIL,
    MASK_PHONE,
    MASK_RUN,
    OBFUSCATED_IDENT,
    RISKS,
    SKIP_DIR_NAMES,
    TIERS,
    VENDOR_DIR_NAMES,
)

# ---------------------------------------------------------------- 工具函数


def mask_snippet(text: str, limit: int = 100) -> str:
    """把一行压成可安全粘贴的片段。

    与 `har_source.mask_runs` 同一纪律：**降噪与防误贴，不是安全边界**。
    它挡的是"顺手把目标脚本里的真值抄进报告"，挡不住刻意规避。
    """
    collapsed = re.sub(r"\s+", " ", text).strip()
    collapsed = MASK_EMAIL.sub("<email>", collapsed)
    collapsed = MASK_PHONE.sub("<phone>", collapsed)
    collapsed = MASK_RUN.sub(lambda m: f"<len={len(m.group(0))}>", collapsed)
    if len(collapsed) > limit:
        collapsed = collapsed[:limit] + "…"
    return collapsed


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _compile_all(patterns: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.MULTILINE) for pattern in patterns]


_COMPILED: dict[tuple[str, ...], list[re.Pattern[str]]] = {}


def _patterns_of(owner: Any) -> list[re.Pattern[str]]:
    """按 regexes 元组缓存编译结果。

    刻意不用 `id(owner)` 当键：id 会在对象回收后被复用，缓存可能张冠李戴；
    而 regexes 是字符串元组，本身可哈希，做键既稳定又能跨 Feature/Risk 共享。
    """
    key = owner.regexes
    if key not in _COMPILED:
        _COMPILED[key] = _compile_all(key)
    return _COMPILED[key]


# ---------------------------------------------------------------- 分类


def classify(text: str, relative: str, suffix: str, decoded: bool) -> dict[str, Any]:
    """判定一个文件属于哪一类，并给出**可复核的线索**。

    判定是启发式，所以每条结论都带 why：报告里"因为行太长"比"压缩"更有用，
    因为下一个人可以据此推翻它。
    """
    if not decoded:
        # 早返回也必须带上完整字段：调用方一律读 `language`，
        # 少一个键就是 KeyError，而"读不出的文件"恰恰是最需要被报出来的那一类。
        return {
            "kind": "unreadable",
            "confidence": "high",
            "why": ["文件不是 UTF-8 文本，未解析"],
            "lines": 0,
            "longest_line": 0,
            "packed": False,
            "language": LANG_BY_SUFFIX.get(suffix, "other"),
        }

    lines = text.splitlines() or [""]
    line_count = len(lines)
    longest = max((len(line) for line in lines), default=0)
    average = sum(len(line) for line in lines) / max(line_count, 1)
    parts = {part.lower() for part in Path(relative).parts}
    obfuscated = OBFUSCATED_IDENT.findall(text)
    escapes = ESCAPE_RUN.findall(text)
    blobs = BASE64_BLOB.findall(text)

    # 「压缩」与「打包成一段不透明载荷」是两件事：前者美化一下就还原了，
    # 后者（自解密脚本的密文段、`exec(base64…)` 的载荷）美化器对它无效，
    # 得先拿到解密方式。**两者都会让关键词彻底看不见**，所以报告必须说出来。
    # 实测校准（本地样本目录）：四个不可读文件的最长行占全文 82%–99%，
    # 而可读文件是 1.3%——单行占比是很干净的分界。
    packed = longest >= 2000 and longest / max(len(text), 1) >= 0.5

    cues: list[str] = []
    kind = "readable"

    if len(obfuscated) >= 20 or len(escapes) >= 3 or (blobs and "eval(" in text):
        kind = "obfuscated"
        if obfuscated:
            cues.append(f"`_0x` 型标识符 {len(obfuscated)} 个")
        if escapes:
            cues.append(f"连续转义串 {len(escapes)} 处")
        if blobs:
            cues.append(f"超长 base64 字面量 {len(blobs)} 处且伴随 eval")
    elif longest >= 1000 or (line_count <= 5 and len(text) > 2000) or average >= 400:
        kind = "minified"
        cues.append(f"最长行 {longest} 字符、平均 {average:.0f} 字符")
    elif BUNDLE_HINT.search(relative):
        kind = "minified"
        cues.append("文件名是打包产物命名")
    elif parts & VENDOR_DIR_NAMES:
        kind = "vendor"
        cues.append(f"位于静态库目录：{'/'.join(sorted(parts & VENDOR_DIR_NAMES))}")

    if kind == "readable":
        cues.append(f"最长行 {longest} 字符、平均 {average:.0f} 字符，未见混淆或打包特征")
    elif packed:
        cues.append(
            f"单行占全文 {longest / max(len(text), 1):.0%}（{longest} 字符）："
            "疑似加密 / 打包载荷，**关键词在里面看不见**，美化器对它无效"
        )

    confidence = "high" if (len(cues) >= 2 or kind == "readable") else "medium"
    return {
        "kind": kind,
        "confidence": confidence,
        "why": cues,
        "lines": line_count,
        "longest_line": longest,
        "packed": packed,
        "language": LANG_BY_SUFFIX.get(suffix, "other"),
    }


# ---------------------------------------------------------------- 能力与风险


def detect_features(text: str, language: str) -> list[dict[str, Any]]:
    """按维度扫描能力命中，返回每条命中的首个行号与掩码片段。

    只报**每文件每维度首个命中**：拆解报告要的是"有没有、在哪"，不是全量出现次数。
    全量会淹没输出，而且行号清单越长越没人复核。
    """
    hits: list[dict[str, Any]] = []
    for feature in FEATURES:
        if language not in feature.langs:
            continue
        for pattern in _patterns_of(feature):
            match = pattern.search(text)
            if match is None:
                continue
            hits.append(
                {
                    "id": feature.id,
                    "label": feature.label,
                    "group": feature.group,
                    "tier": feature.tier,
                    "pattern_ref": feature.pattern_ref,
                    "line": _line_of(text, match.start()),
                    "snippet": mask_snippet(match.group(0)),
                }
            )
            break
    return hits


def detect_risks(text: str) -> list[dict[str, Any]]:
    """扫描"不能照抄"的写法。

    凭据类命中**只给行号**：报告会被贴进对话、写进笔记，
    一旦片段里带上真值，泄露就发生在"检查"这个动作里。
    """
    found: list[dict[str, Any]] = []
    for risk in RISKS:
        for pattern in _patterns_of(risk):
            match = pattern.search(text)
            if match is None:
                continue
            found.append(
                {
                    "id": risk.id,
                    "label": risk.label,
                    "tier": risk.tier,
                    "why": risk.why,
                    "line": _line_of(text, match.start()),
                    "snippet": "" if risk.redact else mask_snippet(match.group(0)),
                }
            )
            break
    return found


# ---------------------------------------------------------------- 扫描


def scan_delivery(targets: Sequence[Path]) -> list[dict[str, Any]]:
    """按目录清单判定配套文件（README / 配置示例 / 依赖清单）。

    只看目标**本身及其下一层**：递归整棵树会把 node_modules 里的 package.json
    也数进来，那报的是"别人装了依赖"，不是"别人交付了什么"。
    """
    buckets: list[dict[str, Any]] = []
    for spec in DELIVERY_SPECS:
        found: list[str] = []
        for target in targets:
            root = target if target.is_dir() else target.parent
            scope = [root, *sorted(child for child in root.iterdir() if child.is_dir())] if root.is_dir() else []
            for directory in scope:
                if SKIP_DIR_NAMES & set(directory.parts):
                    continue
                try:
                    children = list(directory.iterdir())
                except OSError:
                    continue
                for child in children:
                    if child.is_file() and child.name.lower() in spec.names:
                        relative = child.relative_to(root).as_posix()
                        if relative not in found:
                            found.append(relative)
        if found:
            buckets.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "group": "运行与交付",
                    "tier": "direct",
                    "pattern_ref": spec.pattern_ref,
                    "delivery": True,
                    "hits": [{"file": name, "line": 0, "snippet": ""} for name in sorted(found)],
                }
            )
    return buckets


def _read_text(path: Path) -> tuple[str, bool]:
    try:
        return path.read_text(encoding="utf-8"), True
    except (OSError, UnicodeDecodeError):
        return "", False


def collect_files(
    targets: Sequence[Path],
    *,
    extensions: Sequence[str],
    max_files: int,
) -> tuple[list[Path], dict[str, int]]:
    """展开目标为待分析文件，并如实统计被跳过的东西。

    跳过的每一类都计数：`skipped_noise` 是"本来就不该看"，
    `skipped_suffix` 是"后缀不在表里"。两者都不是"这个脚本没有能力"。
    """
    wanted = {extension.lower() for extension in extensions}
    found: list[Path] = []
    stats = {"skipped_noise": 0, "skipped_suffix": 0, "truncated": 0}
    seen: set[Path] = set()

    for target in targets:
        if target.is_file():
            candidates = [target]
        elif target.is_dir():
            candidates = sorted(path for path in target.rglob("*") if path.is_file())
        else:
            continue
        for path in candidates:
            if path in seen:
                continue
            relative_parts = path.parts
            if SKIP_DIR_NAMES & set(relative_parts):
                stats["skipped_noise"] += 1
                continue
            if path.suffix.lower() not in wanted:
                stats["skipped_suffix"] += 1
                continue
            seen.add(path)
            found.append(path)

    if len(found) > max_files:
        stats["truncated"] = len(found) - max_files
        found = found[:max_files]
    return found, stats


def analyze(
    targets: Sequence[str | Path],
    *,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
    max_files: int = 400,
    snippets: bool = True,
) -> dict[str, Any]:
    """扫描目标并产出结构化报告。**不执行任何目标文件。**"""
    roots = [Path(target) for target in targets]
    files, skipped = collect_files(roots, extensions=extensions, max_files=max_files)

    records: list[dict[str, Any]] = []
    feature_index: dict[str, dict[str, Any]] = {}
    risk_rows: list[dict[str, Any]] = []
    unreadable: list[str] = []
    prose_total = 0

    for path in files:
        text, decoded = _read_text(path)
        classification = classify(text, path.name, path.suffix.lower(), decoded)
        language = classification["language"]
        # 每轮重置：非 Python 文件或解析失败时，prose_spans 必须收到 None 而不是
        # 上一轮的语法树——否则会用 A 文件的结构去解释 B 文件的字符串区间。
        tree: ast.AST | None = None
        entry: dict[str, Any] = {
            "path": path.as_posix(),
            "name": path.name,
            "language": language,
            "kind": classification["kind"],
            "confidence": classification["confidence"],
            "why": classification["why"],
            "lines": classification["lines"],
            "packed": classification["packed"],
            "parse_ok": None,
            "symbols": [],
            "features": [],
            "risks": [],
        }
        if decoded and language == "python":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                entry["parse_ok"] = False
            else:
                entry["parse_ok"] = True
                entry["symbols"] = [
                    node.name
                    for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ][:20]
        if decoded:
            # 命中在**去散文**的文本上做：注释与文档字符串里出现的关键词是叙述，
            # 不是代码证据（见 prose_spans）。行号仍然指向原文。
            spans = prose_spans(text, language, tree)
            code_text = blank_spans(text, spans)
            entry["prose_spans"] = len(spans)
            entry["features"] = detect_features(code_text, language)
            entry["risks"] = detect_risks(code_text)
            prose_total += len(spans)
        else:
            unreadable.append(path.name)

        if not snippets:
            for item in entry["features"]:
                item["snippet"] = ""
            for item in entry["risks"]:
                item["snippet"] = ""

        for hit in entry["features"]:
            bucket = feature_index.setdefault(
                hit["id"],
                {
                    "id": hit["id"],
                    "label": hit["label"],
                    "group": hit["group"],
                    "tier": hit["tier"],
                    "pattern_ref": hit["pattern_ref"],
                    "hits": [],
                },
            )
            bucket["hits"].append({"file": path.name, "line": hit["line"], "snippet": hit["snippet"]})
        for risk in entry["risks"]:
            risk_rows.append({"file": path.name, **risk})
        records.append(entry)

    counts = {
        "files": len(records),
        "readable": sum(1 for item in records if item["kind"] == "readable"),
        "minified": sum(1 for item in records if item["kind"] == "minified"),
        "obfuscated": sum(1 for item in records if item["kind"] == "obfuscated"),
        "vendor": sum(1 for item in records if item["kind"] == "vendor"),
        "unreadable": sum(1 for item in records if item["kind"] == "unreadable"),
    }

    # 只有**可读**的文件才算"可借鉴写法"。压缩/混淆/静态库能读，但不是范本。
    # 配套文件维度例外：它的证据就是文件名本身，没有"可读性"可言。
    readable_names = {item["name"] for item in records if item["kind"] == "readable"}
    features = list(feature_index.values()) + scan_delivery(roots)
    for bucket in features:
        bucket["hits"].sort(key=lambda item: (item["file"], item["line"]))
        names = {hit["file"] for hit in bucket["hits"]}
        bucket["readable_files"] = sorted(
            names if bucket.get("delivery") else names & readable_names
        )
        # 展示用的证据优先取**可读文件**里的那一处：结论是据可读代码下的，
        # 却拿压缩文件的行号当证据，读者会以为范本在那段不可读的代码里。
        preferred = [
            hit for hit in bucket["hits"] if hit["file"] in set(bucket["readable_files"])
        ]
        bucket["preferred"] = (preferred or bucket["hits"])[0]
    features.sort(key=lambda item: (GROUPS.index(item["group"]), item["id"]))

    reuse: dict[str, list[dict[str, Any]]] = {tier: [] for tier in TIERS}
    non_reference: list[dict[str, Any]] = []
    for bucket in features:
        if not bucket["readable_files"]:
            # 只在压缩/混淆/静态库里出现过的维度：它是**信号**，不是范本。
            # 放进复用候选会让人以为"这里有值得抄的写法"，实际那段代码不可读。
            non_reference.append(
                {
                    "id": bucket["id"],
                    "label": bucket["label"],
                    "files": sorted({hit["file"] for hit in bucket["hits"]}),
                }
            )
            continue
        reuse[bucket["tier"]].append(
            {
                "id": bucket["id"],
                "label": bucket["label"],
                "pattern_ref": bucket["pattern_ref"],
                "files": bucket["readable_files"],
            }
        )
    for risk in risk_rows:
        if risk["tier"] in reuse:
            reuse[risk["tier"]].append(
                {
                    "id": risk["id"],
                    "label": risk["label"],
                    "pattern_ref": "—",
                    "files": [risk["file"]],
                }
            )

    gaps = [
        {
            "id": feature.id,
            "label": feature.label,
            "group": feature.group,
            "pattern_ref": feature.pattern_ref,
        }
        for feature in FEATURES
        if feature.id not in feature_index
    ]

    notes = _build_notes(records, skipped, unreadable, features, prose_total)

    return {
        "targets": [path.as_posix() for path in roots],
        "scope": {
            "extensions": list(extensions),
            "max_files": max_files,
            "skipped_dirs": sorted(SKIP_DIR_NAMES),
            "snippets": snippets,
            "prose_spans_masked": prose_total,
        },
        "counts": counts,
        "skipped": skipped,
        "files": records,
        "features": features,
        "reuse": reuse,
        "non_reference": non_reference,
        "gaps": gaps,
        "risks": risk_rows,
        "notes": notes,
        "confidence": "heuristic",
        "disclosure": "分类与命中均为静态启发式；未执行、未导入、未联网。结论须经人工复核后才写入知识库。",
    }


def _build_notes(
    records: list[dict[str, Any]],
    skipped: dict[str, int],
    unreadable: list[str],
    features: list[dict[str, Any]],
    prose_total: int = 0,
) -> list[str]:
    """把"没材料"与"没命中"分开说——这是本工具最容易出错的一处。"""
    notes: list[str] = []
    if not records:
        notes.append(
            "没有扫到任何脚本：目标目录为空、后缀不在范围内，或文件都在噪声目录里。"
            "这是「没有材料」，不是「这个脚本没有能力」。"
        )
        return notes
    if skipped.get("skipped_suffix"):
        notes.append(
            f"有 {skipped['skipped_suffix']} 个文件因后缀不在扫描范围内被跳过"
            "（通常含 README、配置示例、数据文件）；目标若用其它后缀，用 --ext 显式扩大范围。"
        )
    if skipped.get("truncated"):
        notes.append(f"有 {skipped['truncated']} 个文件因 --max-files 上限未分析。")
    if unreadable:
        notes.append(
            f"{len(unreadable)} 个文件不是 UTF-8 文本（{', '.join(unreadable[:3])}…），"
            "**能力矩阵对它们无结论**。"
        )
    if prose_total:
        # 过滤必须**被说明**：静默剔除会让人以为"这里本来就没有关键词"，
        # 而真相是"有，但在注释里"。想连散文一起看的人得知道有这个开关。
        notes.append(
            f"已在 {prose_total} 处注释/文档字符串上做去散文过滤：那里的关键词是叙述，"
            "不算代码证据（实测这类误报占多数）。**过滤不等于否定**——"
            "若怀疑某维度被误杀，回原文核对那几行。"
        )
    # 「没命中」与「没材料」要分开说。压缩 / 混淆 / 加密的文件是**读了、但看不进去**：
    # 关键词在那里彻底不可见，所以它们的 0 命中不能被读成"没有这个能力"。
    # 实测原形：本地样本目录里那个 143 KB 的 JS 是个自解密脚本，
    # 外层只有几十行解密器，140 KB 的正文是 AES-256-GCM 密文——
    # 工具的 26 个维度对它命中 0 个，而报告一个字都不说，读者会以为"它什么都没有"。
    packed = [item["name"] for item in records if item.get("packed")]
    if packed:
        notes.append(
            f"{len(packed)} 个文件是**加密 / 打包载荷**（{', '.join(packed[:3])}…）："
            "关键词在里面看不见，所以它们的 0 命中**不代表没有能力**，"
            "命中也不进复用候选（范本必须来自可读代码）。"
            "要判断它们的能力，先按解密 / 解混淆技能处理再回来——美化器对密文段无效。"
        )
    if not features:
        notes.append("能力矩阵全空：要么目标确实只有业务代码，要么材料没读全，先确认后者。")
    unparsed = [item["name"] for item in records if item.get("parse_ok") is False]
    if unparsed:
        notes.append(
            f"{len(unparsed)} 个 Python 文件语法解析失败（{', '.join(unparsed[:3])}…）："
            "**符号表为空，且文档字符串未参与去散文过滤**——能力矩阵会偏多"
            "（叙述被当成证据），结构清单也不全。按「材料不全」对待，"
            "不是「这个脚本没有结构」；先看它是不是被某一行非法语句弄崩了。"
        )
    readable = [item for item in records if item["kind"] == "readable"]
    if records and not readable:
        notes.append(
            "没有任何文件被判定为可读：压缩/混淆/静态库只能提供信号，"
            "不能作为「值得复用的写法」来源。"
        )
    return notes


# ---------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="第三方脚本静态拆解（只读、离线、不执行目标文件）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("targets", nargs="*", help="目标目录或脚本文件，可多个")
    parser.add_argument("--ext", action="append", default=None, help="只分析这些后缀（可重复，含点）")
    parser.add_argument("--max-files", type=int, default=400, help="最多分析多少个文件（默认 400）")
    parser.add_argument("--top", type=int, default=12, help="结构清单列出前几个文件（默认 12）")
    parser.add_argument("--no-snippets", action="store_true", help="完全不输出命中片段，只给行号")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    parser.add_argument("--ascii", action="store_true", help="用 ASCII 制表符（控制台编码画不出时自动退回）")
    parser.add_argument("--out", help="把 JSON 报告写入文件")
    args = parser.parse_args(argv)

    if not args.targets:
        parser.error("需要至少一个目标目录或文件")
    if args.max_files < 1 or args.top < 1:
        parser.error("--max-files 与 --top 必须为正整数")

    missing = [target for target in args.targets if not Path(target).exists()]
    if missing:
        print(f"[失败] 目标不存在：{', '.join(missing)}", file=sys.stderr)
        return 2

    extensions = tuple(args.ext) if args.ext else DEFAULT_EXTENSIONS
    report = analyze(
        args.targets,
        extensions=extensions,
        max_files=args.max_files,
        snippets=not args.no_snippets,
    )

    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    box = not args.ascii and supports_box(sys.stdout.encoding)
    print(render(report, box=box, top=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
