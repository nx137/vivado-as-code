#!/usr/bin/env python3
"""bd_diff.py —— Block Design 语义 diff（不是文本 diff）。

为什么需要它：
    write_bd_tcl 导出的 BD 脚本动辄 600~700 行，`git diff` 只能看出"某几行变了"，
    看不出"多了一个 IP、`NUM_MI` 从 1 变成 2、地址多了一个 0x41240000"。
    本工具把这些信息解析成结构化差异，用于 code review、PR 描述和 CI 门禁。

用法：
    python bd_diff.py a.tcl b.tcl
    python bd_diff.py a.tcl b.tcl --json
    python bd_diff.py a.tcl b.tcl --fail-on-change     # 有差异时退出码 5（CI 用）

退出码：
    0 = 比较完成（默认：有无差异都返回 0）
    5 = 有差异且指定了 --fail-on-change
    1 = 用法/文件错误

解析范围（best-effort，覆盖 write_bd_tcl 生成脚本的常见写法）：
    - create_bd_cell -type ip -vlnv <vlnv> <name>
    - create_bd_cell -type module -reference <ref> <name>
    - set_property -dict [list CONFIG.X {v} ...] $cell
    - connect_bd_intf_net / connect_bd_net
    - assign_bd_address -offset ... -range ... [get_bd_addr_segs <seg>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CELL_IP_RE = re.compile(r"create_bd_cell\s+-type\s+ip\s+-vlnv\s+(\S+)\s+(\S+?)\s*\]")
CELL_MOD_RE = re.compile(r"create_bd_cell\s+-type\s+module\s+-reference\s+(\S+)\s+(\S+?)\s*\]")
CONFIG_BLOCK_RE = re.compile(r"set_property\s+-dict\s+\[\s*list\s+(.*?)\]\s*(\$?[\w\.\-]+)", re.S)
CONFIG_ITEM_RE = re.compile(r"CONFIG\.([A-Za-z0-9_]+)\s+\{\s*([^{}]*?)\s*\}")
ADDR_RE = re.compile(
    r"assign_bd_address\s+-offset\s+(\S+)\s+-range\s+(\S+)[^\n]*?get_bd_addr_segs\s+([^\]\s]+)"
)
NET_RE = re.compile(r"connect_bd_intf_net\s+(.*?)(?=\n|$)")
PIN_RE = re.compile(r"get_bd_(?:intf_)?pins\s+([^\]]+)\]")
# write_bd_tcl 对 module_ref 生成的变量形式：
#   set block_cell_name <name>
#   if { [catch {set ... [create_bd_cell -type module -reference $block_name $block_cell_name] } ...
MOD_VAR_RE = re.compile(
    r"set\s+block_cell_name\s+(\S+)\s*\n\s*if\s*\{\s*\[catch\s*\{\s*set", re.S
)


def _clean(name: str) -> str:
    return name.strip().strip("$").strip("{}").strip("[]")


def load(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    # 展开 Tcl 续行，让每条语句落在一行里
    return raw.replace("\\\r\n", " ").replace("\\\n", " ")


def parse_bd(text: str) -> dict:
    cells: dict[str, dict] = {}
    for vlnv, name in CELL_IP_RE.findall(text):
        cells[_clean(name)] = {"kind": "ip", "vlnv": vlnv}
    for ref, name in CELL_MOD_RE.findall(text):
        name = _clean(name)
        # write_bd_tcl 对 module_ref 可能写变量名（$block_name/$block_cell_name），跳过
        if "$" in name or "]" in name or "[" in name or name == "":
            continue
        cells[name] = {"kind": "module", "vlnv": ref}
    # 变量形式的 module_ref：set block_cell_name <name> + create_bd_cell ... $block_cell_name
    for name in MOD_VAR_RE.findall(text):
        cells[name] = {"kind": "module", "vlnv": "(module_ref)"}

    configs: dict[str, dict[str, str]] = {}
    for block, cell in CONFIG_BLOCK_RE.findall(text):
        cell = _clean(cell)
        props = configs.setdefault(cell, {})
        for key, value in CONFIG_ITEM_RE.findall(block):
            props[key] = value.strip()

    addresses: dict[str, dict[str, str]] = {}
    for offset, rng, seg in ADDR_RE.findall(text):
        addresses[seg] = {"offset": offset, "range": rng}

    conns: set[str] = set()
    for stmt in NET_RE.findall(text):
        pins = [ _clean(p) for p in PIN_RE.findall(stmt) ]
        if len(pins) >= 2:
            conns.add(" <-> ".join(sorted(pins)))

    return {"cells": cells, "configs": configs, "addresses": addresses, "connections": conns}


def diff(parsed_a: dict, parsed_b: dict) -> dict:
    cells_a, cells_b = parsed_a["cells"], parsed_b["cells"]
    added = sorted(set(cells_b) - set(cells_a))
    removed = sorted(set(cells_a) - set(cells_b))

    vlnv_changed = []
    for name in sorted(set(cells_a) & set(cells_b)):
        if cells_a[name]["vlnv"] != cells_b[name]["vlnv"]:
            vlnv_changed.append({"cell": name, "old": cells_a[name]["vlnv"], "new": cells_b[name]["vlnv"]})

    config_changes = []
    cells_cfg_a, cells_cfg_b = parsed_a["configs"], parsed_b["configs"]
    for name in sorted(set(cells_cfg_a) | set(cells_cfg_b)):
        pa, pb = cells_cfg_a.get(name, {}), cells_cfg_b.get(name, {})
        for key in sorted(set(pa) | set(pb)):
            if pa.get(key) != pb.get(key):
                config_changes.append({"cell": name, "prop": key, "old": pa.get(key), "new": pb.get(key)})

    addr_a, addr_b = parsed_a["addresses"], parsed_b["addresses"]
    address_changes = []
    for seg in sorted(set(addr_a) | set(addr_b)):
        if addr_a.get(seg) != addr_b.get(seg):
            address_changes.append({"segment": seg, "old": addr_a.get(seg), "new": addr_b.get(seg)})

    conns_a, conns_b = parsed_a["connections"], parsed_b["connections"]
    return {
        "cells_added": added,
        "cells_removed": removed,
        "vlnv_changed": vlnv_changed,
        "config_changes": config_changes,
        "address_changes": address_changes,
        "connections_added": sorted(conns_b - conns_a),
        "connections_removed": sorted(conns_a - conns_b),
    }


def has_changes(result: dict) -> bool:
    return any(bool(v) for v in result.values())


def format_text(result: dict, max_detail: int = 20) -> str:
    if not has_changes(result):
        return "no semantic changes"

    lines = []

    def section(title: str, items: list, render) -> None:
        if not items:
            return
        lines.append(f"\n{title} ({len(items)}):")
        for item in items[:max_detail]:
            lines.append("  " + render(item))
        if len(items) > max_detail:
            lines.append(f"  ... {len(items) - max_detail} more")

    section("cells added", result["cells_added"], lambda x: f"+ {x}")
    section("cells removed", result["cells_removed"], lambda x: f"- {x}")
    section("vlnv changed", result["vlnv_changed"],
            lambda x: f"~ {x['cell']}: {x['old']} -> {x['new']}")
    section("config changed", result["config_changes"],
            lambda x: f"~ {x['cell']}.{x['prop']}: {x['old']} -> {x['new']}")
    section("address changed", result["address_changes"],
            lambda x: f"~ {x['segment']}: {x['old']} -> {x['new']}")
    section("connections added", result["connections_added"], lambda x: f"+ {x}")
    section("connections removed", result["connections_removed"], lambda x: f"- {x}")
    return "\n".join(lines)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description="Block Design semantic diff")
    p.add_argument("bd_a", help="旧 BD TCL")
    p.add_argument("bd_b", help="新 BD TCL")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--fail-on-change", action="store_true", help="有差异时退出码 5")
    p.add_argument("--max-detail", type=int, default=20, help="每类最多显示条数")
    args = p.parse_args()

    a, b = Path(args.bd_a), Path(args.bd_b)
    for f in (a, b):
        if not f.is_file():
            print(f"file not found: {f}", file=sys.stderr)
            return 1

    result = diff(parse_bd(load(a)), parse_bd(load(b)))
    changed = has_changes(result)

    if args.json:
        payload = dict(result)
        payload["has_changes"] = changed
        payload["bd_a"] = str(a)
        payload["bd_b"] = str(b)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"BD diff: {a} -> {b}")
        print(format_text(result, args.max_detail))

    if changed and args.fail_on_change:
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
