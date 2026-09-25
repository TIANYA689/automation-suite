from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from public_release_check import (
    REQUIRED_FILES,
    _git_listed_files,
    find_pii,
    find_private_config,
    iter_candidate_files,
)

ROOT = Path(__file__).resolve().parents[3]


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


if __name__ == "__main__":
    unittest.main()
