# =============================================================================
# patch_fix_bd_issues.tcl —— 真实工程接入时发现的问题修复（幂等，可重复执行）
# -----------------------------------------------------------------------------
# 发现方式：用 vivado-as-code 的日志门禁跑了一次原来的 BD，报出 3 类
#           `BD 41-759`（未连接输入被 tie 成 0）。原来 build.bat 不检查
#           CRITICAL WARNING，所以这些一直存在。
#
#   1) axi_mem_intercon 配了 NUM_SI=3，但 S02_AXI 从未连接（历史残留）
#      → 改回 NUM_SI=2；否则 S02_ARESETN 被 tie 0。
#   2) xlconcat_0/In1 只创建了网名 axi_dma_0_s2mm_introut，却没接驱动
#      → 补上 axi_dma_0/s2mm_introut，否则 S2MM 中断永远进不了 PS
#         （这也解释了为什么 PYNQ 侧最后改成轮询）。
#   3) mod_demod_mux_0 的 AM 预留通道（s_axis0/2）tvalid 没有驱动
#      → 显式接常量 0，语义（预留不用）不变，但不再有未连接输入。
#
# 顺序：在 bd_add_fm_modem.tcl 之后执行（mod_demod_mux_0 由它创建）。
# =============================================================================

# ---- 1) 去掉从未使用的第三个 AXI 主口 -------------------------------------
set _mem [get_bd_cells -quiet axi_mem_intercon]
if {[llength $_mem] > 0} {
    set _si [get_property CONFIG.NUM_SI $_mem]
    if {$_si > 2} {
        set_property CONFIG.NUM_SI {2} $_mem
        puts "  \[fix\] axi_mem_intercon NUM_SI: $_si -> 2（S02_AXI 从未连接）"
    } else {
        puts "  \[fix\] axi_mem_intercon NUM_SI=$_si，无需修改"
    }
}

# ---- 2) 补上 S2MM 中断驱动 -------------------------------------------------
if {[llength [get_bd_pins -quiet axi_dma_0/s2mm_introut]] > 0} {
    set _in1 [get_bd_pins -quiet xlconcat_0/In1]
    if {[llength $_in1] > 0} {
        set _net [get_bd_nets -quiet -of_objects $_in1]
        set _net_pins 0
        if {[llength $_net] > 0} {
            set _net_pins [llength [get_bd_pins -quiet -of_objects [lindex $_net 0]]]
        }
        if {$_net_pins < 2} {
            connect_bd_net [get_bd_pins axi_dma_0/s2mm_introut] [get_bd_pins xlconcat_0/In1]
            puts "  \[fix\] 连接 axi_dma_0/s2mm_introut -> xlconcat_0/In1"
        } else {
            puts "  \[fix\] xlconcat_0/In1 已有驱动，跳过"
        }
    }
}

# ---- 3) 预留通道的 tvalid 显式接 0 ----------------------------------------
if {[llength [get_bd_cells -quiet mod_demod_mux_0]] > 0} {
    set _const [get_bd_cells -quiet xlconstant_tie0]
    if {[llength $_const] == 0} {
        set _const [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 xlconstant_tie0]
        set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {0}] $_const
        puts "  \[fix\] 创建 xlconstant_tie0（1bit 常量 0）"
    }
    foreach _p {mod_demod_mux_0/s_axis0_tvalid mod_demod_mux_0/s_axis2_tvalid} {
        set _pin [get_bd_pins -quiet $_p]
        if {[llength $_pin] == 0} { continue }
        if {[llength [get_bd_nets -quiet -of_objects $_pin]] > 0} { continue }
        connect_bd_net [get_bd_pins xlconstant_tie0/dout] [get_bd_pins $_p]
        puts "  \[fix\] xlconstant_tie0/dout -> $_p"
    }
}

# ---- 4) 给 module_ref 的输出时钟补 FREQ_HZ（否则 IP_Flow 19-4751）---------
set _daclk [get_bd_intf_pins -quiet da_driver_0/da_clk]
if {[llength $_daclk] > 0} {
    set _freq ""
    catch { set _freq [get_property CONFIG.FREQ_HZ $_daclk] }
    if {$_freq eq ""} {
        catch { set_property CONFIG.FREQ_HZ {55560000} $_daclk }
        puts "  \[fix\] da_driver_0/da_clk FREQ_HZ = 55560000"
    } else {
        puts "  \[fix\] da_driver_0/da_clk FREQ_HZ 已为 $_freq，跳过"
    }
}