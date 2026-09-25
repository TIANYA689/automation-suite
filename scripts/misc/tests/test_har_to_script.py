"""HAR → 脚本骨架生成器的离线测试。

重点验三件事：

1. **生成的代码是合法 Python**——一个会吐出语法错误文件的生成器毫无价值，
   所以每个渲染用例都过一遍 `compile()`。
2. **工具不猜语义**——role 没填、动态参数没策略，必须变成明确的失败或待办，
   不能变成看似合理的默认值。
3. **不泄漏抓包里的凭证**——正文只能出现参数名，不能出现参数值。

零第三方依赖，可被 scripts/misc/run_offline_tests.py 直接发现。
"""

from __future__ import annotations

import atexit
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

from automation.har_probe import probe as har_probe  # noqa: E402
from automation.har_to_script import (  # noqa: E402
    _identifier,
    _split_template,
    _template_expression,
    _todos,
    emit_plan,
    is_step_candidate,
    main,
    render_script,
    split_step_candidates,
    validate_plan,
)
from test_har_probe import (  # noqa: E402
    MULTIPART_BOUNDARY,
    SIGN_A,
    SIGN_B,
    _entry,
    multipart_body,
    multipart_har,
    multipart_post,
    synthetic_har,
)


def report() -> dict:
    return har_probe(synthetic_har(), include_static=False, redact_values=True)


def multipart_report() -> dict:
    return har_probe(multipart_har(), include_static=False, redact_values=True)


def multipart_plan() -> dict:
    """纯文本 multipart 的计划：字段全部走 static/dynamic。"""
    plan = valid_plan()
    plan["dynamic"] = {"token": "UNRESOLVED"}
    plan["steps"] = [
        {
            "id": "request_code",
            "role": "task",
            "endpoint": "POST /v1/auth/code",
            "body": "multipart",
            "path_params": {},
            "headers": {},
            "static": {"loginName": "a@example.com"},
            "dynamic": ["token"],
            "capture": {},
            "on_failure": "abort",
        }
    ]
    return plan


def valid_plan() -> dict:
    return {
        "name": "example-signin",
        "base_url": "https://api.example.com",
        "env_name": "EXAMPLE_ACCOUNT",
        "paradigm": "oop",
        "account": {"fields": ["phone", "password"], "separator": "#"},
        "dynamic": {"ts": "timestamp_s", "nonce": "uuid4", "sign": "UNRESOLVED"},
        "steps": [
            {
                "id": "login",
                "role": "login",
                "endpoint": "POST /v1/auth/login",
                "body": "json",
                "static": {"deviceId": "web-01"},
                "dynamic": ["ts"],
                "capture": {"token": "data.token"},
            },
            {
                "id": "sign_in",
                "role": "task",
                "endpoint": "POST /v1/sign/in",
                "body": "json",
                "headers": {"Authorization": "Bearer {token}"},
                "static": {"uid": "12345"},
                "dynamic": ["ts", "nonce", "sign"],
                "capture": {},
            },
            {
                "id": "profile",
                "role": "query",
                "endpoint": "GET /v1/user/{id}/profile",
                "body": "query",
                "path_params": {"id": "account:phone"},
                "static": {},
                "dynamic": [],
                "capture": {},
            },
        ],
    }


def kinds(issues: list[dict[str, str]]) -> set[str]:
    return {issue["kind"] for issue in issues}


class TestHelpers(unittest.TestCase):
    def test_split_template(self) -> None:
        self.assertEqual(
            _split_template("Bearer {token}"),
            [("literal", "Bearer "), ("slot", "token")],
        )
        self.assertEqual(_split_template("plain"), [("literal", "plain")])
        self.assertEqual(_split_template("{a}{b}"), [("slot", "a"), ("slot", "b")])
        self.assertEqual(_split_template("unclosed {a"), [("literal", "unclosed {a")])

    def test_template_expression_concatenates_instead_of_nesting_quotes(self) -> None:
        expression = _template_expression("Bearer {token}", "self.state")
        self.assertEqual(expression, '"Bearer " + str(self.state.get("token", \'\'))')
        compile(f"value = {expression}", "<expr>", "exec")

    def test_template_expression_without_slot(self) -> None:
        self.assertEqual(_template_expression("static", "self.state"), '"static"')

    def test_identifier_sanitizes(self) -> None:
        self.assertEqual(_identifier("ts"), "ts")
        self.assertEqual(_identifier("x-sign"), "x_sign")
        self.assertEqual(_identifier("2fa"), "p_2fa")
        self.assertEqual(_identifier(""), "p_")


class TestEmitPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = emit_plan(report())

    def test_one_step_per_endpoint(self) -> None:
        self.assertEqual(len(self.template["steps"]), 3)
        endpoints = {step["endpoint"] for step in self.template["steps"]}
        self.assertIn("POST /v1/sign/in", endpoints)
        self.assertIn("GET /v1/user/{id}/profile", endpoints)

    def test_role_is_left_empty_for_humans(self) -> None:
        for step in self.template["steps"]:
            self.assertEqual(step["role"], "")

    def test_body_shape_inferred_from_probe(self) -> None:
        by_endpoint = {step["endpoint"]: step["body"] for step in self.template["steps"]}
        self.assertEqual(by_endpoint["POST /v1/sign/in"], "json")
        self.assertEqual(by_endpoint["GET /v1/user/{id}/profile"], "query")

    def test_dynamic_prefilled_from_volatile_candidates(self) -> None:
        self.assertEqual(self.template["dynamic"]["ts"], "timestamp_s")
        self.assertEqual(self.template["dynamic"]["sign"], "UNRESOLVED")

    def test_credentials_are_not_mistaken_for_dynamic_params(self) -> None:
        self.assertNotIn("SESSIONID", self.template["dynamic"])

    def test_base_url_derived_from_api_host(self) -> None:
        self.assertEqual(self.template["base_url"], "https://api.example.com")

    def test_template_alone_is_not_valid(self) -> None:
        issues = validate_plan(self.template, report())
        self.assertIn("missing_role", kinds(issues))
        self.assertIn("missing_field", kinds(issues))


class TestStructuralNoise(unittest.TestCase):
    """协议层产物（隧道 / 预检）不该出现在步骤模板里——这是结构判定，不是语义猜测。"""

    ENDPOINTS = [
        {"method": "CONNECT", "path": "/"},
        {"method": "GET", "path": "/v1/me"},
        {"method": "OPTIONS", "path": "/v1/me"},
        {"method": "POST", "path": "/v1/sign/in"},
        {"method": "OPTIONS", "path": "/v1/sign/in"},
        {"method": "OPTIONS", "path": "/v1/capabilities"},
    ]

    def test_connect_is_never_a_step(self) -> None:
        self.assertFalse(is_step_candidate("CONNECT", "/", self.ENDPOINTS))

    def test_options_paired_with_another_method_is_preflight(self) -> None:
        self.assertFalse(is_step_candidate("OPTIONS", "/v1/me", self.ENDPOINTS))

    def test_lone_options_is_kept_for_humans_to_judge(self) -> None:
        self.assertTrue(is_step_candidate("OPTIONS", "/v1/capabilities", self.ENDPOINTS))

    def test_normal_methods_are_always_candidates(self) -> None:
        self.assertTrue(is_step_candidate("GET", "/v1/me", self.ENDPOINTS))
        self.assertTrue(is_step_candidate("POST", "/v1/sign/in", self.ENDPOINTS))

    def test_split_preserves_order_and_partitions_everything(self) -> None:
        steps, noise = split_step_candidates(self.ENDPOINTS)
        self.assertEqual([row["method"] for row in steps], ["GET", "POST", "OPTIONS"])
        self.assertEqual(len(steps) + len(noise), len(self.ENDPOINTS))
        self.assertEqual(
            {f"{row['method']} {row['path']}" for row in noise},
            {"CONNECT /", "OPTIONS /v1/me", "OPTIONS /v1/sign/in"},
        )

    def test_emit_plan_drops_noise_and_says_so(self) -> None:
        template = emit_plan({"endpoints": list(self.ENDPOINTS), "hosts": [], "fields": {}})
        emitted = [step["endpoint"] for step in template["steps"]]
        self.assertEqual(emitted, ["GET /v1/me", "POST /v1/sign/in", "OPTIONS /v1/capabilities"])
        self.assertTrue(any("协议层产物" in note for note in template["_说明"]))

    def test_emit_plan_stays_quiet_when_there_is_no_noise(self) -> None:
        clean = [{"method": "GET", "path": "/v1/me"}]
        template = emit_plan({"endpoints": clean, "hosts": [], "fields": {}})
        self.assertFalse(any("协议层产物" in note for note in template["_说明"]))

    def test_off_host_endpoints_are_flagged_not_dropped(self) -> None:
        report_dict = {
            "endpoints": [
                {"method": "GET", "path": "/v1/me", "host": "api.example.com"},
                {"method": "GET", "path": "/recaptcha/api2/anchor", "host": "www.gstatic.cn"},
            ],
            "hosts": [{"host": "api.example.com", "api": 1}, {"host": "www.gstatic.cn", "api": 1}],
            "fields": {},
        }
        template = emit_plan(report_dict)
        self.assertEqual(len(template["steps"]), 2)  # 不剔除
        self.assertTrue(any("不在主接口域名" in note for note in template["_说明"]))
        self.assertTrue(any("www.gstatic.cn" in note for note in template["_说明"]))

    def test_emit_plan_omits_off_host_note_when_all_are_primary(self) -> None:
        report_dict = {
            "endpoints": [{"method": "GET", "path": "/v1/me", "host": "api.example.com"}],
            "hosts": [{"host": "api.example.com", "api": 1}],
            "fields": {},
        }
        template = emit_plan(report_dict)
        self.assertFalse(any("不在主接口域名" in note for note in template["_说明"]))

    def test_human_can_add_a_noise_endpoint_back(self) -> None:
        """剔除只是默认值；人若判断它是业务接口，加回来必须仍被放行。"""
        probe_report = {"endpoints": list(self.ENDPOINTS), "hosts": [], "fields": {}}
        plan = {
            "name": "x",
            "base_url": "https://a.example.com",
            "env_name": "X",
            "paradigm": "oop",
            "dynamic": {},
            "steps": [{"id": "cap", "role": "query", "endpoint": "OPTIONS /v1/capabilities", "body": "none"}],
        }
        self.assertNotIn("unknown_endpoint", kinds(validate_plan(plan, probe_report)))



class TestValidate(unittest.TestCase):
    def test_valid_plan_has_no_issues(self) -> None:
        self.assertEqual(validate_plan(valid_plan(), report()), [])

    def test_missing_role_is_reported(self) -> None:
        plan = valid_plan()
        plan["steps"][0]["role"] = ""
        issues = validate_plan(plan, report())
        self.assertIn("missing_role", kinds(issues))

    def test_unknown_endpoint_is_reported(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["endpoint"] = "POST /v1/not/in/the/har"
        self.assertIn("unknown_endpoint", kinds(validate_plan(plan, report())))

    def test_undefined_dynamic_is_reported(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["dynamic"] = ["ts", "mystery"]
        self.assertIn("undefined_dynamic", kinds(validate_plan(plan, report())))

    def test_header_slot_with_no_source_is_reported(self) -> None:
        """{token} 只从 state 取，state = 账号字段 + 前序 capture。三者都没有就是空串。"""
        plan = valid_plan()
        plan["steps"][1]["headers"] = {"Authorization": "Bearer {nowhere}"}
        issues = validate_plan(plan, report())
        self.assertIn("unresolved_slot", kinds(issues))
        detail = next(i["detail"] for i in issues if i["kind"] == "unresolved_slot")
        self.assertIn("nowhere", detail)

    def test_header_slot_resolved_by_an_account_field(self) -> None:
        """无登录步骤、长期令牌走环境变量——这是最常见的真实形态。"""
        plan = valid_plan()
        plan["account"]["fields"] = ["phone", "password", "token"]
        plan["steps"][1]["headers"] = {"Authorization": "Bearer {token}"}
        self.assertEqual(validate_plan(plan, report()), [])

    def test_header_slot_resolved_by_a_previous_login_capture(self) -> None:
        plan = valid_plan()  # login 步骤 capture token，sign_in 用它
        self.assertEqual(validate_plan(plan, report()), [])

    def test_step_cannot_use_a_slot_it_captures_itself(self) -> None:
        """capture 发生在响应之后，同一个请求用不上——这是鸡生蛋，必须拦。"""
        plan = valid_plan()
        plan["steps"] = [plan["steps"][1]]
        plan["steps"][0]["headers"] = {"Authorization": "Bearer {token}"}
        plan["steps"][0]["capture"] = {"token": "data.token"}
        plan["steps"][0]["role"] = "login"
        self.assertIn("unresolved_slot", kinds(validate_plan(plan, report())))

    def test_header_slot_resolved_by_an_earlier_non_login_step(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["capture"] = {"csrf": "data.csrf"}
        plan["steps"][2]["headers"] = {"X-CSRF": "{csrf}"}
        self.assertEqual(validate_plan(plan, report()), [])

    def test_later_capture_does_not_resolve_an_earlier_slot(self) -> None:
        plan = valid_plan()
        plan["steps"][0]["capture"] = {}
        plan["steps"][0]["headers"] = {"Authorization": "Bearer {token}"}
        issues = validate_plan(plan, report())  # token 由第 2 步 capture
        self.assertIn("unresolved_slot", kinds(issues))

    def test_literal_only_headers_need_no_source(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["headers"] = {"X-Client": "web-1.0"}
        self.assertEqual(validate_plan(plan, report()), [])

    def test_unknown_strategy_is_reported(self) -> None:
        plan = valid_plan()
        plan["dynamic"]["ts"] = "vibes"
        self.assertIn("unknown_strategy", kinds(validate_plan(plan, report())))

    def test_credential_in_static_is_refused(self) -> None:
        plan = valid_plan()
        # 值本身无所谓（校验看的是字段名）；但字面量仍要带占位标记，
        # 否则发布检查会把这条夹具当成真凭证。
        plan["steps"][0]["static"] = {"password": "example-value"}
        issues = validate_plan(plan, report())
        self.assertIn("credential_in_plan", kinds(issues))

    def test_credential_colliding_with_account_fields_is_refused(self) -> None:
        plan = valid_plan()
        plan["steps"][0]["static"] = {"phone": "13800000000"}
        self.assertIn("field_collision", kinds(validate_plan(plan, report())))

    def test_duplicate_and_invalid_step_ids(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["id"] = "login"
        self.assertIn("duplicate_id", kinds(validate_plan(plan, report())))

        plan = valid_plan()
        plan["steps"][1]["id"] = "sign-in"
        self.assertIn("invalid_id", kinds(validate_plan(plan, report())))

    def test_missing_path_param_is_refused(self) -> None:
        plan = valid_plan()
        plan["steps"][2].pop("path_params")
        self.assertIn("missing_path_param", kinds(validate_plan(plan, report())))

    def test_unused_path_param_is_reported(self) -> None:
        plan = valid_plan()
        plan["steps"][2]["path_params"]["ghost"] = "literal:1"
        self.assertIn("unused_path_param", kinds(validate_plan(plan, report())))

    def test_body_mismatch_against_probe_is_reported(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["body"] = "form"
        self.assertIn("body_mismatch", kinds(validate_plan(plan, report())))

    def test_multipart_with_file_part_is_refused(self) -> None:
        """带 filename 的 part 内容还原不出来，继续拒绝。"""
        plan = multipart_plan()
        plan["steps"][0]["endpoint"] = "POST /v1/upload/avatar"
        plan["steps"][0]["static"] = {"photo": "x"}
        plan["dynamic"] = {}
        self.assertIn("unsupported_body", kinds(validate_plan(plan, multipart_report())))

    def test_text_only_multipart_is_accepted(self) -> None:
        """纯文本 multipart 的字段值在 HAR 里是完整的，没有理由拒绝。"""
        self.assertEqual([], validate_plan(multipart_plan(), multipart_report()))

    def test_multipart_declared_as_form_is_reported_as_mismatch(self) -> None:
        plan = multipart_plan()
        plan["steps"][0]["body"] = "form"
        self.assertIn("body_mismatch", kinds(validate_plan(plan, multipart_report())))

    def test_multipart_without_any_field_is_refused(self) -> None:
        """空 multipart 连 Content-Type 都发不出去——form 允许零字段，multipart 不允许。"""
        plan = multipart_plan()
        plan["steps"][0]["static"] = {}
        plan["steps"][0]["dynamic"] = []
        plan["dynamic"] = {}
        issues = validate_plan(plan, multipart_report())
        self.assertIn("empty_multipart_body", kinds(issues))

    def test_multipart_login_may_take_fields_from_account(self) -> None:
        """login 步骤的字段来自 account.fields，所以不算空。"""
        plan = multipart_plan()
        plan["account"]["fields"] = ["loginName", "token"]
        plan["steps"][0]["role"] = "login"
        plan["steps"][0]["static"] = {}
        plan["steps"][0]["dynamic"] = []
        plan["dynamic"] = {}
        self.assertEqual([], validate_plan(plan, multipart_report()))

    def test_non_oop_paradigm_is_refused_with_reason(self) -> None:
        plan = valid_plan()
        plan["paradigm"] = "async"
        issues = validate_plan(plan, report())
        self.assertIn("unsupported_paradigm", kinds(issues))
        self.assertTrue(any("尚未实现" in issue["detail"] for issue in issues))

    def test_unknown_on_failure_is_refused(self) -> None:
        plan = valid_plan()
        plan["steps"][1]["on_failure"] = "retry"
        self.assertIn("unknown_on_failure", kinds(validate_plan(plan, report())))

    def test_on_failure_defaults_to_abort(self) -> None:
        plan = valid_plan()
        for step in plan["steps"]:
            step.pop("on_failure", None)
        self.assertEqual([], validate_plan(plan, report()))

    def test_placeholder_fields_are_refused(self) -> None:
        plan = valid_plan()
        plan["name"] = "<待填：脚本名>"
        self.assertIn("missing_field", kinds(validate_plan(plan, report())))

    def test_empty_steps_is_refused(self) -> None:
        plan = valid_plan()
        plan["steps"] = []
        self.assertIn("missing_field", kinds(validate_plan(plan, report())))

    def test_malformed_step_is_reported_not_crashed(self) -> None:
        plan = valid_plan()
        plan["steps"].append("not-an-object")
        self.assertIn("malformed_step", kinds(validate_plan(plan, report())))


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = render_script(valid_plan(), report(), "example.plan.json", "capture.har")

    def test_generated_script_is_valid_python(self) -> None:
        compile(self.script, "<generated>", "exec")

    def test_client_accepts_every_body_kind(self) -> None:
        """_request 的形参必须覆盖生成器会发出的每一种实参。

        这条是真实抓包逼出来的：multipart 支持加好了、`files=` 也发出了，
        但 `_request` 的签名里没有 files，运行到那一行才 TypeError——
        生成器自己发出的调用自己接不住。
        """
        signature = self.script.split("    def _request(self, method: str, endpoint: str, *,")[1]
        signature = signature.split("):")[0]
        for parameter in ("params", "json_body", "data", "files", "headers"):
            self.assertIn(parameter, signature)

    def test_header_records_both_inputs(self) -> None:
        self.assertIn("plan: example.plan.json", self.script)
        self.assertIn("har : capture.har", self.script)

    def test_endpoints_are_called(self) -> None:
        self.assertIn('"/v1/auth/login"', self.script)
        self.assertIn('"/v1/sign/in"', self.script)
        self.assertIn('"/v1/user/"', self.script)

    def test_login_runs_before_tasks(self) -> None:
        run_body = self.script.split("    def run(self) -> None:")[1]
        self.assertLess(run_body.index("self.login()"), run_body.index("self.sign_in()"))

    def _run_body(self, plan: dict) -> str:
        script = render_script(plan, report(), "p.json", "c.har")
        return script.split("    def run(self) -> None:")[1].split("def load_accounts")[0]

    def test_on_failure_abort_stops_the_flow(self) -> None:
        """on_failure 必须落进 run()。

        原先它只是计划里的一个字段，生成器从不读它——作者写了 abort、
        以为失败会停下，实际每一步照跑不误。这是最典型的"声明了但没人看"。
        """
        plan = valid_plan()
        for step in plan["steps"]:
            step["on_failure"] = "abort"
        run_body = self._run_body(plan)
        self.assertIn("按 on_failure=abort 中止", run_body)
        self.assertIn("return", run_body)

    def test_on_failure_continue_keeps_going(self) -> None:
        plan = valid_plan()
        for step in plan["steps"]:
            step["on_failure"] = "continue"
        run_body = self._run_body(plan)
        self.assertIn("按声明继续后续步骤", run_body)
        self.assertNotIn("return", run_body)

    def test_login_step_keeps_its_own_skip_message(self) -> None:
        plan = valid_plan()
        plan["steps"][0]["on_failure"] = "abort"
        self.assertIn("登录未成功，后续任务不执行", self._run_body(plan))

    def test_unresolved_dynamic_raises_instead_of_faking_a_value(self) -> None:
        self.assertIn("raise NotImplementedError", self.script)

    def test_account_fields_seed_state_so_slots_resolve_without_a_login_step(self) -> None:
        """没有登录步骤时，{token} 只能靠账号字段打底；否则运行时静默变成空串。"""
        self.assertIn("self.state: dict = dict(account)", self.script)

    def test_capture_overwrites_the_account_seeded_state(self) -> None:
        self.assertIn('self.state["token"] = token', self.script)

    def test_zero_param_form_post_keeps_its_content_type(self) -> None:
        """抓包里 keepSignIn 就是 Content-Length: 0 + form 型 Content-Type。
        不传 data 会把 Content-Type 一起丢掉，服务端可能直接拒。"""
        plan = valid_plan()
        plan["steps"] = [
            {
                "id": "keep_sign_in",
                "role": "task",
                "endpoint": "POST /v1/sign/in",
                "body": "form",
                "headers": {"Authorization": "{token}"},
                "static": {},
                "dynamic": [],
                "capture": {},
            }
        ]
        plan["account"]["fields"] = ["phone", "password", "token"]
        script = render_script(plan, report(), "p.json", "c.har")
        compile(script, "<generated>", "exec")
        body = script.split("    def keep_sign_in(self) -> bool:")[1]
        self.assertIn("payload = {}", body)
        self.assertIn("data=payload", body)

    def test_zero_param_query_step_does_not_fake_a_body(self) -> None:
        plan = valid_plan()
        plan["steps"] = [
            {
                "id": "ping",
                "role": "query",
                "endpoint": "GET /v1/user/{id}/profile",
                "body": "none",
                "path_params": {"id": "account:phone"},
                "static": {},
                "dynamic": [],
                "capture": {},
            }
        ]
        script = render_script(plan, report(), "p.json", "c.har")
        body = script.split("    def ping(self) -> bool:")[1]
        self.assertNotIn("payload", body)

    def test_multipart_step_uses_files_with_text_parts(self) -> None:
        """纯文本 multipart 用 files={name: (None, value)} 生成文本 part。

        边界值由 requests 生成——服务端按 Content-Type 里的 boundary 切分，
        不校验它的字面量，所以不必复现抓包里的 WebKitFormBoundary。
        """
        script = render_script(multipart_plan(), multipart_report(), "p.json", "c.har")
        compile(script, "<generated>", "exec")
        body = script.split("    def request_code(self) -> bool:")[1]
        self.assertIn("files={name: (None, value) for name, value in payload.items()}", body)
        self.assertNotIn("data=payload", body)

    def test_multipart_step_keeps_its_fields(self) -> None:
        script = render_script(multipart_plan(), multipart_report(), "p.json", "c.har")
        body = script.split("    def request_code(self) -> bool:")[1]
        self.assertIn('"loginName": "a@example.com",', body)
        self.assertIn('"token": Dynamic.token(),', body)

    def test_empty_account_fields_does_not_demand_an_env_var(self) -> None:
        """注册流程天然没有 account.fields。

        原先的写法会要求配一个完全用不到的环境变量：填了才肯跑，跑了又不用它。
        这种"仪式性配置"迟早被误解成"这里要填真的"。
        """
        plan = valid_plan()
        plan["account"]["fields"] = []
        plan["steps"] = [
            {
                "id": "ping",
                "role": "query",
                "endpoint": "GET /v1/user/{id}/profile",
                "body": "none",
                "path_params": {"id": "literal:1"},
                "static": {},
                "dynamic": [],
                "capture": {},
            }
        ]
        script = render_script(plan, report(), "p.json", "c.har")
        compile(script, "<generated>", "exec")
        self.assertIn("return [{}]", script)
        self.assertNotIn("未配置账号", script)

    def test_account_fields_still_demand_the_env_var(self) -> None:
        script = render_script(valid_plan(), report(), "p.json", "c.har")
        self.assertIn("未配置账号", script)
        self.assertNotIn("return [{}]", script)


        self.assertIn("def sign(", self.script)

    def test_headers_reference_captured_state(self) -> None:
        self.assertIn('"Bearer " + str(self.state.get("token", \'\'))', self.script)

    def test_path_params_are_substituted_from_declaration(self) -> None:
        self.assertIn('"/v1/user/" + str(self.account.get("phone", "")) + "/profile"', self.script)

    def test_account_fields_come_from_environment_not_from_capture(self) -> None:
        self.assertIn('self.account.get("phone", "")', self.script)
        self.assertIn("load_accounts", self.script)
        self.assertIn('ENV_NAME = "EXAMPLE_ACCOUNT"', self.script)

    def test_captured_values_are_masked_in_logs(self) -> None:
        self.assertIn("_mask(str(token))", self.script)

    def test_no_credential_values_from_the_har_leak_into_the_script(self) -> None:
        self.assertNotIn(SIGN_A, self.script)
        self.assertNotIn(SIGN_B, self.script)
        self.assertNotIn("example-password", self.script)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", self.script)

    def test_todo_list_names_the_unresolved_signature(self) -> None:
        self.assertIn("待人工完成", self.script)
        self.assertIn("复现参数 sign 的生成算法", self.script)

    def test_todo_list_names_the_unverified_capture_path(self) -> None:
        self.assertIn("data.token", self.script)
        self.assertIn("未验证", self.script)

    def test_todo_list_carries_the_authorisation_reminder(self) -> None:
        self.assertIn("授权范围", self.script)

    def test_unused_endpoint_shows_up_as_a_todo(self) -> None:
        plan = valid_plan()
        plan["steps"] = plan["steps"][:2]
        script = render_script(plan, report(), "plan.json", "capture.har")
        self.assertIn("未被任何 step 使用", script)

    def test_protocol_noise_is_not_reported_as_an_unused_endpoint(self) -> None:
        """emit_plan 已按结构剔除它们；再报"未被使用"就是工具自己打自己。"""
        plan = valid_plan()
        plan["steps"] = plan["steps"][:2]
        noisy_report = {
            "endpoints": [
                {"method": "POST", "path": "/v1/auth/login", "host": "api.example.com", "count": 1,
                 "body_kinds": {"json": 1}, "query_keys": [], "statuses": {"200": 1}},
                {"method": "POST", "path": "/v1/sign/in", "host": "api.example.com", "count": 1,
                 "body_kinds": {"json": 1}, "query_keys": [], "statuses": {"200": 1}},
                {"method": "OPTIONS", "path": "/v1/sign/in", "host": "api.example.com", "count": 1,
                 "body_kinds": {"empty": 1}, "query_keys": [], "statuses": {"204": 1}},
                {"method": "CONNECT", "path": "/", "host": "api.example.com", "count": 1,
                 "body_kinds": {"text": 1}, "query_keys": [], "statuses": {"-1": 1}},
            ],
            "hosts": [{"host": "api.example.com", "api": 1}],
            "fields": {},
        }
        script = render_script(plan, noisy_report, "plan.json", "capture.har")
        self.assertNotIn("端点 OPTIONS /v1/sign/in 未被任何 step 使用", script)
        self.assertNotIn("端点 CONNECT / 未被任何 step 使用", script)
        self.assertIn("协议层产物", script)

    def test_no_emoji_in_generated_console_output(self) -> None:
        for char in self.script:
            self.assertLess(ord(char), 0x1F000, f"生成了 emoji: {char!r}")

    def test_missing_account_fields_produce_a_todo(self) -> None:
        plan = valid_plan()
        plan["account"]["fields"] = []
        plan["steps"][0]["role"] = "task"
        plan["steps"][0]["capture"] = {}
        script = render_script(plan, report(), "plan.json", "capture.har")
        self.assertIn("account.fields 为空", script)


def plan_with_expect() -> dict:
    plan = valid_plan()
    plan["steps"] = [
        {
            "id": "keep_sign_in",
            "role": "task",
            "endpoint": "POST /v1/sign/in",
            "body": "json",
            "headers": {"Authorization": "{token}"},
            "static": {},
            "dynamic": [],
            "capture": {},
            "expect": {
                "code_field": "code",
                "success_values": [0],
                "benign": [{"value": 500, "msg_contains": "已经签到", "note": "今日已签到，视为完成"}],
            },
        }
    ]
    plan["account"]["fields"] = ["phone", "password", "token"]
    return plan


class TestExpect(unittest.TestCase):
    """HTTP 200 + 业务码失败 是这类接口的常态，只看 status_code 会把失败报成成功。"""

    def test_valid_expect_passes_validation(self) -> None:
        self.assertEqual(validate_plan(plan_with_expect(), report()), [])

    def test_expect_must_be_an_object(self) -> None:
        plan = plan_with_expect()
        plan["steps"][0]["expect"] = "code"
        self.assertIn("malformed_expect", kinds(validate_plan(plan, report())))

    def test_expect_needs_a_code_field(self) -> None:
        plan = plan_with_expect()
        plan["steps"][0]["expect"]["code_field"] = ""
        self.assertIn("malformed_expect", kinds(validate_plan(plan, report())))

    def test_success_values_must_be_a_list(self) -> None:
        plan = plan_with_expect()
        plan["steps"][0]["expect"]["success_values"] = 0
        self.assertIn("malformed_expect", kinds(validate_plan(plan, report())))

    def test_benign_entries_need_a_value(self) -> None:
        plan = plan_with_expect()
        plan["steps"][0]["expect"]["benign"] = [{"msg_contains": "已经签到"}]
        self.assertIn("malformed_expect", kinds(validate_plan(plan, report())))

    def test_steps_without_expect_get_a_todo(self) -> None:
        script = render_script(valid_plan(), report(), "plan.json", "capture.har")
        self.assertIn("没声明业务码约定", script)

    def test_steps_with_expect_do_not_get_that_todo(self) -> None:
        script = render_script(plan_with_expect(), report(), "plan.json", "capture.har")
        self.assertNotIn("没声明业务码约定", script)

    def _helper(self, script: str) -> dict:
        """把生成的源码 exec 出来，好直接调它真正会跑的那个判定函数。"""
        import types

        stub = types.ModuleType("requests")
        stub.Session = object
        stub.RequestException = Exception
        saved = sys.modules.get("requests")
        sys.modules["requests"] = stub
        try:
            namespace: dict = {}
            exec(compile(script, "<generated>", "exec"), namespace)
        finally:
            if saved is None:
                del sys.modules["requests"]
            else:
                sys.modules["requests"] = saved
        return namespace

    def _response(self, payload: dict):
        class _Response:
            def json(self):
                return payload

        return _Response()

    def test_generated_judgement_accepts_the_declared_success_code(self) -> None:
        namespace = self._helper(render_script(plan_with_expect(), report(), "p.json", "c.har"))
        verdict = namespace["_business_code"](
            {"code": 0, "msg": "操作成功"}, "keep_sign_in", plan_with_expect()["steps"][0]["expect"]
        )
        self.assertEqual(verdict, "ok")

    def test_generated_judgement_treats_already_signed_in_as_benign(self) -> None:
        namespace = self._helper(render_script(plan_with_expect(), report(), "p.json", "c.har"))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            verdict = namespace["_business_code"](
                {"code": 500, "msg": "今日已经签到，请明日再来"},
                "keep_sign_in",
                plan_with_expect()["steps"][0]["expect"],
            )
        self.assertEqual(verdict, "benign")
        self.assertIn("今日已签到", buffer.getvalue())

    def test_generated_judgement_fails_on_an_unexpected_code(self) -> None:
        namespace = self._helper(render_script(plan_with_expect(), report(), "p.json", "c.har"))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            verdict = namespace["_business_code"](
                {"code": 401, "msg": "登录已过期"}, "keep_sign_in", plan_with_expect()["steps"][0]["expect"]
            )
        self.assertEqual(verdict, "fail")
        self.assertIn("401", buffer.getvalue())

    def test_generated_judgement_fails_when_the_code_field_is_absent(self) -> None:
        """响应里没有约定的字段，说明实际约定与声明不符——不能当成功放过去。"""
        namespace = self._helper(render_script(plan_with_expect(), report(), "p.json", "c.har"))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            verdict = namespace["_business_code"](
                {"msg": "操作成功"}, "keep_sign_in", plan_with_expect()["steps"][0]["expect"]
            )
        self.assertEqual(verdict, "fail")

    def test_a_benign_value_with_the_wrong_message_is_not_swallowed(self) -> None:
        """benign 靠 msg 收窄；否则服务端真出错时也会被当成"今天签过了"咽下去。"""
        namespace = self._helper(render_script(plan_with_expect(), report(), "p.json", "c.har"))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            verdict = namespace["_business_code"](
                {"code": 500, "msg": "服务器内部错误"}, "keep_sign_in", plan_with_expect()["steps"][0]["expect"]
            )
        self.assertEqual(verdict, "fail")

    def test_generated_script_with_expect_compiles(self) -> None:
        script = render_script(plan_with_expect(), report(), "p.json", "c.har")
        compile(script, "<generated>", "exec")
        body = script.split("    def keep_sign_in(self) -> bool:")[1]
        self.assertIn("_business_code(body", body)
        self.assertIn('if verdict == "fail":', body)
        self.assertIn('if verdict == "benign":', body)


class TestCli(unittest.TestCase):
    def _har_file(self, directory: str) -> Path:
        path = Path(directory) / "capture.har"
        path.write_text(json.dumps(synthetic_har()), encoding="utf-8", newline="\n")
        return path

    def test_emit_plan_writes_a_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            target = Path(directory) / "plan.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--har", str(har), "--emit-plan", str(target)])
            self.assertEqual(code, 0)
            self.assertTrue(target.is_file())
            template = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("_说明", template)
            self.assertEqual(len(template["steps"]), 3)

    def test_check_passes_on_valid_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(valid_plan()), encoding="utf-8", newline="\n")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--har", str(har), "--plan", str(plan_path), "--check"])
            self.assertEqual(code, 0)
            self.assertIn("RESULT=OK", stdout.getvalue())

    def test_check_fails_on_invalid_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            plan = valid_plan()
            plan["steps"][0]["role"] = ""
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8", newline="\n")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--har", str(har), "--plan", str(plan_path), "--check"])
            self.assertEqual(code, 1)
            self.assertIn("missing_role", stdout.getvalue())

    def test_out_writes_compilable_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(valid_plan()), encoding="utf-8", newline="\n")
            target = Path(directory) / "signin.py"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--har", str(har), "--plan", str(plan_path), "--out", str(target)])
            self.assertEqual(code, 0)
            generated = target.read_text(encoding="utf-8")
            compile(generated, str(target), "exec")

    def test_plan_is_required_when_not_emitting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["--har", str(har)])
            self.assertEqual(code, 2)
            self.assertIn("--plan", stderr.getvalue())

    def test_unreadable_har_returns_two(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["--har", "does-not-exist.har", "--plan", "whatever.json"])
        self.assertEqual(code, 2)
        self.assertIn("无法解析", stderr.getvalue())

    def test_invalid_json_plan_returns_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            har = self._har_file(directory)
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text("{broken", encoding="utf-8", newline="\n")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["--har", str(har), "--plan", str(plan_path)])
            self.assertEqual(code, 2)
            self.assertIn("计划文件读取失败", stderr.getvalue())


# ------------------------------------------------ 第 4 步：复现产物回填与自检
#
# 这一组测的是「签名算法复现之后，怎么把产物交回骨架」。
# 核心不是"能塞进去"，而是**待办清单什么时候才真的能消掉**：
# 回填不等于消待办，带证据的回填才消。
#
# 全部用合成输入（test_har_probe 的 synthetic_har + 本文件里的假产物），
# 不碰任何真实抓包——本作业的抓包里根本没有签名参数。

# 模块级沙箱：Windows 上每次 rmtree 空目录也要近 1 秒，
# 放进逐用例的临时目录会拖垮整个套件。整模块共用一个，退出时一次性清理。
_SANDBOX = Path(tempfile.mkdtemp(prefix="har_to_script_impl_"))
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)

PY_IMPL = '''import hashlib


def compute_sign(payload):
    """合成签名：md5("uid|ts|nonce")。"""
    raw = "|".join(str(payload[key]) for key in ("uid", "ts", "nonce"))
    return hashlib.md5(raw.encode()).hexdigest()
'''

JS_IMPL = """function computeSign(payload) {
  const raw = [payload.uid, payload.ts, payload.nonce].join("|");
  let a = 0, b = 0;
  for (let i = 0; i < raw.length; i++) {
    a = (a * 31 + raw.charCodeAt(i)) >>> 0;
    b = (b * 17 + raw.charCodeAt(i) + i) >>> 0;
  }
  return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
}
"""

PY_INPUT = {"uid": "12345", "ts": 1758700000, "nonce": "n-1"}
# 两个期望值都是实跑出来的，不是手算：Python 侧 md5，JS 侧 node。
# 故意都长于 8 个字符——自检输出走 _mask，太短的值会被整段遮掉，
# 报「不一致」时就看不出差在哪。真实签名没有这么短的。
PY_EXPECT = "666730a1929d846e04ff7d70740513d3"
JS_EXPECT = "ec7ba961e27238cd"


def workspace(name: str) -> Path:
    path = _SANDBOX / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_impl(directory: Path, relative: str, text: str) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def backfilled_plan(directory: Path, *, impl: str = "python", verified: bool = True, **overrides) -> dict:
    """把 valid_plan 里的 sign 从 UNRESOLVED 换成一份回填的复现产物。"""
    python_side = impl == "python"
    source = "impl/sign.py" if python_side else "impl/sign.js"
    entry = "compute_sign" if python_side else "computeSign"
    write_impl(directory, source, PY_IMPL if python_side else JS_IMPL)

    plan = valid_plan()
    record: dict = {"impl": impl, "source": source, "entry": entry}
    if verified:
        record["verified"] = {
            "against": "synthetic_har#POST /v1/sign/in",
            "input": dict(PY_INPUT),
            "expect": PY_EXPECT if python_side else JS_EXPECT,
        }
    record.update(overrides)
    plan["dynamic"]["sign"] = record
    if not python_side:
        plan["allow_external_runtime"] = True
    return plan


def generate(directory: Path, plan: dict) -> str:
    """生成骨架并确认它至少是合法 Python。"""
    script = render_script(plan, report(), "example.plan.json", "capture.har", directory)
    compile(script, "<generated>", "exec")
    return script


def run_selftest(directory: Path, plan: dict, *, env: dict | None = None):
    """生成、写盘、跑 --selftest，返回 (CompletedProcess, 脚本正文)。"""
    script = generate(directory, plan)
    target = directory / "generated.py"
    target.write_text(script, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [sys.executable, str(target), "--selftest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(directory),
        env=env,
    )
    return result, script


class TestValidateImpl(unittest.TestCase):
    """回填产物的校验：错误要具体，合法状态要放行。"""

    def setUp(self) -> None:
        self.dir = workspace("validate")

    def check(self, plan: dict) -> set[str]:
        return kinds(validate_plan(plan, report(), self.dir))

    def test_backfilled_python_impl_passes(self) -> None:
        self.assertEqual(validate_plan(backfilled_plan(self.dir), report(), self.dir), [])

    def test_backfill_without_evidence_is_legal_not_an_error(self) -> None:
        """缺证据不是「错误」，是一种**会被记进待办**的合法状态。

        把它判成错误，人就只能二选一：要么编一个假证据，要么干脆不回填。
        """
        plan = backfilled_plan(self.dir, verified=False)
        self.assertEqual(validate_plan(plan, report(), self.dir), [])

    def test_missing_source_file_is_refused(self) -> None:
        self.assertIn("missing_impl_source", self.check(backfilled_plan(self.dir, source="impl/nope.py")))

    def test_empty_source_is_refused(self) -> None:
        self.assertIn("missing_impl_source", self.check(backfilled_plan(self.dir, source="")))

    def test_unknown_impl_kind_is_refused(self) -> None:
        """生成器不按扩展名猜语言。"""
        self.assertIn("unknown_impl", self.check(backfilled_plan(self.dir, impl="ruby")))

    def test_entry_must_exist_at_the_top_level(self) -> None:
        self.assertIn("missing_impl_entry", self.check(backfilled_plan(self.dir, entry="nope")))

    def test_missing_entry_is_refused(self) -> None:
        self.assertIn("missing_impl_entry", self.check(backfilled_plan(self.dir, entry="")))

    def test_async_entry_is_refused(self) -> None:
        plan = backfilled_plan(self.dir)
        write_impl(self.dir, "impl/sign.py", "async def compute_sign(payload):\n    return 'x'\n")
        self.assertIn("unsupported_impl_entry", self.check(plan))

    def test_executable_toplevel_is_refused(self) -> None:
        """内联是有损变换：顶层语句落进方法体后会「每次调用都执行」。

        产物文件很自然地带一个 `if __name__ == "__main__"` 自测块——
        内联后它就成了每次算签名都跑一遍的东西。
        """
        plan = backfilled_plan(self.dir)
        write_impl(
            self.dir,
            "impl/sign.py",
            "def compute_sign(payload):\n    return 'x'\n\n\nif __name__ == '__main__':\n    print(compute_sign({}))\n",
        )
        self.assertIn("impure_impl_toplevel", self.check(plan))

    def test_verified_needs_a_traceable_source(self) -> None:
        plan = backfilled_plan(self.dir)
        del plan["dynamic"]["sign"]["verified"]["against"]
        self.assertIn("malformed_verified", self.check(plan))

    def test_verified_needs_an_expectation(self) -> None:
        plan = backfilled_plan(self.dir)
        plan["dynamic"]["sign"]["verified"]["expect"] = ""
        self.assertIn("malformed_verified", self.check(plan))

    def test_verified_input_must_be_an_object(self) -> None:
        plan = backfilled_plan(self.dir)
        plan["dynamic"]["sign"]["verified"]["input"] = ["12345"]
        self.assertIn("malformed_verified", self.check(plan))

    def test_js_impl_needs_explicit_authorisation(self) -> None:
        """调外部进程是能力越界，必须由计划显式授权。"""
        plan = backfilled_plan(self.dir, impl="js")
        del plan["allow_external_runtime"]
        self.assertIn("external_runtime_not_authorized", self.check(plan))

    def test_js_impl_is_accepted_once_authorised(self) -> None:
        self.assertEqual(validate_plan(backfilled_plan(self.dir, impl="js"), report(), self.dir), [])

    def test_js_impl_with_triple_quotes_is_refused(self) -> None:
        """生成的骨架必须自包含，所以 JS 是内联的；内联不进就得说清楚。"""
        plan = backfilled_plan(self.dir, impl="js")
        write_impl(self.dir, "impl/sign.js", 'function computeSign(p) { return """x"""; }\n')
        self.assertIn("malformed_impl_source", self.check(plan))

    def test_malformed_python_impl_is_refused(self) -> None:
        plan = backfilled_plan(self.dir)
        write_impl(self.dir, "impl/sign.py", "def compute_sign(payload)\n    return 'x'\n")
        self.assertIn("malformed_impl_source", self.check(plan))

    def test_dynamic_table_must_be_an_object(self) -> None:
        """畸形输入要变成一条能读的校验失败，而不是 TypeError。"""
        plan = backfilled_plan(self.dir)
        plan["dynamic"] = ["ts"]
        self.assertIn("malformed_dynamic", self.check(plan))

    def test_impl_strategy_is_not_mistaken_for_an_unknown_strategy(self) -> None:
        """对象形态直接当字符串用会撞 unhashable，这条守着那个边界。"""
        self.assertNotIn("unknown_strategy", self.check(backfilled_plan(self.dir)))


class TestRenderImpl(unittest.TestCase):
    """回填后的生成结果。"""

    def setUp(self) -> None:
        self.dir = workspace("render")

    def test_python_impl_body_is_inlined(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir))
        self.assertIn("def compute_sign(payload):", script)
        self.assertIn("return compute_sign(payload)", script)
        self.assertIn("复现产物原文", script)

    def test_inlining_preserves_every_line_of_the_impl(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir))
        for line in PY_IMPL.splitlines():
            if line.strip():
                self.assertIn(line, script)

    def test_impl_receives_the_whole_payload(self) -> None:
        """签名要吃 body 里好几个字段，而字典字面量内部引用不了自己。"""
        script = generate(self.dir, backfilled_plan(self.dir))
        body = script.split("    def sign_in(self) -> bool:")[1]
        self.assertLess(
            body.index('"nonce": Dynamic.uuid4(),'),
            body.index('payload["sign"] = Dynamic.sign(payload)'),
        )

    def test_impl_is_assigned_after_the_literal_is_closed(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir))
        body = script.split("    def sign_in(self) -> bool:")[1]
        self.assertLess(body.index("        }"), body.index('payload["sign"] ='))

    def test_header_records_the_impl_source(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir))
        self.assertIn("impl/sign.py → compute_sign", script)

    def test_header_flags_missing_evidence(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir, verified=False))
        self.assertIn("**无验证证据**", script)

    def test_js_impl_is_inlined_as_a_constant(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir, impl="js"))
        self.assertIn('_JS_SIGN = r"""', script)
        self.assertIn("function computeSign(payload)", script)

    def test_js_impl_brings_its_runtime_helper(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir, impl="js"))
        self.assertIn("def _run_node(", script)
        self.assertIn("import shutil", script)
        self.assertIn("import subprocess", script)

    def test_no_impl_means_no_extra_machinery(self) -> None:
        """没有回填产物时不该凭空多出 node 支撑与自检入口。"""
        script = generate(self.dir, valid_plan())
        self.assertNotIn("_run_node", script)
        self.assertNotIn("import shutil", script)
        self.assertNotIn("def selftest(", script)
        self.assertIn("import requests", script)

    def test_selftest_does_not_drag_in_the_network_stack(self) -> None:
        """自检只算签名；让 requests 的缺失挡住它，等于把复核绑在无关依赖上。"""
        script = generate(self.dir, backfilled_plan(self.dir))
        self.assertIn('if "--selftest" not in sys.argv:', script)

    def test_selftest_entry_is_wired(self) -> None:
        script = generate(self.dir, backfilled_plan(self.dir))
        self.assertIn('if "--selftest" in sys.argv:', script)
        self.assertIn("sys.exit(selftest())", script)

    def test_two_backfilled_parameters_both_land(self) -> None:
        plan = backfilled_plan(self.dir)
        write_impl(self.dir, "impl/stamp.py", "def compute_stamp(payload):\n    return '7'\n")
        plan["dynamic"]["stamp"] = {
            "impl": "python",
            "source": "impl/stamp.py",
            "entry": "compute_stamp",
            "verified": {"against": "synthetic_har", "input": {}, "expect": "7"},
        }
        plan["steps"][1]["dynamic"].append("stamp")
        script = generate(self.dir, plan)
        self.assertIn("def compute_stamp(payload)", script)
        # 方法名取自**参数名**，不是 entry 名——参数名才是计划里的键。
        self.assertIn('payload["stamp"] = Dynamic.stamp(payload)', script)


class TestImplTodos(unittest.TestCase):
    """待办清单的三态：这才是「第 4 步接口」真正要达成的事。"""

    def setUp(self) -> None:
        self.dir = workspace("todos")

    def todos(self, plan: dict) -> str:
        return "\n".join(_todos(plan, report()))

    def test_unresolved_still_asks_for_the_algorithm(self) -> None:
        self.assertIn("复现参数 sign 的生成算法", self.todos(valid_plan()))

    def test_verified_backfill_clears_that_todo(self) -> None:
        text = self.todos(backfilled_plan(self.dir))
        self.assertNotIn("复现参数 sign", text)
        self.assertNotIn("已回填", text)

    def test_unverified_backfill_replaces_the_todo_instead_of_clearing_it(self) -> None:
        """回填本身不是完成——它只是把「没有实现」换成「有个没人验证过的实现」。

        不区分这两者，待办清单就会在第一次回填后变成一张空头支票。
        """
        text = self.todos(backfilled_plan(self.dir, verified=False))
        self.assertNotIn("复现参数 sign 的生成算法", text)
        self.assertIn("已回填", text)
        self.assertIn("没有任何验证证据", text)

    def test_clearing_requires_evidence_not_just_a_file(self) -> None:
        """同一个参数，只有证据的有无决定清单长短。"""
        self.assertNotEqual(
            self.todos(backfilled_plan(self.dir, verified=True)).count("sign"),
            self.todos(backfilled_plan(self.dir, verified=False)).count("sign"),
        )

    def test_literal_still_gets_its_own_todo(self) -> None:
        plan = backfilled_plan(self.dir)
        plan["dynamic"]["device"] = "literal:web-01"
        self.assertIn("确认参数 device 的固定值是否长期有效", self.todos(plan))


class TestSelftestExecution(unittest.TestCase):
    """自检实跑。一个永远说「通过」的自检等于没有自检。"""

    def setUp(self) -> None:
        self.dir = workspace("selftest")

    def test_matching_expectation_passes(self) -> None:
        result, _ = run_selftest(self.dir, backfilled_plan(self.dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1/1 一致", result.stdout)

    def test_wrong_expectation_fails_loudly(self) -> None:
        plan = backfilled_plan(self.dir)
        plan["dynamic"]["sign"]["verified"]["expect"] = "0" * 32
        result, _ = run_selftest(self.dir, plan)
        self.assertEqual(result.returncode, 1)
        self.assertIn("[不一致]", result.stdout)

    def test_backfill_without_evidence_cannot_claim_success(self) -> None:
        result, _ = run_selftest(self.dir, backfilled_plan(self.dir, verified=False))
        self.assertEqual(result.returncode, 1)
        self.assertIn("没有验证证据", result.stdout)

    def test_js_impl_runs_under_node_or_refuses_loudly(self) -> None:
        """有 node 就算出正确值，没有 node 就明确报错——两种都不许静默。"""
        result, _ = run_selftest(self.dir, backfilled_plan(self.dir, impl="js"))
        if shutil.which("node"):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1/1 一致", result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("找不到 node", result.stdout)

    def test_js_impl_refuses_loudly_when_node_is_absent(self) -> None:
        """把 PATH 清空来强制「本机没有 node」，这样任何机器上都能验这条。"""
        env = dict(os.environ)
        env["PATH"] = ""
        env.pop("PATHEXT", None)
        result, _ = run_selftest(self.dir, backfilled_plan(self.dir, impl="js"), env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("找不到 node", result.stdout)

    def test_selftest_never_prints_the_raw_expected_value(self) -> None:
        """自检输出走 _mask，和正文一样不留明文。"""
        result, _ = run_selftest(self.dir, backfilled_plan(self.dir))
        self.assertNotIn(PY_EXPECT, result.stdout)


if __name__ == "__main__":
    unittest.main()
