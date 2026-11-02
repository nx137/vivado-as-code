#!/usr/bin/env python3
"""MCP server 协议测试：initialize / tools/list / tools/call / 错误处理。

不依赖任何第三方 MCP SDK：直接以子进程方式跑 server，按 MCP 2024-11-05 的
换行分隔 JSON-RPC 收发消息。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "vivado_as_code_server.py"
FIX = Path(__file__).parent / "fixtures"


def run_session(messages: list[dict]) -> tuple[list[dict], str]:
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    payload = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
    out, err = proc.communicate(payload, timeout=180)
    responses = [json.loads(line) for line in out.splitlines() if line.strip()]
    return responses, err


class McpProtocolTest(unittest.TestCase):
    def test_full_session(self) -> None:
        responses, err = run_session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "vac_bd_diff",
                        "arguments": {"bd_a": str(FIX / "bd_before.tcl"),
                                      "bd_b": str(FIX / "bd_after.tcl")}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "no_such_tool", "arguments": {}}},
        ])
        # 4 个带 id 的请求 => 4 个响应（notifications 不响应）
        self.assertEqual(len(responses), 5, err)
        by_id = {r.get("id"): r for r in responses}

        init = by_id[1]["result"]
        self.assertEqual(init["protocolVersion"], "2024-11-05")
        self.assertEqual(init["serverInfo"]["name"], "vivado-as-code")
        self.assertIn("tools", init["capabilities"])

        tools = by_id[2]["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertEqual(names, {
            "vac_build", "vac_check_log", "vac_bd_diff",
            "vac_bd_export", "vac_check_handoff", "vac_recipe_render",
        })
        for tool in tools:
            self.assertIn("description", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

        self.assertEqual(by_id[3]["result"], {})

        diff_payload = json.loads(by_id[4]["result"]["content"][0]["text"])
        self.assertTrue(diff_payload["has_changes"])
        self.assertEqual(diff_payload["cells_added"], ["axi_gpio_user"])

        bad = by_id[5]
        self.assertIn("error", bad)
        self.assertEqual(bad["error"]["code"], -32602)

    def test_unknown_method(self) -> None:
        responses, err = run_session([
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        ])
        self.assertEqual(responses[0]["error"]["code"], -32601, err)

    def test_parse_error(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        out, err = proc.communicate("not-json\n", timeout=60)
        responses = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertTrue(responses)
        self.assertEqual(responses[0]["error"]["code"], -32700, err)

    def test_tool_error_returns_is_error(self) -> None:
        responses, err = run_session([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "vac_check_log", "arguments": {"log_path": "no-such.log"}}},
        ])
        result = responses[0]["result"]
        self.assertTrue(result["isError"], err)

    def test_self_test_flag(self) -> None:
        proc = subprocess.run([sys.executable, str(SERVER), "--self-test"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tools=6", proc.stderr)


if __name__ == "__main__":
    unittest.main()
