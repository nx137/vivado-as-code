# PS7 配置速查（Zynq-7000 processing_system7）

> 本文件回答："怎么用 Tcl 改 PS 的时钟、外设、DDR、HP 口、中断，以及怎么验证改对了"。
> 所有属性名都经过 Vivado 2020.2 + `xc7z020clg400-2` 实测。

## 0. 核心心智模型

PS 配置 = 在 `processing_system7` 这个 IP 上设 `CONFIG.PCW_*` 属性。

Vivado 的 PCW 属性分三类：

| 类型 | 例子 | 能否直接写 |
|---|---|---|
| 用户意图（requested） | `PCW_FPGA0_PERIPHERAL_FREQMHZ`、`PCW_USE_S_AXI_HP0` | ✅ 写这个 |
| Vivado 计算出的实际值（ACT） | `PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ`、`PCW_CLK0_FREQ` | ❌ 不要写，会被重算 |
| 分频器/反馈系数 | `PCW_FCLK0_PERIPHERAL_DIVISOR0/1`、`PCW_IOPLL_CTRL_FBDIV` | ⚠️ 通常由 Vivado 自动算，手改易冲突 |

**正确姿势**：只写用户意图，`get_property` 回读 ACT/DIVISOR 确认。

```tcl
set ps [get_bd_cells processing_system7_0]
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150} $ps
```
Vivado 会自动把 IO_PLL/分频改到能产生 150 MHz 的组合，回读：

```tcl
get_property CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ $ps   ;# 150.000000
get_property CONFIG.PCW_CLK0_FREQ $ps                      ;# 150000000
get_property CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR0 $ps      ;# 4
get_property CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR1 $ps      ;# 3
```

实测：100 MHz → DIV 6/3（1800/6/3）；改成 150 MHz → DIV 4/3（1800/4/3）。
**这就是"改频率只需要改一个属性"的原因**。

## 1. 时钟链（Zynq-7000）

```
PS_CLK 33.333MHz
  ├─ ARM PLL  → PCW_ARMPLL_CTRL_FBDIV → CPU 666/766MHz (PCW_CPU_CPU_PLL_FREQMHZ)
  ├─ DDR PLL  → PCW_DDRPLL_CTRL_FBDIV → DDR 533MHz   (PCW_DDR_DDR_PLL_FREQMHZ)
  └─ IO  PLL  → PCW_IOPLL_CTRL_FBDIV  → 1000/1800MHz (PCW_IO_IO_PLL_FREQMHZ)
        └─ FCLK0..3 = IO_PLL / DIVISOR0 / DIVISOR1
             PCW_FPGA_FCLK0_ENABLE = 1
             PCW_FPGA0_PERIPHERAL_FREQMHZ = <请求值>
             PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ = <实际值>
```

常见约束：FCLK0 请求 100 MHz 时 IO_PLL=1800、÷6÷3；请求 150 MHz 时 ÷4÷3。

## 2. 菜谱

### 2.1 改 FCLK0 频率（最常用）

```tcl
set ps [get_bd_cells processing_system7_0]
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150} $ps
# 回读
puts [get_property CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ $ps]
```

放进 `VAC_POST_BD_TCL` 就能"每次重建都生效"，例如 `tcl/post_fclk.tcl`。

> ⚠️ 改完记得同步软件侧常量（PYNQ 的 `FS`），否则频率轴整体错。见 `references/pynq-handoff.md`。

### 2.2 新开一个 DDR 高速口（给第二个 DMA）

```tcl
set_property -dict [list \
    CONFIG.PCW_USE_S_AXI_HP1 {1} \
] [get_bd_cells processing_system7_0]
```

然后给新 HP 口建**独立的** AXI interconnect（不要复用已有多主口互连）：

```tcl
set ic [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_mem_intercon_1]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $ic
```

复用同一个 interconnect 扩 `NUM_SI` 是常见翻车点：XCI 丢失、`.hwh` 里缺 MEMRANGE、
读通道静默不工作。**一个 DMA 一个 HP 口一条互连最稳**。

### 2.3 打开 PL→PS 中断（PYNQ + axi_intc）

```tcl
set_property -dict [list \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR {1} \
] [get_bd_cells processing_system7_0]
```
BD 侧需要 `axi_intc`：`concat → intc → IRQ_F2P`，intc 挂到 GP0（例如 `0x41800000`）。

> ⚠️ PYNQ 2.4 上 DMA 中断经常不可用（`ip_dict[...]['interrupts']` 为空、`wait()` 挂死），
> 最稳的是**轮询 DMA 状态寄存器**，别把中断当必需项。

### 2.4 打开 MIO 外设（UART/SDIO/ENET/QSPI/USB）

```tcl
set_property -dict [list \
    CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_UART1_UART1_IO {MIO 48 .. 49} \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_QSPI_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {1} \
] [get_bd_cells processing_system7_0]
```

MIO 分配必须与板子原理图一致；写错不会报 ERROR，只在 `.hwh`/生成的设计里体现。

### 2.5 DDR 地址范围

```tcl
get_property CONFIG.PCW_DDR_RAM_HIGHADDR [get_bd_cells processing_system7_0]  ;# 0x3FFFFFFF = 1GB
```

HP 口地址映射（BD 里 assign）：

```tcl
assign_bd_address -offset 0x00000000 -range 0x40000000 \
    -target_address_space [get_bd_addr_spaces axi_dma_0/Data_MM2S] \
    [get_bd_addr_segs processing_system7_0/S_AXI_HP0/HP0_DDR_LOWOCM] -force
```

## 3. 验证清单（改完 PS 必做）

```tcl
set ps [get_bd_cells processing_system7_0]
foreach p {PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ PCW_CLK0_FREQ \
           PCW_FCLK0_PERIPHERAL_DIVISOR0 PCW_FCLK0_PERIPHERAL_DIVISOR1 \
           PCW_USE_S_AXI_HP0 PCW_USE_S_AXI_HP1 \
           PCW_USE_FABRIC_INTERRUPT PCW_IRQ_F2P_INTR} {
    puts "$p = [get_property CONFIG.$p $ps]"
}
validate_bd_design
```

- `validate_bd_design` 必须无 ERROR；
- 构建日志必须 0 条 `CRITICAL WARNING`（`scripts/check_build.py`）；
- `.hwh` 里的地址段与预期一致（`python scripts/check_handoff.py ...`）。

## 4. 最重要的一个坑：BD 里的 FCLK ≠ 板上实际频率

**PYNQ 的 PS 时钟由 FSBL 初始化，`Overlay()` 加载 `.bit` 只写 PL，不改 PS PLL。**

实测案例：BD 里 FCLK0 = 100 MHz，板上实际跑 55.56 MHz（IO_PLL=1000，÷6÷3）。
`/sys/kernel/debug/clk/clk_summary` 也不一定准（曾显示 50 MHz，实际 55.56）。

后果：DDS 输出频率、FFT 频率轴、UART 波特率全按错的 `FS` 算；
DDS 和 FFT 用同一个错 `FS` 时两者互相抵消，**读数自洽但硬件是错的**——只有示波器能发现。

处理：
1. 软件侧 `FS` 用板上**实测值**（示波器反推 `ratio = f_meas/f_set`，`FS_new = ratio × FS_old`）；
2. UART Lite 这类按 `C_S_AXI_ACLK_FREQ_HZ` 算分频的 IP，要把属性写成板上实际频率（如 55560000）；
3. 换 PYNQ 镜像/换板后重新校准；
4. 时序分析仍按 BD 的设计值做（100 MHz 收敛则 55.56 MHz 裕量充足）。

## 5. 声明式配置（v0.3 推荐做法）

手写 `CONFIG.PCW_*` 容易写错参数名（Vivado 只报 CRITICAL WARNING），也看不出设计意图。
把意图写进 `ps7.yaml`，由 `scripts/ps7_config.py` 生成"设置 + 回读断言"的 Tcl：

```yaml
# ps7.yaml
clocks:
  fclk0: 150          # MHz；写 0 表示关闭
  fclk1: 200
hp_ports: [0, 1]
irq_f2p: true
mio:
  uart1: {enable: true, io: "MIO 48 .. 49"}
  sdio0: {enable: true, io: "MIO 40 .. 45"}
ddr:
  size_gb: 1
extra_props:           # 逃生口：直接写 PCW_* 属性
  PCW_USE_M_AXI_GP0: 1
```

```bash
python scripts/ps7_config.py check  ps7.yaml                       # 只校验
python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl
```

挂到构建：

```powershell
$env:VAC_POST_BD_TCL = "tcl/post_bd_ps7.tcl"     # 相对路径按项目根解析
scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

生成物包含两类内容：

1. `set_property CONFIG.PCW_*`（只写"用户意图"，不写 ACT/分频）；
2. **回读断言**：`_ps7_check_freq` 用 `get_property CONFIG.PCW_ACT_FPGA<n>_PERIPHERAL_FREQMHZ`
   比较实际频率，偏差 >0.01 MHz 直接 `exit 1`；IRQ/DDR 也回读打印。

实测（示例工程）：`fclk0: 150` → 构建日志出现
`[ps7] FCLK0 = 150 MHz (ACT=150.000000)`，0 CRITICAL。

schema 是**严格**的：未知键（如把 `clocks` 写成 `clock`）直接报错，避免拼错被静默忽略。
支持的键见脚本头部 docstring，或 `python scripts/ps7_config.py example`。