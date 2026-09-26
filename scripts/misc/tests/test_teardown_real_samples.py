"""真材料回归用例：**只在真实材料上踩到过的误判**，各钉一条。

单独一个文件，是因为它的变更频率与引擎用例不同：引擎用例随引擎改，
这个文件随"又拿到一批真材料"改。三类来源：

- 误判 1-6：第一次真用（雨云签到脚本，2128 行）——单个真实样本能验证"判据对不对"。
- 误判 7：本套件自扫（`scripts/automation/har_probe.py`）——验证规则有没有只认一种写法。
- 误判 8-10：第二轮真用（本地样本目录 17 个文件，含一个 JS）——**一批真材料**
  才能碰到的形态。单个样本上 `***:***@` 这类作者自打码根本没出现过；
  样本一多，误报才有机会露头。
- 误判 11-14：第三轮真用（本仓库自己的可读 JS，116 行）+ 收紧时的反向验证——
  `langs` 声明覆盖 5 种语言，正则却只写了 Python 的形状。

这组用例的价值在于：它们全部来自**真实材料**，不是设想出来的边界。
合成夹具能验证"逻辑对"，只有真材料能验证"判据对"。
"""

from __future__ import annotations

import json
import unittest

from _teardown_support import SandboxCase, _write  # noqa: E402
from script_teardown import analyze  # noqa: E402


class TestRealSampleRegressions(SandboxCase):
    """真实材料上踩到过的误判，各钉一条。来源与理由见模块开头的说明。"""

    def _ids(self, report: dict) -> set[str]:
        return {bucket["id"] for bucket in report["features"]}

    def _risk_ids(self, report: dict) -> set[str]:
        return {item["id"] for item in report["risks"]}

    def _scan(self, name: str, text: str) -> dict:
        directory = self.case_dir(f"real_{name}")
        _write(directory, name, text)
        return analyze([directory])

    # ---- 误判 1：`ACCOUNTS = [` 不命中「多账号加载」 ----

    def test_account_list_is_multi_account(self):
        report = self._scan(
            "acc.py",
            'ACCOUNTS = [\n    ("备注", "user", "pass"),\n]\n\n\ndef main():\n'
            "    for account in ACCOUNTS:\n        print(account)\n",
        )
        self.assertIn("accounts", self._ids(report))

    def test_account_list_variable_is_multi_account(self):
        report = self._scan(
            "acc2.py", 'account_list = load()\nprint("共", len(account_list), "个账号")\n'
        )
        self.assertIn("accounts", self._ids(report))

    def test_single_account_literal_is_not_multi_account(self):
        # 单个 `ACCOUNT = "..."` 是"单账号硬编码"，与"多账号加载"不是一回事。
        # 收进来会把这一档的意思搞浑——复用候选是给人照着做的。
        report = self._scan("acc3.py", 'ACCOUNT = "someone"\nprint(ACCOUNT)\n')
        self.assertNotIn("accounts", self._ids(report))

    # ---- 误判 2：`Config` 类之外的「配置头」不命中「配置集中」 ----

    def test_config_header_block_is_detected(self):
        report = self._scan(
            "cfg.py",
            'API_BASE = "https://api.example.com"\n'
            'APP_URL = "https://app.example.com"\n'
            'AID = "1234567890"\n'
            'TIMEOUT = 20\n'
            "\n\n\ndef main():\n    return API_BASE\n",
        )
        self.assertIn("config", self._ids(report))

    def test_single_constant_is_not_a_config_header(self):
        # 要求**连续两行**才认：单个常量到处都是，认它这个维度就没信息量了。
        report = self._scan("cfg2.py", 'MAX_RETRIES = 3\n\n\ndef main():\n    return MAX_RETRIES\n')
        self.assertNotIn("config", self._ids(report))

    # ---- 误判 3：打码占位符被当成「敏感信息脱敏」 ----

    def test_masked_literal_is_not_a_mask_routine(self):
        # 实测原形：`OCR_TOKEN = os.environ.get("OCR_TOKEN", "ocr_f315317b2ee2ec****")`
        # 那个 `****` 是**作者自己打码后的配置值**，脚本里连脱敏函数都没有。
        # 它曾被报成「敏感信息脱敏」并落进「直接复用」——四档里最不该出错的一档。
        report = self._scan(
            "mask1.py", 'TOKEN = os.environ.get("TOKEN", "ocr_f315317b2ee2ec****")\nprint(TOKEN)\n'
        )
        self.assertNotIn("mask", self._ids(report))

    def test_star_concatenation_is_a_mask_routine(self):
        # 真脱敏长这样：星号是**拼出来**的，不是夹在配置值中段的。
        report = self._scan(
            "mask2.py",
            'def mask_token(token):\n    return token[:4] + "****"\n',
        )
        self.assertIn("mask", self._ids(report))

    def test_star_times_len_is_a_mask_routine(self):
        report = self._scan(
            "mask3.py",
            'def hide(token):\n    return "*" * len(token)\n',
        )
        self.assertIn("mask", self._ids(report))

    # ---- 误判 4：凭据写成环境变量默认值，未被判为「硬编码凭据」 ----

    def test_credential_as_env_default_is_refused(self):
        report = self._scan(
            "secret1.py",
            'OCR_TOKEN = os.environ.get("OCR_TOKEN", "ocr_f315317b2ee2ec")\nprint(OCR_TOKEN)\n',
        )
        self.assertIn("hardcoded_secret", self._risk_ids(report))
        self.assertEqual(
            next(r for r in report["risks"] if r["id"] == "hardcoded_secret")["tier"], "refuse"
        )

    def test_env_default_secret_carries_no_snippet(self):
        report = self._scan(
            "secret2.py",
            'OCR_TOKEN = os.environ.get("OCR_TOKEN", "ocr_f315317b2ee2ec")\nprint(OCR_TOKEN)\n',
        )
        risk = next(r for r in report["risks"] if r["id"] == "hardcoded_secret")
        self.assertEqual(risk["snippet"], "")
        self.assertNotIn("ocr_f315317b2ee2ec", json.dumps(report, ensure_ascii=False))

    def test_benign_env_default_is_not_a_secret(self):
        # 两个条件同时要求才认：变量名像凭据 **且** 默认值非空够长。
        # 否则 `os.getenv("X", "0")` 这类会满天飞，风险表就没人看了。
        report = self._scan(
            "secret3.py",
            'ENABLED = os.getenv("APP_PROXY_ENABLE", "0")\n'
            'API_BASE = os.environ.get("API_BASE", "https://api.example.com")\n',
        )
        self.assertNotIn("hardcoded_secret", self._risk_ids(report))

    # ---- 误判 5：把会话凭据发给第三方，风险表完全没覆盖 ----

    def test_cookie_jar_egress_is_refused(self):
        # 实测原形（雨云脚本 L1812-1821）：cookie jar 被掏成 dict 后
        # `json={"cookies": ..., "token": ...}` POST 到别人的打码服务。
        # 这类写法比"硬编码凭据"更隐蔽：源码里看不到任何密钥，
        # 秘密是在**运行时**被送出去的。
        report = self._scan(
            "egress1.py",
            "jar = {c.name: c.value for c in sess.s.cookies}\n"
            'requests.post(url + "/solve", json={"cookies": jar, "token": t})\n',
        )
        self.assertIn("credential_egress", self._risk_ids(report))
        self.assertEqual(
            next(r for r in report["risks"] if r["id"] == "credential_egress")["tier"], "refuse"
        )

    def test_cookie_jar_comprehension_alone_is_refused(self):
        report = self._scan(
            "egress2.py",
            "jar = {c.name: c.value for c in self.sess.s.cookies}\nprint(jar)\n",
        )
        self.assertIn("credential_egress", self._risk_ids(report))

    def test_reading_a_cookie_is_not_egress(self):
        # 读单个 cookie 与"把整个 jar 序列化送出去"是两件事，不能一起报。
        report = self._scan(
            "egress3.py",
            'sess.cookies.set("rain-session", value, domain=".example.com")\n'
            'name = sess.cookies.get("dev-code")\nprint(name)\n',
        )
        self.assertNotIn("credential_egress", self._risk_ids(report))

    # ---- 误判 6：自建 `def log()` 不算「日志输出」 ----

    def test_hand_rolled_log_helper_is_detected(self):
        # 这类脚本跑在面板里，输出被面板捕获，所以它们不用 `logging` 模块，
        # 而是自己写一个 `def log(msg)`。只认标准库写法就会把它判成"没有日志"。
        report = self._scan(
            "log1.py",
            "import time\n\n\ndef log(msg):\n"
            '    print(f"[{time.strftime(\'%H:%M:%S\')}] {msg}")\n',
        )
        self.assertIn("logging", self._ids(report))

    def test_log_helper_must_be_a_definition_not_a_call(self):
        # `log("...")` 是调用，不是设施。认调用等于把"到处都在打日志"当成"有日志设施"。
        report = self._scan("log2.py", 'log("hello")\nlog("world")\n')
        self.assertNotIn("logging", self._ids(report))

    # ---- 误判 7（另一来源：本套件自扫 `har_probe.py`）----
    # 误判 1-6 来自雨云样本；这一条来自扫本套件自己的代码，是同一类偏差的另一半。

    def test_redact_is_a_mask_routine(self):
        # 实测原形：`har_probe.py:104` 的 `def redact(value: str)` 是货真价实的脱敏实现，
        # 但旧规则只认 `def mask*`，一个都不命中；命中的是第 599 行那句
        # `"输出已脱敏（--no-redact 可关闭）"`——**真证据漏了，提示语反被采信**。
        report = self._scan(
            "mask4.py",
            "def redact(value: str) -> str:\n"
            "    return value[:3] + '*' * 6\n"
            "\n\nprint(redact('secret'))\n",
        )
        self.assertIn("mask", self._ids(report))

    def test_message_mentioning_redaction_is_not_a_mask_routine(self):
        # 散文过滤管不到这里：`"输出已脱敏"` 是**字符串字面量**，不是注释，
        # 而字符串字面量按纪律不剔（`"User-Agent"` 就是实打实的协议证据）。
        # 所以只能把裸 `脱敏` 锚到定义位置上。
        report = self._scan("mask5.py", 'print("输出已脱敏（--no-redact 可关闭）")\n')
        self.assertNotIn("mask", self._ids(report))

    # ---- 误判 8-10（第二轮真用：本地样本目录 17 个文件，含一个 JS）----
    # 前面 1-6 来自单一样本，7 来自自扫；这一轮换成"一批真材料"，
    # 抓到的全是**在单一样本上碰不到**的形态——因为样本一多，误报才有机会出现。

    def test_masked_proxy_display_is_not_a_plaintext_credential(self):
        # 实测原形（顺丰周年庆 v1.3 / 顺丰端午 / 顺丰速运日常，三处全中）：
        #     display = f"http://***:***@{parts[-1]}"
        # 这是作者**主动打码后**才打印的，却被判成"代理凭据明文"落进 refuse 档——
        # 把「已经做了隔离」读成「没有隔离」，还是四档里最不该出错的一档。
        # 与 `"ocr_...****"` 是同一类：**星号是打码，不是泄漏**。
        report = self._scan(
            "proxy1.py",
            "def show(proxy):\n"
            "    if '@' in proxy:\n"
            "        parts = proxy.split('@')\n"
            "        display = f\"http://***:***@{parts[-1]}\"\n"
            "    print(display)\n",
        )
        self.assertNotIn("proxy_credential_in_url", self._risk_ids(report))

    def test_real_proxy_credential_in_url_is_still_refused(self):
        # 主机单独放一个变量：既贴近真实写法（URL 从配置拼出来），
        # 也让这个夹具里不出现**完整的邮箱形态**——`public_release_check`
        # 的邮箱规则会把 `user:pass@host.tld` 判成 PII，而它判得对。
        report = self._scan(
            "proxy2.py",
            'HOST = "proxy.example.com:8080"\n'
            'PROXY = f"http://user:p4ssw0rd@{HOST}"\n'
            "print(PROXY)\n",
        )
        self.assertIn("proxy_credential_in_url", self._risk_ids(report))

    def test_partially_masked_credential_is_still_refused(self):
        # 只排除「凭据段整段都是 `*` 与 `:`」这一**无歧义**形态。
        # `realuser:***@` 仍然要报——它毕竟把用户名拼进了 URL。
        report = self._scan(
            "proxy3.py",
            'PROXY = "http://realuser:***@proxy.example.com"\nprint(PROXY)\n',
        )
        self.assertIn("proxy_credential_in_url", self._risk_ids(report))

    def test_batch_size_is_not_batch_observability(self):
        # 实测原形（电信0点权益_极速版.py:495）：`batch_size = random.randint(2, 3)`
        # 是**并发批量大小**，与 PY-P8.7 要的"run 历史 / worker 状态 / 取消与清理"
        # 是两回事。裸 `batch` 在 17 个真样本里命中 1 次、**真命中 0 次**。
        report = self._scan(
            "batch1.py",
            "import random\n\n\nasync def go():\n"
            "    batch_size = random.randint(2, 3)\n    return batch_size\n",
        )
        self.assertNotIn("batch", self._ids(report))

    def test_batch_id_is_batch_observability(self):
        report = self._scan(
            "batch2.py",
            'batch_id = "run-1"\nprint(f"批次 {batch_id} 开始")\n',
        )
        self.assertIn("batch", self._ids(report))

    # ---- 误判 11-13：JS 侧正则写的是 Python 写法 ----
    #
    # 第三个来源：**本仓库自己的可读 JS**（`tools/automation-modules/过验证码/
    # 通用验证码模块/js/slider_captcha_manager.js`，116 行）。
    # 它是第一个跑得通 JS 侧规则的可读 JS 样本——前两轮真材料里唯一的 JS
    # 恰好是加密载荷，所以 JS 正则的覆盖度一直只是**推断**，这三条是第一次实测。
    # 夹具直接取自该文件的真实行（行号见各条注释）。

    def test_settimeout_is_pacing(self):
        # 原形第 22-24 行：`delay(ms) { return new Promise(resolve =>
        # setTimeout(resolve, ms)); }`；第 53 行 `await this.delay(this.retryDelayMs)`。
        # `time.sleep` 是 Python 的等待写法，JS 里一条都不命中。
        report = self._scan(
            "pacing.js",
            "class M {\n"
            "    delay(ms) {\n"
            "        return new Promise(resolve => setTimeout(resolve, ms));\n"
            "    }\n"
            "}\n",
        )
        self.assertIn("delay", self._ids(report))

    def test_bare_delay_word_is_not_pacing(self):
        # 裸词 `delay` 不算证据——只认调用形态 `delay(`。`DELAY = 5` 是配置值，
        # 与「节奏控制」不是一回事（同 `batch_size` 那条的判据）。
        report = self._scan("pacing2.py", "DELAY = 5\nprint(DELAY)\n")
        self.assertNotIn("delay", self._ids(report))

    def test_max_attempts_is_retry(self):
        # 原形第 9 行 `this.maxAttempts = config.maxAttempts || 50`
        # 与第 34 行 `for (let attempt = 1; attempt <= this.maxAttempts; attempt++)`。
        # 上面只认 `MAX_RETRIES|maxRetries`——"只认得一种命名"的老毛病。
        report = self._scan(
            "retry.js",
            "class M {\n"
            "    constructor(config = {}) {\n"
            "        this.maxAttempts = config.maxAttempts || 50;\n"
            "    }\n"
            "    async run(fn) {\n"
            "        for (let attempt = 1; attempt <= this.maxAttempts; attempt++) {\n"
            "            await fn();\n"
            "        }\n"
            "    }\n"
            "}\n",
        )
        self.assertIn("retry", self._ids(report))

    def test_snake_case_max_attempts_is_retry(self):
        report = self._scan("retry2.py", "max_attempts = 5\nfor i in range(max_attempts):\n    pass\n")
        self.assertIn("retry", self._ids(report))

    def test_colon_timeout_is_timeout(self):
        # 原形第 92-95 行：`axios.post(url, payload, { headers: {...},
        # timeout: 10000 })`。JS 把超时写在对象字面量里用**冒号**，
        # 而规则原本只认 Python 的 `timeout=`。
        report = self._scan(
            "timeout.js",
            "async function go(url, payload) {\n"
            "    return await axios.post(url, payload, {\n"
            "        headers: { 'Content-Type': 'application/json' },\n"
            "        timeout: 10000\n"
            "    });\n"
            "}\n",
        )
        self.assertIn("timeout", self._ids(report))

    def test_statement_colon_is_not_proxy_or_timeout(self):
        # 收紧 `[:=]` 时踩到的：`if '@' in proxy:` 的冒号是**语句结尾**，
        # `if timeout:` 同理——都不是配置项。判据是"冒号后面还有内容"，
        # 而且必须用 `[ \t]` 而不是 `\s`：**`\s` 会跨行**，把下一行当成
        # "冒号后面的内容"，等于没排除（第一版收紧就是这么写错的）。
        report = self._scan(
            "stmt.py",
            "def show(proxy, timeout):\n"
            "    if '@' in proxy:\n"
            "        return timeout\n"
            "    if timeout:\n"
            "        return 1\n"
            "    return 0\n",
        )
        self.assertNotIn("proxy", self._ids(report))
        self.assertNotIn("timeout", self._ids(report))
