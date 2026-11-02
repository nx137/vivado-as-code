#!/usr/bin/env python3
"""ps7_config 单元测试：YAML 子集解析、schema 校验、Tcl 生成、CLI。"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ps7_config  # noqa: E402

CLI = ROOT / "scripts" / "ps7_config.py"


class YamlParseTest(unittest.TestCase):
    def test_nested_and_inline(self) -> None:
        cfg = ps7_config.parse_yaml(
            "# comment\n"
            "clocks:\n"
            "  fclk0: 100\n"
            "  fclk1: 200.5\n"
            "hp_ports: [0, 1]\n"
            "mio:\n"
            "  uart1: {enable: true, io: \"MIO 48 .. 49\"}\n"
            "irq_f2p: false\n"
        )
        self.assertEqual(cfg["clocks"], {"fclk0": 100, "fclk1": 200.5})
        self.assertEqual(cfg["hp_ports"], [0, 1])
        self.assertEqual(cfg["mio"]["uart1"]["io"], "MIO 48 .. 49")
        self.assertIs(cfg["irq_f2p"], False)

    def test_tab_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ps7_config.parse_yaml("clocks:\n\tfclk0: 100\n")

    def test_not_key_value(self) -> None:
        with self.assertRaises(ValueError):
            ps7_config.parse_yaml("just-a-string\n")


class ValidateTest(unittest.TestCase):
    def test_valid_minimal(self) -> None:
        self.assertEqual(ps7_config.validate({"clocks": {"fclk0": 100}}), [])

    def test_unknown_top_key(self) -> None:
        errs = ps7_config.validate({"clock": {"fclk0": 100}})
        self.assertTrue(any("未知顶层键" in e for e in errs), errs)

    def test_clock_out_of_range(self) -> None:
        self.assertTrue(ps7_config.validate({"clocks": {"fclk0": 400}}))
        self.assertEqual(ps7_config.validate({"clocks": {"fclk0": 0}}), [])

    def test_bad_hp_ports(self) -> None:
        self.assertTrue(ps7_config.validate({"hp_ports": [5]}))
        self.assertTrue(ps7_config.validate({"hp_ports": [0, 0]}))

    def test_bad_mio(self) -> None:
        self.assertTrue(ps7_config.validate({"mio": {"nope": {"enable": True}}}))
        self.assertTrue(ps7_config.validate({"mio": {"uart1": {"io": "48"}}}))

    def test_bad_ddr(self) -> None:
        self.assertTrue(ps7_config.validate({"ddr": {"size_gb": 3}}))

    def test_extra_props_prefix(self) -> None:
        self.assertTrue(ps7_config.validate({"extra_props": {"USE_X": 1}}))
        self.assertEqual(ps7_config.validate({"extra_props": {"PCW_USE_M_AXI_GP0": 1}}), [])


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = ps7_config.parse_yaml(ps7_config.EXAMPLE)
        self.tcl = ps7_config.render_tcl(self.cfg, "ps7.yaml")

    def test_has_guard(self) -> None:
        self.assertIn("processing_system7_0", self.tcl)
        self.assertIn("exit 1", self.tcl)

    def test_clocks(self) -> None:
        self.assertIn("CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}", self.tcl)
        self.assertIn("CONFIG.PCW_FPGA_FCLK0_ENABLE {1}", self.tcl)
        # fclk2 写 0 -> 关闭
        self.assertIn("CONFIG.PCW_FPGA_FCLK2_ENABLE {0}", self.tcl)
        self.assertNotIn("CONFIG.PCW_FPGA2_PERIPHERAL_FREQMHZ", self.tcl)

    def test_hp_irq(self) -> None:
        self.assertIn("CONFIG.PCW_USE_S_AXI_HP0 {1}", self.tcl)
        self.assertIn("CONFIG.PCW_USE_S_AXI_HP1 {1}", self.tcl)
        self.assertIn("CONFIG.PCW_USE_S_AXI_HP2 {0}", self.tcl)
        self.assertIn("CONFIG.PCW_IRQ_F2P_INTR {1}", self.tcl)

    def test_mio(self) -> None:
        self.assertIn("CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1}", self.tcl)
        self.assertIn('CONFIG.PCW_UART1_UART1_IO {MIO 48 .. 49}', self.tcl)
        self.assertIn("CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {1}", self.tcl)
        self.assertIn("CONFIG.PCW_USB0_PERIPHERAL_ENABLE {0}", self.tcl)

    def test_ddr(self) -> None:
        self.assertIn("CONFIG.PCW_DDR_RAM_HIGHADDR {0x3FFFFFFF}", self.tcl)

    def test_extra_props(self) -> None:
        self.assertIn("CONFIG.PCW_USE_M_AXI_GP0 {1}", self.tcl)

    def test_generated_tcl_scope_and_expr(self) -> None:
        """proc 里访问全局 _ps 必须声明 global；表达式里必须用 $expect。"""
        self.assertIn("global _ps", self.tcl)
        self.assertIn("double($expect)", self.tcl)

    def test_readback_assertions(self) -> None:
        self.assertIn("_ps7_check_freq 0 100", self.tcl)
        self.assertIn("PCW_ACT_FPGA${idx}_PERIPHERAL_FREQMHZ", self.tcl)
        self.assertIn("abs(double($_act)", self.tcl)


class CliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(__import__("os").environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, str(CLI), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env)

    def test_example(self) -> None:
        proc = self.run_cli("example")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("clocks:", proc.stdout)
        self.assertIn("hp_ports:", proc.stdout)

    def test_check_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "ps7.yaml"
            f.write_text(ps7_config.EXAMPLE, encoding="utf-8")
            proc = self.run_cli("check", str(f))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_check_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "bad.yaml"
            f.write_text("clocks:\n  fclk0: 999\n", encoding="utf-8")
            proc = self.run_cli("check", str(f))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("配置非法", proc.stderr)

    def test_render_to_file_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            yml = Path(td) / "ps7.yaml"
            yml.write_text(ps7_config.EXAMPLE, encoding="utf-8")
            out = Path(td) / "post_bd_ps7.tcl"
            proc = self.run_cli("render", str(yml), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("PCW_FPGA0_PERIPHERAL_FREQMHZ", out.read_text(encoding="utf-8"))
            proc2 = self.run_cli("render", str(yml), "--out", str(out))
            self.assertEqual(proc2.returncode, 1)

    def test_render_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            yml = Path(td) / "ps7.yaml"
            yml.write_text("clocks:\n  fclk0: 150\n", encoding="utf-8")
            proc = self.run_cli("render", str(yml))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150}", proc.stdout)

    def test_missing_file(self) -> None:
        proc = self.run_cli("check", "no-such.yaml")
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
