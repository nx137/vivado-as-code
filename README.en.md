# vivado-as-code

> Turn a Xilinx Vivado project into **"project as code"**: no `.xpr` in version control,
> one command rebuilds the bitstream from scratch, and the Block Design plus Zynq PS
> configuration live in reviewable Tcl. Ships as an **AI-agent skill + MCP tool server**
> so Claude Code / DeepSeek Harness can run builds, read logs, diff Block Designs and
> render parameterized patches directly.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/nx137/vivado-as-code/actions/workflows/ci.yml/badge.svg)](https://github.com/nx137/vivado-as-code/actions/workflows/ci.yml)

[中文 README](README.md) · [中文 SKILL](SKILL.md)

---

## 1. What problem does it solve

| Conventional workflow | This project |
|---|---|
| Commit `.xpr/.runs/.gen`; binaries cannot be reviewed | Commit only `src/` + `xdc/` + `tcl/<bd>.tcl` + build scripts |
| Nobody can tell what changed inside the Block Design | `write_bd_tcl` exports text; review with `git diff` / `bd_diff.py` |
| A teammate's clone does not build | One command rebuilds everything from scratch |
| PS clocks / HP ports / interrupts only exist as GUI state | All are `CONFIG.PCW_*` properties, scriptable |
| A typo in an IP parameter still produces a bitstream | Log gate: zero `CRITICAL WARNING`, with fix hints |
| The AI assistant re-reads docs and hand-builds commands | MCP tool layer + `SKILL.md`, with validation and structured results |

## 2. Features

### v0.3

| Capability | Usage | Notes |
|---|---|---|
| **Declarative PS7 config** | `python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl` | Describe intent (FCLK / HP ports / IRQ / MIO / DDR) in YAML; the generated Tcl **reads properties back and fails** on mismatch. Unknown keys are rejected. |
| **Full English docs** | this file / [`SKILL.en.md`](SKILL.en.md) | For English-speaking users and agents. |

### v0.2

| Capability | Usage | Notes |
|---|---|---|
| **MCP server** | `python mcp/vivado_as_code_server.py` | Tools: `vac_build` / `vac_check_log` / `vac_bd_diff` / `vac_bd_export` / `vac_check_handoff` / `vac_ps7_render`. One `.mcp.json` works for both Claude Code and DSH. |
| **Semantic BD diff** | `python scripts/bd_diff.py old.tcl new.tcl --json` | Cells, CONFIG changes, address changes, connection changes; `--fail-on-change` for CI gating. |
| **Log diagnosis** | `python scripts/check_build.py build.log --explain` | Known errors (`BD 41-759/758/701`, version lock, Vivado environment) → action + relevant `pitfalls.md` section. |
| **Tests + CI** | `python -m unittest discover -s tests -t . -v` | 66 cases; GitHub Actions on Ubuntu/Windows × Python 3.9/3.12; no Vivado required. |

## 3. Measured results (Vivado 2020.2 / xc7z020clg400-2)

| Check | Result |
|---|---|
| Rebuild BD + `.hwh` from BD Tcl | ✅ ~**0.5 min**, 0 ERROR / 0 CRITICAL |
| Patch idempotency (same build, patch twice) | ✅ exported BD **byte-identical** |
| Full synthesis + implementation + bitstream | ✅ ~**4.8 min**, `.bit` 3.95 MB, **WNS +1.932 ns** |
| PS7 clock override (FCLK0 100→150 MHz) | ✅ `ACT=150.000000` read back |
| Declarative PS7 (yaml → Tcl → build) | ✅ `fclk0: 150` → `ACT=150.000000`, 0 CRITICAL |
| Semantic diff | ✅ reports cell add, `NUM_MI 1→2`, address `0x41240000` |
| Log diagnosis | ✅ injected `BD 41-759` → action + `pitfalls.md` B3 |
| MCP end-to-end | ✅ 6 tools listed; `vac_build`/`vac_bd_diff`/`vac_check_handoff`/`vac_ps7_render` return structured results |
| Clean clone end-to-end | ✅ exit 0, `RESULT: PASS` |
| Real project adoption (20 IP + 12 RTL) | ✅ BD 0.8 min; full build 16.1 min, bit 3.95 MB; gate caught 3 wiring defects + 1 marginal timing violation |

> See `references/` for details and `examples/` for runnable samples.

Dependencies: Python ≥ 3.9 (scripts and MCP use only the standard library; no `pip install`) + Vivado 2020.2 for actual builds.

## 4. Quick start

### 4.1 Install as an agent skill

```bash
git clone https://github.com/nx137/vivado-as-code ~/.claude/skills/vivado-as-code   # Claude Code
git clone https://github.com/nx137/vivado-as-code ~/.dsh/skills/vivado-as-code      # DeepSeek Harness
```

### 4.2 Mount as MCP tools (recommended)

Put `.mcp.json` in your project root (works for Claude Code and DSH; DSH also reads `.dsh/mcp.json`):

```json
{
  "mcpServers": {
    "vivado-as-code": {
      "command": "python",
      "args": ["D:/vivado-as-code/mcp/vivado_as_code_server.py"]
    }
  }
}
```

See [`mcp/README.md`](mcp/README.md).

### 4.3 Use as a template (no AI required)

```bash
mkdir -p myproj/vivado
cp -r templates/project-skeleton/. myproj/
cp templates/rebuild.tcl myproj/vivado/rebuild.tcl
cp -r scripts myproj/scripts            # optional: project-local toolchain

# Existing project: export the Block Design as the source of truth
vivado -mode batch -source scripts/bd_export.tcl -tclargs \
    old_project.xpr design_1 myproj/tcl/design_1.tcl

./scripts/build.ps1 -ProjectRoot myproj -StopAfter bd   # BD only (~1 min)
./scripts/build.ps1 -ProjectRoot myproj                  # full bitstream
```

### 4.4 Run the minimal example

```bash
cd examples/zynq7020-min
vivado -mode batch -source tcl/mk_min_bd.tcl     # generate tcl/design_1.tcl (once)
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

### 4.5 Adopt an existing project (no layout change)

Existing projects often keep RTL/XDC under `vivado/`, the BD under `vivado/tcl/`, and copy
the renamed artifacts into a PYNQ directory. A ~20-line adapter and `-RebuildScript` are enough;
the original `build.bat` stays untouched:

```tcl
# vivado/rebuild_vac.tcl
set env(VAC_ROOT)          [file dirname [file dirname [file normalize [info script]]]]
set env(VAC_SRC_DIR)       vivado/src
set env(VAC_XDC_DIR)       vivado/xdc
set env(VAC_BD_TCL)        vivado/tcl/bd_design_1.tcl
set env(VAC_PATCH_TCL)     vivado/tcl/bd_add_fm_modem.tcl
set env(VAC_POST_BD_TCL)   vivado/tcl/post_bd_uart_aclk.tcl
set env(VAC_COPY_TO)       software/pynq/main
set env(VAC_ARTIFACT_NAME) xinhao_uart_kb_adf4351_rf
source [file join $env(VIVADO_AS_CODE) templates rebuild.tcl]
```

```bash
scripts/build.ps1 -ProjectRoot . -RebuildScript vivado/rebuild_vac.tcl -StopAfter bd
```

Measured adoption notes and copy-ready files: [`examples/real-project-adoption/`](examples/real-project-adoption/).

## 5. Repository layout

```
.
├── SKILL.md                 # skill entry: rules, decision table, tool list, on-demand references
├── SKILL.en.md              # English mirror
├── references/
│   ├── ps7-config.md        # PS7 config patterns (clocks/HP/IRQ/MIO/DDR) + declarative config
│   ├── bd-patterns.md       # BD as Tcl: export, idempotent patches, addresses, diff
│   ├── build-pipeline.md    # nine phases, staged validation, log gate, layout conventions
│   ├── pitfalls.md          # symptom → root cause → check command (20+ entries)
│   └── pynq-handoff.md      # .bit/.hwh, overlay, FS calibration, consistency checks
├── scripts/
│   ├── build.ps1 / build.sh # build entry (Vivado discovery, log gate)
│   ├── bd_export.tcl        # write_bd_tcl round-trip + archive
│   ├── lib/guards.tcl       # idempotent guard library
│   ├── bd_diff.py           # semantic BD diff
│   ├── ps7_config.py        # declarative PS7 config (yaml → Tcl)
│   ├── check_build.py       # log gate + --explain diagnosis
│   └── check_handoff.py     # BD ↔ .hwh ↔ .bit consistency
├── mcp/
│   ├── vivado_as_code_server.py  # zero-dependency stdio MCP server
│   └── README.md            # Claude Code / DSH setup
├── templates/
│   ├── rebuild.tcl          # parameterized nine-phase build
│   └── project-skeleton/    # empty project skeleton
├── examples/zynq7020-min/   # runnable minimal example (PS7 + DMA loopback, no pin constraints)
├── examples/ps7/            # declarative PS7 example
├── examples/real-project-adoption/  # real-project adoption template
├── tests/                   # 66 unit/protocol tests (no Vivado needed)
├── .github/workflows/ci.yml # Ubuntu/Windows × Python 3.9/3.12
└── docs/                    # self-hosted CI template
```

## 6. Core conventions

1. Never commit `.xpr/.runs/.gen`; the BD source of truth is `tcl/<bd>.tcl`.
2. GUI edit → `bd_export.tcl` round-trip → `bd_diff.py` review → clean rebuild → commit.
3. Always validate on a **clean rebuild**; do not rely on incremental caches.
4. Every build must pass the log gate (`check_build.py`): CRITICAL count must be zero.
5. `.bit` / `.hwh` must share a basename and come from the same build; verify with `check_handoff.py`.

## 7. Boundaries

- **Zynq-7000 (PS7) first**; plain 7-series PL projects also work.
  UltraScale+ MPSoC needs the PS section rewritten with `zynq_ultra_ps_e` / `CONFIG.PSU__*`.
- Does not install or license Vivado (examples use the WebPACK-covered xc7z020).
- Ships no board pin definitions — board-level XDC is your responsibility.
- BD Tcl carries a Vivado version guard; cross-version path: open the design in the new Vivado, run Report IP Status to upgrade, then `write_bd_tcl` again (`references/pitfalls.md` A4).

## 8. Origin and license

The method comes from a 2026 Jiangsu Province Undergraduate Electronic Design Contest (TI Cup)
entry (Nanjing University of Science and Technology, team NJ505; Zynq-7020 + PYNQ). The original
project collapsed its whole build into `rebuild.tcl` + `bd_design_1.tcl`; this repository
abstracts and hardens the reusable parts: idempotent guards, log gate, semantic diff,
MCP tool layer and tests.

Code and scripts: [MIT](LICENSE).
