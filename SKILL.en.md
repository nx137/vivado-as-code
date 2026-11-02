---
name: vivado-as-code
description: >
  Drive Xilinx Vivado with a full-Tcl flow and treat the FPGA project as code:
  no .xpr in version control, one-command clean rebuild, Block Design exported as
  text via write_bd_tcl, Zynq PS7 configured through CONFIG.PCW_* (clocks/PLL,
  HP ports, IRQ, MIO peripherals, DDR), and design evolution via idempotent patch
  scripts. Use for Vivado full-Tcl flow, Block Design as code, Zynq PS7
  configuration, write_bd_tcl round-trip, reproducible bitstream without .xpr,
  PYNQ overlay handoff, BD semantic diff, PS7 declarative config (ps7.yaml),
  cross-version BD upgrade, and idempotent BD patches.
  Trigger phrases: "Vivado full Tcl", "Block Design as code", "PS7 config",
  "write_bd_tcl", "clone and rebuild", "no .xpr", "BD diff".
license: MIT
---

# vivado-as-code

Turn a Vivado project from "clicking around the GUI plus committing binaries" into
"text scripts plus one command to rebuild".

## What this approach solves

- `.xpr/.runs/.gen` cannot be diffed or merged, and a fresh clone often fails to build;
- nobody can tell what changed inside the Block Design;
- PS-side configuration (Zynq clocks, HP ports, interrupts, MIO) only lives in GUI state.

Approach: **every source of truth is text** — `src/*.v`, `xdc/*.xdc`, `tcl/<bd>.tcl`,
`vivado/rebuild.tcl`.

## Five hard rules

1. **Never commit `.xpr` / `.runs` / `.gen`**; commit RTL, XDC, BD Tcl and build scripts only.
2. **Every Block Design change must land in `tcl/<bd>.tcl`** — after editing in the GUI,
   immediately round-trip with `write_bd_tcl -force` (use `scripts/bd_export.tcl`).
3. **Validate on a clean rebuild** (delete the project and rerun). Do not rely on incremental
   caches, otherwise it works locally but not for whoever clones it.
4. **A successful build is not a correct build**: a mistyped IP parameter only produces a
   `CRITICAL WARNING` and the bitstream is still written. Always run
   `scripts/check_build.py` (zero CRITICALs required).
5. **Artifacts must be paired and share a basename**: `.bit` + `.hwh` in the same directory,
   otherwise PYNQ `Overlay()` cannot parse `ip_dict`.

## If the host has the MCP server mounted (prefer tools)

`mcp/vivado_as_code_server.py` exposes 8 tools, more reliable than hand-built commands
(validation + structured results):

| Tool | When to use |
|---|---|
| `vac_build` | Run a build; validate the BD with `stop_after=bd`, then `impl` for the bitstream |
| `vac_check_log` | After a build: ERROR/CRITICAL/WNS plus known-issue hints |
| `vac_bd_diff` | After BD edits: semantic diff (cells / CONFIG / addresses) |
| `vac_bd_export` | Round-trip a GUI-edited BD back to the source of truth |
| `vac_check_handoff` | Before PYNQ delivery: check `.bit/.hwh` consistency |
| `vac_recipe_render` | Render a parameterized patch (GPIO/UART/DMA/clock/IRQ) |
| `vac_ps7_render` | Render `ps7.yaml` into Tcl with read-back assertions |
| `vac_bd_upgrade` | Cross-version BD upgrade, exporting a new source of truth |

Setup is in `mcp/README.md` (one `.mcp.json` works for Claude Code and DSH).
Without MCP, use the CLI equivalents below.

## Quick start (3 steps)

```bash
# 1) Put it on the skill search path (or read this file from anywhere)
git clone <this-repo> ~/.claude/skills/vivado-as-code     # Claude Code
git clone <this-repo> ~/.dsh/skills/vivado-as-code        # DeepSeek Harness

# 2) Start from the template (or adopt an existing project: keep src/ xdc/, export the BD to tcl/design_1.tcl)
mkdir -p myproj/vivado
cp -r templates/project-skeleton/. myproj/
cp templates/rebuild.tcl myproj/vivado/rebuild.tcl
cp -r scripts myproj/scripts          # optional: project-local toolchain

# 3) Build (Vivado auto-detected; validate BD first, then go full)
scripts/build.ps1 -ProjectRoot myproj -StopAfter bd     # Windows, ~1 min
scripts/build.sh  -p myproj -s bd                       # Linux/macOS
scripts/build.ps1 -ProjectRoot myproj                    # full bitstream
```

Artifacts: `outputs/<top>.bit`, `outputs/<top>.hwh`, `outputs/build_manifest.json`,
`outputs/timing_summary.txt`, `outputs/utilization.txt`.
Note: `StopAfter=bd` also produces a `.hwh` (no `.bit`), useful for PYNQ address checks.

## Decision table: what kind of change?

| Need | How | Read |
|---|---|---|
| Change PS clock / PLL / divider | Declarative: `clocks.fclk0: 150` in `ps7.yaml` → `python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl` (generated Tcl asserts read-back) | `references/ps7-config.md` |
| Add a DDR high-speed port / second DMA | `hp_ports: [0, 1]` in `ps7.yaml`; use an independent interconnect in the BD | `references/ps7-config.md` |
| Enable PL→PS interrupts | `irq_f2p: true` in `ps7.yaml` + `axi_intc` in the BD | `references/ps7-config.md` |
| Add a peripheral IP (GPIO/UART/DMA…) | Prefer a recipe: `python scripts/recipe.py render add_axi_gpio -p name=xxx --out tcl/patch_gpio.tcl`; for complex edits write an idempotent patch and set `VAC_PATCH_TCL` | `scripts/recipes/` + `references/bd-patterns.md` |
| See what actually changed in the BD | `python scripts/bd_diff.py a.tcl b.tcl` (`--json` / `--fail-on-change`) | `references/bd-patterns.md` §6 |
| Build fails / timing fails / hardware misbehaves | `python scripts/check_build.py build.log --explain`, then the symptom → cause → check table | `references/pitfalls.md` |
| Add / change an RTL module | Put it in `src/`, then `create_bd_cell -type module -reference` in the BD | `references/bd-patterns.md` |
| Round-trip a GUI-edited BD | `scripts/bd_export.tcl` (auto-archives the old version) | `references/bd-patterns.md` |
| Adopt an existing project (no layout change) | Write `vivado/rebuild_vac.tcl` setting `VAC_SRC_DIR`/`VAC_XDC_DIR`/`VAC_PATCH_TCL`, pass it via `-RebuildScript` | `examples/real-project-adoption/` + `references/build-pipeline.md` §7 |
| Upgrade to a newer Vivado | `vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs old.tcl new.tcl <part>`, then review with `bd_diff.py` | `references/version-upgrade.md` |
| Hand the bitstream to a PYNQ board | Same-basename `.bit/.hwh` + FS calibration | `references/pynq-handoff.md` |

## Scripts

| Script | Purpose |
|---|---|
| `scripts/build.ps1` / `build.sh` | Entry point: detect Vivado → run rebuild → log gate → propagate exit code |
| `templates/rebuild.tcl` | Parameterized nine-phase build (`VAC_STOP_AFTER` can stop at bd/synth/impl) |
| `scripts/bd_export.tcl` | `write_bd_tcl -force` round-trip + timestamped archive |
| `scripts/lib/guards.tcl` + `guard_loader.tcl` | Idempotent guards: `vac_ensure_ip` / `vac_connect_net_if_free` / `vac_ensure_addr` / `vac_verify_prop` |
| `scripts/bd_patch_template.tcl` | Incremental patch template (full AXI GPIO example; running twice is safe) |
| `scripts/recipe.py` + `scripts/recipes/` | Parameterized patches: `add_axi_gpio` / `add_axi_uartlite` / `add_axi_dma_hp` / `set_fclk` / `open_irq_f2p` |
| `scripts/bd_diff.py` | Semantic BD diff (cells / CONFIG / addresses / connections), `--json`, `--fail-on-change` |
| `scripts/ps7_config.py` | Declarative PS7: `ps7.yaml` → Tcl with read-back assertions |
| `scripts/bd_upgrade.tcl` | Cross-version BD upgrade (relax version guard → upgrade_ip → export) |
| `scripts/check_build.py` | Log gate: ERROR / CRITICAL WARNING / WNS + `--explain` hints |
| `scripts/check_handoff.py` | BD ↔ `.hwh` ↔ `.bit` consistency (stale artifacts, basename pairing) |
| `mcp/vivado_as_code_server.py` | Zero-dependency stdio MCP server exposing all of the above |

## Environment variables (rebuild.tcl)

| Variable | Default | Meaning |
|---|---|---|
| `VAC_PART` | `xc7z020clg400-2` | Device |
| `VAC_TOP` | `design_1_wrapper` | Top module |
| `VAC_STOP_AFTER` | `impl` | `bd` / `synth` / `impl` |
| `VAC_SRC_DIR` | `<root>/src` | RTL directory; existing projects often use `vivado/src` |
| `VAC_XDC_DIR` | `<root>/xdc` | Constraints directory; often `vivado/xdc` |
| `VAC_BD_TCL` | `<root>/tcl/<bd>.tcl` | BD source of truth |
| `VAC_PATCH_TCL` | empty | Comma-separated patches, applied in order; **relative paths resolve against the project root** |
| `VAC_POST_BD_TCL` | empty | Property overrides after patches (e.g. PS clocks); relative to project root too |
| `VAC_EXPORT_BD` | empty | When set, export the patched BD to `outputs/` |
| `VAC_COPY_TO` / `VAC_ARTIFACT_NAME` | empty | Copy artifacts to a deploy directory, optionally renamed |
| `VAC_JOBS` | `8` | Parallel jobs |
| `VAC_CHECK_ALLOW` | empty | Regex allowlist for the log gate (`;`/`,` separated); project-level list in `<root>/.vac-lint-allow` |

## Minimal runnable example

`examples/zynq7020-min/`: PS7 + FCLK0 100 MHz + AXI DMA (MM2S looped to S2MM) + two interconnects,
**no PL pins or XDC required**, builds a bitstream on any xc7z020 board. Measured (Vivado 2020.2):
BD stage ~0.5 min, full build ~4.8 min, WNS +1.932 ns.

```bash
cd examples/zynq7020-min
vivado -mode batch -source tcl/mk_min_bd.tcl   # run once: generates tcl/design_1.tcl
../../scripts/build.ps1 -ProjectRoot .          # every later change can be clean-rebuilt
```

## Boundaries

- **Zynq-7000 (PS7) first**; plain 7-series PL projects also work. UltraScale+ MPSoC requires
  rewriting the PS section with `zynq_ultra_ps_e` / `CONFIG.PSU__*`.
- Version lock: scripts generated by `write_bd_tcl` carry a Vivado version guard (default 2020.2).
  Cross-version path: `references/version-upgrade.md`.
- Out of scope: installing/licensing Vivado, board-level pin definitions (board-specific),
  host-side application software.
