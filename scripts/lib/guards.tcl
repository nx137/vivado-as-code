# =============================================================================
# guards.tcl —— 增量补丁守卫库（让 BD 补丁"可重复执行"）
# -----------------------------------------------------------------------------
# 为什么需要它：
#   直接 create_bd_cell / connect_bd_* 的脚本**不能重复执行**——第二次跑会因
#   cell 重名、端口已连接而报错，甚至留下半改状态。这套守卫把每个操作变成
#   "存在则跳过、不存在则创建"，于是补丁可以反复跑、失败后重跑。
#
# 用法：在补丁脚本开头 source 本文件
#   source [file join [file dirname [info script]] lib guards.tcl]
# 约定：所有 proc 以 vac_ 前缀，避免与项目自己的 proc 冲突。
# =============================================================================

# 统一的失败出口：优先复用 rebuild.tcl 的 fail
if {![llength [info procs fail]]} {
    proc fail {msg} { puts "  ERROR: $msg"; exit 1 }
}

proc vac_log {msg} { puts "    \[guard\] $msg" }

# ---- cell ---------------------------------------------------------------
proc vac_cell_exists {name} {
    return [expr {[llength [get_bd_cells -quiet $name]] > 0}]
}

proc vac_require_cell {name} {
    if {![vac_cell_exists $name]} { fail "前置 cell 不存在：$name" }
}

# 幂等创建 IP cell：已存在则直接返回
proc vac_ensure_ip {vlnv name {config ""}} {
    if {[vac_cell_exists $name]} {
        vac_log "$name 已存在，跳过创建"
        return [get_bd_cells $name]
    }
    set cell [create_bd_cell -type ip -vlnv $vlnv $name]
    if {$config ne ""} { set_property -dict $config $cell }
    vac_log "创建 IP $name ($vlnv)"
    return $cell
}

# ---- 地址 ---------------------------------------------------------------
# 确保 (space, seg) 上分配了地址段；-force 覆盖，天然幂等
proc vac_ensure_addr {offset range space seg} {
    if {[llength [get_bd_addr_spaces -quiet $space]] == 0} { fail "地址空间不存在：$space" }
    if {[llength [get_bd_addr_segs -quiet $seg]] == 0} { fail "地址段不存在：$seg" }
    assign_bd_address -offset $offset -range $range \
        -target_address_space [get_bd_addr_spaces $space] \
        [get_bd_addr_segs $seg] -force
    vac_log "地址 $offset/$range -> $seg"
}

# ---- 连线 ---------------------------------------------------------------
# 把一组 pin 连到同一个 net。语义：允许"多个 pin 共享一个已存在的 net"
# （这是最常见的场景，例如 FCLK0 已经驱动了很多引脚），只有以下情况报错：
#   - pin 不存在
#   - 这些 pin 分属两个不同的 net（状态不一致，必须人工判断）
proc vac_connect_net_if_free {pins} {
    set objs {}; set nets {}; set free_objs {}
    foreach p $pins {
        set pin [get_bd_pins -quiet $p]
        if {[llength $pin] == 0} { fail "pin 不存在：$p" }
        set obj [lindex $pin 0]
        lappend objs $obj
        set n [get_bd_nets -quiet -of_objects $pin]
        # 注意：不能用 expr 处理网表名（含 '/' 会被当成除号）
        if {[llength $n] > 0} {
            lappend nets [lindex $n 0]
        } else {
            lappend nets ""
            lappend free_objs $obj
        }
    }
    set distinct {}
    foreach n $nets {
        if {$n ne "" && [lsearch -exact $distinct $n] < 0} { lappend distinct $n }
    }
    if {[llength $distinct] > 1} { fail "这些 pin 已分属不同 net（状态不一致）：$pins" }
    if {[llength $free_objs] == 0} {
        vac_log "已全部连到同一 net，跳过：$pins"
        return
    }
    if {[llength $distinct] == 1} {
        # 把空闲 pin 接到已有 net 上：用"pin 接 pin"最稳（用 net 名做参数在部分版本会被当成 pin 路径）
        set anchored [lindex [lsearch -all -inline -not -exact $objs ""] 0]
        foreach f $free_objs { connect_bd_net $anchored $f }
        vac_log "挂到已有 net：$pins"
    } else {
        connect_bd_net {*}$objs
        vac_log "新建 net：$pins"
    }
}

# 接口连线：两个接口都空 -> 新建；一侧已连（例如已连到 interconnect）-> 报错让人判断
proc vac_connect_if_free {pins} {
    set objs {}
    foreach p $pins {
        set pin [get_bd_intf_pins -quiet $p]
        if {[llength $pin] == 0} { fail "接口 pin 不存在：$p" }
        if {[llength [get_bd_intf_nets -quiet -of_objects $pin]] > 0} {
            fail "接口已连接，拒绝重复连接：$p（请人工确认是否应删除旧连接）"
        }
        lappend objs [lindex $pin 0]
    }
    connect_bd_intf_net {*}$objs
    vac_log "连接接口 $pins"
}

# ---- 校验 ---------------------------------------------------------------
# 参数名写错在 Vivado 里只报 CRITICAL WARNING，不会中断。
# 重要属性改完必须回读确认"确实写进去了"。
proc vac_verify_prop {cell prop expected} {
    set got [get_property $prop [get_bd_cells $cell]]
    if {$got ne $expected} {
        fail "$cell 的属性 $prop 回读为 '$got'，期望 '$expected'（参数名可能写错）"
    }
    vac_log "$cell.$prop = $got"
}

# 补丁收尾：校验 + 保存（任何补丁脚本都应以此结尾）
proc vac_finalize {bd_name} {
    validate_bd_design
    save_bd_design
    puts "  BD 校验通过并已保存（$bd_name）"
    puts "  下一步：重跑 vivado/rebuild.tcl 做全量重建，验证补丁可复现"
}
