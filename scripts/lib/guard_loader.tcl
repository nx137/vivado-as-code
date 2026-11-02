# =============================================================================
# guard_loader.tcl —— 共享的 guards.tcl 载入器（补丁模板与 recipe 共用）
# -----------------------------------------------------------------------------
# 为什么单独一个文件：
#   补丁脚本和 recipe 生成物都需要"在多个位置找 guards.tcl 并 source"。
#   此前这段逻辑（6 个候选路径 + 失败提示）在两处各写一份，改一处漏一处。
#   现在候选路径只在这里维护；调用方只需用几行找到本文件即可。
#
# 调用方式（写在补丁/recipe 开头）：
#   set _here [file dirname [file normalize [info script]]]
#   set _loader ""
#   foreach _c [list \
#       [file join $_here lib guard_loader.tcl] \
#       [file normalize [file join $_here .. scripts lib guard_loader.tcl]] \
#       [file normalize [file join $_here .. .. scripts lib guard_loader.tcl]] \
#   ] { if {[file exists $_c]} { set _loader $_c; break } }
#   if {$_loader eq ""} { puts "ERROR: 找不到 guard_loader.tcl"; exit 1 }
#   source $_loader
#
# 载入顺序：VAC_GUARDS_TCL -> 本文件同目录 guards.tcl -> 调用方目录附近
# =============================================================================

if {[info exists env(VAC_GUARDS_TCL)] && $env(VAC_GUARDS_TCL) ne ""} {
    if {[file exists $env(VAC_GUARDS_TCL)]} {
        source $env(VAC_GUARDS_TCL)
    } else {
        puts "  ERROR: VAC_GUARDS_TCL 指向的文件不存在：$env(VAC_GUARDS_TCL)"
        exit 1
    }
} else {
    set _guard_here [file dirname [file normalize [info script]]]
    set _guard_file [file join $_guard_here guards.tcl]
    if {![file exists $_guard_file]} {
        puts "  ERROR: 在 $(_guard_here) 找不到 guards.tcl"
        puts "  解决：把 scripts/lib/guards.tcl 与本文件放在同一目录"
        exit 1
    }
    source $_guard_file
}
