# 真实工程接入示例：把已有 Zynq 工程接到 vivado-as-code

> 这是一份**实测记录 + 可直接抄的适配文件**。对象是一个真实参赛工程：
> Zynq-7020 + PYNQ，17 个 IP + 13 个自研 RTL，BD 真源 678 行，
> 用编号补丁脚本演进，构建产物拷到 PYNQ overlay 目录。

## 1. 接入前的工程形态

```
project/
├── build.bat / build.sh            # 原构建入口（保留，不动）
├── vivado/
│   ├── rebuild.tcl                 # 原九阶段脚本（保留，不动）
│   ├── src/                        # RTL（13 个 .v）
│   ├── xdc/                        # 约束（7 个 .xdc）
│   ├── tcl/
│   │   ├── bd_design_1.tcl         # BD 真源（write_bd_tcl 导出）
│   │   └── bd_add_fm_modem.tcl     # 增量补丁（FM 调制解调）
│   └── history/                    # 历史 01~25 号补丁
└── software/pynq/main/             # overlay 目录（.bit/.hwh 改名后放这里）
```

和工具链默认布局的差异：`src/`、`xdc/` 在 `vivado/` 下，BD 在 `vivado/tcl/`，
产物要改名复制到 `software/pynq/main/`。

## 2. 接入只加 2 个文件（不改原工程任何文件）

### 2.1 `vivado/rebuild_vac.tcl`（适配器）

把原布局翻译成环境变量，再 source 工具链模板：

```tcl
set _here  [file normalize [info script]]
set _root  [file dirname [file dirname $_here]]
set _toolkit "D:/vivado-as-code"          ;# 或读 $env(VIVADO_AS_CODE)

set env(VAC_ROOT)          $_root
set env(VAC_SRC_DIR)       vivado/src      ;# 关键：RTL 不在根目录
set env(VAC_XDC_DIR)       vivado/xdc
set env(VAC_BD_TCL)        vivado/tcl/bd_design_1.tcl
set env(VAC_PATCH_TCL)     "vivado/tcl/bd_add_fm_modem.tcl,vivado/tcl/patch_fix_bd_issues.tcl"
set env(VAC_POST_BD_TCL)   vivado/tcl/post_bd_uart_aclk.tcl
set env(VAC_COPY_TO)       software/pynq/main
set env(VAC_ARTIFACT_NAME) xinhao_uart_kb_adf4351_rf

source [file join $_toolkit templates rebuild.tcl]
```

完整文件见本目录 [`rebuild_vac.tcl`](rebuild_vac.tcl)。

### 2.2 `vivado/tcl/post_bd_uart_aclk.tcl`（原工程已有的一行修补）

AXI UART Lite 的分频按 `C_S_AXI_ACLK_FREQ_HZ` 计算；板上实际 FCLK0 是 55.56 MHz
（FSBL 决定），BD 里写的是 100 MHz。原脚本在 source BD 之后覆盖一次，接进来时
用 `VAC_POST_BD_TCL` 保持同样行为：

```tcl
set_property CONFIG.C_S_AXI_ACLK_FREQ_HZ {55560000} [get_bd_cells axi_uartlite_0]
```

### 2.3 可选：`.vac-lint-allow`（项目级白名单）

构建日志里"确认无害但无法在 BD 里消除"的警告写在这里（每行一个正则，`#` 注释），
`build.ps1` / `build.sh` 会自动传给 `check_build.py --allow`。
本工程的用法见 [`.vac-lint-allow`](.vac-lint-allow)。

## 3. 第一次构建：门禁抓到 3 类问题

```powershell
D:/vivado-as-code/scripts/build.ps1 -ProjectRoot . `
    -RebuildScript vivado/rebuild_vac.tcl -StopAfter bd
```

结果：Vivado 退出码 0，但门禁 FAIL —— 原流程（`build.bat`）从没检查过 CRITICAL WARNING：

| # | 警告 | 真实含义 | 处理 |
|---|---|---|---|
| 1 | `BD 41-759` `/axi_mem_intercon/S02_ARESETN` | `NUM_SI=3`，但 `S02_AXI` **从未连接**（历史残留） | 改 `NUM_SI=2` |
| 2 | `BD 41-759` `/xlconcat_0/In1` | 只建了网名 `axi_dma_0_s2mm_introut`，**没接驱动** → S2MM 中断进不了 PS | 连上 `axi_dma_0/s2mm_introut` |
| 3 | `BD 41-759` `/mod_demod_mux_0/s_axis0_tvalid` 等 | FM 补丁创建的 AM 预留通道，本就不用 | 显式接常量 0 |

第 2 条解释了工程文档里"PYNQ 2.4 DMA 中断不可用、改成轮询"的现象——中断线其实没接上。

修复写成幂等补丁 [`patch_fix_bd_issues.tcl`](patch_fix_bd_issues.tcl)，挂在 `VAC_PATCH_TCL` 末尾。
修复后重新构建：**0 ERROR / 0 CRITICAL**，日志里残余的 3 条均为补丁中间态（已进白名单并注明原因）。

## 4. 用 `bd_diff.py` 看清"这次构建到底改了什么"

```bash
python D:/vivado-as-code/scripts/bd_diff.py \
    vivado/tcl/bd_design_1.tcl outputs/bd_final.tcl
```

```
cells added (8):
  + adc_dac_loopback_v2_0, axi_gpio_modem, axis_mux4_0,
    fm_demodulator_0, fm_modulator_0, mod_demod_mux_0,
    xlconstant_tie0, xlslice_modem_sel
config changed:
  ~ adc_dac_loopback_0.SELECT_CH: 2 -> None
  ~ ps7_0_axi_periph.NUM_MI: 8 -> 9
  ~ axi_mem_intercon.NUM_SI: 3 -> 2
address changed:
  ~ axi_gpio_modem/S_AXI/Reg -> 0x41240000
connections added: 12 条
```

一眼就能看出"FM 补丁加了什么、我们修了什么"，而不是 700 行 TCL 的文本 diff。

## 5. 构建结果（本机 Vivado 2020.2，12 并发）

| 阶段 | 结果 |
|---|---|
| BD 阶段（`-StopAfter bd`） | **0.8 分钟**，20 IP + 12 RTL module_ref，`.hwh` 827 KB |
| 产物一致性（`check_handoff.py`，用**导出后的 BD** 对比 `.hwh`） | **PASS**（32 MODULE 全部对上） |
| 全量（`-StopAfter impl`） | **16.1 分钟**，`.bit` 3.95 MB，LUT 53.1% / FF 6.8% / BRAM 3.2% |
| 时序门禁 | ❌ **WNS = -0.070 ns**（单条违例），门禁以退出码 3 拦下 |

### 5.1 时序违例分析（门禁抓到的第 4 个真实问题）

```
Slack (VIOLATED): -0.070ns
Source:      axi_gpio_loop/U0/gpio_core_1/Dual.gpio_Data_Out_reg[13]_replica_5/C
Destination: loop_player_0/inst/bram_reg_15040_15103_9_11/RAMA/WADR2
Path Group:  clk_fpga_0 (10 ns)
Data Path:   9.629ns = logic 0.379ns + route 9.250ns   ← 96% 是布线延迟，0 级逻辑
```

特征：**只有 1 条路径违例、0 级逻辑、96% 是布线**，属于布局布线主导的边际违例
（不是逻辑太深）。这条路径（`axi_gpio_loop` 输出寄存器 → `loop_player` 的 BRAM 写地址）
不在本次接入改动范围内（我们改的是 `NUM_SI`、S2MM 中断连线、两个预留 `tvalid` 的常量），
所以判为**原工程既有的边际违例**；对照实验（同工具链、不打修复补丁）见
`docs/verification.md` 的 V20。

给工程所有者的建议（按成本从低到高）：

1. `launch_runs impl_1 -jobs 12` + `-directive Explore`（换布局策略，边际违例常能翻正）；
2. 给这条路径加 `set_multicycle_path` 或把 `axi_gpio_loop` 的输出先在本地打一拍
   （它在 BD 里直接驱动 `loop_player` 的 BRAM 地址，跨了半片器件）；
3. 用 Pblock 把 `loop_player` 约束到 `axi_gpio_loop` 附近；
4. 时序目标放宽到实际板上 55.56 MHz（若 BD 设计值仍是 100 MHz，按实际时钟约束可释放裕量）。

> 注意：`check_handoff` 要拿"构建后导出的 BD"（`VAC_EXPORT_BD`）去比 `.hwh`；
> 用原始 `bd_design_1.tcl` 比会漏掉补丁新增的 IP，那是预期行为。

## 6. 复用清单

把这三个文件抄到你自己的工程，改路径即可：

1. [`rebuild_vac.tcl`](rebuild_vac.tcl) —— 目录/补丁/产物映射；
2. `vivado/tcl/post_bd_*.tcl` —— 原工程里"source BD 之后"的那些 set_property；
3. [`.vac-lint-allow`](.vac-lint-allow) —— 只有确认无害的才写进来，并注明原因。
