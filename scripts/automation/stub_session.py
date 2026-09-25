#!/usr/bin/env python3
"""桩会话：把生成的骨架装进假 requests，喂预设响应，看它的判定对不对。

生成器只能保证「请求拼得对」——判定逻辑对不对，必须在**真实形态的响应**上跑一遍。
尤其是业务码型接口：HTTP 200 什么都不能说明，成功与失败都在响应体里。

这个模块**不发任何网络请求**：它把 requests 换成一个按顺序吐出预设响应的桩。
所以它能在 CI 里跑、能在没有账号的情况下跑、能在没有网络的机器上跑。

它**不是重放器**：桩响应完全由调用方给出，模块本身不知道任何真实接口的形态，
也不读抓包。往桩里喂什么，是调用方的事。

零第三方依赖。
"""

from __future__ import annotations

import io
import json
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class StubRequestException(Exception):
    """骨架会写 `except requests.RequestException`；桩不抛它，但名字必须在。"""


@dataclass(frozen=True)
class StubCall:
    """一次被桩拦下的请求。字段名跟着骨架 `_request` 的形参走。"""

    method: str
    url: str
    kwargs: dict[str, Any]

    @property
    def headers(self) -> dict[str, str]:
        return dict(self.kwargs.get("headers") or {})

    @property
    def json_body(self) -> Any:
        """骨架 `_request` 的形参叫 `json_body`，但它转手给 requests 时用的是 `json=`。

        桩记的是**真正发出去的那一层**，所以这里读 `json`——名字保留成 `json_body`，
        是因为调用方关心的是「这一步的请求体」，不是 requests 的拼写。
        """
        return self.kwargs.get("json")

    @property
    def data(self) -> Any:
        return self.kwargs.get("data")

    @property
    def files(self) -> Any:
        return self.kwargs.get("files")

    @property
    def params(self) -> Any:
        return self.kwargs.get("params")


class StubResponse:
    """假装是 requests.Response。只实现骨架真正用到的那几样。"""

    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False) if self._payload is not None else ""

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("桩响应没有 JSON 体")
        return self._payload


class StubSession:
    """按顺序吐出预设响应，并记下每一次请求。"""

    def __init__(self, responses: Sequence[tuple[int, Any]]) -> None:
        self._pending = list(responses)
        self.calls: list[StubCall] = []

    def request(self, method: str, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append(StubCall(method=method, url=url, kwargs=kwargs))
        if not self._pending:
            raise AssertionError(
                f"桩响应用完了，脚本还在请求 {method} {url}。"
                "要么补一条预设响应，要么说明脚本多发了请求——后者往往是真缺陷"
            )
        status_code, payload = self._pending.pop(0)
        return StubResponse(status_code, payload)


@dataclass
class StubResult:
    """一次桩会话运行的结果。"""

    exit_code: int
    output: str
    calls: tuple[StubCall, ...] = ()
    failure_marks: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """骨架自己有没有报失败。

        判定看输出里的 `[失败]` 标记，**不是** `exit_code`：生成的 `main()`
        只在「没配账号」和「NotImplementedError」时返回非零，某一步失败它仍然返回 0。
        这是骨架的既有约定，这里不改它，只把它翻译成一个好用的布尔。
        """
        return not self.failure_marks


def _stub_module(session: StubSession) -> types.ModuleType:
    module = types.ModuleType("requests")
    module.Session = lambda: session  # type: ignore[attr-defined]
    module.post = lambda *a, **k: session.request("POST", *a, **k)  # type: ignore[attr-defined]
    module.get = lambda *a, **k: session.request("GET", *a, **k)  # type: ignore[attr-defined]
    module.RequestException = StubRequestException  # type: ignore[attr-defined]
    module.exceptions = types.SimpleNamespace(RequestException=StubRequestException)  # type: ignore[attr-defined]
    return module


def _execute(path: Path, namespace: dict[str, Any]) -> None:
    """exec 骨架源码。调用方负责挂桩、改 argv、捕获输出。"""
    source = path.read_text(encoding="utf-8")
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102


def _restore(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def run_script(
    script_path: Path | str,
    responses: Sequence[tuple[int, Any]],
    *,
    env: Mapping[str, str] | None = None,
) -> StubResult:
    """把骨架装进桩会话跑一遍 `main()`，返回它做了什么。

    骨架从环境变量读账号，所以 `env` 里要给 `Config.ENV_NAME` 那一项，
    否则 `main()` 会直接打印「未配置账号」返回 1。
    """
    path = Path(script_path)
    session = StubSession(responses)
    stub = _stub_module(session)

    saved_env = {key: os.environ.get(key) for key in (env or {})}
    saved_argv = sys.argv
    saved_stdout = sys.stdout
    os.environ.update(env or {})
    # 骨架在模块级 `import requests`，所以桩必须先挂进 sys.modules——
    # 晚一步，import 就已经拿到真模块了。
    # argv 也要收干净：骨架会看 `--selftest` 决定要不要 import requests，
    # 而这里要的正是「导入 requests（用桩）」这条路径。
    sys.argv = [str(path)]
    previous_requests = sys.modules.get("requests")
    sys.modules["requests"] = stub

    namespace: dict[str, Any] = {"__name__": "generated", "__file__": str(path)}
    stdout = io.StringIO()
    exit_code = 0
    try:
        sys.stdout = stdout
        _execute(path, namespace)
        outcome = namespace["main"]()
        exit_code = outcome if isinstance(outcome, int) else 0
    except SystemExit as stop:
        exit_code = int(stop.code or 0)
    finally:
        sys.stdout = saved_stdout
        sys.argv = saved_argv
        if previous_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = previous_requests
        for key, value in saved_env.items():
            _restore(key, value)

    text = stdout.getvalue()
    return StubResult(
        exit_code=exit_code,
        output=text,
        calls=tuple(session.calls),
        failure_marks=tuple(line.strip() for line in text.splitlines() if "[失败]" in line),
    )


def run_selftest(script_path: Path | str) -> StubResult:
    """在**没有 requests** 的前提下跑骨架的 `--selftest`。

    骨架把 `import requests` 关在 `if "--selftest" not in sys.argv:` 后面，
    正是为了让复核复现产物这件事不依赖网络栈。这里刻意把 requests 从
    `sys.modules` 里摘掉再跑，好让那条设计**被证明**，而不是「碰巧环境里有」。
    """
    path = Path(script_path)
    saved_argv = sys.argv
    saved_stdout = sys.stdout
    sys.argv = [str(path), "--selftest"]
    stdout = io.StringIO()
    exit_code = 0
    withdrawn = sys.modules.pop("requests", None)
    namespace: dict[str, Any] = {"__name__": "generated", "__file__": str(path)}
    try:
        _execute(path, namespace)
        sys.stdout = stdout
        exit_code = int(namespace["selftest"]())
    finally:
        sys.stdout = saved_stdout
        sys.argv = saved_argv
        if withdrawn is not None:
            sys.modules["requests"] = withdrawn

    text = stdout.getvalue()
    return StubResult(
        exit_code=exit_code,
        output=text,
        failure_marks=tuple(line.strip() for line in text.splitlines() if "[失败]" in line or "[不一致]" in line),
    )
