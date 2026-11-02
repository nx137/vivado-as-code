# =============================================================================
# bd_upgrade.tcl —— Block Design 跨 Vivado 版本升级助手
# -----------------------------------------------------------------------------
# 解决什么问题：
#   write_bd_tcl 生成的脚本开头有版本校验（例如 2020.2），换到新版本 Vivado
#   直接 source 会 return 1；而"用新版本重新导出"又需要先把设计打开、升级 IP。
#   本脚本把这条路径自动化：放宽版本校验 → 建临时工程 → source BD →
#   upgrade_ip → validate → write_bd_tcl 导出新版本真源。
#
# 用法：
#   vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs \
#          <in_bd.tcl> <out_bd.tcl> [part]
#
#   示例：
#   vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs \
#          tcl/design_1.tcl tcl/design_1_upgraded.tcl xc7z020clg400-2
#
# 环境变量：
#   VAC_UPGRADE_KEEP=1   保留临时工程目录（排查用）
#
# 退出码：0 成功；1 失败
#
# ⚠️ 跨版本升级后必须回归：
#   1. 用新导出的 BD TCL 跑一次 -StopAfter bd（验证可复现）；
#   2. 对比升级前后的 IP 版本（脚本会打印 IPDEF 列表，形如 xilinx.com:ip:axi_dma:7.1）；
#   3. 跑全量构建 + 时序门禁（IP 升级可能改变时序/资源）。
# =============================================================================

proc fail {msg} {
    puts "\n  ERROR: $msg"
    exit 1
}

if {![info exists argv] || [llength $argv] < 2} {
    puts "用法: vivado -mode batch -source bd_upgrade.tcl -tclargs <in_bd.tcl> <out_bd.tcl> \[part\]"
    exit 1
}

set in_bd  [file normalize [lindex $argv 0]]
set out_bd [file normalize [lindex $argv 1]]
set part   [expr {[llength $argv] >= 3 ? [lindex $argv 2] : "xc7z020clg400-2"}]

if {![file exists $in_bd]} { fail "找不到输入 BD TCL：$in_bd" }
file mkdir [file dirname $out_bd]

set cur_ver [version -short]
puts "============================================================================"
puts " bd_upgrade.tcl"
puts "   输入: $in_bd"
puts "   输出: $out_bd"
puts "   器件: $part"
puts "   目标 Vivado: $cur_ver"
puts "============================================================================"

# ---- 1. 放宽版本校验：复制一份，把 scripts_vivado_version 改成当前版本 -------
set raw [read [open $in_bd r]]
set patched [regsub {set\s+scripts_vivado_version\s+\S+} $raw "set scripts_vivado_version $cur_ver" tmp]
set patched $tmp
if {$patched eq $raw} {
    puts "  WARNING: 没找到 scripts_vivado_version 行，按原样 source"
}

set tmp_dir [file join $::env(TEMP) "vac_bd_upgrade_[pid]"]
file delete -force $tmp_dir
file mkdir $tmp_dir
set tmp_bd [file join $tmp_dir "bd_patched.tcl"]
set fh [open $tmp_bd w]
puts $fh $patched
close $fh
puts "  已放宽版本校验：$tmp_bd"

# ---- 2. 建临时工程并 source BD ---------------------------------------------
set proj_dir [file join $tmp_dir "proj"]
create_project -part $part -force vac_bd_upgrade $proj_dir
set rc [catch {source $tmp_bd} res]
if {$rc != 0} { fail "BD TCL 执行失败：$res" }
if {$res eq "1"} { fail "BD TCL 仍返回 1（版本校验未成功放宽或 BD 本身有错）" }
puts "  BD 已重建"

# ---- 3. 升级 IP（跨版本时才有实际动作；同版本为 no-op）---------------------
set ips [get_ips -quiet -all]
puts "\n  IP 数量: [llength $ips]"
puts "  升级前 IPDEF（含版本）："
foreach ip [lsort $ips] {
    catch { puts "    $ip : [get_property IPDEF $ip]" }
}

if {[llength $ips] > 0} {
    set rc [catch {upgrade_ip -quiet $ips} msg]
    if {$rc != 0} {
        puts "  WARNING: upgrade_ip 返回：$msg"
        puts "  （同版本工程通常无可升级项；跨版本时若失败，请在 GUI 里跑 Report IP Status）"
    } else {
        puts "  upgrade_ip 完成"
    }
} else {
    puts "  没有可升级的 IP（纯 module_ref 设计属正常）"
}

# ---- 4. 校验 + 保存 + 导出新真源 -------------------------------------------
set bd_files [get_files -quiet *.bd]
if {[llength $bd_files] == 0} { fail "工程里没有 .bd 文件" }
set bd_file [lindex $bd_files 0]
open_bd_design $bd_file
validate_bd_design
save_bd_design
write_bd_tcl -force $out_bd
puts "\n  已导出新真源：$out_bd"

puts "  升级后 IPDEF（含版本）："
foreach ip [lsort [get_ips -quiet -all]] {
    catch { puts "    $ip : [get_property IPDEF $ip]" }
}

close_project
if {![info exists env(VAC_UPGRADE_KEEP)] || $env(VAC_UPGRADE_KEEP) ne "1"} {
    file delete -force $tmp_dir
} else {
    puts "  临时工程保留：$proj_dir"
}

puts "\n完成。回归步骤："
puts "  1) 用新 BD TCL 跑 StopAfter=bd 验证可复现"
puts "  2) 对比上面的 VLNV 列表（IP 版本变化）"
puts "  3) 跑全量构建 + 时序门禁"
