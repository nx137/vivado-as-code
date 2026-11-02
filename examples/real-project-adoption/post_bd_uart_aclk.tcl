# =============================================================================
# post_bd_uart_aclk.tcl —— 现有工程的 BD 后处理补丁
# -----------------------------------------------------------------------------
# 作用：AXI UART Lite 的分频按 C_S_AXI_ACLK_FREQ_HZ 计算。本板 PYNQ 实际
#       FCLK0 = 55.56 MHz（FSBL 决定，Vivado BD 里写的是 100 MHz），
#       不覆盖会导致波特率偏差约 11%（115200 -> ~64k，表现为乱码）。
#
# 由 rebuild_vac.tcl 通过 VAC_POST_BD_TCL 挂载，每次构建自动生效。
# =============================================================================

set _uart [get_bd_cells -quiet axi_uartlite_0]
if {[llength $_uart] == 0} {
    puts "  WARNING: 没有 axi_uartlite_0，跳过 UART ACLK 修正"
} else {
    set_property CONFIG.C_S_AXI_ACLK_FREQ_HZ {55560000} $_uart
    puts "  \[post_bd\] axi_uartlite_0 C_S_AXI_ACLK_FREQ_HZ = [get_property CONFIG.C_S_AXI_ACLK_FREQ_HZ $_uart]"
}
