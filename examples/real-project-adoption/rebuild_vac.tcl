# =============================================================================
# rebuild_vac.tcl —— 用 vivado-as-code 工具链构建本工程（不改动原有 build.bat）
# -----------------------------------------------------------------------------
# 背景：本工程把 RTL 放在 vivado/src、约束放在 vivado/xdc、BD 真源在 vivado/tcl/，
#       并用 vivado/tcl/bd_add_fm_modem.tcl 做增量修改、构建后复制 overlay 到
#       software/pynq/main/。vivado-as-code 的模板支持用环境变量适配这套布局。
#
# 用法：
#   ../vivado-as-code/scripts/build.ps1 -ProjectRoot . -RebuildScript vivado/rebuild_vac.tcl -StopAfter bd
#   （工具链位置用 VIVADO_AS_CODE 环境变量指定，默认 D:/vivado-as-code）
#
# 与原 build.bat 的关系：两者并存，互不影响。build.bat 仍是原来的九阶段脚本；
# 本文件只是把同样的工程接到"可配置 + 带日志门禁 + 可出 manifest"的工具链上。
# =============================================================================

set _here [file normalize [info script]]
set _root [file dirname [file dirname $_here]]
# 工具链位置：优环境变量 VIVADO_AS_CODE；否则用下面这行（改成你 clone 的路径）
set _toolkit "D:/vivado-as-code"
if {[info exists env(VIVADO_AS_CODE)] && $env(VIVADO_AS_CODE) ne ""} {
    set _toolkit $env(VIVADO_AS_CODE)
}
if {![file exists [file join $_toolkit templates rebuild.tcl]]} {
    puts "  ERROR: 找不到 vivado-as-code 工具链：$_toolkit"
    puts "  解决：设置环境变量 VIVADO_AS_CODE 指向 clone 目录"
    exit 1
}

# ---- 适配本工程的目录布局 ---------------------------------------------------
set env(VAC_ROOT)         $_root
set env(VAC_SRC_DIR)      vivado/src
set env(VAC_XDC_DIR)      vivado/xdc
set env(VAC_BD_TCL)       vivado/tcl/bd_design_1.tcl
set env(VAC_BD_NAME)      design_1
set env(VAC_PATCH_TCL)    "vivado/tcl/bd_add_fm_modem.tcl,vivado/tcl/patch_fix_bd_issues.tcl"
set env(VAC_POST_BD_TCL)  vivado/tcl/post_bd_uart_aclk.tcl
set env(VAC_COPY_TO)      software/pynq/main
set env(VAC_ARTIFACT_NAME) xinhao_uart_kb_adf4351_rf

puts "  \[rebuild_vac\] toolkit : $_toolkit"
puts "  \[rebuild_vac\] root    : $_root"

source [file join $_toolkit templates rebuild.tcl]
