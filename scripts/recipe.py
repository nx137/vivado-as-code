#!/usr/bin/env python3
"""recipe.py —— 参数化 BD 补丁渲染器。

为什么需要它：
    `bd_patch_template.tcl` 是"抄一份再改"，容易漏改、容易漂移。
    recipe 把常见增删改做成模板 + 参数，一条命令生成可直接进构建的补丁脚本。

用法：
    python recipe.py --list
    python recipe.py render add_axi_gpio --param name=axi_gpio_user --out tcl/patch_gpio.tcl
    python recipe.py render set_fclk --param fclk=150 --out tcl/post_fclk.tcl
    python recipe.py render add_axi_uartlite --param name=axi_uartlite_0 --stdout

约定：
    - 模板放在 scripts/recipes/*.tcl.tmpl；
    - 模板头用注释声明元数据：
          # @desc 一句话说明
          # @param key=default 说明
    - 正文里用 @@key@@ 占位；渲染后不允许残留 @@（缺参数直接报错）；
    - 生成脚本自带守卫库加载、前置检查与收尾（validate + save）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RECIPE_DIR = Path(__file__).resolve().parent / "recipes"
DESC_RE = re.compile(r"^#\s*@desc\s+(.+)$", re.M)
PARAM_RE = re.compile(r"^#\s*@param\s+(\w+)\s*=\s*(\S*)\s*(.*)$", re.M)
PLACEHOLDER_RE = re.compile(r"@@([A-Za-z_][A-Za-z0-9_]*)@@")

PREAMBLE = r"""# =============================================================================
# 由 scripts/recipe.py 生成的 BD 补丁（recipe: @@recipe@@）
# 生成命令见文件头注释；不要手改本文件，改模板后重新渲染。
#
# 运行方式：
#   VAC_PATCH_TCL=tcl/patch_@@recipe@@.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd
#   或直接由 rebuild.tcl 自动执行（VAC_PATCH_TCL 支持逗号分隔多个补丁）
# =============================================================================

# ---- 载入守卫库（多路径查找；也可用 VAC_GUARDS_TCL 指定）------------------
set _here [file dirname [file normalize [info script]]]
set _guards_cands {}
if {[info exists env(VAC_GUARDS_TCL)] && $env(VAC_GUARDS_TCL) ne ""} {
    lappend _guards_cands $env(VAC_GUARDS_TCL)
}
lappend _guards_cands \
    [file join $_here lib guards.tcl] \
    [file join $_here guards.tcl] \
    [file normalize [file join $_here .. scripts lib guards.tcl]] \
    [file normalize [file join $_here .. .. scripts lib guards.tcl]] \
    [file normalize [file join [pwd] scripts lib guards.tcl]]
set _guards_loaded 0
foreach _cand $_guards_cands {
    if {[file exists $_cand]} { source $_cand; set _guards_loaded 1; break }
}
if {!$_guards_loaded} {
    puts "  ERROR: 找不到 guards.tcl；已尝试："
    foreach _c $_guards_cands { puts "    - $_c" }
    puts "  解决：复制 scripts/lib/guards.tcl 到补丁同级 lib/，或设置 VAC_GUARDS_TCL"
    exit 1
}

if {[llength [get_bd_designs -quiet]] == 0} { fail "没有打开的 BD（请先 source 全量 BD TCL）" }
set _bd [current_bd_design]
puts "  \[recipe:@@recipe@@\] 开始"
"""

FOOTER = r"""
# ---- 收尾：校验 + 保存 ----------------------------------------------------
# 稳定后建议用 scripts/bd_export.tcl 把 BD 固化回 tcl/design_1.tcl
vac_finalize $_bd
puts "  \[recipe:@@recipe@@\] 完成"
"""


def load_recipe(name: str) -> tuple[str, dict[str, str], str]:
    path = RECIPE_DIR / f"{name}.tcl.tmpl"
    if not path.is_file():
        raise FileNotFoundError(f"recipe 不存在：{name}")
    text = path.read_text(encoding="utf-8")
    desc_m = DESC_RE.search(text)
    desc = desc_m.group(1).strip() if desc_m else ""
    defaults = {k: (v if v != "" else "") for k, v, _ in PARAM_RE.findall(text)}
    body = PARAM_RE.sub("", text)
    body = DESC_RE.sub("", body)
    return desc, defaults, body


def list_recipes() -> int:
    names = sorted(p.name[: -len(".tcl.tmpl")] for p in RECIPE_DIR.glob("*.tcl.tmpl"))
    if not names:
        print("没有找到 recipe 模板（scripts/recipes/*.tcl.tmpl）", file=sys.stderr)
        return 1
    for name in names:
        desc, defaults, _ = load_recipe(name)
        params = ", ".join(f"{k}={v}" for k, v in defaults.items())
        print(f"{name:22s} {desc}")
        if params:
            print(f"{'':22s} params: {params}")
    return 0


def render(name: str, params: dict[str, str]) -> str:
    desc, defaults, body = load_recipe(name)
    values = dict(defaults)
    unknown = [k for k in params if k not in defaults]
    if unknown:
        raise ValueError(f"未知参数：{', '.join(sorted(unknown))}（可用：{', '.join(defaults)}）")
    values.update(params)
    values["recipe"] = name

    rendered = PREAMBLE + body + FOOTER
    for key, value in values.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    leftover = sorted(set(PLACEHOLDER_RE.findall(rendered)))
    if leftover:
        raise ValueError(f"渲染后仍有未替换的占位符：{', '.join(leftover)}")
    return rendered


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description="BD 补丁 recipe 渲染器")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有 recipe")

    r = sub.add_parser("render", help="渲染一个 recipe")
    r.add_argument("name")
    r.add_argument("--param", "-p", action="append", default=[], metavar="KEY=VALUE")
    r.add_argument("--out", "-o", help="输出文件；省略则打印到 stdout")
    r.add_argument("--force", "-f", action="store_true", help="允许覆盖已存在文件")
    args = p.parse_args()

    if args.cmd == "list":
        return list_recipes()

    params: dict[str, str] = {}
    for item in args.param:
        if "=" not in item:
            print(f"参数格式应为 KEY=VALUE：{item}", file=sys.stderr)
            return 1
        k, v = item.split("=", 1)
        params[k.strip()] = v.strip()

    try:
        text = render(args.name, params)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.out:
        out = Path(args.out)
        if out.exists() and not args.force:
            print(f"文件已存在（加 --force 覆盖）：{out}", file=sys.stderr)
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"已生成：{out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
