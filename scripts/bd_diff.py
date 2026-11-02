#!/usr/bin/env python3
"""bd_diff.py —— Block Design 语义 diff（不是文本 diff）。

为什么需要它：
    write_bd_tcl 导出的 BD 脚本动辄 600~700 行，`git diff` 只能看出"某几行变了"，
    看不出"多了一个 IP、`NUM_MI` 从 1 变成 2、地址多了一个 0x41240000"。
    本工具把这些信息解析成结构化差异，用于 code review、PR 描述和 CI 门禁。

解析逻辑在 scripts/lib/bd_parse.py（与 check_handoff.py 共用，避免两处漂移）。

用法：
    python bd_diff.py a.tcl b.tcl
    python bd_diff.py a.tcl b.tcl --json
    python bd_diff.py a.tcl b.tcl --fail-on-change     # 有差异时退出码 5（CI 用）

退出码：
    0 = 比较完成（默认：有无差异都返回 0）
    5 = 有差异且指定了 --fail-on-change
    1 = 用法/文件错误
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from bd_parse import load, parse_bd  # noqa: E402  （重新导出给测试用）


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
