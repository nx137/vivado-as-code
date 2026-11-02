#!/usr/bin/env python3
"""check_handoff.py —— 检查 BD 真源与交付产物是否一致。

解决两个真实问题：
    1. 提交进仓库的 .hwh 与当前 BD 的 IP 集不一致（例如 BD 新增了 IP，.hwh 还是旧的）；
    2. .bit / .hwh 必须**同名同目录**，PYNQ 的 Overlay() 才能解析出 ip_dict。

用法：
    python check_handoff.py --bd tcl/design_1.tcl --hwh outputs/design_1_wrapper.hwh
    python check_handoff.py --bd tcl/design_1.tcl --hwh x.hwh --bit x.bit

退出码：
    0 = 一致
    4 = 不一致（IP 集差异 / 文件不同名）
    1 = 用法错误或文件不存在

说明：为跨平台稳定，命令行输出使用英文。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from bd_parse import load as load_bd, parse_bd, ip_cells, module_cells  # noqa: E402

# .hwh: <MODULE COREREVISION="23" FULLNAME="/axi_dma_0" ...>（属性顺序不固定）
HWH_MOD_RE = re.compile(r'<MODULE\b[^>]*?\bFULLNAME="/([^"]+)"')


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BD vs .hwh vs .bit consistency check")
    p.add_argument("--bd", required=True, help="BD TCL path")
    p.add_argument("--hwh", required=True, help=".hwh path")
    p.add_argument("--bit", help="optional .bit path (basename pairing check)")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    bd = Path(args.bd)
    hwh = Path(args.hwh)
    for f in (bd, hwh):
        if not f.is_file():
            print(f"file not found: {f}", file=sys.stderr)
            return 1

    bd_text = load_bd(bd)
    hwh_text = hwh.read_text(encoding="utf-8", errors="replace")

    # 解析逻辑与 bd_diff.py 共用 scripts/lib/bd_parse.py
    parsed = parse_bd(bd_text)
    bd_ips = set(ip_cells(parsed))
    bd_mods = set(module_cells(parsed))
    hwh_ips = set(HWH_MOD_RE.findall(hwh_text))

    only_bd = sorted(bd_ips - hwh_ips)
    only_hwh = sorted(hwh_ips - bd_ips - bd_mods)

    problems: list[str] = []
    if only_bd:
        problems.append("in BD but not in .hwh (stale .hwh): " + ", ".join(only_bd))
    if only_hwh:
        problems.append("in .hwh but not in BD (from another version): " + ", ".join(only_hwh))

    if args.bit:
        bit = Path(args.bit)
        if not bit.is_file():
            problems.append(f".bit not found: {bit}")
        elif bit.stem != hwh.stem:
            problems.append(f".bit/.hwh names differ: {bit.name} vs {hwh.name} "
                            "(PYNQ requires same basename in the same directory)")

    report = {
        "bd": str(bd),
        "hwh": str(hwh),
        "bd_ip_count": len(bd_ips),
        "hwh_module_count": len(hwh_ips),
        "bd_module_ref_count": len(bd_mods),
        "only_in_bd": only_bd,
        "only_in_hwh": only_hwh,
        "status": "pass" if not problems else "fail",
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not problems else 4

    print(f"BD   : {bd}  ({len(bd_ips)} IP cells, {len(bd_mods)} RTL module_ref)")
    print(f".hwh : {hwh}  ({len(hwh_ips)} MODULE entries)")
    if bd_mods:
        print("  note: RTL module_ref cells (" + ", ".join(sorted(bd_mods)) + ") are matched from "
              "variable-style declarations and also appear in .hwh.")
    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        print("\nfix: rebuild (BD or full) and replace the stale .hwh; "
              "never mix artifacts produced by different builds.")
        return 4
    print("\nRESULT: PASS (BD / .hwh / .bit consistent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
