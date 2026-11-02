#!/usr/bin/env python3
"""仓库一致性测试：防止模板/示例副本漂移、技能元数据损坏。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").rstrip() + "\n"


class RepoConsistencyTest(unittest.TestCase):
    def test_template_and_example_rebuild_are_identical(self) -> None:
        """examples 里的 rebuild.tcl 是模板副本；曾经漂移过，这里加锁。"""
        tpl = ROOT / "templates" / "rebuild.tcl"
        ex = ROOT / "examples" / "zynq7020-min" / "vivado" / "rebuild.tcl"
        self.assertTrue(tpl.is_file())
        self.assertTrue(ex.is_file())
        self.assertEqual(normalized(tpl), normalized(ex),
                         "模板与示例的 rebuild.tcl 不一致：改模板后请重新复制到示例目录")

    def test_skill_frontmatter(self) -> None:
        text = normalized(ROOT / "SKILL.md")
        self.assertTrue(text.startswith("---\n"), "SKILL.md 必须以 YAML frontmatter 开头")
        end = text.find("\n---\n", 3)
        self.assertGreater(end, 0, "SKILL.md frontmatter 未闭合")
        meta = text[3:end]
        for key in ("name:", "description:", "license:"):
            self.assertIn(key, meta, f"SKILL.md frontmatter 缺 {key}")
        m = re.search(r"^name:\s*(\S+)", meta, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "vivado-as-code")

    def test_skill_en_frontmatter(self) -> None:
        en = ROOT / "SKILL.en.md"
        self.assertTrue(en.is_file(), "缺少英文 SKILL")
        text = normalized(en)
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: vivado-as-code", text)
        self.assertIn("license: MIT", text)

    def test_scripts_have_no_bom(self) -> None:
        """Python 脚本不能被写入 BOM（会让 shebang/首行解析出问题）。"""
        for p in (ROOT / "scripts").glob("*.py"):
            head = p.read_bytes()[:3]
            self.assertNotEqual(head, b"\xef\xbb\xbf", f"{p.name} 含 UTF-8 BOM")

    def test_mcp_server_exists_and_compiles(self) -> None:
        server = ROOT / "mcp" / "vivado_as_code_server.py"
        self.assertTrue(server.is_file(), "缺少 MCP server")
        import py_compile
        py_compile.compile(str(server), doraise=True)


if __name__ == "__main__":
    unittest.main()
