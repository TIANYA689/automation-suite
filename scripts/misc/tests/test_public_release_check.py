from __future__ import annotations

import atexit
import contextlib
import io
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import public_release_check  # noqa: E402
from public_release_check import (  # noqa: E402
    ID_CHECK_CODES,
    ID_WEIGHTS,
    MIN_SCANNED_FILES,
    REQUIRED_FILES,
    _git_listed_files,
    _is_synthetic_path,
    find_pii,
    find_private_config,
    iter_candidate_files,
)

ROOT = Path(__file__).resolve().parents[3]

# 模块共用一个沙箱：热路径里没有 rmtree（规则 36）。
_TMP_ROOT = Path(__file__).resolve().parents[3] / "tmp"
_TMP_ROOT.mkdir(exist_ok=True)
_SANDBOX = Path(tempfile.mkdtemp(dir=_TMP_ROOT, prefix="pubrel-test-"))
_COUNTER = itertools.count()


def _cleanup(target: Path) -> None:
    try:
        shutil.rmtree(target, ignore_errors=True)
    except SystemExit:
        pass


atexit.register(_cleanup, _SANDBOX)


def _valid_id(body17: str) -> str:
    """按 GB 11643 的 mod-11-2 算出校验位，拼一个**合法**身份证号。"""
    total = sum(int(c) * w for c, w in zip(body17, ID_WEIGHTS))
    return body17 + ID_CHECK_CODES[total % 11]


def _path_hits(text: str) -> list[tuple[str, str]]:
    """复刻 `main()` 的路径判据（含合成标记过滤）。"""
    hits = []
    for name, rx in public_release_check.PATH_PATTERNS:
        for match in rx.finditer(text):
            if not _is_synthetic_path(match.group(0)):
                hits.append((name, match.group(0)))
    return hits



class PrivateConfigDetectionTests(unittest.TestCase):
    def test_detects_hardcoded_python_secret(self) -> None:
        matches = find_private_config('api_' + 'key = "sk-live-a1b2c3d4"')
        self.assertEqual(len(matches), 1)

    def test_detects_hardcoded_json_secret(self) -> None:
        matches = find_private_config('{"pass' + 'word": "hunter2"}')
        self.assertEqual(len(matches), 1)

    def test_detects_non_placeholder_bearer_token(self) -> None:
        matches = find_private_config(
            "Author" + "ization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
        )
        self.assertEqual(len(matches), 1)

    def test_allows_documentation_placeholders(self) -> None:
        text = '\n'.join(
            [
                'api_key = "sk-xxx"',
                'PASSWORD = "API-密码"',
                '{"password": "pwd"}',
                'Author' + 'ization: Bearer <JWT>',
            ]
        )
        self.assertEqual(find_private_config(text), [])

    def test_allows_variable_forwarding(self) -> None:
        text = "api_key=config.api_key\npassword=password\npassword=None"
        self.assertEqual(find_private_config(text), [])

    def test_detects_private_key_material(self) -> None:
        matches = find_private_config("-----BEGIN PRIVATE " + "KEY-----")
        self.assertEqual(len(matches), 1)


class PiiEmailDetectionTests(unittest.TestCase):
    """邮箱规则的判据：**保留域 或 明确的非个人本地部分**，两条都不满足才报。

    为什么要两条并列：本仓库的邮箱模块就是在讲临时邮箱服务（`linshiyou.com`
    一类），只做域名白名单会把文档的正当内容全部报红，然后规则会被关掉。
    """

    def test_flags_a_person_like_address(self) -> None:
        # 字面量一律拼出来：本文件自己也在扫描范围内，写整串会被本规则抓住。
        # 这与本文件既有的 `'api_' + 'key = "sk-live-..."'` 是同一个手法。
        matches = find_pii("联系人：" + "zhang.san.1988@" + "gmail.com")
        self.assertEqual(len(matches), 1)

    def test_flags_a_digit_only_local_part(self) -> None:
        """实测抓包里的真实形态之一：纯数字 QQ 邮箱。用合成号，不用真号。"""
        self.assertEqual(len(find_pii("1234567890@" + "qq.com")), 1)

    def test_allows_reserved_domains(self) -> None:
        text = "\n".join(
            [
                "a@example.com",
                "user@example.org",
                "someone@example.net",
                "pass@auth.example.test",
                "root@host.invalid",
            ]
        )
        self.assertEqual(find_pii(text), [])

    def test_allows_declared_non_personal_local_parts(self) -> None:
        """服务域不是 PII，本地部分是 `demo` / `test123` 这类才不是。"""
        text = "\n".join(
            ["demo@gmail.com", "test123@linshiyou.com", "abc12345@chacuo.net"]
        )
        self.assertEqual(find_pii(text), [])

    def test_does_not_let_a_lookalike_domain_through(self) -> None:
        """`notexample.com` 以 `example.com` 结尾，但它不是保留域。

        用 `endswith("example.com")` 会把另一个域名一起放过——所以精确域名走相等。
        """
        self.assertEqual(len(find_pii("someone@" + "notexample.com")), 1)

    def test_substring_of_a_placeholder_word_is_not_enough(self) -> None:
        """本地部分**含** "test" 不等于本地部分**是** `test`。子串匹配会放过真人邮箱。"""
        self.assertEqual(len(find_pii("david1988test@" + "gmail.com")), 1)

    def test_its_own_sources_are_clean(self) -> None:
        """规则的第一批用户是它的作者。

        实测两次：① 规则先抓到 `public_release_check.py` 自己注释里抄的那个真实
        地址；② 又抓到本测试文件里当反例用的字面量。两次都是「作者顺手写下真值」。
        所以这一条盯的就是这两处——正例字面量必须拼出来，不能写整串。
        """
        for relative in (
            "scripts/misc/public_release_check.py",
            "scripts/misc/tests/test_public_release_check.py",
        ):
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(find_pii(source), [])

    def test_own_sources_have_no_path_hits(self) -> None:
        """F8 的同一句话：**新加的路径规则第一条命中的是它自己的定义行**。

        实测首版 5 条自命中：两条是 `/Users/` / `/home/` 的**字面量**（前向斜杠没法
        像反斜杠那样转义，得写成 `[U]sers` / `[h]ome`），三条是**注释里为了解释规则
        而照抄的路径**（规则 30 的原话：描述这些正则时不要照抄字面量）。
        这条判据把两边都钉住。
        """
        for relative in (
            "scripts/misc/public_release_check.py",
            "scripts/misc/tests/test_public_release_check.py",
        ):
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(_path_hits(source), [])


class PiiPhoneDetectionTests(unittest.TestCase):
    """F7：手机号规则。**必须带占位识别**——实测本仓 5 处命中全是占位号。

    正例字面量一律拼出来：本文件自己也在扫描范围内（同上面邮箱那组的手法）。
    """

    def test_flags_a_person_like_number(self) -> None:
        hits = find_pii("联系人 138" + "12345678 收")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][2], "pii_phone")

    def test_allows_documented_placeholder_numbers(self) -> None:
        text = "\n".join(["138" + "00000000", "138" + "00138000", "188" + "88888888"])
        self.assertEqual(find_pii(text), [])

    def test_allows_all_same_digits(self) -> None:
        self.assertEqual(find_pii("111" + "11111111"), [])

    def test_a_longer_digit_run_is_not_a_phone(self) -> None:
        """13 位数字串里嵌着 11 位手机号，那是个订单号，不是手机号。

        没有 `(?!\\d)` 的话这条会报——而误报比漏报更快让规则被关掉（规则 79）。
        """
        self.assertEqual(find_pii("138" + "12345678" + "00"), [])

    def test_embedded_in_prose_is_still_found(self) -> None:
        hits = find_pii("手机号：159" + "87654321，备用号 138" + "12345678")
        self.assertEqual(len(hits), 2)


class PiiIdNumberTests(unittest.TestCase):
    """F7：身份证规则。**校验位是这道闸**——编造的号通不过，真实泄漏的必然通过。"""

    def test_checksum_algorithm_matches_the_standard(self) -> None:
        """用一个公开的合法样例钉住算法本身（拼出来写，别让规则抓到本文件）。"""
        known = "110105" + "19491231" + "002" + "X"
        self.assertTrue(public_release_check._id_checksum_ok(known))
        self.assertTrue(public_release_check._looks_like_real_id(known))

    def test_flags_a_checksum_valid_id(self) -> None:
        number = _valid_id("110105" + "19900101" + "123")
        self.assertEqual(len(number), 18)
        hits = find_pii("证件号 " + number)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][2], "pii_id_number")

    def test_allows_a_made_up_id_that_fails_the_checksum(self) -> None:
        self.assertEqual(find_pii("110101" + "19900101" + "1234"), [])

    def test_boundary_rejects_a_19_digit_run(self) -> None:
        """两侧的 `(?!\\d)` 是承重的：19 位数字串里不该截出一个"身份证"。"""
        number = _valid_id("110105" + "19900101" + "123")
        self.assertEqual(find_pii("9" + number), [])

    def test_a_bad_checksum_never_reports(self) -> None:
        """穷举：把校验位换成别的字符，只有正确那一个能被认出来。

        这条防的是"校验位算错但恰好自洽"——如果算法写反了，这里会同时认出两个。
        """
        body = "110105" + "19900101" + "123"
        accepted = [c for c in "0123456789X" if public_release_check._id_checksum_ok(body + c)]
        self.assertEqual(len(accepted), 1, f"校验位判定不唯一：{accepted}")


class AbsolutePathDetectionTests(unittest.TestCase):
    """F8：绝对路径从 3 种形态扩到 6 种，并带**合成路径识别**。

    实测新增的通用盘符规则命中 10 处，**全部**在 `scripts/misc/tests/` 且都是合成值；
    `/Users/` `/home/` `/tmp/` 三种新形态命中 0 处（潜伏缺口，不是活缺陷）。
    """

    def test_flags_macos_home(self) -> None:
        hits = _path_hits("/Use" + "rs/zhangsan/code/x.py")
        self.assertEqual([name for name, _ in hits], ["macos_user_path"])

    def test_flags_linux_home(self) -> None:
        """小写 `home`。实测把 `h` 写成 `H`（`[H]ome`）这条规则一次都不命中。"""
        hits = _path_hits("/ho" + "me/lisi/work/x.py")
        self.assertEqual([name for name, _ in hits], ["linux_user_path"])

    def test_flags_a_bare_drive_letter(self) -> None:
        hits = _path_hits("E:" + "\\projects\\secret\\x.py")
        self.assertEqual([name for name, _ in hits], ["generic_drive_path"])

    def test_url_is_not_a_drive_path(self) -> None:
        """`(?<![\\w])` 是承重的：没有它，协议分隔符前那个字母加冒号会被当成盘符。"""
        self.assertEqual(_path_hits("https://example.com/a.md"), [])

    def test_synthetic_fixtures_are_exempt(self) -> None:
        text = "\n".join(
            [
                "C:" + "\\tools\\someone\\python.exe",
                "D:/work/example/tools/x",
                "C:/py.exe",
                "C:" + "\\it's\\python.exe",
                "C:" + "\\Users\\<name>\\x.py",
            ]
        )
        self.assertEqual(_path_hits(text), [])

    def test_a_real_user_name_is_not_excused_by_the_synthetic_rule(self) -> None:
        """判据落在**路径内容**上，不是"文件是不是测试"。

        所以测试目录里真抄进一条带真用户名的路径，照样会被 `windows_user_path` 抓住。
        """
        hits = _path_hits("C:" + "\\Users\\" + "zhangsan" + "\\x.py")
        self.assertIn("windows_user_path", [name for name, _ in hits])

    def test_specific_rule_wins_over_the_generic_one(self) -> None:
        """同一条命中只报一次，且报**具体**那条——重复报是把噪音当成覆盖。"""
        case = _SANDBOX / f"case-{next(_COUNTER)}"
        case.mkdir(parents=True, exist_ok=True)
        target = case / "leak.py"
        target.write_text(
            "ROOT = " + repr("D:" + "/Git" + "/automation-suite") + "\n", encoding="utf-8"
        )

        original = public_release_check.iter_candidate_files
        public_release_check.iter_candidate_files = lambda: [target]
        stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(stream):
                public_release_check.main()
        finally:
            public_release_check.iter_candidate_files = original

        issues = json.loads(stream.getvalue())["issues"]
        path_types = {name for name, _ in public_release_check.PATH_PATTERNS}
        kinds = [issue["type"] for issue in issues if issue["type"] in path_types]
        self.assertEqual(kinds, ["hardcoded_d_git"], f"应当是具体规则胜出：{kinds}")


class CandidateScopeTests(unittest.TestCase):
    """检查范围 = **会进公开仓库的那些**（交给 git 算），不是整个工作区。

    实测两处后果：① `tools/automation-modules/邮箱/22do_free_receiver/data/`
    里那份含真实 gmail 的本地派生物一直被当待检对象；② `IGNORE_DIRS_PREFIX`
    与 `.gitignore` 各维护一份必然分叉（`.trae/`、`CLAUDE.md`、`.workbuddy-ai/`
    都已进 `.gitignore`，而旧清单不知道它们）。
    """

    def setUp(self) -> None:
        if _git_listed_files() is None:
            self.skipTest("没有 git：范围退化为 is_ignored 兜底，另有用例覆盖")

    def candidates(self) -> set[str]:
        return {p.relative_to(ROOT).as_posix() for p in iter_candidate_files()}

    def test_local_artifacts_are_out_of_scope(self) -> None:
        candidates = self.candidates()
        for relative in (
            "tools/automation-modules/邮箱/22do_free_receiver/data/har_summary.json",
            ".workbuddy-ai/memory/MEMORY.md",
            "CLAUDE.md",
            "routing.index.json",
        ):
            with self.subTest(path=relative):
                if (ROOT / relative).exists():
                    self.assertNotIn(relative, candidates)

    def test_publishable_documents_are_in_scope(self) -> None:
        candidates = self.candidates()
        for relative in ("README.md", "docs/public-release.md", "projects/README.md"):
            with self.subTest(path=relative):
                self.assertIn(relative, candidates)


class LineEndingTests(unittest.TestCase):
    """仓库必须把行尾钉成 LF，否则全新 clone 会整棵变成 CRLF。

    实测：本机 `core.autocrlf=true`，仓库里没有 `.gitattributes`，一次
    `git clone` 之后 `git ls-files --eol` 得到 **`w/lf=0  w/crlf=240`** ——
    240 个已跟踪文本文件全部 CRLF，`test_committed_findings_use_lf_endings`
    立刻失败。GitHub Actions 的 `windows-latest` 镜像同样是 `core.autocrlf=true`，
    所以这是 CI 上必然发生的失败，不是本机设置问题。

    仓库里的 blob 本来就是 LF，所以加 `.gitattributes` 不需要重写任何内容。
    """

    def test_gitattributes_exists_and_pins_lf(self) -> None:
        path = ROOT / ".gitattributes"
        self.assertTrue(path.is_file(), "缺 .gitattributes——全新 clone 会变成 CRLF")
        rules = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(
            any(rule.startswith("*") and "eol=lf" in rule for rule in rules),
            ".gitattributes 里必须有一条覆盖 `*` 的 `eol=lf` 规则",
        )

    def test_no_tracked_file_is_checked_out_as_crlf(self) -> None:
        if _git_listed_files() is None:
            self.skipTest("没有 git，无法问行尾")
        completed = subprocess.run(
            ["git", "ls-files", "--eol"], cwd=ROOT, capture_output=True, check=True
        )
        offenders = [
            line.split("\t")[-1]
            for line in completed.stdout.decode("utf-8", "replace").splitlines()
            if "w/crlf" in line
        ]
        self.assertEqual(
            offenders[:10],
            [],
            "这些文件是 CRLF 检出；确认 .gitattributes 已提交后重做一次 checkout"
            "（`git rm --cached -r . && git reset --hard`）",
        )


class RequiredFilesDriftTests(unittest.TestCase):
    """`docs/public-release.md` 的清单与脚本里的 REQUIRED_FILES 必须一致。

    两处分叉过一次：脚本要求 `SECURITY.md` 而文档同步滞后，结果 README 出现死链。
    """

    def _documented_required_files(self) -> list[str]:
        document = (ROOT / "docs" / "public-release.md").read_text(encoding="utf-8")
        section = document.split("## Required Files", 1)[1].split("##", 1)[0]
        return re.findall(r"^- `([^`]+)`$", section, flags=re.MULTILINE)

    def test_document_matches_script(self) -> None:
        documented = self._documented_required_files()
        self.assertTrue(documented, "文档里应至少列出一个必选文件")
        self.assertEqual(
            sorted(documented),
            sorted(REQUIRED_FILES),
            "docs/public-release.md 与 public_release_check.REQUIRED_FILES 已分叉",
        )

    def test_no_duplicates(self) -> None:
        self.assertEqual(len(REQUIRED_FILES), len(set(REQUIRED_FILES)))


class ScanFloorTests(unittest.TestCase):
    """F10：扫描面塌了要报红，而不是报 ok。

    修复前 "只扫到 1 个文件" 与 "扫到 222 个文件" 都报 `ok: true`——
    前者意味着这条检查**其实什么都没看**，而退出码上看不出区别。
    """

    def _run_with(self, files: list[Path]) -> tuple[int, dict]:
        original = public_release_check.iter_candidate_files
        public_release_check.iter_candidate_files = lambda: list(files)
        stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(stream):
                code = public_release_check.main()
        finally:
            public_release_check.iter_candidate_files = original
        return code, json.loads(stream.getvalue())

    def test_tiny_scan_is_a_failure_not_a_pass(self) -> None:
        code, report = self._run_with([Path(__file__)])
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertIn("scan_too_small", {issue["type"] for issue in report["issues"]})

    def test_report_declares_the_floor(self) -> None:
        """下限必须**报出来**，否则它是魔法数字，读日志的人不知道判据是什么。"""
        _, report = self._run_with([Path(__file__)])
        self.assertEqual(report["scan_floor"], MIN_SCANNED_FILES)

    def test_just_below_the_floor_fails_and_just_above_passes(self) -> None:
        """边界两侧都要钉住，否则守卫可能只是恒真/恒假。"""
        below = [Path(__file__)] * (MIN_SCANNED_FILES - 1)
        at = [Path(__file__)] * MIN_SCANNED_FILES
        self.assertEqual(self._run_with(below)[0], 1)
        self.assertEqual(self._run_with(at)[0], 0)

    def test_real_repository_clears_the_floor(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = public_release_check.main()
        report = json.loads(stream.getvalue())
        self.assertEqual(code, 0, report["issues"])
        self.assertGreaterEqual(report["scanned_files"], MIN_SCANNED_FILES)


    def test_self_detection_exemption_is_pinned_to_the_detector(self) -> None:
        """豁免表只允许「检测器 + 它的测试」，且只允许检测器必然要写出的那几类。

        要扩表就得同时改这条用例——改不动，就说明这次豁免需要单独论证。
        """
        self.assertEqual(
            set(public_release_check.SELF_DETECTION_EXEMPT),
            {
                "scripts/misc/check_history_leaks.py",
                "scripts/misc/tests/test_check_history_leaks.py",
            },
        )
        # 与检测逻辑无关的类型不在这张表里：往这两个文件里塞真人手机号或身份证号照样报。
        self.assertNotIn("pii_phone", public_release_check.SELF_DETECTION_KINDS)
        self.assertNotIn("pii_id_number", public_release_check.SELF_DETECTION_KINDS)
        # 豁免不蔓延到别的测试文件。
        self.assertFalse(
            public_release_check._is_self_detection(
                "scripts/misc/tests/test_public_release_check.py", "pii_email"
            )
        )


if __name__ == "__main__":
    unittest.main()
