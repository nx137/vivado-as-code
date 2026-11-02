#!/usr/bin/env python3
"""check_build.py —— Vivado 构建日志门禁 + 时序检查。

为什么需要它：
    Vivado 里 **参数名写错通常只报 CRITICAL WARNING，不报 ERROR**，
    综合/实现甚至能跑完并产出 bit，但硬件行为是错的。
    因此"构建成功"不能只看退出码，必须扫日志。

用法：
    python check_build.py build.log
    python check_build.py build.log --manifest outputs/build_manifest.json
    python check_build.py build.log --allow "^CRITICAL WARNING: \\[Labtools"

退出码：
    0 = 通过
    2 = 日志里有 ERROR 或 CRITICAL WARNING
    3 = 时序未收敛（manifest 里 WNS < 0）
    1 = 用法错误 / 文件不存在

说明：为跨平台稳定，命令行输出使用英文（Windows 控制台编码差异过大）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ERROR_RE = re.compile(r"^\s*(ERROR|CRITICAL WARNING):", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vivado build-log gate")
    p.add_argument("log", help="path to the Vivado build log")
    p.add_argument("--manifest", help="optional build_manifest.json")
    p.add_argument("--allow", action="append", default=[],
                   help="regex whitelist; matching lines are ignored (repeatable)")
    p.add_argument("--json", action="store_true", help="print JSON only")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    log_path = Path(args.log)
    if not log_path.is_file():
        print(f"log not found: {log_path}", file=sys.stderr)
        return 1

    allow = [re.compile(a) for a in args.allow]
    errors: list[tuple[int, str]] = []
    criticals: list[tuple[int, str]] = []
    ignored = 0

    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            if not ERROR_RE.match(line):
                continue
            if any(a.search(line) for a in allow):
                ignored += 1
                continue
            if line.lstrip().upper().startswith("ERROR"):
                errors.append((lineno, line.strip()))
            else:
                criticals.append((lineno, line.strip()))

    timing_ok = True
    wns = None
    manifest_ok = True
    if args.manifest and Path(args.manifest).is_file():
        try:
            data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            manifest_ok = str(data.get("status", "ok")) == "ok"
            raw = data.get("wns")
            if raw not in (None, "", "nan"):
                wns = float(raw)
                timing_ok = wns >= 0
        except (json.JSONDecodeError, ValueError):
            manifest_ok = False

    code = 0
    if errors or criticals or not manifest_ok:
        code = 2
    if wns is not None and wns < 0:
        code = 3

    report = {
        "log": str(log_path),
        "status": "pass" if code == 0 else "fail",
        "errors": len(errors),
        "critical_warnings": len(criticals),
        "ignored": ignored,
        "wns": wns,
        "exit_code": code,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return code

    print(f"log: {log_path}")
    print(f"  ERROR            : {len(errors)}")
    print(f"  CRITICAL WARNING : {len(criticals)}")
    if ignored:
        print(f"  ignored (allow)  : {ignored}")
    if wns is not None:
        print(f"  WNS              : {wns} ns -> {'PASS' if timing_ok else 'FAIL (timing not met)'}")

    def show(title: str, items: list[tuple[int, str]], limit: int = 15) -> None:
        if not items:
            return
        print(f"\n{title} (showing up to {limit}):")
        for lineno, line in items[:limit]:
            # 日志里可能含控制台无法编码的字符（中文/替换符）；统一降级为 ASCII 安全形式
            safe = line[:200].encode("ascii", "replace").decode("ascii")
            print(f"  L{lineno}: {safe}")
        if len(items) > limit:
            print(f"  ... {len(items) - limit} more, see the log")

    show("ERROR", errors)
    show("CRITICAL WARNING", criticals)

    if code == 0:
        print("\nRESULT: PASS")
    elif code == 3:
        print("\nRESULT: FAIL - timing not met (WNS < 0); fix constraints or reduce clock")
    else:
        print("\nRESULT: FAIL - ERROR / CRITICAL WARNING found. "
              "In Vivado, a mistyped IP parameter only produces a CRITICAL WARNING "
              "and silently falls back to the default; read properties back with get_property.")
    return code


if __name__ == "__main__":
    sys.exit(main())
