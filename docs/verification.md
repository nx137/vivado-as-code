# 验证记录

环境：Windows 10/11 · Vivado **2020.2** · 器件 `xc7z020clg400-2` · 2026-11-02。

## V1 — 只重建 BD（`StopAfter=bd`）

```bash
scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter bd
```

结果：✅ Vivado 退出码 0，耗时 **0.5 分钟**；
产物 `outputs/design_1_wrapper.hwh`（约 300 KB）+ `build_manifest.json`；
`check_build.py`：ERROR 0 / CRITICAL WARNING 0 / `RESULT: PASS`。

## V2 — 增量补丁幂等性

验证必须让**同一次构建**把补丁跑两遍（只跑两次 build 不算：每次都是干净重建）：

```bash
VAC_PATCH_TCL="patch_add_gpio.tcl,patch_add_gpio.tcl" \
VAC_EXPORT_BD=bd_exported.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

| 运行 | 补丁执行次数 | 导出 BD |
|---|---|---|
| A | 1 次 | 16,337 bytes |
| B | 2 次（第二次走"已连接，跳过"分支） | 16,337 bytes |

结果：✅ 两次导出的 `bd_exported.tcl` **SHA256 完全一致**（幂等成立）。

第一版补丁并不幂等：`NUM_MI` 从 1→2→3，第二次运行把 AXI 互连多扩了一个口。
修复方式：整段"扩互连 + 接线 + 分地址"用"S_AXI 是否已连接"统一判断。

## V3 — 全量构建出 bit

```bash
scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter impl
```

结果：✅ 退出码 0，耗时 **4.8 分钟**（287 s）

| 产物 | 大小 |
|---|---|
| `design_1_wrapper.bit` | 3,950.9 KB |
| `design_1_wrapper.hwh` | 296 KB |
| `build_manifest.json` | `status=ok`, `wns=1.932`, `elapsed_sec=287` |
| `timing_summary.txt` / `utilization.txt` | 已生成 |

时序：**WNS = +1.932 ns**（满足），日志门禁 PASS。

## V4 — 日志门禁负例

构造只含一条 `CRITICAL WARNING: [BD 41-759] ...` 的假日志：

```bash
python scripts/check_build.py fake_vivado.log
# ERROR 0 / CRITICAL WARNING 1 / RESULT: FAIL
# exit code = 2
```

结果：✅ 正确拦截（退出码 2）。

## V4b — 产物一致性检查（`check_handoff.py`）

- 正例：`BD(5 IP) ↔ .hwh(5 MODULE)` → `RESULT: PASS`，退出码 0；
- 负例：`.bit` 不存在 → 明确报错，退出码 4。

（首版正则过严，`<MODULE>` 属性顺序不固定导致误报 0 个 MODULE，已修复。）

## V5 — PS7 时钟配方（FCLK0 100 → 150 MHz）

```tcl
set ps [get_bd_cells processing_system7_0]
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150} $ps
```

回读结果：

```
ACT_FPGA0 = 150.000000
CLK0_FREQ = 150000000
DIV0 = 4  DIV1 = 3        # 1800 / 4 / 3 = 150 MHz
```

导出的 BD TCL 中对应行：

```tcl
CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ {150.000000}
CONFIG.PCW_CLK0_FREQ {150000000}
CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR0 {4}
CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR1 {3}
```

结果：✅ 只改一个"用户意图"属性，Vivado 自动重算分频。

## V6 — 新助手可用性测试

由全新上下文的 AI 助手只依据 `SKILL.md` 完成"给示例加 AXI GPIO 并重建 BD"：

| 检查 | 结果 |
|---|---|
| 构建退出码 | 0 |
| 日志 CRITICAL WARNING | **0** |
| 导出的 BD / `.hwh` 中出现 `axi_gpio_user` | ✅ / ✅ |
| 补丁幂等性（同轮 1 次 vs 2 次） | ✅ 导出 BD 哈希一致 |
| 是否需要口头提示 | ❌ 不需要，仅靠文档完成 |

暴露并已修复的 6 处问题（详见 `docs/usability.md`）：
守卫库路径解析、`VAC_PATCH_TCL` 相对路径、模板回读不全、幂等验证写法、
BD 阶段 `.hwh` 说明、示例文件名不一致。

## V7 — 技能加载

`git clone --depth 1` 到 `~/.claude/skills/vivado-as-code` 与 `~/.dsh/skills/vivado-as-code`，
两个目录均含 `SKILL.md`（根级）+ `references/`（5 篇）。

结果：✅ 宿主在下一次会话刷新时**自动把 `vivado-as-code` 加入可用技能列表**，
说明目录结构与 frontmatter（`name` / `description` / `license`）符合两套技能系统的约定。

## V8 — 干净 clone 端到端验收

```bash
git clone --depth 1 https://github.com/nx137/vivado-as-code.git /tmp/vac
cd /tmp/vac
scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter bd
```

结果：✅ 退出码 0，`RESULT: PASS`，生成 `design_1_wrapper.hwh` 与 `build_manifest.json`。
即"clone 即可重建"成立（本机 Vivado 自动探测到 `E:\Xilinx\Vivado\2020.2`）。

---

# v0.2 验证（2026-11-02）

## V9 — 单元测试

```bash
python -m unittest discover -s tests -t . -v
```

结果：✅ **47 个用例全部通过**（约 2.5 秒，不需要 Vivado）。
覆盖：`check_build`（计数/白名单/时序/诊断）、`check_handoff`（正负例/同名）、
`bd_diff`（解析/差异/CLI 退出码）、`recipes`（5 个模板渲染/参数覆盖/文件保护）、
`templates_sync`（模板与示例副本一致、技能 frontmatter、BOM）、
`mcp_protocol`（initialize/tools/list/tools/call/错误码）。

## V10 — CI

`.github/workflows/ci.yml`：`ubuntu-latest` + `windows-latest` × Python 3.9/3.12，
执行 `compileall` → `unittest discover` → `mcp --self-test`，不安装 Vivado。

## V11 — BD 语义 diff（真实 BD）

对比 `examples/zynq7020-min/tcl/design_1.tcl` 与"用 recipe 加了 AXI GPIO 后"的导出：

```
cells added (1):
  + axi_gpio_recipe
config changed (6):
  ~ axi_gpio_recipe.C_GPIO_WIDTH: None -> 16
  ~ ps7_0_axi_periph.NUM_MI: 1 -> 2
address changed (1):
  ~ axi_gpio_recipe/S_AXI/Reg: None -> {'offset': '0x41240000', 'range': '0x00010000'}
connections added (1):
  + axi_gpio_recipe/S_AXI <-> ps7_0_axi_periph/M01_AXI
```

结果：✅ 与预期完全一致；`--json` 输出可机读。

## V12 — recipe 渲染 + 构建 + 幂等

```bash
python scripts/recipe.py render add_axi_gpio -p name=axi_gpio_recipe -p width=16 -o tcl/patch_gpio.tcl
VAC_PATCH_TCL=tcl/patch_gpio.tcl VAC_EXPORT_BD=patched.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

结果：✅ 退出码 0、0 CRITICAL；导出 BD 中 `CONFIG.C_GPIO_WIDTH {16}` 与回读一致；
同轮双跑补丁（`patch,patch`）导出的 BD 与单跑**哈希一致**。

## V13 — 日志诊断（真实日志注入已知问题）

在真实构建日志末尾注入一条 `CRITICAL WARNING: [BD 41-759] ...` 后：

```bash
python scripts/check_build.py build.log --explain
```

结果：✅ 退出码 2，输出：

```
HINTS (with action):
  [BD-41-759] unconnected input pins were tied to 0 (x1)
      -> connect the per-port resets (S00_ARESETN/M00_ARESETN ...) or set CONFIG.HAS_ARESETN {0}
      ref: references/pitfalls.md B3
```

## V14 — MCP 端到端

以子进程方式启动 server，依次调用 `initialize` / `tools/list` / `tools/call`：

| 工具 | 结果 |
|---|---|
| `tools/list` | ✅ 6 个工具（vac_build / vac_check_log / vac_bd_diff / vac_bd_export / vac_check_handoff / vac_recipe_render） |
| `vac_build`（`stop_after=bd`） | ✅ exit_code 0，critical_warnings 0，errors 0 |
| `vac_check_log` | ✅ exit_code 0，suggestions 0 |
| `vac_bd_diff` | ✅ `cells_added=["axi_gpio_recipe"]`，`NUM_MI 1->2` |
| `vac_check_handoff` | ✅ status=pass |
| `vac_recipe_render` | ✅ 生成 `post_fclk.tcl`（含 `PCW_FPGA0_PERIPHERAL_FREQMHZ {150}`） |

协议错误处理：未知工具 → `-32602`；未知方法 → `-32601`；非法 JSON → `-32700`；
工具异常 → `isError: true`（不会让 server 崩溃）。
---

# 真实工程接入验证（2026-11-02）

对象：真实参赛工程（Zynq-7020 + PYNQ），**不改动原工程任何文件**，
只在工程里新增 2 个适配文件，用 `-RebuildScript` 切入工具链：

- `vivado/rebuild_vac.tcl`：把 `vivado/src`、`vivado/xdc`、`vivado/tcl/*.tcl`、
  PYNQ 覆盖目录映射成 `VAC_SRC_DIR` / `VAC_XDC_DIR` / `VAC_BD_TCL` / `VAC_PATCH_TCL` /
  `VAC_POST_BD_TCL` / `VAC_COPY_TO` / `VAC_ARTIFACT_NAME`；
- `vivado/tcl/post_bd_uart_aclk.tcl`：保留原脚本"source BD 后覆盖 UART ACLK"的行为。

## V15 — 首次接入：日志门禁抓到 3 类问题

```powershell
scripts/build.ps1 -ProjectRoot . -RebuildScript vivado/rebuild_vac.tcl -StopAfter bd
```

Vivado 退出码 0（原流程 `build.bat` 从不检查 CRITICAL WARNING），门禁 FAIL：

| # | 警告 | 真实含义 |
|---|---|---|
| 1 | `BD 41-759 /axi_mem_intercon/S02_ARESETN` | `NUM_SI=3`，但 `S02_AXI` 从未连接（历史残留） |
| 2 | `BD 41-759 /xlconcat_0/In1` | 只建了网名 `axi_dma_0_s2mm_introut`，没接驱动 → S2MM 中断进不了 PS |
| 3 | `BD 41-759 /mod_demod_mux_0/s_axis0/2_tvalid` | FM 补丁的 AM 预留通道，本就未使用 |

第 1、2 条是**真 bug**（第 2 条解释了文档里"PYNQ DMA 中断不可用、改轮询"的现象），
第 3 条显式接常量 0 即可。修复写成幂等补丁 `vivado/tcl/patch_fix_bd_issues.tcl`。

## V16 — 修复后重建：0 ERROR / 0 CRITICAL

```
ERROR            : 0
CRITICAL WARNING : 0
ignored (allow)  : 3     # 均为补丁中间态，已在 .vac-lint-allow 注明原因
RESULT: PASS
```

- BD 阶段耗时 **0.8 分钟**；
- 最终设计：20 个 IP + 12 个 RTL module_ref；
- "补丁之后不再出现 CRITICAL"已用日志行号验证（修复输出行 650+，CRITICAL 只在 291/347/627）。

## V17 — BD 语义 diff（真实工程）

```bash
python scripts/bd_diff.py vivado/tcl/bd_design_1.tcl outputs/bd_final.tcl
```

```
cells added (8):
  + adc_dac_loopback_v2_0, axi_gpio_modem, axis_mux4_0,
    fm_demodulator_0, fm_modulator_0, mod_demod_mux_0,
    xlconstant_tie0, xlslice_modem_sel
config changed:
  ~ ps7_0_axi_periph.NUM_MI: 8 -> 9
  ~ axi_mem_intercon.NUM_SI: 3 -> 2      # 本次修复
address changed:
  ~ axi_gpio_modem/S_AXI/Reg -> 0x41240000
connections added: 12
```

结论：FM 补丁 + 本次修复的改动被完整、可读地呈现，无需人工读 700 行 TCL。

## V18 — 产物一致性（BD ↔ .hwh）

```bash
python scripts/check_handoff.py --bd outputs/bd_final.tcl --hwh outputs/design_1_wrapper.hwh
```

```
BD   : 20 IP cells, 12 RTL module_ref
.hwh : 32 MODULE entries
RESULT: PASS
```

> 接入时发现并修复了工具链的一个真实缺陷：`write_bd_tcl` 对 module_ref 生成的是
> 变量形式（`set block_cell_name ...` + `create_bd_cell ... $block_cell_name`），
> 原解析器把 `$block_cell_name]` 当成实例名，导致 `.hwh` 里 12 个 module_ref 被误判为
> "多余模块"。已修复并补了回归测试（`bd_with_module_ref.tcl` fixture）。

## V19 — 全量构建（-StopAfter impl）

| 项目 | 结果 |
|---|---|
| 耗时 | **16.1 分钟**（961 s，12 并发） |
| 产物 | `.bit` 3.95 MB、`.hwh` 827 KB、timing/utilization 报告 |
| 资源 | LUT 28250 (53.1%)、FF 7194 (6.8%)、BRAM 4.5 (3.2%)、DSP 3 |
| 时序 | ❌ **WNS = -0.070 ns**（TNS -0.070，仅 1 条失败路径） |
| 门禁 | 正确以退出码 3 拦下（Vivado 本身退出码 0、bit 照出） |

违例路径：

```
Source:      axi_gpio_loop/U0/gpio_core_1/Dual.gpio_Data_Out_reg[13]_replica_5/C
Destination: loop_player_0/inst/bram_reg_15040_15103_9_11/RAMA/WADR2
Path Group:  clk_fpga_0 (10 ns)
Data Path:   9.629ns = logic 0.379ns + route 9.250ns   (96% route, 0 logic levels)
```

结论：这是**布局布线主导的边际违例**，属于原工程既有问题（不在本次接入改动范围内）。
门禁的价值正在于此：Vivado 认为"构建成功"，但设计其实差 70 ps。

## V20 — A/B 对照：同工具链、不打修复补丁

为了排除"接入改动（NUM_SI 3→2、S2MM 中断连线、预留 tvalid 接常量）引入了时序退化"：

```powershell
scripts/build.ps1 -ProjectRoot . `
    -RebuildScript vivado/rebuild_vac_orig.tcl -StopAfter impl
```

（`rebuild_vac_orig.tcl` 与正式适配器相同，只是 `VAC_PATCH_TCL` 不含 `patch_fix_bd_issues.tcl`）

对照结果：

| 版本 | WNS | 违例路径数 | 耗时 |
|---|---|---|---|
| 原设计（不加修复补丁） | **-0.494 ns** | 2 | 14.6 分钟 |
| 接入版（含修复补丁） | **-0.070 ns** | 1 | 16.1 分钟 |

结论：
1. **时序违例是原工程既有的**（原设计更差），不是接入引入；
2. 修复补丁（去掉未使用的 `S02_AXI`、补 S2MM 中断、预留 tvalid 接常量）
   把 WNS 从 -0.494 改善到 -0.070 —— 去掉多余 AXI 主口减少了布线压力；
3. 但仍有 1 条边际违例（-0.070 ns），需要工程所有者按
   `examples/real-project-adoption/README.md` §5.1 的四条建议处理（换布局策略 / 打拍 /
   Pblock / 按板上 55.56 MHz 约束）。

另：原始 `build.bat`（`-jobs 26`）在本机跑到 synth 阶段卡在 `wait_on_run synth_1`
（Vivado 作业队列未推进，runme.log 未生成），因此对照改用"同工具链、不打修复补丁"的
方式完成；这本身也说明接入版把并发降到 12 后更稳定。

## 接入过程对工具链的改进

| 改进 | 来源 |
|---|---|
| `VAC_SRC_DIR` / `VAC_XDC_DIR` | 已有工程 RTL/XDC 不在根目录 |
| `VAC_COPY_TO` 相对路径按项目根解析 | PYNQ 覆盖目录是相对路径 |
| `VAC_CHECK_ALLOW` + 项目级 `.vac-lint-allow` | 补丁中间态噪声需要"可审计的白名单" |
| module_ref 变量形式解析（bd_diff / check_handoff） | 真实 BD 用变量声明 module_ref |
| MCP `vac_build` 支持 `rebuild_script` | 接入工程用自己的适配入口 |
---

# v0.3 验证（2026-11-02）

## V21 — PS7 声明式配置

```bash
python scripts/ps7_config.py check examples/ps7/ps7.example.yaml
python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl
VAC_POST_BD_TCL=tcl/post_bd_ps7.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

单元测试：`tests/test_ps7_config.py` **24 个用例**通过（YAML 子集解析、schema 校验、
Tcl 生成、CLI、proc 作用域/表达式回归）。

端到端（示例工程，`clocks.fclk0: 150`）：

```
[ps7] FCLK0 = 150 MHz (ACT=150.000000)
[ps7] HP 口: 0=1 1=0 2=0 3=0
[ps7] DDR highaddr = 0x3FFFFFFF
[ps7] 配置完成
RESULT: PASS   (0 ERROR / 0 CRITICAL)
```

生成物包含"设置 + 回读断言"：频率偏差 >0.01 MHz 直接 `exit 1`，IRQ/DDR 也回读打印。

## V22 — 跨 Vivado 版本升级助手（同版本往返）

```bash
vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs \
    tcl/design_1.tcl upgraded_design_1.tcl xc7z020clg400-2
```

结果：✅ 退出码 0，日志 **0 ERROR / 0 CRITICAL**，导出新真源 15,470 bytes。

回归：

| 检查 | 结果 |
|---|---|
| 用升级后的 BD TCL 重建 BD | ✅ 0.4 分钟，`RESULT: PASS`，0 CRITICAL |
| `bd_diff.py` 对比升级前后 | ✅ `no semantic changes` |

> 同版本往返是"升级流程不破坏设计"的基线；真正跨版本（如 2020.2 → 2022.2）时脚本会
> 执行 `upgrade_ip`，打印升级前后 IPDEF 列表，需按 `references/version-upgrade.md` 做回归。

## V23 — MCP 扩到 8 个工具

新增 `vac_ps7_render` / `vac_bd_upgrade`；`tests/test_mcp_protocol.py` 覆盖：
tools/list 返回 8 个工具、`vac_ps7_render` 生成 Tcl 文件、协议错误码不变。

## V24 — 全套英文文档

- `README.en.md`：完整英文 README（与中文版结构一致）；
- `SKILL.en.md`：完整英文技能入口（铁律、决策表、脚本表、环境变量、边界）；
- 两份文档与中文版互相链接。

测试总数：**74 个**（新增 PS7 24 个 + 变量 module_ref 2 个 + 既有 48 个）。
