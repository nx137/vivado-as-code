#!/usr/bin/env python3
"""bd_parse.py —— Block Design TCL 的共享解析器。

为什么单独放这里：
    `bd_diff.py` 与 `check_handoff.py` 都需要"从 write_bd_tcl 导出的脚本里
    提取 IP / module_ref / CONFIG / 地址 / 连线"。此前两份正则各自维护，
    修一处漏一处（2026-11-02 审计发现：变量形式 module_ref 的修复做了两遍）。
    本模块是唯一实现，两个 CLI 只负责展示差异。

设计约束：
    - 纯标准库；
    - 尽量贴近 write_bd_tcl 的输出格式（不是完整 Tcl 解析器）；
    - 解析失败不抛异常，返回已解析到的部分（调用方自行判断）。
"""
from __future__ import annotations

import re
from pathlib import Path

# create_bd_cell -type ip -vlnv <vlnv> <name>
CELL_IP_RE = re.compile(r"create_bd_cell\s+-type\s+ip\s+-vlnv\s+(\S+)\s+(\S+?)\s*\]")
# create_bd_cell -type module -reference <ref> <name>
CELL_MOD_RE = re.compile(r"create_bd_cell\s+-type\s+module\s+-reference\s+(\S+)\s+(\S+?)\s*\]")
# 变量形式（write_bd_tcl 对 module_ref 常见输出）：
#   set block_cell_name <name>
#   if { [catch {set ... [create_bd_cell -type module -reference $block_name $block_cell_name] } ...
MOD_VAR_RE = re.compile(
    r"set\s+block_cell_name\s+(\S+)\s*\n\s*if\s*\{\s*\[catch\s*\{\s*set", re.S
)
# set_property -dict [ list CONFIG.X {v} ... ] $cell
CONFIG_BLOCK_RE = re.compile(r"set_property\s+-dict\s+\[\s*list\s+(.*?)\]\s*(\$?[\w\.\-]+)", re.S)
CONFIG_ITEM_RE = re.compile(r"CONFIG\.([A-Za-z0-9_]+)\s+\{\s*([^{}]*?)\s*\}")
# assign_bd_address -offset ... -range ... [get_bd_addr_segs <seg>]
ADDR_RE = re.compile(
    r"assign_bd_address\s+-offset\s+(\S+)\s+-range\s+(\S+)[^\n]*?get_bd_addr_segs\s+([^\]\s]+)"
)
# connect_bd_intf_net / connect_bd_net
NET_RE = re.compile(r"connect_bd_(?:intf_)?net\s+(.*?)(?=\n|$)")
PIN_RE = re.compile(r"get_bd_(?:intf_)?pins\s+([^\]]+)\]")


def clean(name: str) -> str:
    return name.strip().strip("$").strip("{}").strip("[]")


def join_continuations(text: str) -> str:
    """展开 Tcl 续行（行尾反斜杠），让一条语句落在一行，便于逐语句解析。"""
    return text.replace("\\\r\n", " ").replace("\\\n", " ")


def load(path: str | Path) -> str:
    """读取 BD TCL 文本（保留原始行，续行由 parse_bd 展开）。"""
    return Path(path).read_text(encoding="utf-8", errors="replace")


def parse_bd(text: str) -> dict:
    """解析 BD TCL，返回 {cells, configs, addresses, connections}。

    cells: {name: {"kind": "ip"|"module", "vlnv": str}}
    configs: {cell: {CONFIG_KEY: value}}
    addresses: {segment: {"offset": str, "range": str}}
    connections: {"a <-> b", ...}（排序后去重）
    """
    text = join_continuations(text)

    cells: dict[str, dict] = {}
    for vlnv, name in CELL_IP_RE.findall(text):
        cells[clean(name)] = {"kind": "ip", "vlnv": vlnv}
    for ref, raw_name in CELL_MOD_RE.findall(text):
        # 变量名形式（$block_cell_name / $block_name）由 MOD_VAR_RE 处理。
        # 必须在 clean() 之前判断，否则 $block_cell_name 会被清洗成
        # block_cell_name 混进实例列表。
        if "$" in raw_name or "]" in raw_name or "[" in raw_name:
            continue
        name = clean(raw_name)
        if name:
            cells[name] = {"kind": "module", "vlnv": ref}
    for name in MOD_VAR_RE.findall(text):
        name = clean(name)
        if name:
            cells[name] = {"kind": "module", "vlnv": "(module_ref)"}

    configs: dict[str, dict[str, str]] = {}
    for block, cell in CONFIG_BLOCK_RE.findall(text):
        cell = clean(cell)
        props = configs.setdefault(cell, {})
        for key, value in CONFIG_ITEM_RE.findall(block):
            props[key] = value.strip()

    addresses: dict[str, dict[str, str]] = {}
    for offset, rng, seg in ADDR_RE.findall(text):
        addresses[seg] = {"offset": offset, "range": rng}

    connections: set[str] = set()
    for stmt in NET_RE.findall(text):
        pins = [clean(p) for p in PIN_RE.findall(stmt)]
        if len(pins) >= 2:
            connections.add(" <-> ".join(sorted(pins)))

    return {"cells": cells, "configs": configs, "addresses": addresses, "connections": connections}


def ip_cells(parsed: dict) -> dict[str, dict]:
    return {n: c for n, c in parsed["cells"].items() if c["kind"] == "ip"}


def module_cells(parsed: dict) -> dict[str, dict]:
    return {n: c for n, c in parsed["cells"].items() if c["kind"] == "module"}
