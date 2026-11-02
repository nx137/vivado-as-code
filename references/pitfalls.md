# 踩坑清单：症状 → 根因 → 检查 → 修复

> 每条都是实际踩过并验证过的。**先查表，再动手**。

## A. 构建/工具链

| # | 症状 | 根因 | 一条检查命令 | 修复 |
|---|---|---|---|---|
| A1 | 综合实现都过、bit 也出了，但硬件行为不对 | IP 参数名写错，Vivado 只报 `CRITICAL WARNING` 并静默取默认值 | `grep -i "CRITICAL" build.log` 或 `python scripts/check_build.py build.log` | 改对参数名，用 `get_property CONFIG.X` 回读确认 |
| A2 | 同一份代码，昨天能构建今天不行 | Vivado batch 偶发（IP init 找不到 `init.tcl/utils.tcl`、run 卡死） | `grep -i "init.tcl\|ipgen" build.log` | 关 GUI → 重跑一次 → 仍失败 `reset_target all` |
| A3 | batch 改完 BD，GUI 一打开保存就回滚 | GUI 与 batch 各持一份 BD | 有无 vivado GUI 进程 | **batch 前关 GUI**；重开工程后 Regenerate Layout |
| A4 | 换 Vivado 版本后 BD TCL 直接 return 1 | 生成脚本带版本校验 | 日志 `BD::TCL 2041` | 新版本打开设计 → Report IP Status 升级 → 重新 `write_bd_tcl` |
| A5 | 改了 RTL 端口/参数，行为还是旧的 | 综合吃模块名缓存 | `reset_run synth_1` 后是否还复现 | 模块改名 `_v2`，删旧 OOC synth run，重新 generate_target |
| A6 | `.ps1` 在本机报"意外的标记" | Windows PowerShell 5.1 按 ANSI 读无 BOM 的 UTF-8 脚本 | `Get-Content -Encoding Byte -TotalCount 3` 看是否 `239,187,191` | 存成 **UTF-8 with BOM**（本仓库 `build.ps1` 已带 BOM） |
| A7 | 日志检查脚本崩溃 `UnicodeEncodeError: gbk` | Windows 控制台是 GBK，日志含不可编码字符 | 直接跑 `python scripts/check_build.py build.log` | 输出降级为 ASCII 安全形式（本仓库已处理） |

## B. Block Design / Tcl

| # | 症状 | 根因 | 检查 | 修复 |
|---|---|---|---|---|
| B1 | 补丁跑第二次出现 cell 重名/`NUM_MI` 变成 3 | 脚本不幂等：`create_bd_cell` 重复执行、`NUM_MI+1` 每次叠加 | 连跑两次补丁对比导出的 BD TCL | 用 `vac_ensure_ip`；把"扩互连+接线+分地址"整体用"S_AXI 是否已连接"判断 |
| B2 | `validate_bd_design` 报 `BD 41-758 clock pins not connected` | 漏连 `M_AXI_GP0_ACLK` / `S_AXI_HP0_ACLK` | `get_bd_pins -of_objects [get_bd_cells ...] -filter {TYPE==clk}` | 把每个 AXI 端口的 ACLK 都连到 FCLK |
| B3 | `41-759 input pins tied to all 0's` | AXI Interconnect 每端口 `S00_ARESETN/M00_ARESETN` 未连（只连了 `ARESETN`） | `connect_bd_net` 是否覆盖了每端口复位 | 逐口连，或 `CONFIG.HAS_ARESETN {0}` |
| B4 | BD 大改后 XDC 约束"失效"，但构建不报错 | 顶层端口名漂移（`gpio_io_o_0`→`_1`），XDC 找不到端口只报 CRITICAL | `get_bd_ports` 对比 XDC 里的端口名 | 更新 XDC；构建后用 `check_build.py` 兜底 |
| B5 | `connect_bd_net` 报 `BD 41-701` | 用"网表名字符串"接已有 net，被当成 pin 路径解析 | 命令参数是 net 对象还是字符串 | 用已连在该 net 上的 **pin 作锚点**：`connect_bd_net $anchored_pin $free_pin` |
| B6 | 补丁里 `NUM_MI` 算出来了，但连 `MM01_ACLK` 报 pin 不存在 | `mi_idx` 已含前缀 `M`，又拼了一遍 `M` | 打印 `mi_idx` | `ps7_0_axi_periph/${mi_idx}_ACLK`，不要再加 `M` |
| B7 | 扩了同一个 interconnect 的 `NUM_SI` 后读通道不工作、`.hwh` 缺 MEMRANGE | 复用多主口互连 + XCI 丢失 | 对比 IP 数量与 `.hwh` | **一个 DMA 一个 HP 口一条 intercon**，或 `reset_target all` 重建 |
| B8 | `module_ref` 的 `CONFIG.SELECT_CH` 设了不生效 | module_ref 的 `CONFIG.*` 不会进入生成的 `#()` 参数列表 | 看生成的 wrapper/RTL 参数 | 直接改 RTL 的 `parameter` 默认值，或封装成标准 IP-XACT |
| B9 | Tcl 里 `expr` 报 "invalid bareword" | 网表名含 `/`，`expr` 把 `/` 当除号 | 报错行是不是 `expr {... [lindex ...] ...}` | 用 `if/else` 分支，别在 expr 里塞路径字符串 |

## C. 硬件/时钟/数据链

| # | 症状 | 根因 | 检查 | 修复 |
|---|---|---|---|---|
| C1 | DDS 设定 1 kHz，示波器测到 ~500 Hz / 1.11 kHz | BD 的 FCLK 设计值 ≠ 板上实际值（FSBL 决定） | 示波器反推 `ratio = f_meas/f_set` | 软件 `FS` 用实测值；见 `references/pynq-handoff.md` |
| C2 | UART 乱码，实际波特率约 64k（期望 115200） | `C_S_AXI_ACLK_FREQ_HZ` 按 BD 的 100 MHz 算分频，但板上实际 55.56 MHz | 回环收发测试 | 把该属性改成板上实际频率（如 `55560000`） |
| C3 | DMA S2MM 收不到数据、`wait()` 永不返回 | ① S2MM 的 `M_AXI_S2MM` 悬空未连内存互连；② PYNQ 2.4 中断不可用；③ AXI-Stream 缺 `tlast` | `get_bd_intf_nets -of_objects [get_bd_intf_pins axi_dma_0/M_AXI_S2MM]` 为空即断裂；DMASR 判读 | 连上 HP 口；改轮询；在流末端加 packetizer 补 `tlast` |
| C4 | DMA 复位后卡死（DMACR 恒 `0x10006`） | MM2S-only DMA 的已知问题 + 复位接法错误 | `DMACR` 值 | 双通道都开；复位接 `FCLK_RESET0_N → ext_reset_in` |
| C5 | DDS 无输入却一直输出 ~625 Hz | DDS Compiler 的 `PINC` 默认非零 | `get_property CONFIG.PINC` | 显式 `CONFIG.PINC {0}` |
| C6 | DDS 无视下游反压、数据丢 | `Has_TREADY` 未开 | IP 配置 | `CONFIG.Has_TREADY {true}` |
| C7 | 时序违例：DAC/ADC 接口 `output_delay` 负 slack | 引脚输出延迟与时钟插入延迟叠加 | `report_timing_summary` | `max output_delay` 调小（如 1.0→0.0）；DAC 用 `posedge` 发射；必要时 `set_multicycle_path -setup 2` |
| C8 | 换板后全部时序都差 | 板卡时钟引脚/Bank 不同（clock tree 延迟不同） | 对比板卡原理图 | 重新验证该时钟域约束，重新校准 FCLK |

## D. 交付/部署

| # | 症状 | 根因 | 检查 | 修复 |
|---|---|---|---|---|
| D1 | PYNQ `Overlay()` 报错或 `ip_dict` 为空 | `.bit`/`.hwh` 不同名或不同目录 | `ls` 两个文件 | 同名同目录 |
| D2 | 代码里 `ip_dict['xxx']` KeyError | 提交的 `.hwh` 是旧版本（IP 集与 BD 不一致） | `python scripts/check_handoff.py --bd ... --hwh ...` | 重新构建并替换 `.hwh`，别手工混搭产物 |
| D3 | 换了 bit 之后软件全错（频率/幅度偏移） | `FS` 常量没跟着改；标定文件（`.npy`）与旧前端不匹配 | 对比 `FS` 与示波器实测 | 重新校准并生成标定文件 |

## E. 排查顺序铁律

1. **先看模拟输出（示波器），再看数字链路**——数字域自洽会掩盖真实错误；
2. **先确认时钟**（BD 设计值 vs 板上实测值），再看数据；
3. **先确认连线**（`get_bd_intf_nets` 是否为空），再看寄存器；
4. **先确认 DMASR**（`0x1002` 正常 / `0x10006` 复位卡死 / `0x10` 内部错误），再看 buffer；
5. 每次只改一个变量并**全量重建**，否则无法归因。
