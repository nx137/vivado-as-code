# =============================================================================
# rebuild.tcl —— Vivado 全量 / 分级重建（参数化模板）
# -----------------------------------------------------------------------------
# 放置位置： <project-root>/vivado/rebuild.tcl
# 运行方式： vivado -mode batch -source vivado/rebuild.tcl
#            （推荐用 scripts/build.ps1 或 build.sh，会自动探测 Vivado 并做日志门禁）
#
# 设计原则：
#   1. 仓库不保存 .xpr / .runs / .gen —— 一切由本脚本 + BD TCL 重建；
#   2. 每次构建都是一次"干净重建"，避免缓存导致的行为不一致；
#   3. 支持 -StopAfter 分级（bd / synth / impl），便于快速验证；
#   4. 任一阶段失败立即 exit 1，可直接作为 CI 门禁。
#
# 全部参数通过环境变量传入（均有默认值）：
#   VAC_ROOT           项目根目录（默认 = 本脚本上一级）
#   VAC_PART           器件（默认 xc7z020clg400-2）
#   VAC_TOP            顶层 module（默认 design_1_wrapper）
#   VAC_STOP_AFTER     bd | synth | impl （默认 impl）
#   VAC_JOBS           并行任务数（默认 8）
#   VAC_PROJECT        工程目录名（默认 vivado_project）
#   VAC_BD_TCL         BD 全量 TCL（默认 <root>/tcl/<bd_name>.tcl）
#   VAC_BD_NAME        Block Design 名（默认 design_1）
#   VAC_SRC_DIR        RTL 目录（默认 <root>/src；现有工程可指向 vivado/src）
#   VAC_XDC_DIR        约束目录（默认 <root>/xdc；现有工程可指向 vivado/xdc）
#   VAC_PATCH_TCL      可选增量补丁，逗号分隔，按顺序在 BD 之后执行
#                      （相对路径按项目根目录解析，如 tcl/patch_add_gpio.tcl）
#   VAC_POST_BD_TCL    可选，补丁之后再执行（属性覆盖等）
#   VAC_OUT_DIR        产物目录（默认 <root>/outputs）
#   VAC_COPY_TO        可选，把 .bit/.hwh 复制到该目录
#   VAC_ARTIFACT_NAME  可选，复制时的文件名（如 PYNQ overlay 名）
# =============================================================================

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
proc env_or {name default} {
    if {[info exists ::env($name)] && $::env($name) ne ""} { return $::env($name) }
    return $default
}

proc phase {n total msg} {
    puts "\n\[PHASE $n/$total\] [clock format [clock seconds] -format %H:%M:%S]  $msg"
}

proc fail {msg} {
    puts "\n  ERROR: $msg"
    puts "  （排查提示：grep -i \"CRITICAL\\|ERROR\" <build.log>）"
    exit 1
}

# 用 forward slash 表示路径，便于写进 JSON
proc slash {p} { string map {\\ /} $p }

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
set script_dir [file dirname [file normalize [info script]]]
set root_override [env_or VAC_ROOT ""]
if {$root_override ne ""} {
    set root [file normalize $root_override]
} else {
    set root [file dirname $script_dir]
}

set part          [env_or VAC_PART        xc7z020clg400-2]
set top           [env_or VAC_TOP         design_1_wrapper]
set stop_after    [env_or VAC_STOP_AFTER  impl]
set jobs          [env_or VAC_JOBS        8]
set proj_name     [env_or VAC_PROJECT     vivado_project]
set bd_name       [env_or VAC_BD_NAME     design_1]
set out_dir       [file join $root [env_or VAC_OUT_DIR outputs]]
set copy_to       [env_or VAC_COPY_TO     ""]
if {$copy_to ne "" && [file pathtype $copy_to] ne "absolute"} {
    set copy_to [file normalize [file join $root $copy_to]]
}
set artifact_name [env_or VAC_ARTIFACT_NAME ""]
set bd_tcl        [env_or VAC_BD_TCL      [file join $root tcl "${bd_name}.tcl"]]
set patch_raw     [env_or VAC_PATCH_TCL   ""]
set post_bd_tcl   [env_or VAC_POST_BD_TCL ""]
set proj_dir      [file join $root $proj_name]

set patches {}
foreach p [split $patch_raw ",;"] {
    set p [string trim $p]
    if {$p eq ""} { continue }
    # 相对路径按"项目根目录"解析，而不是按 Vivado 的当前目录
    if {[file pathtype $p] ne "absolute"} { set p [file join $root $p] }
    lappend patches [file normalize $p]
}

if {$post_bd_tcl ne "" && [file pathtype $post_bd_tcl] ne "absolute"} {
    set post_bd_tcl [file normalize [file join $root $post_bd_tcl]]
}
if {[file pathtype $bd_tcl] ne "absolute"} {
    set bd_tcl [file normalize [file join $root $bd_tcl]]
}

if {![string match "bd" $stop_after] && ![string match "synth" $stop_after] && ![string match "impl" $stop_after]} {
    fail "VAC_STOP_AFTER 必须是 bd / synth / impl，当前: $stop_after"
}

set total 9
set ::vac_start [clock seconds]
puts "============================================================================"
puts " rebuild.tcl — 全量重建"
puts "   root      : $root"
puts "   part      : $part"
puts "   top       : $top"
puts "   stop_after: $stop_after"
puts "   bd_tcl    : $bd_tcl"
puts "   vivado    : [version -short]"
puts "   开始      : [clock format [clock seconds]]"
puts "============================================================================"

# ---------------------------------------------------------------------------
# Phase 1: 清理（每次构建都是全量干净重建）
# ---------------------------------------------------------------------------
phase 1 $total "清理旧工程..."
close_project -quiet
catch {file delete -force $proj_dir}
file mkdir $out_dir

# ---------------------------------------------------------------------------
# Phase 2: 创建工程
# ---------------------------------------------------------------------------
phase 2 $total "创建工程 ($proj_name)..."
if {![file exists [file join $proj_dir "${proj_name}.xpr"]]} {
    create_project -part $part -force $proj_name $proj_dir
}
if {[get_property PART [current_project]] ne $part} {
    set_property PART $part [current_project]
}

# ---------------------------------------------------------------------------
# Phase 3: RTL 源文件
# ---------------------------------------------------------------------------
phase 3 $total "添加 RTL 源文件..."
# 目录可覆盖：现有工程常把 RTL 放在 vivado/src（用 VAC_SRC_DIR 指向）
set src_dir [env_or VAC_SRC_DIR ""]
if {$src_dir eq ""} { set src_dir [file join $root src] }
if {[file pathtype $src_dir] ne "absolute"} { set src_dir [file normalize [file join $root $src_dir]] }
puts "  RTL 目录: $src_dir"
set rtl_files {}
foreach ext {*.v *.sv *.vh} {
    foreach f [glob -nocomplain [file join $src_dir $ext]] { lappend rtl_files $f }
}
if {[llength $rtl_files] == 0} {
    puts "  WARNING: src/ 下没有 .v/.sv 文件（纯 IP 设计可忽略）"
} else {
    foreach f $rtl_files { puts "  + [file tail $f]" }
    add_files -norecurse {*}$rtl_files
}

# ---------------------------------------------------------------------------
# Phase 4: 约束文件
# ---------------------------------------------------------------------------
phase 4 $total "添加约束文件..."
set xdc_dir [env_or VAC_XDC_DIR ""]
if {$xdc_dir eq ""} { set xdc_dir [file join $root xdc] }
if {[file pathtype $xdc_dir] ne "absolute"} { set xdc_dir [file normalize [file join $root $xdc_dir]] }
puts "  约束目录: $xdc_dir"
set xdc_files [glob -nocomplain [file join $xdc_dir *.xdc]]
if {[llength $xdc_files] == 0} {
    puts "  WARNING: xdc/ 下没有 .xdc 文件"
} else {
    foreach f $xdc_files { puts "  + [file tail $f]" }
    add_files -fileset constrs_1 -norecurse {*}$xdc_files
}
if {[llength $rtl_files] > 0} { update_compile_order -fileset sources_1 }

# ---------------------------------------------------------------------------
# Phase 5: 重建 Block Design
# ---------------------------------------------------------------------------
phase 5 $total "重建 Block Design（$bd_name）..."
if {![file exists $bd_tcl]} {
    fail "缺少 BD TCL：$bd_tcl（先用 scripts/bd_export.tcl 导出，或参考 templates/project-skeleton）"
}
# 每次构建前存档 BD TCL —— 改坏了可从这里恢复（archive/ 已在 .gitignore）
set archive_dir [file join $root tcl archive]
file mkdir $archive_dir
set ts [clock format [clock seconds] -format %Y%m%d_%H%M%S]
file copy -force $bd_tcl [file join $archive_dir "${bd_name}_${ts}.tcl"]
puts "  存档: tcl/archive/${bd_name}_${ts}.tcl"

set rc [catch {source $bd_tcl} res]
if {$rc != 0} { fail "BD TCL 执行失败：$res" }
if {$res eq "1"} { fail "BD TCL 版本校验未通过（脚本生成的 Vivado 版本与本机不同，见日志中的 BD::TCL 2041）" }

# 可选：增量补丁（按顺序）
foreach p $patches {
    if {![file exists $p]} { fail "补丁脚本不存在：$p" }
    puts "  执行补丁: $p"
    set rc [catch {source $p} res]
    if {$rc != 0} { fail "补丁执行失败（$p）：$res" }
}

# 可选：BD 之后的属性覆盖 / 收尾
if {$post_bd_tcl ne ""} {
    if {![file exists $post_bd_tcl]} { fail "VAC_POST_BD_TCL 不存在：$post_bd_tcl" }
    puts "  执行 BD 后处理: $post_bd_tcl"
    set rc [catch {source $post_bd_tcl} res]
    if {$rc != 0} { fail "BD 后处理失败：$res" }
}

set bd_file [get_files -quiet $bd_name.bd]
if {$bd_file eq ""} { fail "BD 未生成：$bd_name.bd 不存在" }
validate_bd_design
save_bd_design
puts "  BD 校验通过"

# 可选：把"打了补丁之后"的 BD 重新导出成新的全量真源。
# 这是增量补丁 -> 固化真源 的桥梁：补丁验证稳定后，用它生成新的 BD TCL 取代旧文件。
if {[env_or VAC_EXPORT_BD ""] ne ""} {
    set export_path [file join $out_dir [env_or VAC_EXPORT_BD bd_exported.tcl]]
    write_bd_tcl -force $export_path
    puts "  + 已导出打补丁后的 BD: $export_path"
}

# ---------------------------------------------------------------------------
# Phase 6: wrapper + IP 产物
# ---------------------------------------------------------------------------
phase 6 $total "生成 wrapper + IP 产物..."
make_wrapper -files [get_files $bd_file] -top -import
set_property top $top [current_fileset]
generate_target all [get_files $bd_file]
update_compile_order -fileset sources_1
puts "  wrapper: $top"

# ---------------------------------------------------------------------------
# Phase 7/8/9: 综合 / 实现 / 比特流
# ---------------------------------------------------------------------------
set wns ""
set bit_path ""
set hwh_path ""

if {$stop_after eq "bd"} {
    puts "\n  STOP_AFTER=bd：跳过综合、实现与比特流"
} else {
    phase 7 $total "综合 (synth_1)..."
    reset_run synth_1
    launch_runs synth_1 -jobs $jobs
    wait_on_run synth_1
    set st [get_property STATUS [get_runs synth_1]]
    puts "  synth_1: $st"
    if {![string match "*Complete*" $st]} { fail "综合失败：$st" }

    phase 8 $total "实现 (impl_1)..."
    reset_run impl_1
    launch_runs impl_1 -jobs $jobs
    wait_on_run impl_1
    set st [get_property STATUS [get_runs impl_1]]
    puts "  impl_1: $st"
    if {![string match "*Complete*" $st]} { fail "布局布线失败：$st" }

    phase 9 $total "生成比特流..."
    launch_runs impl_1 -to_step write_bitstream
    wait_on_run impl_1
    puts "  比特流完成"
}

# ---------------------------------------------------------------------------
# 报告 + 产物收集
# ---------------------------------------------------------------------------
if {$stop_after ne "bd"} {
    open_run impl_1
    report_timing_summary -file [file join $out_dir timing_summary.txt]
    report_utilization   -file [file join $out_dir utilization.txt]
    catch { set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] }
    puts "  + timing_summary.txt / utilization.txt"

    set impl_dir [get_property DIRECTORY [get_runs impl_1]]
    set bit_src  [file join $impl_dir "${top}.bit"]
    if {[file exists $bit_src]} {
        set bit_path [file join $out_dir "${top}.bit"]
        file copy -force $bit_src $bit_path
        puts "  + [file tail $bit_path]"
    } else {
        puts "  WARNING: 未找到 ${top}.bit"
    }
}

# .hwh 在 .gen/.../hw_handoff 下（bd 模式也会生成）
set hwh_candidates [glob -nocomplain [file join $proj_dir *.gen sources_1 bd $bd_name hw_handoff "${bd_name}.hwh"]]
if {[llength $hwh_candidates] > 0} {
    set hwh_path [file join $out_dir "${top}.hwh"]
    file copy -force [lindex $hwh_candidates 0] $hwh_path
    puts "  + [file tail $hwh_path]"
} else {
    puts "  WARNING: 未找到 ${bd_name}.hwh"
}

# 可选：复制到部署目录（如 PYNQ overlay 目录），支持改名
# 必须成对复制：只拷其中一个会让部署目录出现"不同一次构建"的 .bit/.hwh 混搭。
if {$copy_to ne ""} {
    if {$bit_path eq "" || ![file exists $hwh_path]} {
        puts "  跳过 COPY_TO：没有同时拿到 .bit 与 .hwh（StopAfter 不是 impl 时不复制，避免混搭产物）"
    } else {
        file mkdir $copy_to
        set name [expr {$artifact_name ne "" ? $artifact_name : $top}]
        file copy -force $bit_path [file join $copy_to "${name}.bit"]
        file copy -force $hwh_path [file join $copy_to "${name}.hwh"]
        puts "  + 已复制到 $copy_to（${name}.bit/.hwh，必须同名同目录）"
    }
}

# ---------------------------------------------------------------------------
# 构建清单（供 scripts/check_build.py 与 CI 使用）
# ---------------------------------------------------------------------------
set manifest [file join $out_dir build_manifest.json]
set fh [open $manifest w]
puts $fh "\{"
puts $fh "  \"status\": \"ok\","
puts $fh "  \"vivado\": \"[version -short]\","
puts $fh "  \"part\": \"$part\","
puts $fh "  \"top\": \"$top\","
puts $fh "  \"bd\": \"$bd_name\","
puts $fh "  \"stop_after\": \"$stop_after\","
puts $fh "  \"bit\": \"[slash $bit_path]\","
puts $fh "  \"hwh\": \"[slash $hwh_path]\","
puts $fh "  \"wns\": \"$wns\","
puts $fh "  \"finished\": \"[clock format [clock seconds] -format %Y-%m-%dT%H:%M:%S]\","
puts $fh "  \"elapsed_sec\": [expr {[clock seconds] - $::vac_start}]"
puts $fh "\}"
close $fh
puts "  + build_manifest.json"

puts "\n────────────────────────────────────────"
puts " 重建完成：$out_dir"
puts " 结束：[clock format [clock seconds]]"
