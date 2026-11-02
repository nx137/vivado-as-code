#!/usr/bin/env python3
"""ps7_config.py —— Zynq PS7 声明式配置（YAML → 带回读断言的 Tcl 补丁）。

为什么需要它：
    PS7 有 85+ 个 CONFIG.PCW_* 属性，手写 Tcl 容易写错参数名（Vivado 只报
    CRITICAL WARNING），也看不出"设计意图"（我要 150MHz / 两个 HP 口 / 开中断）。
    本工具把设计意图写成 ps7.yaml，生成"设置 + 回读校验"的 Tcl，挂到
    VAC_POST_BD_TCL 即可每次构建生效。

用法：
    python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl
    python scripts/ps7_config.py render ps7.yaml --stdout
    python scripts/ps7_config.py example            # 打印一份带注释的示例
    python scripts/ps7_config.py check ps7.yaml     # 只校验 schema

退出码：0 成功；1 配置非法或文件不存在；2 渲染后仍有位置问题（保留）

支持的 YAML 子集（刻意最小化，避免引入 PyYAML 依赖）：
    - 注释、空行、嵌套映射、行内列表 [a, b]、行内映射 {k: v, ...}
    - 标量：int / float / true / false / 字符串（可带引号）
    不支持：多行字符串、锚点、合并键、tab 缩进。

配置 schema（未知键会报错，避免拼写错误被静默忽略）：
    part: xc7z020clg400-2        # 可选，仅做格式校验
    clocks:                       # 单位 MHz；0 表示关闭该 FCLK
      fclk0: 100
      fclk1: 200
    hp_ports: [0]                 # 启用的 S_AXI_HP 口（0..3）
    irq_f2p: true                 # 打开 PL→PS 中断（IRQ_F2P）
    mio:                          # 打开/关闭 MIO 外设
      uart1: {enable: true, io: "MIO 48 .. 49"}
      sdio0: {enable: true, io: "MIO 40 .. 45"}
      enet0: {enable: true, io: "MIO 16 .. 27"}
      qspi:  {enable: true, single_ss: true}
      usb0:  {enable: false}
    ddr:
      size_gb: 1                  # 决定 PCW_DDR_RAM_HIGHADDR
    extra_props:                   # 逃生口：直接写 PCW_* 属性
      PCW_USE_M_AXI_GP0: 1
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCHEMA_TOP = {"part", "clocks", "hp_ports", "irq_f2p", "mio", "ddr", "extra_props"}
SCHEMA_CLOCKS = {"fclk0", "fclk1", "fclk2", "fclk3"}
SCHEMA_MIO = {"uart0", "uart1", "sdio0", "sdio1", "enet0", "enet1", "qspi", "usb0", "usb1", "gpio_mio"}
SCHEMA_DDR = {"size_gb"}

# FCLK 上限：Zynq-7000 -2 速度等级建议不超过 250MHz
FCLK_MAX_MHZ = 250.0
DDR_ALLOWED_GB = {0.25, 0.5, 1.0, 2.0, 4.0}

MIO_IO_KEY = {
    "uart0": ("PCW_UART0_PERIPHERAL_ENABLE", "PCW_UART0_UART0_IO"),
    "uart1": ("PCW_UART1_PERIPHERAL_ENABLE", "PCW_UART1_UART1_IO"),
    "sdio0": ("PCW_SD0_PERIPHERAL_ENABLE", "PCW_SD0_SD0_IO"),
    "sdio1": ("PCW_SD1_PERIPHERAL_ENABLE", "PCW_SD1_SD1_IO"),
    "enet0": ("PCW_ENET0_PERIPHERAL_ENABLE", "PCW_ENET0_ENET0_IO"),
    "enet1": ("PCW_ENET1_PERIPHERAL_ENABLE", "PCW_ENET1_ENET1_IO"),
    "qspi": ("PCW_QSPI_PERIPHERAL_ENABLE", None),
    "usb0": ("PCW_USB0_PERIPHERAL_ENABLE", None),
    "usb1": ("PCW_USB1_PERIPHERAL_ENABLE", None),
    "gpio_mio": ("PCW_GPIO_MIO_GPIO_ENABLE", None),
}


# ---------------------------------------------------------------------------
# 最小 YAML 子集解析
# ---------------------------------------------------------------------------
def _strip_comment(line: str) -> str:
    out = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = ""
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _split_top(text: str, sep: str) -> list[str]:
    parts, buf, quote, depth = [], [], "", 0
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def parse_scalar(raw: str):
    text = raw.strip()
    if text == "":
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(p) for p in _split_top(inner, ",")]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        result = {}
        if inner:
            for item in _split_top(inner, ","):
                if ":" not in item:
                    raise ValueError(f"行内映射缺少冒号: {item}")
                k, v = item.split(":", 1)
                result[k.strip().strip("\"'")] = parse_scalar(v)
        return result
    if ":" in text and not text.startswith(("http://", "https://")):
        # 形如 "a: b" 的行内映射（嵌套）
        k, v = text.split(":", 1)
        if k.strip() and not v.strip().startswith(("/", "\\")):
            return {k.strip(): parse_scalar(v)}
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?", text):
        return float(text)
    return text


def parse_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for lineno, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError(f"第 {lineno} 行用了 tab 缩进（请用空格）")
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if ":" not in body:
            raise ValueError(f"第 {lineno} 行不是 key: value 形式: {body}")
        key, value = body.split(":", 1)
        key = key.strip().strip("\"'")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"第 {lineno} 行缩进异常")
        parent = stack[-1][1]
        if value.strip() == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(value)
    return root


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def validate(config: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["配置根节点必须是映射"]

    unknown = set(config) - SCHEMA_TOP
    if unknown:
        errors.append(f"未知顶层键: {', '.join(sorted(unknown))}（允许: {', '.join(sorted(SCHEMA_TOP))}）")

    part = config.get("part")
    if part is not None and not re.fullmatch(r"(xc|xa)[a-z0-9]+(-[0-9])?", str(part)):
        errors.append(f"part 格式可疑: {part}")

    clocks = config.get("clocks") or {}
    if not isinstance(clocks, dict):
        errors.append("clocks 必须是映射")
    else:
        unknown = set(clocks) - SCHEMA_CLOCKS
        if unknown:
            errors.append(f"clocks 未知键: {', '.join(sorted(unknown))}")
        for key, value in clocks.items():
            if key not in SCHEMA_CLOCKS:
                continue
            if not isinstance(value, (int, float)):
                errors.append(f"clocks.{key} 必须是数字（MHz）")
            elif value != 0 and not (0 < float(value) <= FCLK_MAX_MHZ):
                errors.append(f"clocks.{key}={value} 超出 (0, {FCLK_MAX_MHZ}] MHz")

    hp = config.get("hp_ports") or []
    if not isinstance(hp, list) or any(not isinstance(p, int) or not (0 <= p <= 3) for p in hp):
        errors.append("hp_ports 必须是 0..3 的整数列表")
    elif len(set(hp)) != len(hp):
        errors.append("hp_ports 有重复端口")

    if "irq_f2p" in config and not isinstance(config["irq_f2p"], bool):
        errors.append("irq_f2p 必须是 true/false")

    mio = config.get("mio") or {}
    if not isinstance(mio, dict):
        errors.append("mio 必须是映射")
    else:
        unknown = set(mio) - SCHEMA_MIO
        if unknown:
            errors.append(f"mio 未知外设: {', '.join(sorted(unknown))}（允许: {', '.join(sorted(SCHEMA_MIO))}）")
        for name, spec in mio.items():
            if name not in SCHEMA_MIO:
                continue
            if isinstance(spec, bool):
                continue
            if not isinstance(spec, dict):
                errors.append(f"mio.{name} 必须是映射或布尔")
                continue
            unknown_keys = set(spec) - {"enable", "io", "single_ss"}
            if unknown_keys:
                errors.append(f"mio.{name} 未知字段: {', '.join(sorted(unknown_keys))}")
            if "enable" in spec and not isinstance(spec["enable"], bool):
                errors.append(f"mio.{name}.enable 必须是布尔")
            io_key = MIO_IO_KEY.get(name, (None, None))[1]
            if "io" in spec and io_key is None:
                errors.append(f"mio.{name} 不支持 io 字段（该外设不走 MIO 分组）")
            if "io" in spec and not re.fullmatch(r"MIO \d+\s*\.\.\s*\d+", str(spec["io"])):
                errors.append(f"mio.{name}.io 格式应为 \"MIO 48 .. 49\"，实际: {spec['io']}")

    ddr = config.get("ddr") or {}
    if not isinstance(ddr, dict):
        errors.append("ddr 必须是映射")
    else:
        unknown = set(ddr) - SCHEMA_DDR
        if unknown:
            errors.append(f"ddr 未知键: {', '.join(sorted(unknown))}")
        if "size_gb" in ddr:
            try:
                size = float(ddr["size_gb"])
                if size not in DDR_ALLOWED_GB:
                    errors.append(f"ddr.size_gb={ddr['size_gb']} 不在支持范围 {sorted(DDR_ALLOWED_GB)}")
            except (TypeError, ValueError):
                errors.append("ddr.size_gb 必须是数字")

    extra = config.get("extra_props") or {}
    if not isinstance(extra, dict):
        errors.append("extra_props 必须是映射")
    else:
        for key in extra:
            if not str(key).startswith("PCW_"):
                errors.append(f"extra_props 的键必须以 PCW_ 开头: {key}")

    return errors


# ---------------------------------------------------------------------------
# 生成 Tcl
# ---------------------------------------------------------------------------
def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_tcl(config: dict, source: str = "ps7.yaml") -> str:
    lines: list[str] = []
    a = lines.append
    a("# =============================================================================")
    a("# 由 scripts/ps7_config.py 从 %s 生成 —— 不要手改，改 YAML 后重新生成" % source)
    a("# 挂到构建：VAC_POST_BD_TCL=tcl/post_bd_ps7.tcl")
    a("# 生成内容 = 设置 CONFIG.PCW_* + 回读断言（Vivado 写错参数名只报 CRITICAL WARNING）")
    a("# =============================================================================")
    a("")
    a('set _ps [get_bd_cells -quiet processing_system7_0]')
    a('if {[llength $_ps] == 0} {')
    a('    puts "  ERROR: \\[ps7\\] 没有 processing_system7_0"')
    a("    exit 1")
    a("}")
    a("")

    clocks = config.get("clocks") or {}
    if clocks:
        a("# ---- FCLK 时钟 -----------------------------------------------------------")
    for idx in range(4):
        key = f"fclk{idx}"
        if key not in clocks:
            continue
        mhz = clocks[key]
        enable = 1 if mhz and float(mhz) > 0 else 0
        a("set_property CONFIG.PCW_FPGA_FCLK%d_ENABLE {%d} $_ps" % (idx, enable))
        if enable:
            a("set_property CONFIG.PCW_FPGA%d_PERIPHERAL_FREQMHZ {%s} $_ps" % (idx, _num(mhz)))
    if clocks:
        a("")

    hp = config.get("hp_ports") or []
    if "hp_ports" in config:
        a("# ---- S_AXI_HP 口 ---------------------------------------------------------")
        for idx in range(4):
            a("set_property CONFIG.PCW_USE_S_AXI_HP%d {%d} $_ps" % (idx, 1 if idx in hp else 0))
        a("")

    if "irq_f2p" in config:
        flag = 1 if config["irq_f2p"] else 0
        a("# ---- PL→PS 中断 ----------------------------------------------------------")
        a("set_property CONFIG.PCW_USE_FABRIC_INTERRUPT {%d} $_ps" % flag)
        a("set_property CONFIG.PCW_IRQ_F2P_INTR {%d} $_ps" % flag)
        a("")

    mio = config.get("mio") or {}
    if mio:
        a("# ---- MIO 外设 ------------------------------------------------------------")
        for name in ("uart0", "uart1", "sdio0", "sdio1", "enet0", "enet1", "qspi", "usb0", "usb1", "gpio_mio"):
            if name not in mio:
                continue
            spec = mio[name]
            enable = spec if isinstance(spec, bool) else bool((spec or {}).get("enable", False))
            enable_prop, io_prop = MIO_IO_KEY[name]
            a("set_property CONFIG.%s {%d} $_ps" % (enable_prop, 1 if enable else 0))
            if enable and io_prop and isinstance(spec, dict) and spec.get("io"):
                a("set_property CONFIG.%s {%s} $_ps" % (io_prop, spec["io"]))
            if name == "qspi" and enable and isinstance(spec, dict) and spec.get("single_ss"):
                a("set_property CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {1} $_ps")
        a("")

    ddr = config.get("ddr") or {}
    if "size_gb" in ddr:
        high = int(float(ddr["size_gb"]) * 1024 ** 3) - 1
        a("# ---- DDR -----------------------------------------------------------------")
        a("set_property CONFIG.PCW_DDR_RAM_HIGHADDR {0x%08X} $_ps" % high)
        a("")

    extra = config.get("extra_props") or {}
    if extra:
        a("# ---- 额外属性（extra_props）---------------------------------------------")
        for key, value in extra.items():
            a("set_property CONFIG.%s {%s} $_ps" % (key, value))
        a("")

    # ---- 回读断言 ----
    a("# ---- 回读断言（写错参数名/频率不可达时这里会失败）-------------------------")
    if clocks:
        a("proc _ps7_check_freq {idx expect} {")
        a("    global _ps")
        a("    set _act [get_property CONFIG.PCW_ACT_FPGA${idx}_PERIPHERAL_FREQMHZ $_ps]")
        a("    if {abs(double($_act) - double($expect)) > 0.01} {")
        a('        puts "  ERROR: \\[ps7\\] FCLK${idx} 实际 ${_act}MHz，期望 ${expect}MHz"')
        a("        exit 1")
        a("    }")
        a('    puts "  \\[ps7\\] FCLK${idx} = ${expect} MHz (ACT=${_act})"')
        a("}")
        for idx in range(4):
            key = f"fclk{idx}"
            if key not in clocks:
                continue
            mhz = clocks[key]
            if not mhz or float(mhz) <= 0:
                a('puts "  \\[ps7\\] FCLK%d 已关闭"' % idx)
                continue
            a("_ps7_check_freq %d %s" % (idx, _num(mhz)))
        a("")
    if "hp_ports" in config:
        for idx in range(4):
            a("set _hp%d [get_property CONFIG.PCW_USE_S_AXI_HP%d $_ps]" % (idx, idx))
        a('puts "  \\[ps7\\] HP 口: 0=$_hp0 1=$_hp1 2=$_hp2 3=$_hp3"')
        a("")
    if "irq_f2p" in config:
        a("set _irq [get_property CONFIG.PCW_IRQ_F2P_INTR $_ps]")
        a('if {"$_irq" ne "%d"} { puts "  ERROR: \\[ps7\\] IRQ_F2P 回读不一致"; exit 1 }'
          % (1 if config["irq_f2p"] else 0))
        a('puts "  \\[ps7\\] IRQ_F2P = $_irq"')
        a("")
    if "ddr" in config and "size_gb" in ddr:
        a("set _ddr [get_property CONFIG.PCW_DDR_RAM_HIGHADDR $_ps]")
        a('puts "  \\[ps7\\] DDR highaddr = $_ddr"')
        a("")
    a('puts "  \\[ps7\\] 配置完成"')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 示例
# ---------------------------------------------------------------------------
EXAMPLE = """\
# ps7.yaml —— Zynq PS7 声明式配置示例
part: xc7z020clg400-2

# FCLK（MHz）；写 0 表示关闭
clocks:
  fclk0: 100
  fclk1: 200
  fclk2: 0
  fclk3: 0

# 启用的 S_AXI_HP 口
hp_ports: [0, 1]

# PL→PS 中断
irq_f2p: true

# MIO 外设（io 必须与板卡原理图一致）
mio:
  uart1: {enable: true, io: "MIO 48 .. 49"}
  sdio0: {enable: true, io: "MIO 40 .. 45"}
  enet0: {enable: true, io: "MIO 16 .. 27"}
  qspi:  {enable: true, single_ss: true}
  usb0:  {enable: false}

# DDR 容量（GB）→ PCW_DDR_RAM_HIGHADDR
ddr:
  size_gb: 1

# 逃生口：直接写 PCW_* 属性
extra_props:
  PCW_USE_M_AXI_GP0: 1
"""


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description="Zynq PS7 声明式配置（YAML → Tcl）")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="渲染成 Tcl")
    r.add_argument("file")
    r.add_argument("--out", "-o", help="输出文件；省略则打印到 stdout")
    r.add_argument("--force", "-f", action="store_true")
    c = sub.add_parser("check", help="只校验 schema")
    c.add_argument("file")
    sub.add_parser("example", help="打印示例 YAML")
    args = p.parse_args()

    if args.cmd == "example":
        sys.stdout.write(EXAMPLE)
        return 0

    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: 找不到配置: {path}", file=sys.stderr)
        return 1
    try:
        config = parse_yaml(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"ERROR: YAML 解析失败: {exc}", file=sys.stderr)
        return 1

    errors = validate(config)
    if errors:
        print("ERROR: 配置非法：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if args.cmd == "check":
        print(f"OK: {path} 通过 schema 校验")
        return 0

    tcl = render_tcl(config, source=str(path))
    if args.out:
        out = Path(args.out)
        if out.exists() and not args.force:
            print(f"ERROR: 文件已存在（加 --force 覆盖）: {out}", file=sys.stderr)
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tcl.encode("utf-8"))
        print(f"已生成: {out}")
    else:
        sys.stdout.write(tcl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
