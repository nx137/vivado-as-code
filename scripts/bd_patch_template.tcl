# =============================================================================
# bd_patch_template.tcl —— 幂等增量补丁模板（照抄改这一段）
# -----------------------------------------------------------------------------
# 适用场景：
#   已有可用的全量 BD（tcl/design_1.tcl），现在要"加一个外设"，
#   但不想每次都在 GUI 里点。做法：写一个补丁脚本，在 rebuild.tcl 里用
#   VAC_PATCH_TCL 挂上去，每次全量重建都自动生效。
#
# 本模板做的事（可按需删减）：
#   1. 在 BD 里加一个双通道 AXI GPIO（axi_gpio_user），接到 FCLK0 与复位；
#   2. 扩展 ps7_0_axi_periph 的 NUM_MI（如果还不够）；
#   3. 连接 S_AXI，分配地址 0x41240000；
#   4. 校验并保存。
#
# 幂等的关键（踩过的坑）：
#   - create_bd_cell 重复执行会报重名；NUM_MI + 1 重复执行会越加越多。
#     所以"扩互连 + 接线 + 分地址"必须**整体判断是否需要做**，而不是各判各的；
#   - 判据用"目标从口的 S_AXI 是否已经连上"——连上了说明补丁已经跑过；
#   - 改完重要属性要回读（参数名写错只报 CRITICAL WARNING！）；
#   - NUM_MI 扩容后必须重新 assign_bd_address，否则 PYNQ 拿不到地址。
#
# 运行方式（三种任选）：
#   1) 由 rebuild.tcl 自动执行：VAC_PATCH_TCL=tcl/patch_add_gpio.tcl build.ps1
#   2) 手动单跑：vivado -mode batch -source scripts/bd_patch_template.tcl
#   3) GUI Tcl Console：source scripts/bd_patch_template.tcl
#
# 依赖：scripts/lib/（guards.tcl + guard_loader.tcl；也可用 VAC_GUARDS_TCL 指定 guards.tcl），
#       若把补丁复制到 <proj>/tcl/，把 scripts/lib/（含 guards.tcl 与 guard_loader.tcl）\n#       复制到 <proj>/scripts/lib/ 或 <proj>/tcl/lib/。
#
# 验证幂等（正确做法）：让**同一次构建**把补丁跑两遍——
#   VAC_PATCH_TCL="tcl/patch_add_gpio.tcl,tcl/patch_add_gpio.tcl" \
#   VAC_EXPORT_BD=bd_exported.tcl
# 两次导出的 BD 应完全一致。只跑两次 build 不算验证：每次都是干净重建，天然一致。
# =============================================================================

# ---- 载入守卫库（共享 guard_loader.tcl；候选路径只在那里维护）-------------
set _here [file dirname [file normalize [info script]]]
set _loader ""
foreach _c [list \
    [file join $_here lib guard_loader.tcl] \
    [file normalize [file join $_here .. scripts lib guard_loader.tcl]] \
    [file normalize [file join $_here .. .. scripts lib guard_loader.tcl]] \
] {
    if {[file exists $_c]} { set _loader $_c; break }
}
if {$_loader eq ""} {
    puts "  ERROR: 找不到 guard_loader.tcl（scripts/lib/guard_loader.tcl）"
    puts "  解决：复制整个 scripts/lib/ 到补丁同级 lib/，或设 VAC_GUARDS_TCL"
    exit 1
}
source $_loader

puts "  \[patch\] 开始增量修改 BD ..."

# ---- 1. 前置检查：确认目标 BD 已打开 ------------------------------------
if {[llength [get_bd_designs -quiet]] == 0} { fail "没有打开的 BD，请先 source 全量 BD TCL" }
set _bd [current_bd_design]
puts "  \[patch\] 当前 BD: $_bd"

# ---- 2. 创建（或复用）新 cell -------------------------------------------
# 注意：GPIO 宽度、双通道等参数写在 -dict 里；实例名一旦定了就别改，
#       因为 PYNQ 侧代码是按实例名取 IP 的。
set gpio [vac_ensure_ip xilinx.com:ip:axi_gpio:2.0 axi_gpio_user {
    CONFIG.C_GPIO_WIDTH    {8}
    CONFIG.C_GPIO2_WIDTH   {8}
    CONFIG.C_IS_DUAL       {1}
    CONFIG.C_ALL_OUTPUTS   {1}
    CONFIG.C_ALL_OUTPUTS_2 {1}
}]

# ---- 3. 判断补丁是否已经跑过 -------------------------------------------
# 判据：目标从口 S_AXI 已经有 net => 接线/扩互连/分地址都做过。
set _target_pin [get_bd_intf_pins -quiet axi_gpio_user/S_AXI]
if {[llength $_target_pin] == 0} { fail "axi_gpio_user 没有 S_AXI 接口" }
set already_wired [expr {[llength [get_bd_intf_nets -quiet -of_objects $_target_pin]] > 0}]

# 时钟/复位连接本身是幂等的（已连则跳过），放在分支外也不会重复建网络
vac_require_cell processing_system7_0
vac_connect_net_if_free [list \
    processing_system7_0/FCLK_CLK0 \
    axi_gpio_user/s_axi_aclk \
]
if {[llength [get_bd_pins -quiet rst_ps7_0_100M/peripheral_aresetn]] > 0} {
    vac_connect_net_if_free [list \
        rst_ps7_0_100M/peripheral_aresetn \
        axi_gpio_user/s_axi_aresetn \
    ]
}

if {$already_wired} {
    puts "  \[patch\] axi_gpio_user/S_AXI 已连接，跳过扩互连与地址分配（补丁已执行过）"
} else {
    # ---- 4. 扩展 AXI 互连：NUM_MI 必须比现有从机多 1 --------------------
    # 先读当前值再 +1，不要硬编码（别的分支上可能不是 1）。
    set mi_cur [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
    set mi_new [expr {$mi_cur + 1}]
    set_property CONFIG.NUM_MI $mi_new [get_bd_cells ps7_0_axi_periph]
    puts "  \[patch\] ps7_0_axi_periph NUM_MI: $mi_cur -> $mi_new"

    set mi_idx [format "M%02d" [expr {$mi_new - 1}]]

    # 新 MI 口的时钟/复位（显式连，避免依赖自动布线）
    vac_connect_net_if_free [list \
        processing_system7_0/FCLK_CLK0 \
        ps7_0_axi_periph/${mi_idx}_ACLK \
    ]
    if {[llength [get_bd_pins -quiet rst_ps7_0_100M/peripheral_aresetn]] > 0} {
        vac_connect_net_if_free [list \
            rst_ps7_0_100M/peripheral_aresetn \
            ps7_0_axi_periph/${mi_idx}_ARESETN \
        ]
    }

    # ---- 5. 连接 AXI-Lite 并分配地址 -----------------------------------
    vac_connect_if_free [list \
        ps7_0_axi_periph/${mi_idx}_AXI \
        axi_gpio_user/S_AXI \
    ]
    vac_ensure_addr 0x41240000 0x10000 processing_system7_0/Data axi_gpio_user/S_AXI/Reg
}

# ---- 6. 重要属性回读（防"参数名写错静默取默认值"）---------------------
# 双通道 GPIO 至少回读 4 个属性：位宽、是否双通道、两个通道的方向
vac_verify_prop axi_gpio_user CONFIG.C_GPIO_WIDTH    {8}
vac_verify_prop axi_gpio_user CONFIG.C_GPIO2_WIDTH   {8}
vac_verify_prop axi_gpio_user CONFIG.C_IS_DUAL       {1}
vac_verify_prop axi_gpio_user CONFIG.C_ALL_OUTPUTS   {1}
vac_verify_prop axi_gpio_user CONFIG.C_ALL_OUTPUTS_2 {1}

# ---- 7. 收尾：校验 + 保存 ----------------------------------------------
# 注意：补丁只是"改当前工程的 BD"，要得到可复现的 bit 必须**重跑全量重建**。
#       稳定后建议用 scripts/bd_export.tcl 把 BD 固化回 tcl/design_1.tcl。
vac_finalize $_bd
puts "  \[patch\] 完成。请重跑 vivado/rebuild.tcl 验证可复现性。"
