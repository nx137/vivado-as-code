#!/usr/bin/env python3
"""check_build 单元测试：日志门禁的计数、白名单、时序与退出码。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check_build.py"


def run_check(lines: list[str], *extra: str, manifest: dict | None = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "build.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        args = [sys.executable, str(CHECK), str(log), *extra]
        if manifest is not None:
            mf = Path(td) / "build_manifest.json"
            mf.write_text(json.dumps(manifest), encoding="utf-8")
            args += ["--manifest", str(mf)]
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")


class CheckBuildTest(unittest.TestCase):
    def test_clean_log_passes(self) -> None:
        proc = run_check([
            "INFO: [Common 17-206] Starting",
            "WARNING: [BD 41-2384] Width mismatch (benign)",
            "INFO: done",
        ])
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("RESULT: PASS", proc.stdout)

    def test_critical_warning_fails(self) -> None:
        proc = run_check([
            "CRITICAL WARNING: [BD 41-759] input pins are not connected",
        ])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("CRITICAL WARNING : 1", proc.stdout)

    def test_error_fails(self) -> None:
        proc = run_check(["ERROR: [BD 41-701] connect_bd_net requires at least two pins"])
        self.assertEqual(proc.returncode, 2)

    def test_allow_whitelist(self) -> None:
        proc = run_check(
            ["CRITICAL WARNING: [Labtools 27-2269] harmless"],
            "--allow", r"\[Labtools",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_timing_violation_exits_3(self) -> None:
        proc = run_check(
            ["INFO: done"],
            manifest={"status": "ok", "wns": "-0.123"},
        )
        self.assertEqual(proc.returncode, 3)
        self.assertIn("WNS", proc.stdout)

    def test_timing_met_passes(self) -> None:
        proc = run_check(["INFO: done"], manifest={"status": "ok", "wns": "1.932"})
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_json_output(self) -> None:
        proc = run_check(["CRITICAL WARNING: x"], "--json")
        self.assertEqual(proc.returncode, 2)
        data = json.loads(proc.stdout)
        self.assertEqual(data["critical_warnings"], 1)
        self.assertEqual(data["exit_code"], 2)

    def test_missing_log(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CHECK), "no-such-file.log"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 1)

    def test_explain_hints(self) -> None:
        proc = run_check(["CRITICAL WARNING: [BD 41-759] unconnected input pins"], "--explain")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BD-41-759", proc.stdout)
        self.assertIn("references/pitfalls.md B3", proc.stdout)

    def test_json_suggestions(self) -> None:
        proc = run_check(["ERROR: [BD 41-758] clock pins are not connected"], "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["suggestions"][0]["id"], "BD-41-758")

    def test_timing_suggestion(self) -> None:
        proc = run_check(["INFO: done"], "--json", manifest={"status": "ok", "wns": "-0.2"})
        data = json.loads(proc.stdout)
        self.assertTrue(any(s["id"] == "TIMING-WNS" for s in data["suggestions"]))

    def test_no_hints_on_clean_log(self) -> None:
        proc = run_check(["INFO: done"], "--json")
        data = json.loads(proc.stdout)
        self.assertEqual(data["suggestions"], [])


if __name__ == "__main__":
    unittest.main()
