# =============================================================================
# bd_export.tcl —— 把当前 Block Design 导出为全量 TCL（真源回写）
# -----------------------------------------------------------------------------
# 用途：
#   在 Vivado GUI 里改完 BD 后，用本脚本把 BD 固化成可版本控制的 TCL；
#   这是"BD 即代码"的写回环节。脚本会自动带时间戳存档，改坏了能回滚。
#
# 用法（batch）：
#   vivado -mode batch -source scripts/bd_export.tcl -tclargs \
#          <project.xpr> <bd_name> <out_tcl> [archive_dir]
# 用法（GUI Tcl Console，工程已打开时）：
#   source scripts/bd_export.tcl
#   bd_export "" design_1 tcl/design_1.tcl
#
# 退出码：0 成功；1 失败
# =============================================================================

proc bd_export {project bd_name out_tcl {archive_dir ""}} {
    if {$project ne "" && [file exists $project]} {
        puts "  打开工程: $project"
        open_project $project
    }
    if {$bd_name eq ""} { puts "  ERROR: 需要 BD 名"; return 1 }

    # 打开 BD（工程已 open 时 get_files 才能找到）
    set bd_files [get_files -quiet -of_objects [get_filesets sources_1] "${bd_name}.bd"]
    if {[llength $bd_files] == 0} {
        set bd_files [get_files -quiet "${bd_name}.bd"]
    }
    if {[llength $bd_files] == 0} {
        puts "  ERROR: 找不到 ${bd_name}.bd"
        return 1
    }
    open_bd_design [lindex $bd_files 0]

    # 导出前必须校验：BD 不合法时导出的脚本也是坏的
    if {[catch {validate_bd_design} msg]} {
        puts "  ERROR: BD 校验失败: $msg"
        return 1
    }

    set archive_dir [expr {$archive_dir ne "" ? $archive_dir : [file join [file dirname $out_tcl] archive]}]
    file mkdir $archive_dir
    if {[file exists $out_tcl]} {
        set ts [clock format [clock seconds] -format %Y%m%d_%H%M%S]
        set bak [file join $archive_dir "${bd_name}_${ts}.tcl"]
        file copy -force $out_tcl $bak
        puts "  旧版本已存档: $bak"
    }

    file mkdir [file dirname $out_tcl]
    write_bd_tcl -force $out_tcl
    puts "  已导出: $out_tcl"

    # 回读统计，方便确认"导出的是你以为的那个 BD"
    set ips [get_bd_cells -quiet -filter {TYPE == ip}]
    set mods [get_bd_cells -quiet -filter {TYPE == module}]
    set addrs [get_bd_addr_segs -quiet]
    puts "  统计: IP [llength $ips] 个 / RTL module [llength $mods] 个 / 地址段 [llength $addrs] 个"
    foreach c [lsort [get_bd_cells -quiet]] {
        puts "    - $c"
    }
    return 0
}

# --------------------------- batch 入口 ---------------------------
if {[info exists argv] && [llength $argv] >= 3} {
    set rc [bd_export [lindex $argv 0] [lindex $argv 1] [lindex $argv 2] \
                      [expr {[llength $argv] >= 4 ? [lindex $argv 3] : ""}]]
    if {$rc != 0} { exit 1 }
    puts "  BD 导出完成"
} elseif {![info exists argv] || [llength $argv] == 0} {
    puts "用法: vivado -mode batch -source bd_export.tcl -tclargs <project.xpr> <bd_name> <out_tcl> \[archive_dir\]"
    puts "  或在已打开工程的 Tcl Console 中: bd_export \"\" <bd_name> <out_tcl>"
}
