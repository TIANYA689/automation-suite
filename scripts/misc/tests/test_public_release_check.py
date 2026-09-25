from __future__ import annotations

import re
import unittest
from pathlib import Path

from public_release_check import REQUIRED_FILES, find_private_config

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
