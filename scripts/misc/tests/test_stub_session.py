"""桩会话的离线测试。

被测对象是 `scripts/automation/stub_session.py`——它把生成的骨架装进假 requests
跑一遍，所以这里**不发任何网络请求**，也不需要任何账号。

重点验四件事：

1. **判定逻辑真的被跑到了**——业务码型的成败必须能被区分出来，
   而不是「脚本没崩就算过」。
2. **桩记下的请求是真的**——`files=` / `data=` / `json_body=` 必须能从记录里读出来，
   否则「multipart 走了 files=」这类断言就是空的。
3. **副作用被清干净**——`sys.modules` / `sys.argv` / `sys.stdout` / 环境变量
   跑完必须恢复原状。测试工具污染测试环境，是最难查的一类问题。
4. **自检路径不依赖网络栈**——`run_selftest` 会刻意摘掉 requests 再跑。

零第三方依赖，可被 scripts/misc/run_offline_tests.py 直接发现。
"""

from __future__ import annotations

import atexit
import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

from automation.har_to_script import render_script  # noqa: E402
from automation.stub_session import (  # noqa: E402
    StubSession,
    run_script,
    run_selftest,
)
from test_har_to_script import (  # noqa: E402
    backfilled_plan,
    report,
    valid_plan,
)

# 整模块共用一个沙箱，退出时一次性清理：Windows 上 rmtree 一个空目录也要近 1 秒，
# 放进逐用例的临时目录会拖垮整个套件。
_SANDBOX = Path(tempfile.mkdtemp(prefix="stub_session_"))
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)

# valid_plan 的 env_name 是 EXAMPLE_ACCOUNT，account.fields 是 phone#password。
ENV = {"EXAMPLE_ACCOUNT": "13800138000#secret"}

LOGIN_OK = {"code": 0, "msg": "登录成功", "data": {"token": "stub-token"}}
STEP_OK = {"code": 0, "msg": "操作成功"}


def write_script(name: str, plan: dict) -> Path:
    script = render_script(plan, report(), "example.plan.json", "capture.har", _SANDBOX)
    compile(script, "<generated>", "exec")
    target = _SANDBOX / name
    target.write_text(script, encoding="utf-8", newline="\n")
    return target


def plan_with_expect() -> dict:
    """回填过签名的计划，并给任务步骤补上业务码约定。"""
    plan = backfilled_plan(_SANDBOX)
    for step in plan["steps"]:
        if step["id"] == "sign_in":
            step["expect"] = {"code_field": "code", "success_values": [0]}
    return plan


class TestRunScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = write_script("happy.py", plan_with_expect())

    def run_it(self, responses, env=None):
        return run_script(self.script, responses, env=env if env is not None else ENV)

    def test_success_path_reports_ok(self) -> None:
        result = self.run_it([(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)])
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.failure_marks, ())

    def test_business_code_failure_is_caught_despite_http_200(self) -> None:
        """这条是整个工具存在的理由：HTTP 200 什么都不能说明。"""
        result = self.run_it([(200, LOGIN_OK), (200, {"code": 500, "msg": "今日已经签到"})])
        self.assertFalse(result.ok)
        self.assertTrue(any("业务码" in mark or "[失败]" in mark for mark in result.failure_marks))

    def test_missing_code_field_is_a_failure_not_a_pass(self) -> None:
        result = self.run_it([(200, LOGIN_OK), (200, {"msg": "没有 code 字段"})])
        self.assertFalse(result.ok)

    def test_every_request_is_recorded_in_order(self) -> None:
        result = self.run_it([(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)])
        self.assertEqual(len(result.calls), 3)
        self.assertEqual(result.calls[0].method, "POST")
        self.assertTrue(result.calls[0].url.endswith("/v1/auth/login"))
        self.assertTrue(result.calls[1].url.endswith("/v1/sign/in"))
        self.assertEqual(result.calls[2].method, "GET")

    def test_json_body_is_readable_from_the_record(self) -> None:
        result = self.run_it([(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)])
        body = result.calls[1].json_body
        self.assertIn("sign", body)
        self.assertEqual(body["uid"], "12345")

    def test_captured_token_reaches_the_next_request(self) -> None:
        """capture 串联是生成器最容易静默做错的地方：取不到就拼出空 Bearer。"""
        result = self.run_it([(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)])
        self.assertEqual(result.calls[0].headers.get("Authorization"), None)
        self.assertEqual(result.calls[1].headers.get("Authorization"), "Bearer stub-token")

    def test_login_response_without_the_capture_path_fails(self) -> None:
        result = self.run_it([(200, {"code": 0, "msg": "登录成功", "data": None})])
        self.assertFalse(result.ok)

    def test_absent_account_env_exits_with_one(self) -> None:
        result = self.run_it([], env={})
        self.assertEqual(result.exit_code, 1)
        self.assertIn("未配置账号", result.output)

    def test_running_out_of_stub_responses_is_loud(self) -> None:
        """脚本多发了一个请求，桩必须喊出来——那往往就是缺陷本身。"""
        with self.assertRaises(AssertionError) as caught:
            self.run_it([(200, LOGIN_OK)])
        self.assertIn("桩响应用完了", str(caught.exception))


class TestSideEffects(unittest.TestCase):
    """测试工具污染测试环境，是最难查的一类问题。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = write_script("side_effects.py", plan_with_expect())

    def test_requests_module_is_restored(self) -> None:
        sentinel = types.ModuleType("requests")
        sentinel.MARKER = "sentinel"  # type: ignore[attr-defined]
        previous = sys.modules.get("requests")
        sys.modules["requests"] = sentinel
        try:
            run_script(self.script, [(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)], env=ENV)
            self.assertIs(sys.modules.get("requests"), sentinel)
        finally:
            if previous is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous

    def test_requests_module_is_not_left_behind_when_it_was_absent(self) -> None:
        previous = sys.modules.pop("requests", None)
        try:
            run_script(self.script, [(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)], env=ENV)
            self.assertNotIn("requests", sys.modules)
        finally:
            if previous is not None:
                sys.modules["requests"] = previous

    def test_argv_and_stdout_are_restored(self) -> None:
        saved_argv = sys.argv
        saved_stdout = sys.stdout
        run_script(self.script, [(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)], env=ENV)
        self.assertIs(sys.argv, saved_argv)
        self.assertIs(sys.stdout, saved_stdout)

    def test_account_env_does_not_leak_between_runs(self) -> None:
        run_script(self.script, [(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)], env=ENV)
        self.assertNotIn("EXAMPLE_ACCOUNT", os.environ)

    def test_script_output_does_not_reach_the_real_stdout(self) -> None:
        """桩跑的时候骨架会 print 一堆东西，不能漏到调用方的终端里。"""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = run_script(self.script, [(200, LOGIN_OK), (200, STEP_OK), (200, STEP_OK)], env=ENV)
        self.assertEqual(captured.getvalue(), "")
        self.assertIn("[完成]", result.output)


class TestRunSelftest(unittest.TestCase):
    """自检路径：只算签名，不该被网络栈挡住。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = write_script("with_selftest.py", backfilled_plan(_SANDBOX))

    def test_selftest_runs_without_requests_installed(self) -> None:
        """刻意把 requests 从 sys.modules 摘掉——这条设计要被证明，不是碰巧成立。"""
        withdrawn = sys.modules.pop("requests", None)
        try:
            result = run_selftest(self.script)
        finally:
            if withdrawn is not None:
                sys.modules["requests"] = withdrawn
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("1/1 一致", result.output)

    def test_selftest_fails_loudly_on_a_wrong_expectation(self) -> None:
        plan = backfilled_plan(_SANDBOX)
        plan["dynamic"]["sign"]["verified"]["expect"] = "0" * 32
        script = write_script("wrong_expect.py", plan)
        result = run_selftest(script)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("不一致", result.output)

    def test_selftest_restores_requests(self) -> None:
        sentinel = types.ModuleType("requests")
        previous = sys.modules.get("requests")
        sys.modules["requests"] = sentinel
        try:
            run_selftest(self.script)
            self.assertIs(sys.modules.get("requests"), sentinel)
        finally:
            if previous is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous


class TestStubSession(unittest.TestCase):
    def test_stub_response_without_json_body_raises_value_error(self) -> None:
        """骨架靠 `except ValueError` 判「不是 JSON」，桩要如实复现这个行为。"""
        session = StubSession([(200, None)])
        with self.assertRaises(ValueError):
            session.request("GET", "https://example.test").json()

    def test_stub_response_text_is_json(self) -> None:
        session = StubSession([(200, {"code": 0})])
        self.assertEqual(session.request("GET", "https://example.test").text, '{"code": 0}')

    def test_bare_plan_without_impl_still_loads(self) -> None:
        """没回填产物的骨架也能装进桩——它会在跑到那一步时抛 NotImplementedError。"""
        script = write_script("bare.py", valid_plan())
        result = run_script(script, [(200, LOGIN_OK)], env=ENV)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("未完成", result.output)


if __name__ == "__main__":
    unittest.main()
