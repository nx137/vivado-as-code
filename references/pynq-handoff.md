# 交付到 PYNQ：.bit / .hwh 与软件对齐

> 本文件回答："构建产物怎么交给板子，软件里哪些常量必须和 BD 同步"。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `<name>.bit` | 比特流（只含 PL） |
| `<name>.hwh` | 硬件手递：IP 实例名、基地址、中断号、参数 —— PYNQ 靠它生成 `ip_dict` |

**硬约定：两个文件必须同名、同目录。** 不同名时 `Overlay()` 找不到 `.hwh`，
`ip_dict` 直接为空或加载失败。

`rebuild.tcl` 可以自动完成复制与改名：

```bash
VAC_COPY_TO=/home/xilinx/jupyter_notebooks/proj \
VAC_ARTIFACT_NAME=signal_proc \
  scripts/build.ps1 -ProjectRoot . -StopAfter impl
# -> outputs/signal_proc.bit + signal_proc.hwh
```

## 2. 板上的加载

```python
from pynq import Overlay
ol = Overlay("signal_proc.bit")      # 自动匹配同目录 signal_proc.hwh
ol.ip_dict                            # {实例名: {phys_addr, interrupts, ...}}

dma = ol.axi_dma_0
gpio = ol.axi_gpio_kb
```

- 地址**不要写死**在 Python 里：用 `ol.ip_dict[实例名]['phys_addr']` 或 PYNQ 的
  `DefaultIP` 自动映射；
- 实例名是隐式契约：BD 里改名，Python 就会 KeyError。改名前全局搜一遍代码。

## 3. 软件与 BD 的强耦合点（换板/改 BD 必查）

| 常量 | 在哪 | 对齐对象 |
|---|---|---|
| `FS`（采样时钟） | Python 配置 | 板上实测 FCLK0（**不是** BD 设计值） |
| `PKT`（DMA 单包长度） | Python | RTL packetizer 的 `PKT_LEN` |
| IP 实例名 | Python | BD 里的 `create_bd_cell` 名字 |
| 寄存器偏移 | Python（若直接 `write/read`） | IP 手册 / `.hwh` 基址 + 偏移 |
| GPIO 通道含义 | Python + RTL | BD 里 `C_GPIO_WIDTH` / `C_IS_DUAL` 与实际接线 |

### 3.1 FS 必须单一事实源

FCLK0 在 BD 里是**设计值**（如 100 MHz，用于时序分析）；
板上实际值由 **FSBL 初始化**（`Overlay()` 只写 PL，不改 PS PLL），可能完全不同
（实测 50 MHz 或 55.56 MHz）。

后果与排查：

- DDS 输出频率、FFT 频率轴、UART 波特率都依赖 `FS`；
- DDS 与 FFT 用同一个错 `FS` 会互相抵消 → 读数自洽但硬件错；
- 唯一可靠判据是**示波器**：`ratio = f_meas / f_set`，`FS_new = ratio × FS_old`。

做法：在配置里写清 `FS` 的来历和校准方法，换镜像/换板后重新校准一次。

### 3.2 UART 的分频也依赖时钟

AXI UART Lite 用 `C_S_AXI_ACLK_FREQ_HZ` 算分频。如果板上实际是 55.56 MHz 而属性写的
100 MHz，波特率会偏 ~11%（115200 → 约 64k），表现为乱码。把属性写成板上实际值。

## 4. 产物一致性检查

```bash
python scripts/check_handoff.py \
    --bd  tcl/design_1.tcl \
    --hwh outputs/design_1_wrapper.hwh \
    --bit outputs/design_1_wrapper.bit
```

它做三件事：
1. BD TCL 里的 IP 实例集 vs `.hwh` 里的 `MODULE` 集（找"提交了旧 .hwh"）；
2. `.bit` / `.hwh` 是否同名；
3. 输出差异清单（退出码 4）。

> 背景：真实项目出现过"仓库里的 `.hwh` 只有 23 个 IP，而 BD 已有 27 个"，
> 结果按名字取 IP 的代码在某些分支上 KeyError。**产物必须由同一次构建生成**。

## 5. 上板自检顺序

1. `Overlay()` 加载成功，`ip_dict` 键数量与 BD 预期一致；
2. 读一个只读寄存器（如 DMA 的 `MM2S_DMASR`）确认 AXI-Lite 通；
3. 用 GPIO 打一个已知电平，示波器/万用表确认引脚方向；
4. DMA 自环（MM2S→S2MM）跑一次，确认数据链路；
5. 再接真实 ADC/DAC，最后跑算法。

## 6. 可选：开机自固化

```ini
# /etc/systemd/system/pynq-overlay.service
[Unit]
Description=Load PYNQ overlay
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/xilinx/load_overlay.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`load_overlay.py` 里 `Overlay(bit, download=True)`；或先 `download=False` 预加载，
交互时再 `download=True`（视 PYNQ 版本行为而定，建议实测）。
