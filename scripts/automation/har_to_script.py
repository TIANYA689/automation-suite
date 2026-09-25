#!/usr/bin/env python3
"""HAR → 脚本骨架生成器：把"意图声明"翻译成符合套件范式的脚本骨架。

分工是本工具的全部设计：

| 环节 | 谁做 | 做什么 |
|---|---|---|
| 自动 | `har_probe.py` | 解析抓包、归并接口、判定参数形态 —— **只出证据** |
| 人工 | `<name>.plan.json` | 指出哪个接口是登录、哪个是签到、哪些参数要动态生成 |
| 自动 | 本脚本 | 按声明拼出骨架，并把"推不出来的部分"列成待办 |

**工具不猜语义。** role 没填、动态参数没写策略，都会变成骨架末尾「待人工完成」
清单里的一条，而不是被静默补一个看似合理的默认值。一个静默猜错的默认值，
比一条明确的待办昂贵得多——它会让人以为脚本已经能跑。

**第 4 步（签名复现）怎么闭环。** 签名算法推不出来时，生成器留一个抛错的桩，
清单上多一条待办。要消掉它，就把复现产物**回填**进 `dynamic`：

    "dynamic": {
      "sign": {
        "impl": "python",
        "source": "impl/sign.py",
        "entry": "compute_sign",
        "verified": {
          "against": "capture/x.har#POST /v1/sign/in",
          "input": {"uid": "12345", "ts": 1758700000, "nonce": "n-1"},
          "expect": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        }
      }
    }

生成器把产物原文内联进骨架的 `Dynamic`，并生成 `--selftest` 复核它。
**回填不等于消待办**：没有 `verified` 的回填只会把"没有实现"换成
"有一个没人验证过的实现"，清单不会因此变短。让"看起来能跑"变得廉价，
是本项目最贵的失败模式。

用法：

    # 1. 先盘点，并据此生成一份待填的计划模板
    python scripts/automation/har_to_script.py --har capture.har --emit-plan plan.json
    # 2. 填 role / dynamic / capture，然后校验
    python scripts/automation/har_to_script.py --har capture.har --plan plan.json --check
    # 3. 生成骨架
    python scripts/automation/har_to_script.py --har capture.har --plan plan.json --out signin.py
    # 4. 复核回填的复现产物（跑的是生成后的文件，不是产物源文件）
    python signin.py --selftest

零第三方依赖。JS 产物需要 node，且要计划显式授权（见 `allow_external_runtime`）。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.har_probe import (  # noqa: E402
    SENSITIVE_HINTS,
    load_har,
    name_hits,
    probe,
    redact,
)

# 骨架里能自动展开的动态参数策略。其余一律标 UNRESOLVED，交人工。
SUPPORTED_STRATEGIES = {
    "timestamp_s",
    "timestamp_ms",
    "uuid4",
    "random_hex32",
    "random_digits",
}

ROLES = ("login", "task", "query")
# 失败后的动作。`abort` 中止整个流程，`continue` 记一笔继续跑。
# 必须落到生成的 run() 里——只写进计划不生成代码，就是"声明了但没人看"。
ON_FAILURE = ("abort", "continue")
# multipart 只在**盘点确认没有文件字段**时可用：纯文本 part 的值在 HAR 里是完整的，
# 而文件 part 的内容还原不出来。判据由 har_probe 的 multipart_file_parts 提供。
BODY_KINDS = ("json", "form", "multipart", "query", "none")
PARADIGMS = ("oop",)

STRATEGY_FOR_KIND = {
    "timestamp_s": "timestamp_s",
    "timestamp_ms": "timestamp_ms",
    "uuid": "uuid4",
}

# --------------------------------------------------------------- 复现产物回填
#
# `dynamic` 的每个值有两种形态：
#
#   字符串 —— 策略（timestamp_s / UNRESOLVED / literal:... / env:...），工具自己展开；
#   对象   —— **复现产物**，签名算法这类推不出来的参数由人复现后回填。
#
# 回填**不等于**消待办。只有带 `verified` 证据的回填才消掉那条待办；
# 没有证据的回填会降级成一条新的待办（"已回填，但没人证明它对"）。
# 让"看起来能跑"变得廉价，是本项目最贵的失败模式——骨架一跑通，
# 就没人再去核对那个签名到底算得对不对了。
IMPL_KINDS = ("python", "js")

# 回填产物必须接收**整个 payload**、返回字符串。
# 签名通常要吃 body 里的好几个字段，而字典字面量内部引用不了自己——
# 所以约定产物收整个 payload，生成器在字典构建完之后单独赋值。
# 约定写死在这里，是为了让生成器**不用猜参数顺序**：猜错就是静默错值。
IMPL_CONTRACT = "(payload: dict) -> str"

# JS 产物靠 node 承载，是外部运行时。必须由计划显式授权才允许生成——
# "能力越界必须显式写进交付物"，不能靠生成器自己决定要不要调外部进程。
EXTERNAL_RUNTIME_FLAG = "allow_external_runtime"

METHOD_VERB = {
    "login": "login",
    "task": "run_task",
    "query": "query",
}

# 协议层产物，不是业务步骤。它们可以安全地自动识别——判据是 HTTP 协议本身，
# 不涉及"哪个接口是签到"这类语义判断，所以不违反"工具不猜语义"。
#
# · CONNECT 是代理隧道，永远不是接口。
# · OPTIONS 与**同路径**的其它方法并存时是 CORS 预检（浏览器自动发出，业务代码从不主动调）。
#   只有同路径没有别的方法的 OPTIONS 才保留——那可能是能力探测，需要人来判。
TUNNEL_METHODS = frozenset({"CONNECT"})


def is_step_candidate(method: str, path: str, all_endpoints: Sequence[dict[str, Any]]) -> bool:
    """这个端点是否可能是一个业务步骤。只做结构判定，不判断它是登录还是签到。"""
    method = (method or "").upper()
    if method in TUNNEL_METHODS:
        return False
    if method == "OPTIONS":
        return not any(
            (row.get("method") or "").upper() != "OPTIONS" and row.get("path") == path
            for row in all_endpoints
        )
    return True


def split_step_candidates(
    endpoints: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把端点分成（可作步骤的，协议噪音的）。顺序保持原样。"""
    steps: list[dict[str, Any]] = []
    noise: list[dict[str, Any]] = []
    for row in endpoints:
        target = steps if is_step_candidate(row.get("method", ""), row.get("path", ""), endpoints) else noise
        target.append(row)
    return steps, noise


def dynamic_impl(entry: Any) -> dict[str, Any] | None:
    """`dynamic` 的某个值是不是「复现产物」形态；是则返回规范化结果，否则 None。

    **每一处读 `dynamic` 的代码都必须先过这个函数。** 直接把值当字符串用，
    对象形态会走到 `strategy in SUPPORTED_STRATEGIES` 上——dict 是 unhashable 的，
    抛的是 `TypeError` 而不是一条能读的校验失败。
    """
    if not isinstance(entry, dict):
        return None
    return {
        "impl": str(entry.get("impl", "")).strip().lower(),
        "source": str(entry.get("source", "")).strip(),
        "entry": str(entry.get("entry", "")).strip(),
        "runtime": str(entry.get("runtime", "")).strip().lower(),
        "verified": entry.get("verified") or None,
    }


def _impl_kinds(plan: dict[str, Any]) -> set[str]:
    """计划里回填产物用到了哪些实现形态。"""
    found: set[str] = set()
    for raw in (plan.get("dynamic") or {}).values():
        impl = dynamic_impl(raw)
        if impl:
            found.add(impl["impl"])
    return found


class PlanError(Exception):
    """计划文件不合法。"""


# ------------------------------------------------------------------ 计划模板


def emit_plan(report: dict[str, Any]) -> dict[str, Any]:
    """从盘点结果生成一份**待填**的计划模板。

    能自动填的都填上（端点、body 形态、动态参数候选），
    填不了的一律留空并给出说明——留空本身就是交给人的信息。
    """
    endpoints = report.get("endpoints") or []
    hosts = [row["host"] for row in report.get("hosts") or [] if row.get("api")]
    base_url = "https://" + hosts[0] if hosts else "<待填：接口所在域名>"

    dynamic: dict[str, str] = {}
    for row in (report.get("fields") or {}).get("volatile_candidates") or []:
        # cookie / header 里的值不是"要生成"的参数，是"要带上"的凭证，别混进 dynamic。
        where = set(row.get("where") or [])
        if where and not where & {"query", "body.json", "body.form", "body.multipart"}:
            continue
        kinds = list((row.get("value_kinds") or {}).keys())
        strategy = "UNRESOLVED"
        for kind in kinds:
            if kind in STRATEGY_FOR_KIND:
                strategy = STRATEGY_FOR_KIND[kind]
                break
        dynamic.setdefault(row["name"], strategy)

    step_endpoints, noise = split_step_candidates(endpoints)

    steps = []
    for index, row in enumerate(step_endpoints, 1):
        kinds = [kind for kind in (row.get("body_kinds") or {}) if kind != "empty"]
        if not kinds:
            body = "query" if row.get("query_keys") else "none"
        elif "json" in kinds:
            body = "json"
        elif "form" in kinds:
            body = "form"
        elif "multipart" in kinds:
            body = "multipart"
        else:
            body = "none"
        steps.append(
            {
                "id": f"step_{index}",
                "role": "",
                "endpoint": f"{row['method']} {row['path']}",
                "body": body,
                "path_params": {},
                "static": {},
                "dynamic": [],
                "capture": {},
                "on_failure": "abort",
            }
        )

    notes = [
        "role 必须由人或代理填写（login / task / query）——工具不猜哪个接口是签到。",
        "endpoint 必须与 har_probe 的接口清单逐字一致。",
        "路径里的 {id} 等占位符要在 path_params 里声明取值方式（literal:/env:/account:/state:）。",
        "dynamic 里的名字要在顶层 dynamic 里有策略；UNRESOLVED 会进骨架的待人工完成清单。",
        "签名这类推不出来的参数，除了让生成器留一个抛错的桩，还可以**回填复现产物**："
        "把实现写成一个真实文件，在 dynamic 里写 "
        '{"impl": "python"|"js", "source": "<相对本计划的路径>", "entry": "<入口函数>", '
        '"verified": {"against": "<证据来自哪个抓包+端点>", "input": {...}, "expect": "..."}}。'
        "生成器会把产物内联进骨架的 Dynamic，并生成 --selftest 复核它。"
        "注意：**回填不等于消待办**——没有 verified 的回填会换成另一条待办，"
        "而不是让清单变短。",
        "回填产物的入口约定是收整个 payload、返回字符串；js 产物还需要在本文件里写 "
        f'"{EXTERNAL_RUNTIME_FLAG}": true，显式授权生成器去调外部运行时。',
        "static 里不要写凭证：名字命中凭证词表的常量会被拒绝生成。",
        "on_failure 决定这一步失败后是中止还是继续（abort / continue）；它会被写进生成的 run()，不是摆设。",
        "body=multipart 只在盘点确认**没有文件字段**（multipart_file_parts=0）时可用；"
        "含文件字段的 multipart 会被校验拒绝——文件内容无法从 HAR 可靠还原。",
    ]
    if noise:
        listed = "、".join(sorted({f"{row['method']} {row['path']}" for row in noise}))
        notes.append(
            f"已从步骤里剔除 {len(noise)} 个协议层产物（CONNECT 隧道 / 同路径 CORS 预检 OPTIONS），"
            f"它们不承载业务意图：{listed}。"
            "若其中确有业务接口，手工加回 steps 即可——校验仍会放行，因为它们仍在盘点结果里。"
        )

    # 跨域名端点几乎总是第三方（验证码 / CDN / 统计）。不剔除，只点名——人自己决定要不要走它。
    primary_host = hosts[0] if hosts else ""
    off_host = sorted(
        {
            f"{row['method']} {row['path']}（{row.get('host', '?')}）"
            for row in step_endpoints
            if primary_host and row.get("host") and row["host"] != primary_host
        }
    )
    if off_host:
        notes.append(
            f"以下 {len(off_host)} 个端点不在主接口域名 {primary_host} 上，通常是第三方"
            f"（验证码 / CDN / 统计）：{'、'.join(off_host)}。"
            "需要就走、不需要就删，但别当成自家接口来猜参数。"
        )

    return {
        "_说明": notes,
        "name": "<待填：脚本名>",
        "base_url": base_url,
        "env_name": "<待填：青龙环境变量名>",
        "paradigm": "oop",
        "account": {"fields": [], "separator": "#"},
        "dynamic": dynamic,
        "steps": steps,
    }


# -------------------------------------------------------------------- 校验


def _validate_impl(
    where: str, impl: dict[str, Any], plan: dict[str, Any], plan_dir: Path
) -> list[dict[str, str]]:
    """校验一份回填的复现产物。只判定，不执行——执行是产物自己的事（见 selftest）。"""
    issues: list[dict[str, str]] = []

    def add(kind: str, detail: str) -> None:
        issues.append({"where": where, "kind": kind, "detail": detail})

    kind = impl["impl"]
    if kind not in IMPL_KINDS:
        add(
            "unknown_impl",
            f"impl 取值 {'/'.join(IMPL_KINDS)}；当前为 {impl['impl']!r}。"
            "复现产物必须声明它是什么语言——生成器不按扩展名猜",
        )
        return issues

    if not impl["source"]:
        add(
            "missing_impl_source",
            "复现产物缺 source——产物必须是仓库里一个真实文件，不能是计划里的一段内联字符串。"
            "内联字符串无法被 review，也无法被独立测试",
        )
        return issues

    source_path = (plan_dir / impl["source"]).resolve()
    if not source_path.is_file():
        add(
            "missing_impl_source",
            f"source 指向的 {impl['source']} 不存在（按计划文件所在目录解析）。"
            "产物文件必须随计划一起提交，否则换台机器就生成不出来",
        )
        return issues

    if not impl["entry"]:
        add("missing_impl_entry", "复现产物缺 entry——必须指明入口函数名，工具不猜")
    elif kind == "python":
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            add("malformed_impl_source", f"复现产物不是合法 Python：{error}")
            return issues
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if impl["entry"] not in functions:
            add(
                "missing_impl_entry",
                f"复现产物顶层没有函数 {impl['entry']}（找到：{sorted(functions) or '无'}）。"
                "入口必须在顶层——嵌套函数没法内联成 Dynamic 的方法体",
            )
        elif isinstance(functions[impl["entry"]], ast.AsyncFunctionDef):
            add(
                "unsupported_impl_entry",
                f"入口 {impl['entry']} 是 async 函数，本生成器只支持 oop 范式、不生成事件循环。"
                "请把它改成同步函数（复现签名本身是纯计算，通常不需要异步）",
            )
        # 内联是**有损变换**：产物顶层的语句会落进方法体。
        # 顶层放一句 print 或 if __name__ == "__main__" 的自测块，
        # 内联后就成了"每次调用都执行"——那正是产物作者最不想要的效果。
        # 所以只放行声明类语句，其余一律让人自己挪进函数。
        allowed = (
            ast.Import,
            ast.ImportFrom,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Assign,
            ast.AnnAssign,
        )
        for node in tree.body:
            if isinstance(node, allowed):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue  # 模块 docstring
            add(
                "impure_impl_toplevel",
                f"复现产物顶层第 {node.lineno} 行是可执行语句（{type(node).__name__}）。"
                "产物会被内联进 Dynamic 的方法体，顶层语句届时变成「每次调用都执行」——"
                "尤其是 if __name__ == \"__main__\" 自测块和 print。"
                "请把这类代码挪进函数，顶层只留 import / def / class / 赋值",
            )
    elif kind == "js":
        if not plan.get(EXTERNAL_RUNTIME_FLAG):
            add(
                "external_runtime_not_authorized",
                f"复现产物是 JS，需要 node 这个**外部运行时**；计划里没有 "
                f"{EXTERNAL_RUNTIME_FLAG}: true。让生成的脚本去调外部进程是能力越界，"
                "必须由计划显式授权，不能由工具替你决定",
            )
        else:
            text = source_path.read_text(encoding="utf-8", errors="replace")
            if '"""' in text:
                add(
                    "malformed_impl_source",
                    'JS 产物里含 """，无法安全内联进生成的骨架。'
                    "请改写成不含三引号的形态（生成的骨架必须自包含，不能依赖旁边那个 .js 文件）",
                )
            elif text.rstrip().endswith("\\"):
                add("malformed_impl_source", "JS 产物以反斜杠结尾，内联进原始字符串会吞掉结尾引号")

    verified = impl["verified"]
    if verified is not None:
        if not isinstance(verified, dict):
            add("malformed_verified", "verified 必须是对象（against / input / expect）")
        else:
            for key in ("against", "expect"):
                if not str(verified.get(key) or "").strip():
                    add(
                        "malformed_verified",
                        f"verified.{key} 必须是非空字符串。"
                        "against 记录这份证据来自哪里（抓包文件 + 端点），expect 是期望值；"
                        "少了任何一个，这条「验证」就无从复核，等于没有证据",
                    )
            if not isinstance(verified.get("input"), dict):
                add("malformed_verified", "verified.input 必须是对象（产物的入参样本）")

    return issues


def validate_plan(
    plan: dict[str, Any], report: dict[str, Any], plan_dir: Path | None = None
) -> list[dict[str, str]]:
    """校验计划与盘点结果是否自洽。只判定，不修改。"""
    issues: list[dict[str, str]] = []

    def add(where: str, kind: str, detail: str) -> None:
        issues.append({"where": where, "kind": kind, "detail": detail})

    for field in ("name", "base_url", "env_name"):
        value = str(plan.get(field, "")).strip()
        if not value or value.startswith("<待填"):
            add(field, "missing_field", f"{field} 未填写")

    paradigm = plan.get("paradigm", "oop")
    if paradigm not in PARADIGMS:
        add(
            "paradigm",
            "unsupported_paradigm",
            f"目前只支持 {'/'.join(PARADIGMS)}；{paradigm} 尚未实现，请改用 oop 或手工改写",
        )

    known = {f"{row['method']} {row['path']}" for row in report.get("endpoints") or []}
    probe_body = {
        f"{row['method']} {row['path']}": set(k for k in (row.get("body_kinds") or {}) if k != "empty")
        for row in report.get("endpoints") or []
    }
    probe_files = {
        f"{row['method']} {row['path']}": int(row.get("multipart_file_parts") or 0)
        for row in report.get("endpoints") or []
    }

    dynamic_table = plan.get("dynamic") or {}
    if not isinstance(dynamic_table, dict):
        add("dynamic", "malformed_dynamic", "dynamic 必须是对象：键是参数名，值是策略或复现产物")
        dynamic_table = {}
    base_dir = plan_dir if plan_dir is not None else Path.cwd()

    for name, raw in dynamic_table.items():
        impl = dynamic_impl(raw)
        if impl is not None:
            issues.extend(_validate_impl(f"dynamic.{name}", impl, plan, base_dir))
            continue
        strategy = str(raw)
        if strategy in SUPPORTED_STRATEGIES or strategy == "UNRESOLVED":
            continue
        if strategy.startswith(("literal:", "env:")):
            continue
        add(
            f"dynamic.{name}",
            "unknown_strategy",
            f"策略 {strategy} 不认识；可用 {'/'.join(sorted(SUPPORTED_STRATEGIES))}"
            " 或 literal:<值> 或 env:<变量名> 或 UNRESOLVED"
            "，或写成一个复现产物对象（impl / source / entry，可再加 verified）",
        )

    steps = plan.get("steps") or []
    if not steps:
        add("steps", "missing_field", "至少要有一个 step")

    seen_ids: set[str] = set()
    account_fields = list((plan.get("account") or {}).get("fields") or [])

    # 生成代码的执行顺序是「先全部 login 步骤，再其余步骤」——校验必须按同一个顺序推
    # 每一步能拿到哪些 capture，否则会把"先用了后捕获"的槽位判成可用。
    login_captures: set[str] = set()
    rest_captures: set[str] = set()
    available_before: dict[int, set[str]] = {}
    for position, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            available_before[position] = set()
            continue
        is_login = step.get("role") == "login"
        available_before[position] = (
            set(login_captures) if is_login else login_captures | rest_captures
        )
        captured = set((step.get("capture") or {}).keys())
        if is_login:
            login_captures |= captured
        else:
            rest_captures |= captured

    # 一个槽位能被解析，只可能是这三种来源之一：账号字段（打底）、动态参数、前序 capture。
    static_names = set(account_fields) | set(dynamic_table)

    for position, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            add(f"steps[{position}]", "malformed_step", "step 必须是对象")
            continue
        where = step.get("id") or f"steps[{position}]"

        identifier = str(step.get("id", "")).strip()
        if not identifier:
            add(where, "missing_field", "step 缺 id")
        elif identifier in seen_ids:
            add(where, "duplicate_id", f"step id {identifier} 重复")
        elif not identifier.isidentifier():
            add(where, "invalid_id", f"step id {identifier} 不是合法标识符（会用作方法名）")
        else:
            seen_ids.add(identifier)

        role = step.get("role")
        if role not in ROLES:
            add(where, "missing_role", f"role 必须由人填写，取值 {'/'.join(ROLES)}；当前为 {role!r}")

        on_failure = step.get("on_failure", "abort")
        if on_failure not in ON_FAILURE:
            add(
                where,
                "unknown_on_failure",
                f"on_failure 取值 {'/'.join(ON_FAILURE)}；当前为 {on_failure!r}。"
                "它决定这一步失败后整个流程是停下还是继续，不能含糊",
            )

        endpoint = str(step.get("endpoint", "")).strip()
        if endpoint not in known:
            add(where, "unknown_endpoint", f"{endpoint} 不在本次盘点结果里")
        elif " " in endpoint:
            _, path_template = endpoint.split(" ", 1)
            slots = [value for kind, value in _split_template(path_template) if kind == "slot"]
            declared = step.get("path_params") or {}
            for slot in slots:
                if slot not in declared:
                    add(
                        where,
                        "missing_path_param",
                        f"路径里的 {{{slot}}} 没有声明取值方式"
                        "（literal:/env:/account:/state:）——路径 id 工具猜不出来，也不该猜",
                    )
            for extra in sorted(set(declared) - set(slots)):
                add(where, "unused_path_param", f"声明了路径参数 {extra}，但路径里没有 {{{extra}}}")
            for slot, strategy in declared.items():
                if not str(strategy).startswith(("literal:", "env:", "account:", "state:")):
                    add(
                        where,
                        "unknown_strategy",
                        f"path_params.{slot} 的策略 {strategy!r} 不认识"
                        "（可用 literal:/env:/account:/state:）",
                    )

        body = step.get("body", "none")
        if body not in BODY_KINDS:
            add(where, "unknown_body", f"body 取值 {'/'.join(BODY_KINDS)}；当前为 {body!r}")
        elif endpoint in known and body in ("json", "form", "multipart"):
            observed = probe_body.get(endpoint, set())
            if observed and body not in observed:
                add(
                    where,
                    "body_mismatch",
                    f"声明 body={body}，但盘点观察到 {sorted(observed)}——确认是否写错",
                )
            elif body == "multipart" and probe_files.get(endpoint, 0):
                # 判据收窄到"确实有文件字段"：multipart 本身不是问题，
                # 还原不出内容的是带 filename 的 part。原先一律拒绝，
                # 会把纯文本 multipart 也挡在门外（阿瓦隆的登录接口就是纯文本的）。
                add(
                    where,
                    "unsupported_body",
                    f"盘点观察到 {probe_files[endpoint]} 个文件字段（带 filename 的 part）。"
                    "文件内容无法从 HAR 可靠还原，这条路径不能自动展开——需人工改写，或改用别的接口",
                )

        # multipart 至少要有一个字段，否则连 Content-Type 都发不出去。
        # form 允许零字段（keepSignIn 就是 Content-Length: 0 的空表单），multipart 不允许。
        if body == "multipart":
            has_payload = bool(step.get("static") or step.get("dynamic")) or (
                role == "login" and bool(account_fields)
            )
            if not has_payload:
                add(
                    where,
                    "empty_multipart_body",
                    "body=multipart 但没有任何字段来源（static / dynamic / login 的 account.fields）——"
                    "空 multipart 连 Content-Type 都发不出去，需要至少一个字段",
                )

        for name in step.get("dynamic") or []:
            if name not in dynamic_table:
                add(where, "undefined_dynamic", f"step 用到 {name}，但顶层 dynamic 里没有它的策略")

        # header 模板里的 {token} 只从 state 取；state = 账号字段 + 前序 capture。
        # 漏了这一步，脚本会在运行时静默拼出 "Bearer " 并被服务端拒绝——
        # 这正是"看起来跑通了"的假象，必须在生成前拦下。
        resolvable = static_names | available_before.get(position, set())
        for header, template in (step.get("headers") or {}).items():
            for kind, slot in _split_template(str(template)):
                if kind != "slot" or slot in resolvable:
                    continue
                add(
                    where,
                    "unresolved_slot",
                    f"headers.{header} 用到 {{{slot}}}，但它既不是账号字段（account.fields）、"
                    "也不是动态参数，更没有任何前序步骤 capture 它——运行时只会得到空串。"
                    f"请把它加进 account.fields，或让某个前序步骤 capture 它（当前可用：{sorted(resolvable) or '空'}）",
                )

        for name in (step.get("static") or {}):
            if name_hits(name, SENSITIVE_HINTS):
                add(
                    where,
                    "credential_in_plan",
                    f"static 里的 {name} 是凭证类字段——凭证必须走环境变量或登录捕获，不能写进计划",
                )

        if "expect" in step:
            expect = step.get("expect")
            if not isinstance(expect, dict):
                add(where, "malformed_expect", "expect 必须是对象")
            else:
                if not str(expect.get("code_field") or "").strip():
                    add(where, "malformed_expect", "expect.code_field 必须是非空字符串（响应体里业务码的字段名）")
                if not isinstance(expect.get("success_values"), list):
                    add(where, "malformed_expect", "expect.success_values 必须是列表")
                for index, row in enumerate(expect.get("benign") or []):
                    if not isinstance(row, dict) or "value" not in row:
                        add(
                            where,
                            "malformed_expect",
                            f"expect.benign[{index}] 必须是带 value 的对象"
                            "（可再带 msg_contains / note）",
                        )

        for name, path in (step.get("capture") or {}).items():
            if not str(path).strip():
                add(where, "empty_capture", f"capture.{name} 的路径为空")

        overlap = set(step.get("dynamic") or []) & set(step.get("static") or {})
        if overlap:
            add(where, "field_collision", f"{sorted(overlap)} 同时出现在 dynamic 与 static")
        if role == "login":
            collision = set(account_fields) & (set(step.get("static") or {}) | set(step.get("dynamic") or []))
            if collision:
                add(
                    where,
                    "field_collision",
                    f"{sorted(collision)} 与 account.fields 冲突——登录步骤会自动注入账号字段",
                )

    return issues


# ------------------------------------------------------------ 生成骨架正文


def _identifier(name: str) -> str:
    """把参数名变成合法的 Python 标识符，用于生成 Dynamic 的方法名。"""
    cleaned = "".join(char if (char.isalnum() or char == "_") else "_" for char in str(name))
    if not cleaned or cleaned[0].isdigit():
        cleaned = "p_" + cleaned
    return cleaned


def _strategy_expression(name: str, strategy: str) -> str:
    """把策略名翻译成 payload 里的一行键值对。"""
    if strategy in SUPPORTED_STRATEGIES:
        return f'"{name}": Dynamic.{strategy}(),'
    if strategy.startswith("env:"):
        variable = strategy.split(":", 1)[1]
        return f'"{name}": os.getenv("{variable}", ""),'
    if strategy.startswith("literal:"):
        return f'"{name}": {json.dumps(strategy.split(":", 1)[1], ensure_ascii=False)},'
    return f'"{name}": Dynamic.{_identifier(name)}(),'


def _impl_method(parameter: str, impl: dict[str, Any], base_dir: Path) -> list[str]:
    """把一份回填的复现产物展开成 `Dynamic` 的一个静态方法。

    产物是**内联**进骨架的，不是 import 进来：生成的脚本必须自包含，
    换台机器、换个目录都能跑。旁边留一个 `.js` / `.py` 的隐式依赖，
    等于给"跑不起来"埋了个和签名无关的雷。
    """
    method_name = _identifier(parameter)
    source_path = (base_dir / impl["source"]).resolve()
    verified = impl["verified"] or {}
    lines = ["", "    @staticmethod", f"    def {method_name}(payload: dict) -> str:"]
    lines.append(f'        """参数 {parameter} 的复现产物。')
    lines.append("")
    lines.append(f"        来源：{impl['source']} → {impl['entry']}（{impl['impl']}）")
    if verified:
        lines.append(f"        验证证据：{verified['against']}")
        lines.append("        由本文件末尾的 selftest() 复核：python <本文件> --selftest")
    else:
        lines.append("        尚未提供验证证据——它只是「能跑」，没人证明它对。")
    lines.append(f"        约定：接收整个 payload，返回字符串（{IMPL_CONTRACT}）。")
    lines.append('        """')
    if impl["impl"] == "python":
        body = source_path.read_text(encoding="utf-8")
        lines.append("        # ---- 以下为复现产物原文（逐行缩进内联）----")
        for raw_line in body.rstrip("\n").splitlines():
            lines.append(("        " + raw_line) if raw_line.strip() else "")
        lines.append("        # ---- 复现产物原文结束 ----")
        lines.append(f"        return {impl['entry']}(payload)")
    else:
        constant = _js_constant_name(method_name)
        lines.append(
            f"        return _run_node({constant}, payload, "
            f"{json.dumps(impl['entry'])}, {json.dumps(parameter, ensure_ascii=False)})"
        )
    return lines


def _js_constant_name(method_name: str) -> str:
    return "_JS_" + method_name.upper()


def _run_node_helper() -> list[str]:
    """生成 JS 产物的运行时支撑。只在确实有 JS 产物时才发出去。"""
    return [
        "",
        "",
        "def _run_node(source: str, payload: dict, entry: str, parameter: str) -> str:",
        '    """在 node 里跑一段复现产物（JS）。',
        "",
        "    JS 产物由**外部运行时**承载：本机没有 node 时明确报错，绝不退回一个假值。",
        "    退回假值会让脚本看起来跑通了、实际每次都被服务端拒——本项目最贵的失败模式。",
        '    """',
        '    node = shutil.which("node")',
        "    if not node:",
        "        raise NotImplementedError(",
        '            f"参数 {parameter} 的复现产物是 JS，但本机找不到 node。"',
        '            "请安装 node，或把该产物改用 Python 复现。"',
        "        )",
        '    program = source + "\\n" + (',
        '        "const _input = JSON.parse(require(\'fs\').readFileSync(0, \'utf8\'));"',
        '        f"process.stdout.write(String({entry}(_input)));"',
        "    )",
        "    completed = subprocess.run(",
        '        [node, "-e", program],',
        "        input=json.dumps(payload, ensure_ascii=False),",
        "        capture_output=True,",
        "        text=True,",
        "        timeout=Config.REQUEST_TIMEOUT,",
        "    )",
        "    if completed.returncode != 0:",
        "        raise NotImplementedError(",
        '            f"参数 {parameter} 的复现产物在 node 里执行失败："',
        "            + completed.stderr.strip()[:200]",
        "        )",
        "    return completed.stdout.strip()",
    ]


def _selftest_lines(impls: dict[str, dict[str, Any]]) -> list[str]:
    """生成产物自检。

    回填本身不等于对。没有这一步，"回填了"就只是一个说法；
    有了它，`--selftest` 会拿产物自带的证据把每个实现跑一遍。
    证据是产物作者提供的，所以自检只能证伪、不能担保——
    但它足以拦住"回填一个占位实现然后把待办删掉"这种最省事的作弊。
    """
    cases = [
        (key, impl)
        for key, impl in impls.items()
        if impl["verified"]
    ]
    unverified = [key for key, impl in impls.items() if not impl["verified"]]
    lines = [
        "",
        "",
        "def selftest() -> int:",
        '    """用复现产物自带的验证证据复核一遍。',
        "",
        "    回填不等于对：只有拿证据跑通，「那条待办消掉了」才是真的。",
        "    没有证据的产物不会被静默放过，会在这里被点名。",
        '    """',
    ]
    if unverified:
        lines.append("    unverified = " + json.dumps(unverified, ensure_ascii=False))
        lines.append('    print("以下复现产物没有验证证据，无法自检：" + "、".join(unverified))')
    else:
        lines.append("    unverified: list[str] = []")
    lines.append("    cases = [")
    for key, impl in cases:
        verified = impl["verified"]
        lines.append(
            "        ("
            + json.dumps(key, ensure_ascii=False)
            + ", Dynamic."
            + _identifier(key)
            + ", "
            + json.dumps(verified["input"], ensure_ascii=False)
            + ", "
            + json.dumps(verified["expect"], ensure_ascii=False)
            + "),"
        )
    lines.append("    ]")
    lines.append("    if not cases:")
    lines.append('        print("没有任何带验证证据的复现产物")')
    lines.append("        return 1 if unverified else 0")
    lines.append("    failed = 0")
    lines.append("    for parameter, producer, sample, expected in cases:")
    lines.append("        try:")
    lines.append("            actual = producer(dict(sample))")
    lines.append("        except NotImplementedError as error:")
    lines.append('            print(f"    [未完成] {parameter}: {error}")')
    lines.append("            failed += 1")
    lines.append("            continue")
    lines.append("        if actual == expected:")
    lines.append('            print(f"    [一致] {parameter}  期望 " + _mask(expected))')
    lines.append("        else:")
    lines.append(
        '            print(f"    [不一致] {parameter}  期望 " + _mask(expected) + "  实得 " + _mask(str(actual)))'
    )
    lines.append("            failed += 1")
    lines.append('    print(f"自检：{len(cases) - failed}/{len(cases)} 一致")')
    lines.append("    return 1 if (failed or unverified) else 0")
    return lines


def _payload_lines(step: dict[str, Any], plan: dict[str, Any], indent: str) -> list[str]:
    """拼出一步请求的 payload 字面量。"""
    lines = [indent + "payload = {"]
    inner = indent + "    "

    if step.get("role") == "login":
        for field in (plan.get("account") or {}).get("fields") or []:
            lines.append(inner + f'"{field}": self.account.get("{field}", ""),')
        if (plan.get("account") or {}).get("fields"):
            lines.append(inner + "# 以上来自账号配置（account.fields），不从抓包里抄")

    for name, value in (step.get("static") or {}).items():
        lines.append(inner + f'"{name}": "{value}",')

    # 回填的复现产物要吃整个 payload，塞不进字典字面量——字面量内部引用不了自己。
    # 摘出来，等字典建完再单独赋值。
    deferred: list[str] = []
    for name in step.get("dynamic") or []:
        raw = (plan.get("dynamic") or {}).get(name, "UNRESOLVED")
        if dynamic_impl(raw) is not None:
            deferred.append(name)
            continue
        lines.append(inner + _strategy_expression(name, str(raw)))

    if len(lines) == 1 and not deferred:
        return []
    lines.append(indent + "}")
    for name in deferred:
        lines.append(
            indent
            + f"payload[{json.dumps(name, ensure_ascii=False)}] = "
            + f"Dynamic.{_identifier(name)}(payload)  # 复现产物，约定 {IMPL_CONTRACT}"
        )
    return lines


def _request_arguments(step: dict[str, Any], payload_var: str) -> str:
    body = step.get("body", "none")
    if body == "json":
        return f"json_body={payload_var}"
    if body == "form":
        return f"data={payload_var}"
    if body == "multipart":
        # 纯文本 multipart：requests 的 files= 收 (None, value) 就生成文本 part。
        # 边界值由 requests 生成——服务端只按 Content-Type 里的 boundary 切分，不校验它的字面量，
        # 所以不必复现抓包里的 WebKitFormBoundary。
        return "files={name: (None, value) for name, value in payload.items()}"
    if body == "query":
        return f"params={payload_var}"
    return ""


def _split_template(text: str) -> list[tuple[str, str]]:
    """把 "Bearer {token}" 拆成 [("literal","Bearer "), ("slot","token")]。"""
    segments: list[tuple[str, str]] = []
    buffer = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            end = text.find("}", index + 1)
            if end == -1:
                buffer += char
                index += 1
                continue
            if buffer:
                segments.append(("literal", buffer))
                buffer = ""
            segments.append(("slot", text[index + 1 : end]))
            index = end + 1
            continue
        buffer += char
        index += 1
    if buffer:
        segments.append(("literal", buffer))
    return segments


def _template_expression(template: str, state: str) -> str:
    """把带 {占位符} 的模板翻成 Python 表达式，供拼接而非嵌套引号。"""
    parts: list[str] = []
    for kind, value in _split_template(template):
        if kind == "literal":
            parts.append(json.dumps(value, ensure_ascii=False))
        else:
            parts.append(f"str({state}.get({json.dumps(value)}, ''))")
    return " + ".join(parts) if parts else '""'


def _has_slot(text: str) -> bool:
    return any(kind == "slot" for kind, _ in _split_template(text))


def _path_expression(template: str, step: dict[str, Any], state: str) -> str:
    """把带 {id} 的路径模板翻成表达式。

    路径参数必须由声明给出（literal: / env: / account: / state:）——
    路径里的 id 通常每次调用都不同，工具猜不出来，也不该猜。
    """
    params = step.get("path_params") or {}
    parts: list[str] = []
    for kind, value in _split_template(template):
        if kind == "literal":
            parts.append(json.dumps(value, ensure_ascii=False))
            continue
        strategy = str(params.get(value, ""))
        if strategy.startswith("literal:"):
            parts.append(json.dumps(strategy.split(":", 1)[1], ensure_ascii=False))
        elif strategy.startswith("env:"):
            parts.append(f'str(os.getenv({json.dumps(strategy.split(":", 1)[1])}, ""))')
        elif strategy.startswith("account:"):
            field = strategy.split(":", 1)[1]
            parts.append(f'str(self.account.get({json.dumps(field)}, ""))')
        elif strategy.startswith("state:"):
            slot = strategy.split(":", 1)[1]
            parts.append(f'str({state}.get({json.dumps(slot)}, ""))')
        else:
            parts.append(f'str({state}.get({json.dumps(value)}, ""))')
    return " + ".join(parts) if parts else '""'


def _header_lines(step: dict[str, Any], state: str, indent: str) -> list[str]:
    headers = step.get("headers") or {}
    if not headers:
        return []
    lines = [indent + "headers = {"]
    for name, template in headers.items():
        expression = _template_expression(str(template), state)
        lines.append(indent + "    " + json.dumps(str(name), ensure_ascii=False) + ": " + expression + ",")
    lines.append(indent + "}")
    return lines


def _step_method(step: dict[str, Any], plan: dict[str, Any], report: dict[str, Any]) -> list[str]:
    """生成一步对应的客户端方法。"""
    step_id = step["id"]
    endpoint = step["endpoint"]
    method, path = endpoint.split(" ", 1)
    evidence = _evidence_line(endpoint, report)
    # 文档字符串里的双引号会提前闭合三引号，统一换成单引号。
    banner = (endpoint + evidence).replace('"', "'")
    lines: list[str] = []
    lines.append(f"    def {step_id}(self) -> bool:")
    lines.append(f'        """{banner}"""')

    payload_lines = _payload_lines(step, plan, "        ")
    if not payload_lines and step.get("body") == "form":
        # 零参数的 form POST 也必须带 Content-Type: application/x-www-form-urlencoded。
        # 抓包里这类请求就是 Content-Length: 0 + form 型 Content-Type；
        # 传一个空 dict 正好复现，而"干脆不传 data"会连 Content-Type 一起丢掉。
        payload_lines = ["        payload = {}"]
    arguments = []
    if payload_lines:
        lines.extend(payload_lines)
        arguments.append(_request_arguments(step, "payload"))
    header_lines = _header_lines(step, "self.state", "        ")
    if header_lines:
        lines.extend(header_lines)
        arguments.append("headers=headers")

    call_args = (", " + ", ".join(a for a in arguments if a)) if arguments else ""
    if _has_slot(path):
        lines.append(f"        path = {_path_expression(path, step, 'self.state')}")
        lines.append(f'        response = self._request("{method}", path{call_args})')
    else:
        lines.append(f'        response = self._request("{method}", {json.dumps(path, ensure_ascii=False)}{call_args})')
    lines.append("        if response is None:")
    lines.append(f'            print("    [失败] {step_id}：请求未成功")')
    lines.append("            return False")

    expect = step.get("expect") or {}
    captures = step.get("capture") or {}
    if expect or captures:
        lines.append("        body = _as_json(response)")

    if expect:
        # 国产 App 的接口普遍是 HTTP 200 + 业务码。只看 status_code 会把
        # "今日已签到"这类业务失败当成成功——脚本报绿，实际什么都没做。
        lines.append(
            f'        verdict = _business_code(body, "{step_id}", '
            + json.dumps(expect, ensure_ascii=False)
            + ")"
        )
        lines.append('        if verdict == "fail":')
        lines.append("            return False")
        lines.append('        if verdict == "benign":')
        lines.append("            return True")

    for name, path_value in captures.items():
        lines.append(f'        {name} = _dig(body, "{path_value}")')
        lines.append(f"        if {name} is None:")
        lines.append(
            f'            print("    [失败] {step_id}：响应里取不到 {name}（路径 {path_value}）'
            '——路径未在真实响应上验证过")'
        )
        lines.append("            return False")
        lines.append(f'        self.state["{name}"] = {name}')

    if len(captures) == 1:
        name = next(iter(captures))
        lines.append(f'        print("    [完成] {step_id}  {name}=" + _mask(str({name})))')
    elif captures:
        lines.append(f'        print("    [完成] {step_id}  " + "  ".join([')
        for name in captures:
            lines.append(f'            "{name}=" + _mask(str({name})),')
        lines.append("        ]))")
    else:
        lines.append(f'        print("    [完成] {step_id}  HTTP " + str(response.status_code))')
    lines.append("        return True")
    return lines


def _evidence_line(endpoint: str, report: dict[str, Any]) -> str:
    for row in report.get("endpoints") or []:
        if f"{row['method']} {row['path']}" == endpoint:
            statuses = ",".join(f"{k}x{v}" for k, v in sorted((row.get("statuses") or {}).items()))
            return f"  —— 抓包证据：命中 {row['count']} 次 / 状态 {statuses}"
    return ""


def _todos(plan: dict[str, Any], report: dict[str, Any]) -> list[str]:
    """推不出来的部分，一条条列出来。"""
    todos: list[str] = []

    for name, raw in sorted((plan.get("dynamic") or {}).items(), key=lambda item: item[0]):
        impl = dynamic_impl(raw)
        if impl is not None:
            # 回填了产物，但没给证据——这条待办**不消失，只换了个说法**。
            # 回填本身不是"完成"，它只是把"没有实现"变成了"有一个没人验证过的实现"。
            # 不区分这两者，待办清单就会在第一次回填后变成一张空头支票。
            if not impl["verified"]:
                todos.append(
                    f"参数 {name} 的复现产物已回填（{impl['source']} → {impl['entry']}），"
                    "但没有任何验证证据——它只是「能跑」，没人证明它对。"
                    "请在真实样本上跑一次，把 against / input / expect 补进 verified；"
                    "补齐后本条待办才会消失"
                )
            continue
        strategy = str(raw)
        if strategy == "UNRESOLVED":
            todos.append(f"复现参数 {name} 的生成算法（HAR 只给出形态 {_shape(report, name)}，给不出算法）")
        elif strategy.startswith("literal:"):
            todos.append(f"确认参数 {name} 的固定值是否长期有效（当前按 literal 写死）")

    for step in plan.get("steps") or []:
        for name, path_value in (step.get("capture") or {}).items():
            todos.append(f"在真实响应上确认 {name} 的取值路径：{path_value}（来自声明，未验证）")

    # 没声明业务码约定的步骤，生成代码只看 HTTP 状态码。这类接口普遍是
    # HTTP 200 + {"code":500}，"只看状态码"会把业务失败报成成功。
    no_expect = [str(step.get("id")) for step in plan.get("steps") or [] if "expect" not in step]
    if no_expect:
        todos.append(
            "以下步骤没声明业务码约定，生成代码只校验 HTTP 状态码："
            + "、".join(no_expect)
            + "。请在真实响应上确认它是靠 HTTP 状态还是靠响应体业务码判定成败；"
            "若是后者，给该步骤补 expect（code_field / success_values，可再加 benign）"
        )

    # success_values 永远只是声明：抓包里可能根本没有一次成功样本，
    # 那时的取值是从兄弟接口推断的。工具验不了，只能点名让人去验。
    has_expect = [str(step.get("id")) for step in plan.get("steps") or [] if "expect" in step]
    if has_expect:
        todos.append(
            "以下步骤的 expect.success_values 来自声明、未经真实成功响应验证："
            + "、".join(has_expect)
            + "。请在一个确实能签成的日子跑一次，确认成功码就在 success_values 里；"
            "若抓包里的成功样本来自其它接口，那这个值是推断而非观测"
        )

    captured: set[str] = set()
    for step in plan.get("steps") or []:
        captured |= set((step.get("capture") or {}))
    for step in plan.get("steps") or []:
        for slot, strategy in (step.get("path_params") or {}).items():
            text = str(strategy)
            if text.startswith("state:") and text.split(":", 1)[1] not in captured:
                todos.append(
                    f"路径参数 {slot} 取自 {text}，但没有任何步骤捕获过它——确认取值来源"
                )

    used = {step.get("endpoint") for step in plan.get("steps") or []}
    step_candidates, noise = split_step_candidates(report.get("endpoints") or [])
    primary_host = next((row["host"] for row in report.get("hosts") or [] if row.get("api")), "")
    for row in step_candidates:
        key = f"{row['method']} {row['path']}"
        if key in used:
            continue
        host = row.get("host") or ""
        # 跨域名端点几乎总是第三方；点名带上域名，省得人回翻计划。
        origin = f"（不在主接口域名 {primary_host} 上，通常是第三方）" if primary_host and host and host != primary_host else ""
        todos.append(f"端点 {key}{origin} 未被任何 step 使用——确认是漏了还是本次不需要")

    # 协议层产物不走上面那条：emit_plan 已经按结构把它们剔出 steps，
    # 再在这里报"未被使用"就是工具自己打自己。只汇总一行，让人复核分类器没吃错。
    if noise:
        todos.append(
            f"另有 {len(noise)} 个协议层产物（CONNECT 隧道 / 同路径 CORS 预检 OPTIONS）"
            "已按结构剔除、未计入上面的未使用清单；若其中混有业务接口，需手工加回 steps"
        )

    known = {f"{row['method']} {row['path']}" for row in report.get("endpoints") or []}
    for step in plan.get("steps") or []:
        if step.get("endpoint") not in known:
            todos.append(f"端点 {step.get('endpoint')} 不在本次盘点结果里——确认抓包是否完整")

    if not (plan.get("account") or {}).get("fields"):
        todos.append("account.fields 为空——确认该流程是否真的不需要账号，还是漏填了")

    return todos


def _shape(report: dict[str, Any], name: str) -> str:
    for bucket in ("volatile_candidates", "signature_candidates", "sensitive"):
        for row in (report.get("fields") or {}).get(bucket) or []:
            if row["name"] == name:
                return "/".join(sorted((row.get("value_kinds") or {}).keys())) or "未知"
    return "未知"


def render_script(
    plan: dict[str, Any],
    report: dict[str, Any],
    plan_name: str,
    har_name: str,
    plan_dir: Path | None = None,
) -> str:
    """按计划拼出骨架。"""
    out: list[str] = []
    base_dir = plan_dir if plan_dir is not None else Path.cwd()
    name = plan["name"]
    account_fields = list((plan.get("account") or {}).get("fields") or [])
    separator = (plan.get("account") or {}).get("separator", "#")
    steps = plan.get("steps") or []
    login_steps = [s for s in steps if s.get("role") == "login"]
    other_steps = [s for s in steps if s.get("role") != "login"]
    # 回填的复现产物：按参数名排序，保证同一份计划每次生成的字节完全一致。
    impls = {
        key: impl
        for key, raw in sorted((plan.get("dynamic") or {}).items(), key=lambda item: item[0])
        for impl in (dynamic_impl(raw),)
        if impl is not None
    }
    uses_node = any(impl["impl"] == "js" for impl in impls.values())

    out.append("#!/usr/bin/env python3")
    out.append(f'"""{name} —— 由 har_to_script 从抓包与意图声明生成的骨架。')
    out.append("")
    out.append("生成来源")
    out.append(f"    plan: {plan_name}")
    out.append(f"    har : {har_name}")
    if impls:
        out.append("")
        out.append("回填的复现产物（Dynamic 里对应的方法体就是它们的原文）")
        for key, impl in impls.items():
            state = "已提供验证证据" if impl["verified"] else "**无验证证据**"
            out.append(f"    {key}: {impl['source']} → {impl['entry']}（{impl['impl']}，{state}）")
    out.append("")
    out.append("本文件是骨架不是成品：文末「待人工完成」列出的部分必须补齐。")
    out.append("未补齐前运行会在对应位置抛错或返回失败，而不是静默用一个假值继续跑。")
    out.append("正文不含抓包里的任何凭证值——动态参数一律走生成器，账号一律走环境变量。")
    out.append("控制台输出刻意不含 emoji：Windows 默认代码页下会 UnicodeEncodeError。")
    out.append('"""')
    out.append("")
    out.append("from __future__ import annotations")
    out.append("")
    out.append("import hashlib")
    out.append("import json")
    out.append("import os")
    out.append("import random")
    if uses_node:
        out.append("import shutil")
    out.append("import sys")
    if uses_node:
        out.append("import subprocess")
    out.append("import time")
    out.append("import uuid")
    out.append("from pathlib import Path")
    out.append("")
    if impls:
        # 自检只算签名，用不到网络栈。让 requests 的缺失挡住自检，
        # 等于把"复核产物"这件最该随时能做的事，绑在了一堆无关依赖上。
        out.append("# --selftest 只复核复现产物，用不到网络栈：缺 requests 不该挡住自检。")
        out.append('if "--selftest" not in sys.argv:')
        out.append("    import requests")
    else:
        out.append("import requests")
    out.append("")
    out.append("")
    out.append("class Config:")
    out.append('    """集中配置：本地直跑用同名字面量，环境变量优先（双源覆盖）。"""')
    out.append("")
    out.append(f'    ENV_NAME = "{plan["env_name"]}"')
    out.append(f'    BASE_URL = "{plan["base_url"]}"')
    out.append(f'    ACCOUNT_SEPARATOR = "{separator}"')
    out.append("")
    out.append("    REQUEST_TIMEOUT = 15")
    out.append("    MAX_RETRIES = 3")
    out.append("    ACCOUNT_DELAY = 3")
    out.append("")
    out.append("    CACHE_DIR = Path(\".cache\")")
    out.append(f'    CACHE_FILE = CACHE_DIR / "{name}.json"')

    # JS 产物以模块级常量内联，不进 Dynamic 类体：类体里塞几 KB 的字符串
    # 会把真正要看的方法挤到屏幕外。
    for key, impl in impls.items():
        if impl["impl"] != "js":
            continue
        text = (base_dir / impl["source"]).resolve().read_text(encoding="utf-8")
        out.append("")
        out.append("")
        out.append(f'# 复现产物原文：{impl["source"]}（入口 {impl["entry"]}）')
        out.append(f"{_js_constant_name(_identifier(key))} = r\"\"\"")
        out.append(text.strip("\n"))
        out.append('"""')

    out.append("")
    out.append("")
    out.append("class Dynamic:")
    out.append('    """动态参数生成器。')
    out.append("")
    out.append("    这些是**按形态推断的占位实现**：HAR 能告诉你某个参数每次都在变、")
    out.append("    长度是 32 位十六进制，但告诉不了你它是怎么算出来的。")
    out.append("    凡是算法推不出来的，一律在此抛错，绝不静默填一个假值——")
    out.append("    假值会让脚本看起来跑通了，实际每次都被服务端拒绝。")
    out.append("")
    out.append("    方法体里出现「复现产物原文」字样的，是人在计划里回填进来的实现：")
    out.append("    它来自一个真实文件、可能带验证证据，由文末 selftest() 复核。")
    out.append('    """')
    out.append("")
    out.append("    @staticmethod")
    out.append("    def timestamp_s() -> int:")
    out.append('        """秒级时间戳。"""')
    out.append("        return int(time.time())")
    out.append("")
    out.append("    @staticmethod")
    out.append("    def timestamp_ms() -> int:")
    out.append('        """毫秒级时间戳。"""')
    out.append("        return int(time.time() * 1000)")
    out.append("")
    out.append("    @staticmethod")
    out.append("    def uuid4() -> str:")
    out.append('        """随机 UUID。"""')
    out.append("        return str(uuid.uuid4())")
    out.append("")
    out.append("    @staticmethod")
    out.append("    def random_hex32() -> str:")
    out.append('        """32 位随机十六进制。"""')
    out.append("        return hashlib.md5(str(random.random()).encode()).hexdigest()")
    out.append("")
    out.append("    @staticmethod")
    out.append("    def random_digits(length: int = 6) -> str:")
    out.append('        """指定长度的随机数字串。"""')
    out.append('        return "".join(random.choice("0123456789") for _ in range(length))')

    # 回填的复现产物先展开——它们的方法体是产物原文，不是占位。
    for key, impl in impls.items():
        out.extend(_impl_method(key, impl, base_dir))

    unresolved = sorted(n for n, s in (plan.get("dynamic") or {}).items() if s == "UNRESOLVED")
    for parameter in unresolved:
        method_name = _identifier(parameter)
        shape = _shape(report, parameter)
        out.append("")
        out.append("    @staticmethod")
        out.append(f"    def {method_name}(**kwargs) -> str:")
        out.append(f'        """参数 {parameter} 的生成算法尚未复现。')
        out.append("")
        out.append(f"        抓包只给出了值的形态（{shape}），给不出算法。")
        out.append("        补齐这个函数是让脚本真正能跑的前提——")
        out.append("        也可以把复现产物写成一个文件，在计划里用")
        out.append("        {impl, source, entry, verified} 回填，让它由生成器内联进来。")
        out.append('        """')
        out.append("        raise NotImplementedError(")
        out.append(f'            "参数 {parameter} 的生成算法未复现（HAR 只给出形态 {shape}）。"')
        out.append(f'            "请先补齐 Dynamic.{method_name} 再运行。"')
        out.append("        )")

    if uses_node:
        out.extend(_run_node_helper())

    out.append("")
    out.append("")
    out.append("def _as_json(response) -> dict:")
    out.append('    """把响应体当 JSON 解析；不是 JSON 就返回空字典，不抛异常。"""')
    out.append("    try:")
    out.append("        payload = response.json()")
    out.append("    except ValueError:")
    out.append("        return {}")
    out.append("    return payload if isinstance(payload, dict) else {}")
    out.append("")
    out.append("")
    out.append("def _dig(payload: dict, path: str):")
    out.append('    """按点号路径取值；取不到返回 None，不抛异常。"""')
    out.append("    node = payload")
    out.append('    for key in path.split("."):')
    out.append("        if isinstance(node, dict):")
    out.append("            node = node.get(key)")
    out.append("        elif isinstance(node, list) and key.isdigit():")
    out.append("            index = int(key)")
    out.append("            node = node[index] if index < len(node) else None")
    out.append("        else:")
    out.append("            return None")
    out.append("        if node is None:")
    out.append("            return None")
    out.append("    return node")
    out.append("")
    out.append("")
    out.append("def _mask(value: str) -> str:")
    out.append('    """日志脱敏：只保留首尾各 4 个字符。"""')
    out.append("    text = str(value)")
    out.append('    return "*" * len(text) if len(text) <= 8 else text[:4] + "*" * 8 + text[-4:]')
    out.append("")
    out.append("")
    out.append('def _business_code(body: dict, step_id: str, expect: dict) -> str:')
    out.append('    """按声明的业务码约定判定成败，返回 "ok" / "benign" / "fail"。')
    out.append("")
    out.append("    HTTP 200 不代表业务成功：这类接口把成败放在响应体的业务码里，")
    out.append('    典型形态是 {"code":0,"msg":"操作成功"} 与 {"code":500,"msg":"今日已经签到"}。')
    out.append("    只看 status_code 会把后者报成成功——脚本报绿，实际什么都没做。")
    out.append('    """')
    out.append('    field = expect.get("code_field")')
    out.append("    if not field:")
    out.append('        return "ok"')
    out.append("    value = _dig(body, field)")
    out.append("    if value is None:")
    out.append(f'        print("    [失败] " + step_id + "：响应里没有 " + str(field) + " 字段——实际约定与声明不符")')
    out.append('        return "fail"')
    out.append('    if value in (expect.get("success_values") or []):')
    out.append('        return "ok"')
    out.append('    message = str(_dig(body, "msg") or _dig(body, "message") or "")')
    out.append('    for row in expect.get("benign") or []:')
    out.append('        if value == row.get("value") and str(row.get("msg_contains", "")) in message:')
    out.append('            print("    [跳过] " + step_id + "：" + (row.get("note") or message))')
    out.append('            return "benign"')
    out.append('    print("    [失败] " + step_id + "：业务码 " + str(field) + "=" + str(value) + " msg=" + message)')
    out.append('    return "fail"')
    out.append("")
    out.append("")
    out.append("class AppClient:")
    out.append('    """按声明的顺序执行：先全部 login 步骤，再其余步骤。"""')
    out.append("")
    out.append("    def __init__(self, account: dict, index: int) -> None:")
    out.append("        self.index = index")
    out.append("        self.account = account")
    out.append("        self.session = requests.Session()")
    out.append("        self.session.trust_env = False")
    out.append("        # 账号字段先落进 state，让 {字段名} 这种占位符处处可用。")
    out.append("        # 登录步骤的 capture 会覆盖同名键——静态凭证打底，动态令牌覆盖。")
    out.append("        self.state: dict = dict(account)")
    out.append("")
    out.append("    def _request(self, method: str, endpoint: str, *, params=None, json_body=None, data=None, files=None, headers=None):")
    out.append('        """带重试的请求；5xx 与网络异常重试，4xx 直接返回交给调用方判断。"""')
    out.append("        url = Config.BASE_URL + endpoint")
    out.append("        for attempt in range(1, Config.MAX_RETRIES + 1):")
    out.append("            try:")
    out.append("                response = self.session.request(")
    out.append("                    method,")
    out.append("                    url,")
    out.append("                    params=params,")
    out.append("                    json=json_body,")
    out.append("                    data=data,")
    out.append("                    files=files,")
    out.append("                    headers=headers,")
    out.append("                    timeout=Config.REQUEST_TIMEOUT,")
    out.append("                )")
    out.append("                if response.status_code < 500:")
    out.append("                    return response")
    out.append('                print(f"    服务端错误 {response.status_code}（尝试 {attempt}/{Config.MAX_RETRIES}）")')
    out.append("            except requests.RequestException as error:")
    out.append('                print(f"    请求异常（尝试 {attempt}/{Config.MAX_RETRIES}）: {error}")')
    out.append("            time.sleep(2)")
    out.append("        return None")

    for step in login_steps + other_steps:
        out.append("")
        out.extend(_step_method(step, plan, report))

    out.append("")
    out.append("    def run(self) -> None:")
    out.append('        """主流程。"""')
    for step in login_steps + other_steps:
        step_id = step["id"]
        # on_failure 原先只是计划里的一个字段，生成器从不读它——作者写了
        # abort、以为失败会停下，实际每一步都照跑不误。这是最典型的
        # "声明了但没人看"，所以现在它必须落到代码里。
        if step.get("on_failure", "abort") == "continue":
            out.append(f"        if not self.{step_id}():")
            out.append(f'            print("    [继续] {step_id} 未成功，按声明继续后续步骤")')
        else:
            out.append(f"        if not self.{step_id}():")
            if step.get("role") == "login":
                out.append('            print("    [跳过] 登录未成功，后续任务不执行")')
            else:
                out.append(f'            print("    [跳过] {step_id} 未成功，按 on_failure=abort 中止")')
            out.append("            return")

    out.append("")
    out.append("")
    out.append("def load_accounts() -> list:")
    if not account_fields:
        # 没有 account.fields 时不该要求配账号：注册流程天然没有凭证可配，
        # 而原先的写法会让人去填一个完全用不到的占位值——填了才肯跑，
        # 跑了又不用它，这种"仪式性配置"迟早会被误解成"这里要填真的"。
        out.append('    """本计划没有 account.fields，所以不需要账号配置。"""')
        out.append("    return [{}]")
    else:
        out.append('    """从环境变量读取多账号；每行一个，字段用 ACCOUNT_SEPARATOR 分隔。"""')
        out.append("    raw = os.getenv(Config.ENV_NAME, \"\").replace(\"&\", \"\\n\")")
        out.append("    accounts = []")
        out.append("    for chunk in raw.split(\"\\n\"):")
        out.append("        chunk = chunk.strip()")
        out.append("        if not chunk:")
        out.append("            continue")
        out.append("        parts = chunk.split(Config.ACCOUNT_SEPARATOR)")
        out.append("        accounts.append(dict(zip(" + json.dumps(account_fields, ensure_ascii=False) + ", parts)))")
        out.append("    return accounts")
    out.append("")
    out.append("")
    out.append("def main() -> int:")
    out.append("    accounts = load_accounts()")
    if account_fields:
        out.append("    if not accounts:")
        out.append("        print(")
        out.append("            \"未配置账号：请设置环境变量 \"")
        out.append("            + Config.ENV_NAME")
        out.append("            + \"（格式 \" + Config.ACCOUNT_SEPARATOR.join(" + json.dumps(account_fields, ensure_ascii=False) + ") + \"，多账号换行）\"")
        out.append("        )")
        out.append("        return 1")
        out.append("")
    out.append("    for index, account in enumerate(accounts, 1):")
    out.append("        print()")
    out.append('        print("=" * 20 + f" 账号{index} " + "=" * 20)')
    out.append("        try:")
    out.append("            AppClient(account, index).run()")
    out.append("        except NotImplementedError as error:")
    out.append('            print(f"    [未完成] {error}")')
    out.append("            return 2")
    out.append("        if index < len(accounts):")
    out.append("            time.sleep(Config.ACCOUNT_DELAY)")
    out.append("    return 0")

    if impls:
        out.extend(_selftest_lines(impls))

    out.append("")
    out.append("")
    out.append('if __name__ == "__main__":')
    if impls:
        out.append('    if "--selftest" in sys.argv:')
        out.append("        sys.exit(selftest())")
    out.append("    sys.exit(main())")

    todos = _todos(plan, report)
    out.append("")
    out.append("")
    out.append("# " + "=" * 70)
    out.append("# 待人工完成")
    out.append("# " + "=" * 70)
    out.append("#")
    out.append("# 这些是「工具不该猜」的部分，全部来自意图声明或盘点结果的对账。")
    out.append("# 补齐一项就删掉一项；清单空了，骨架才算完整。")
    out.append("#")
    if todos:
        for index, todo in enumerate(todos, 1):
            out.append(f"# [ ] {index}. {todo}")
    else:
        out.append("# [ ] （空——所有可推导的部分都已在正文落地）")
    out.append("#")
    out.append("# 另外必须人工确认的（工具无法从抓包判断）：")
    out.append("#     - 该流程是否在授权范围内、平台条款是否允许自动化")
    out.append("#     - 请求频率是否符合平台预期（本骨架只做了固定间隔，未做随机化）")
    out.append("#     - 失败重试是否会触发风控（本骨架对 5xx 无条件重试）")

    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- CLI


def _load_plan(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PlanError(f"计划文件读取失败：{error}") from error
    if not isinstance(payload, dict):
        raise PlanError("计划文件顶层必须是对象")
    return payload


def _build_report(har_path: str) -> dict[str, Any]:
    return probe(load_har(har_path), include_static=False, redact_values=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 HAR 与意图声明生成脚本骨架。")
    parser.add_argument("--har", required=True, help="HAR 文件路径，'-' 表示标准输入")
    parser.add_argument("--plan", help="意图声明 JSON")
    parser.add_argument("--emit-plan", help="生成一份待填的计划模板并写入该路径")
    parser.add_argument("--out", help="骨架输出路径；缺省打印到标准输出")
    parser.add_argument("--check", action="store_true", help="只校验计划，不生成")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    try:
        report = _build_report(args.har)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"无法解析 HAR: {error}", file=sys.stderr)
        return 2

    if args.emit_plan:
        template = emit_plan(report)
        Path(args.emit_plan).write_text(
            json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
        if not args.json:
            print(f"计划模板已写入 {args.emit_plan}")
            print("下一步：填 role / env_name / account.fields / dynamic 策略，再跑 --check")
        return 0

    if not args.plan:
        print("需要 --plan（或 --emit-plan 先出模板）", file=sys.stderr)
        return 2

    try:
        plan = _load_plan(Path(args.plan))
    except PlanError as error:
        print(str(error), file=sys.stderr)
        return 2

    issues = validate_plan(plan, report, Path(args.plan).resolve().parent)
    plan_name = Path(args.plan).name
    har_name = Path(args.har).name if args.har != "-" else "stdin"

    if issues:
        if args.json:
            print(json.dumps({"ok": False, "issues": issues}, ensure_ascii=False, indent=2))
        else:
            print(f"计划不合法，共 {len(issues)} 处：")
            for issue in issues:
                print(f"  [{issue['kind']}] {issue['where']}: {issue['detail']}")
        return 1

    if args.check:
        if args.json:
            print(json.dumps({"ok": True, "issues": []}, ensure_ascii=False, indent=2))
        else:
            print("计划自洽：端点、role、动态策略与账号字段均无冲突")
            print(f"RESULT=OK")
        return 0

    script = render_script(plan, report, plan_name, har_name, Path(args.plan).resolve().parent)
    if args.out:
        Path(args.out).write_text(script, encoding="utf-8", newline="\n")
        if not args.json:
            print(f"骨架已写入 {args.out}")
            print(f"待人工完成 {len(_todos(plan, report))} 项，见文件末尾清单")
    else:
        print(script, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
