#!/usr/bin/env python3
"""bd_diff 单元测试（标准库 unittest；pytest 也能收集）。"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bd_diff  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
BEFORE = FIX / "bd_before.tcl"
AFTER = FIX / "bd_after.tcl"


class BdDiffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.a = bd_diff.parse_bd(bd_diff.load(BEFORE))
        self.b = bd_diff.parse_bd(bd_diff.load(AFTER))
        self.result = bd_diff.diff(self.a, self.b)

    def test_parse_cells(self) -> None:
        self.assertIn("axi_dma_0", self.a["cells"])
        self.assertEqual(self.a["cells"]["axi_dma_0"]["kind"], "ip")
        self.assertNotIn("axi_gpio_user", self.a["cells"])
        self.assertIn("axi_gpio_user", self.b["cells"])

    def test_parse_configs(self) -> None:
        self.assertEqual(self.a["configs"]["ps7_0_axi_periph"]["NUM_MI"], "1")
        self.assertEqual(self.b["configs"]["ps7_0_axi_periph"]["NUM_MI"], "2")

    def test_cells_added(self) -> None:
        self.assertEqual(self.result["cells_added"], ["axi_gpio_user"])
        self.assertEqual(self.result["cells_removed"], [])

    def test_config_change(self) -> None:
        changes = {(c["cell"], c["prop"]): (c["old"], c["new"]) for c in self.result["config_changes"]}
        self.assertEqual(changes[("ps7_0_axi_periph", "NUM_MI")], ("1", "2"))
        self.assertIn(("axi_gpio_user", "C_GPIO_WIDTH"), changes)

    def test_address_change(self) -> None:
        segs = {c["segment"]: c for c in self.result["address_changes"]}
        self.assertIn("axi_gpio_user/S_AXI/Reg", segs)
        self.assertEqual(segs["axi_gpio_user/S_AXI/Reg"]["new"]["offset"], "0x41240000")

    def test_connection_change(self) -> None:
        self.assertTrue(self.result["connections_added"])
        self.assertIn("axi_gpio_user/S_AXI", " ".join(self.result["connections_added"]))

    def test_no_change(self) -> None:
        same = bd_diff.diff(self.a, self.a)
        self.assertFalse(bd_diff.has_changes(same))
        self.assertIn("no semantic changes", bd_diff.format_text(same))

    def test_cli_json(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bd_diff.py"), str(BEFORE), str(AFTER), "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["has_changes"])
        self.assertEqual(data["cells_added"], ["axi_gpio_user"])

    def test_cli_fail_on_change(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bd_diff.py"), str(BEFORE), str(AFTER), "--fail-on-change"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 5)

    def test_cli_no_change_exit_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bd_diff.py"), str(BEFORE), str(BEFORE)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no semantic changes", proc.stdout)

    def test_missing_file(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bd_diff.py"), str(FIX / "nope.tcl"), str(AFTER)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
