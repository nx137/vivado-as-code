#!/usr/bin/env python3
"""recipe 渲染器测试：列表、默认值、参数覆盖、占位符清理、文件保护。"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recipe  # noqa: E402

RECIPE = ROOT / "scripts" / "recipe.py"
EXPECTED = {"add_axi_gpio", "add_axi_uartlite", "add_axi_dma_hp", "set_fclk", "open_irq_f2p"}


class RecipeTest(unittest.TestCase):
    def test_all_recipes_discoverable(self) -> None:
        names = {p.name[: -len(".tcl.tmpl")] for p in (ROOT / "scripts" / "recipes").glob("*.tcl.tmpl")}
        self.assertEqual(names, EXPECTED)

    def test_render_defaults_has_no_placeholders(self) -> None:
        for name in EXPECTED:
            text = recipe.render(name, {})
            self.assertNotIn("@@", text, f"{name} 渲染后仍有占位符")
            self.assertIn("guards.tcl", text)
            self.assertIn("vac_finalize", text)

    def test_render_override(self) -> None:
        text = recipe.render("add_axi_gpio", {"name": "my_gpio", "width": "16", "addr": "0x41250000"})
        self.assertIn("xilinx.com:ip:axi_gpio:2.0 my_gpio", text)
        self.assertIn("CONFIG.C_GPIO_WIDTH", text)
        self.assertIn("{16}", text)
        self.assertIn("0x41250000", text)
        self.assertNotIn("axi_gpio_user", text)

    def test_set_fclk_renders_numeric(self) -> None:
        text = recipe.render("set_fclk", {"fclk": "200", "index": "1"})
        self.assertIn("CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ {200}", text)
        self.assertIn("double($_act) - 200", text)

    def test_unknown_param_rejected(self) -> None:
        with self.assertRaises(ValueError):
            recipe.render("add_axi_gpio", {"nope": "1"})

    def test_cli_list(self) -> None:
        proc = subprocess.run([sys.executable, str(RECIPE), "list"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in EXPECTED:
            self.assertIn(name, proc.stdout)

    def test_cli_render_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "patch.tcl"
            proc = subprocess.run(
                [sys.executable, str(RECIPE), "render", "add_axi_gpio", "-p", "name=gpio_x", "-o", str(out)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out.is_file())
            self.assertIn("gpio_x", out.read_text(encoding="utf-8"))
            # 不加 --force 不允许覆盖
            proc2 = subprocess.run(
                [sys.executable, str(RECIPE), "render", "add_axi_gpio", "-p", "name=gpio_y", "-o", str(out)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(proc2.returncode, 1)

    def test_cli_bad_param_format(self) -> None:
        proc = subprocess.run([sys.executable, str(RECIPE), "render", "set_fclk", "-p", "fclk"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 1)

    def test_cli_unknown_recipe(self) -> None:
        proc = subprocess.run([sys.executable, str(RECIPE), "render", "nope"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
