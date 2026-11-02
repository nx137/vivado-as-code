# =============================================================================
# mk_min_bd.tcl —— 从零生成一个"最小可用" Zynq Block Design
# -----------------------------------------------------------------------------
# 目的：给本技能包一个**不依赖任何特定开发板**的可跑示例，证明
#       "TCL 建 BD → 导出 BD 真源 → 全量重建 → 出 bit" 这条链路可用。
#
# 设计内容（全部在 PS 侧，不需要任何外部引脚 / XDC 约束）：
#   processing_system7_0
#     ├─ FCLK_CLK0 100MHz  → 全设计单一时钟
#     ├─ M_AXI_GP0         → AXI-Lite 控制通路
#     └─ S_AXI_HP0         → DMA 数据通路（DDR）
#   axi_dma_0 (MM2S/S2MM, SG 关闭)  —— AXI-Stream 自环：MM2S → S2MM
#   axi_uartlite_0 (115200)         —— TXD 接 RXD 自环，用于验证 IP 存在
#   ps7_0_axi_periph / axi_mem_intercon / rst_ps7_0_100M
#
# 为什么用自环：外部 AXI-Stream/UART 引脚需要板级 XDC。自环让示例可以在
# **任意** xc7z020 板子上走完综合+实现+出 bit，验证的是构建链路本身。
#
# 用法：
#   vivado -mode batch -source tcl/mk_min_bd.tcl
# 产出：
#   tcl/design_1.tcl   <- 全量 BD 真源（write_bd_tcl 导出，可重复重建）
# =============================================================================

set script_dir [file dirname [file normalize [info script]]]
set root       [file dirname $script_dir]
set out_tcl    [file join $script_dir design_1.tcl]
set work       [file join $root _mkproj]

proc step {n msg} { puts "\n\[mk_min_bd $n\] $msg" }

close_project -quiet
file delete -force $work
file mkdir $work

step 1 "创建工程（xc7z020clg400-2）"
create_project -part xc7z020clg400-2 -force mk_min $work
create_bd_design design_1

# ---------------------------------------------------------------------------
step 2 "创建 PS7 并配置（FCLK0=100MHz, GP0, HP0）"
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
set_property -dict [list \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
] $ps

# DDR / FIXED_IO 提到顶层（PS 固定引脚，不需要额外 XDC）
make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/DDR]
make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/FIXED_IO]

# ---------------------------------------------------------------------------
step 3 "创建 AXI DMA（SG 关闭，MM2S/S2MM 各 32bit）"
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0]
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_sg_include_stscntrl_strm {0} \
    CONFIG.c_sg_length_width {26} \
    CONFIG.c_include_mm2s {1} \
    CONFIG.c_include_s2mm {1} \
    CONFIG.c_m_axis_mm2s_tdata_width {32} \
    CONFIG.c_s_axis_s2mm_tdata_width {32} \
] $dma

# ---------------------------------------------------------------------------
step 4 "创建复位与两座 AXI 互连"
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_0_100M]

# 控制通路：GP0 -> [ps7_0_axi_periph] -> DMA.S_AXI_LITE
set periph [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 ps7_0_axi_periph]
set_property -dict [list CONFIG.NUM_MI {1} CONFIG.NUM_SI {1}] $periph

# 数据通路：{DMA.M_AXI_MM2S, DMA.M_AXI_S2MM} -> [axi_mem_intercon] -> PS.HP0
set mem [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_mem_intercon]
set_property -dict [list CONFIG.NUM_MI {1} CONFIG.NUM_SI {2}] $mem

# ---------------------------------------------------------------------------
step 5 "连接时钟与复位（全设计单一时钟 FCLK_CLK0）"
foreach p {
    processing_system7_0/S_AXI_HP0_ACLK
    axi_dma_0/s_axi_lite_aclk
    axi_dma_0/m_axi_mm2s_aclk
    axi_dma_0/m_axi_s2mm_aclk
    ps7_0_axi_periph/ACLK
    ps7_0_axi_periph/S00_ACLK
    ps7_0_axi_periph/M00_ACLK
    axi_mem_intercon/ACLK
    axi_mem_intercon/S00_ACLK
    axi_mem_intercon/S01_ACLK
    axi_mem_intercon/M00_ACLK
    rst_ps7_0_100M/slowest_sync_clk
} {
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins $p]
}

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_0_100M/ext_reset_in]

foreach p {
    axi_dma_0/axi_resetn
    ps7_0_axi_periph/ARESETN
    ps7_0_axi_periph/S00_ARESETN
    ps7_0_axi_periph/M00_ARESETN
    axi_mem_intercon/ARESETN
    axi_mem_intercon/S00_ARESETN
    axi_mem_intercon/S01_ARESETN
    axi_mem_intercon/M00_ARESETN
} {
    set pin [get_bd_pins -quiet $p]
    if {[llength $pin] == 0} { continue }
    if {[llength [get_bd_nets -quiet -of_objects $pin]] > 0} { continue }
    connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins $p]
}

# ---------------------------------------------------------------------------
step 6 "连接 AXI-Lite 控制通路"
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins ps7_0_axi_periph/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M00_AXI] [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

# ---------------------------------------------------------------------------
step 7 "连接 DMA 数据通路（MM2S+S2MM -> HP0）"
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] [get_bd_intf_pins axi_mem_intercon/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_S2MM] [get_bd_intf_pins axi_mem_intercon/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_mem_intercon/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP0]

# AXI-Stream 自环：MM2S 发出的数据直接回到 S2MM（无需外部引脚）
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]


# ---------------------------------------------------------------------------
step 8 "分配地址"
assign_bd_address -offset 0x40400000 -range 0x00010000 \
    -target_address_space [get_bd_addr_spaces processing_system7_0/Data] \
    [get_bd_addr_segs axi_dma_0/S_AXI_LITE/Reg] -force

# DMA 两个主口都能访问 DDR（HP0）
foreach space {axi_dma_0/Data_MM2S axi_dma_0/Data_S2MM} {
    assign_bd_address -offset 0x00000000 -range 0x40000000 \
        -target_address_space [get_bd_addr_spaces $space] \
        [get_bd_addr_segs processing_system7_0/S_AXI_HP0/HP0_DDR_LOWOCM] -force
}

# ---------------------------------------------------------------------------
step 9 "校验并导出全量 BD TCL"
validate_bd_design
save_bd_design
write_bd_tcl -force $out_tcl
puts "\n  已导出: $out_tcl"
puts "  统计: IP [llength [get_bd_cells -quiet -filter {TYPE == ip}]] 个"
close_project
puts "\n完成。下一步： vivado -mode batch -source vivado/rebuild.tcl"
