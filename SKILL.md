---
name: vivado-as-code
description: >
  用全量 TCL 脚本驱动 Xilinx Vivado，把 Zynq/FPGA 工程做成"工程即代码"：
  不提交 .xpr，用 rebuild.tcl 一键全量重建，用 write_bd_tcl 把 Block Design
  固化成文本真源，通过 CONFIG.PCW_* 在 Tcl 里配置 Zynq PS7（时钟/PLL、HP 口、
  IRQ、MIO 外设、DDR），并用幂等补丁脚本演进设计。
  Use for Vivado full-Tcl flow, Block Design as code, Zynq PS7 configuration,
  write_bd_tcl round-trip, reproducible bitstream without .xpr, PYNQ overlay
  handoff, BD semantic diff, and idempotent BD patches.
  当用户提到 "Vivado 全量脚本"、"Block Design 用 Tcl 建"、"PS 端配置"、
  "write_bd_tcl"、"clone 就能重建"、"BD diff" 时使用。
license: MIT
---

# vivado-as-code

把 Vivado 工程从"GUI 里点点点 + 提交一堆二进制"变成"文本脚本 + 一条命令重建"。

## 这套方法解决什么问题

- `.xpr/.runs/.gen` 不可 diff、冲突无法合并、换台机器就编译不出来；
- BD 里改了什么没人知道，只有工程文件能回答；
- PS 端（Zynq 时钟、HP 口、中断、MIO）配置只存在于 GUI 状态里。

做法：**所有真源都是文本** —— `src/*.v`、`xdc/*.xdc`、`tcl/<bd>.tcl`、`vivado/rebuild.tcl`。

## 五条铁律

1. **仓库不提交 `.xpr` / `.runs` / `.gen`**，只提交 RTL、XDC、BD TCL、构建脚本。
2. **BD 的改动必须落到 `tcl/<bd>.tcl`** —— GUI 改完立刻 `write_bd_tcl -force` 回写（用 `scripts/bd_export.tcl`）。
3. **每次验证都做全量重建**（删工程重跑），不要依赖增量缓存，否则"本地能过、别人 clone 不过"。
4. **构建成功 ≠ 正确**：Vivado 里 IP 参数名写错只报 `CRITICAL WARNING`，照样出 bit。
   必须跑 `scripts/check_build.py`（0 条 CRITICAL 才算过）。
5. **产物必须成对且同名**：`.bit` + `.hwh` 同名同目录，否则 PYNQ `Overlay()` 解析不出 `ip_dict`。

## 如果宿主已挂载本仓库的 MCP（优先用工具）

`mcp/vivado_as_code_server.py` 提供 8 个工具，比手拼命令更可靠（参数校验、结构化返回）：

| 工具 | 什么时候用 |
|---|---|
| `vac_build` | 跑构建；先 `stop_after=bd` 验证 BD，再 `impl` 出 bit |
| `vac_check_log` | 构建后看 ERROR/CRITICAL/WNS + 已知问题建议 |
| `vac_bd_diff` | 改完 BD 看语义差异（新增 cell / CONFIG / 地址） |
| `vac_bd_export` | GUI 改完回写真源 |
| `vac_check_handoff` | 交付 PYNQ 前检查 `.bit/.hwh` 一致性 |
| `vac_recipe_render` | 生成参数化补丁（GPIO/UART/DMA/时钟/中断） |
| `vac_ps7_render` | 把 `ps7.yaml` 渲染成带回读断言的 Tcl |
| `vac_bd_upgrade` | 跨 Vivado 版本升级 BD 并导出新真源 |

接入方式见 `mcp/README.md`（`.mcp.json` 一份配置同时适用 Claude Code 与 DSH）。
没有 MCP 时，按下文用 CLI 完成同样的操作。

## 快速上手（3 步）

```bash
# 1) 放进技能的搜索路径（或任意位置，直接读本文件也行）
git clone <this-repo> ~/.claude/skills/vivado-as-code     # Claude Code
git clone <this-repo> ~/.dsh/skills/vivado-as-code        # DeepSeek Harness

# 2) 用模板起一个工程（或改造已有工程：保留 src/ xdc/，把 BD 导出成 tcl/design_1.tcl）
mkdir -p myproj/vivado
cp -r templates/project-skeleton/. myproj/
cp templates/rebuild.tcl myproj/vivado/rebuild.tcl
cp -r scripts myproj/scripts          # 可选，让工程自带工具链（也能直接用本仓库的 scripts/）

# 3) 构建（自动探测 Vivado；先只验 BD 再全量）
scripts/build.ps1 -ProjectRoot myproj -StopAfter bd     # Windows，约 1 分钟
scripts/build.sh  -p myproj -s bd                       # Linux/macOS
scripts/build.ps1 -ProjectRoot myproj                    # 全量出 bit
```

产物：`outputs/<top>.bit`、`outputs/<top>.hwh`、`outputs/build_manifest.json`、
`outputs/timing_summary.txt`、`outputs/utilization.txt`。
注意：`StopAfter=bd` 时也会生成 `.hwh`（但没有 `.bit`），可直接拿去做 PYNQ 的地址验证。

## 决策树：要做哪类改动？

| 需求 | 做法 | 读这篇 |
|---|---|---|
| 改 PS 时钟 / PLL / 分频 | 推荐声明式：`ps7.yaml` 写 `clocks.fclk0: 150` → `python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl`，产物自带回读断言 | `references/ps7-config.md` |
| 新开 DDR 高速口 / 加第二个 DMA | `ps7.yaml` 的 `hp_ports: [0, 1]`；BD 侧用独立 interconnect | `references/ps7-config.md` |
| 打开 PL→PS 中断 | `ps7.yaml` 的 `irq_f2p: true` + BD 侧 `axi_intc` | `references/ps7-config.md` |
| 加一个外设 IP（GPIO/UART/DMA…） | 优先用参数化 recipe：`python scripts/recipe.py render add_axi_gpio -p name=xxx --out tcl/patch_gpio.tcl`；复杂改动再写幂等补丁，挂到 `VAC_PATCH_TCL` | `scripts/recipes/` + `references/bd-patterns.md` |
| 看 BD 到底改了什么 | `python scripts/bd_diff.py a.tcl b.tcl`（加 `--json` / `--fail-on-change`） | `references/bd-patterns.md` §6 |
| 构建失败 / 时序不过 / 硬件不工作 | `python scripts/check_build.py build.log --explain`，再按"症状 → 根因 → 检查命令"查表 | `references/pitfalls.md` |
| 加/改 RTL 模块 | 放 `src/`，BD 里 `create_bd_cell -type module -reference` | `references/bd-patterns.md` |
| 从 GUI 改完 BD 回写真源 | `scripts/bd_export.tcl`（自动存档旧版本） | `references/bd-patterns.md` |
| 接入已有工程（不改原布局） | 写 `vivado/rebuild_vac.tcl` 适配器设置 `VAC_SRC_DIR`/`VAC_XDC_DIR`/`VAC_PATCH_TCL` 等，`-RebuildScript` 指向它 | `examples/real-project-adoption/` + `references/build-pipeline.md` §7 |
| 升级到新版本 Vivado | `vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs 旧.tcl 新.tcl <part>`，再用 `bd_diff.py` 复核 | `references/version-upgrade.md` |
| bit 交给 PYNQ 板子 | 同名 `.bit/.hwh` + FS 常量校准 | `references/pynq-handoff.md` |

## 脚本一览

| 脚本 | 作用 |
|---|---|
| `scripts/build.ps1` / `build.sh` | 入口：探测 Vivado → 跑 rebuild → 日志门禁 → 透传退出码 |
| `templates/rebuild.tcl` | 参数化九阶段构建（`VAC_STOP_AFTER` 可只到 bd/synth/impl） |
| `scripts/bd_export.tcl` | `write_bd_tcl -force` 回写 BD + 带时间戳存档 |
| `scripts/lib/guards.tcl` + `guard_loader.tcl` | 幂等守卫：`vac_ensure_ip` / `vac_connect_net_if_free` / `vac_ensure_addr` / `vac_verify_prop` |
| `scripts/bd_patch_template.tcl` | 增量补丁模板（加 AXI GPIO 的完整示例，连跑两次结果一致） |
| `scripts/recipe.py` + `scripts/recipes/` | 参数化补丁渲染：`add_axi_gpio` / `add_axi_uartlite` / `add_axi_dma_hp` / `set_fclk` / `open_irq_f2p` |
| `scripts/bd_diff.py` | BD 语义 diff（cell / CONFIG / 地址 / 连线），`--json`、`--fail-on-change` |
| `scripts/check_build.py` | 日志门禁：ERROR / CRITICAL WARNING / WNS + `--explain` 修复建议 |
| `scripts/check_handoff.py` | BD ↔ `.hwh` ↔ `.bit` 一致性（防产物过期/不同名） |
| `scripts/ps7_config.py` | 声明式 PS7 配置：`ps7.yaml` → 带回读断言的 Tcl |
| `scripts/bd_upgrade.tcl` | 跨 Vivado 版本升级 BD（放宽版本校验 → upgrade_ip → 导出新真源） |
| `mcp/vivado_as_code_server.py` | MCP server（零依赖 stdio），把上面这些暴露成 AI 工具 |

## 环境变量（rebuild.tcl）

| 变量 | 默认 | 说明 |
|---|---|---|
| `VAC_PART` | `xc7z020clg400-2` | 器件 |
| `VAC_TOP` | `design_1_wrapper` | 顶层 module |
| `VAC_STOP_AFTER` | `impl` | `bd` / `synth` / `impl` |
| `VAC_SRC_DIR` | `<root>/src` | RTL 目录；已有工程常写成 `vivado/src` |
| `VAC_XDC_DIR` | `<root>/xdc` | 约束目录；已有工程常写成 `vivado/xdc` |
| `VAC_BD_TCL` | `<root>/tcl/<bd>.tcl` | BD 真源 |
| `VAC_PATCH_TCL` | 空 | 逗号分隔的补丁脚本，按顺序执行；**相对路径按项目根目录解析**（如 `tcl/patch_add_gpio.tcl`） |
| `VAC_POST_BD_TCL` | 空 | 补丁之后的属性覆盖（如改 PS 时钟），相对路径同样按项目根解析 |
| `VAC_EXPORT_BD` | 空 | 设了就导出"改动后的 BD"到 `outputs/` |
| `VAC_COPY_TO` / `VAC_ARTIFACT_NAME` | 空 | 把产物复制到部署目录并可改名 |
| `VAC_JOBS` | `8` | 并行任务数 |
| `VAC_CHECK_ALLOW` | 空 | 日志白名单正则（`;`/`,` 分隔）；工程级白名单见 `<root>/.vac-lint-allow` |

## 最小可跑示例

`examples/zynq7020-min/`：PS7 + FCLK0 100MHz + AXI DMA（MM2S 自环回 S2MM）+ 两座互连，
**不需要任何 PL 引脚和 XDC**，在任意 xc7z020 板子上都能出 bit。实测（Vivado 2020.2）：
BD 阶段约 0.5 分钟，全量约 4.8 分钟，WNS +1.932 ns。

```bash
cd examples/zynq7020-min
vivado -mode batch -source tcl/mk_min_bd.tcl   # 只需跑一次：生成 tcl/design_1.tcl
../../scripts/build.ps1 -ProjectRoot .          # 之后每次改脚本都能全量重建
```

## 适用边界

- 优先 **Zynq-7000（PS7）**；7 系列纯 PL 同样适用；UltraScale+ MPSoC 需把 PS 配置段落换成 `zynq_ultra_ps_e` 的 `CONFIG.PSU__*`。
- 版本锁定：`write_bd_tcl` 生成的脚本带 Vivado 版本校验（默认 2020.2）。跨版本见 `references/pitfalls.md`。
- 不负责：Vivado 安装/许可、板级引脚定义（各板不同）、上位机软件。
