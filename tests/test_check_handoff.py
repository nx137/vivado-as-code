#!/usr/bin/env python3
"""check_handoff 单元测试：BD ↔ .hwh ↔ .bit 一致性。"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check_handoff.py"

BD_TEXT = """\
set processing_system7_0 [ create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0 ]
set axi_dma_0 [ create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0 ]
set custom_rtl [ create_bd_cell -type module -reference my_module custom_rtl ]
"""


def hwh_text(modules: list[str]) -> str:
    entries = "\n".join(
        f'<MODULE COREREVISION="23" FULLNAME="/{m}" HWVERSION="1.0" INSTANCE="{m}">\n</MODULE>'
        for m in modules
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<EDKSYSTEM>\n<MODULES>\n{entries}\n</MODULES>\n</EDKSYSTEM>\n'


class CheckHandoffTest(unittest.TestCase):
    def run_check(self, bd: str, hwh: str, bit: Path | None = None) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            bd_path = td_path / "design_1.tcl"
            hwh_path = td_path / "design_1_wrapper.hwh"
            bd_path.write_text(bd, encoding="utf-8")
            hwh_path.write_text(hwh, encoding="utf-8")
            args = [sys.executable, str(CHECK), "--bd", str(bd_path), "--hwh", str(hwh_path)]
            if bit is not None:
                args += ["--bit", str(bit)]
            return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_pass_when_consistent(self) -> None:
        proc = self.run_check(BD_TEXT, hwh_text(["processing_system7_0", "axi_dma_0"]))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("RESULT: PASS", proc.stdout)

    def test_module_ref_is_ignored(self) -> None:
        # custom_rtl 是 module_ref，不出现在 .hwh 的 MODULE 列表里，不应判失败
        proc = self.run_check(BD_TEXT, hwh_text(["processing_system7_0", "axi_dma_0"]))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("custom_rtl", proc.stdout)

    def test_stale_hwh_fails(self) -> None:
        proc = self.run_check(BD_TEXT, hwh_text(["processing_system7_0"]))
        self.assertEqual(proc.returncode, 4)
        self.assertIn("axi_dma_0", proc.stdout)

    def test_extra_module_in_hwh_fails(self) -> None:
        proc = self.run_check(BD_TEXT, hwh_text(["processing_system7_0", "axi_dma_0", "old_ip"]))
        self.assertEqual(proc.returncode, 4)
        self.assertIn("old_ip", proc.stdout)

    def test_bit_basename_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bit = Path(td) / "wrong_name.bit"
            bit.write_bytes(b"\x00")
            proc = self.run_check(BD_TEXT, hwh_text(["processing_system7_0", "axi_dma_0"]), bit)
        self.assertEqual(proc.returncode, 4)
        self.assertIn("names differ", proc.stdout)

    def test_missing_file(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CHECK), "--bd", "nope.tcl", "--hwh", "nope.hwh"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
