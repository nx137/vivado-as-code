# Block Design 即代码：模式与配方

> 本文件回答："BD 怎么变成文本、怎么演进、怎么保证可重复"。

## 1. 两条工作流，先选一条

| 路线 | 适合 | 做法 |
|---|---|---|
| **A. GUI 编辑 + 回写真源**（推荐给新手/大改） | 新建 BD、大范围重连、看时序/资源 | Vivado GUI 里改 → `write_bd_tcl -force tcl/design_1.tcl` → 全量重建验证 → commit |
| **B. 纯脚本补丁**（推荐给加外设/批量改动） | 加 IP、接线、改地址、CI 里跑 | 写幂等补丁脚本，挂到 `VAC_PATCH_TCL`，每次重建自动执行 |

两者可以混用：日常小改用 B，大改用 A，A 的产物就是 B 的基础。

## 2. 路线 A：`write_bd_tcl` 回写

```bash
# GUI 里改完 BD 后（工程已打开）
vivado -mode batch -source scripts/bd_export.tcl -tclargs \
    vivado_project/vivado_project.xpr design_1 tcl/design_1.tcl
```

脚本会：`open_project` → `open_bd_design` → `validate_bd_design` → 旧文件存到 `tcl/archive/<bd>_<时间戳>.tcl` → `write_bd_tcl -force` → 打印 IP/地址数量。

**回写后必须做的三件事**：
1. `git diff tcl/design_1.tcl` 看改动是否就是你以为的那几处（这是 BD 唯一的 review 手段）；
2. 跑一次全量重建（`StopAfter=bd` 就够）；
3. 再跑一次全量出 bit，确认综合/实现没被破坏。

## 3. BD TCL 的结构（要知道改哪里）

`write_bd_tcl` 生成的脚本，顺序基本固定：

```tcl
# 版本校验（2020.2），不匹配会 return 1
# create_bd_design design_1
# 逐个 create_bd_cell（IP / module_ref）+ set_property -dict CONFIG.*
# connect_bd_intf_net（AXI/接口）与 connect_bd_net（时钟/复位/信号）
# make_bd_intf_pins_external / make_bd_pins_external（顶层端口）
# assign_bd_address（地址映射）
# validate_bd_design / save_bd_design
```

**不要手改生成文件里的 IP 配置**（可以，但容易和 Vivado 内部状态不一致）。要改就：
- 改 `CONFIG.*` 后重新跑一次 `validate_bd_design` + `save_bd_design`，再 `write_bd_tcl` 覆盖；
- 或者用路线 B 的补丁，从"干净 BD + 补丁"生成。

## 4. 路线 B：幂等补丁（本项目实际使用的方式）

### 4.1 骨架

```tcl
# 载入守卫库：只定位共享的 guard_loader.tcl（候选路径在它内部维护）
set _here [file dirname [file normalize [info script]]]
set _loader ""
foreach _c [list \
    [file join $_here lib guard_loader.tcl] \
    [file normalize [file join $_here .. scripts lib guard_loader.tcl]] \
    [file normalize [file join $_here .. .. scripts lib guard_loader.tcl]] \
] { if {[file exists $_c]} { set _loader $_c; break } }
if {$_loader eq ""} { puts "ERROR: 找不到 guard_loader.tcl"; exit 1 }
source $_loader

if {[llength [get_bd_designs -quiet]] == 0} { fail "没有打开的 BD" }
set _bd [current_bd_design]

set gpio [vac_ensure_ip xilinx.com:ip:axi_gpio:2.0 axi_gpio_user {CONFIG.C_GPIO_WIDTH {8}}]

vac_connect_net_if_free [list processing_system7_0/FCLK_CLK0 axi_gpio_user/s_axi_aclk]
vac_connect_if_free      [list ps7_0_axi_periph/M01_AXI      axi_gpio_user/S_AXI]
vac_ensure_addr 0x41240000 0x10000 processing_system7_0/Data axi_gpio_user/S_AXI/Reg
vac_verify_prop axi_gpio_user CONFIG.C_GPIO_WIDTH {8}

vac_finalize $_bd
```

**`scripts/lib/` 放哪里**：补丁只需找到 `guard_loader.tcl`（同目录 `lib/`、`../scripts/lib/`、
`../../scripts/lib/` 三处之一）；`guard_loader.tcl` 再负责载入同目录的 `guards.tcl`，
并支持 `VAC_GUARDS_TCL` 覆盖。候选路径只在 `guard_loader.tcl` 里维护，避免两处漂移。

推荐布局（补丁放工程里）：

```
myproj/
├── tcl/patch_add_gpio.tcl     # 你的补丁
└── scripts/lib/               # 从本仓库复制整个 lib/ 目录
    ├── guard_loader.tcl       # 载入器（候选路径的唯一来源）
    └── guards.tcl             # 守卫实现
```

补丁放在本仓库 `scripts/` 下时不用复制（`lib/` 就在旁边）。

### 4.2 幂等的四条规则（都是踩坑换来的）

1. **创建用 `vac_ensure_ip` / `vac_ensure_module`**，不要裸 `create_bd_cell`（重复执行会报 cell 重名）。
2. **"扩互连 + 接线 + 分地址"必须整体判断**。不要各自判断：
   - `NUM_MI + 1` 每跑一次就多一个口，第二次跑就变成 3 个 MI，虽然不报错但设计已经错了；
   - 正确判据：**目标从口的 `S_AXI` 是否已经有 net**。有 → 说明整段都做过了，直接跳过。
3. **连接时钟/复位时，允许"挂到已有 net"**。FCLK0 往往已经驱动了几十个引脚，
   不能因为"该 pin 已有 net"就报错；正确语义是：把空闲 pin 接到那个 net 上。
4. **重要属性回读**（`vac_verify_prop`）：Vivado 对写错的 IP 参数名只报 `CRITICAL WARNING` 并静默用默认值。

### 4.2.1 怎么验证幂等（别用错方法）

❌ 错误方法："跑两次 build，对比导出的 BD 一致"——每次构建都是**干净重建**，
补丁永远打在干净 BD 上，两次结果天然一致，验证不了任何东西。

✅ 正确方法：让**同一次构建**把补丁跑两遍：

```bash
VAC_PATCH_TCL="tcl/patch_add_gpio.tcl,tcl/patch_add_gpio.tcl" \
VAC_EXPORT_BD=bd_exported.tcl \
  scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

第二次执行时补丁应打印"已连接，跳过扩互连与地址分配"，且导出结果与只跑一次时**逐字节一致**：

```bash
# 对照组（只跑一次）
VAC_PATCH_TCL="tcl/patch_add_gpio.tcl" VAC_EXPORT_BD=bd_exported.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd
sha256sum outputs/bd_exported.tcl     # 两次的哈希应相同
```

### 4.3 两个 Vivado Tcl 的坑（本项目实测）

```tcl
# ❌ 错误：expr 会把含 '/' 的网表名当除法
lappend nets [expr {[llength $n] > 0 ? [lindex $n 0] : ""}]
# ✅ 正确
if {[llength $n] > 0} { lappend nets [lindex $n 0] } else { lappend nets "" }
```

```tcl
# ❌ 用"网表名/对象"接已有 net，某些版本会报 BD 41-701（参数解析成 pin 路径）
connect_bd_net [lindex $distinct 0] $free_pin
# ✅ 用已经连在该 net 上的 pin 作为锚点，pin 接 pin 最稳
connect_bd_net $anchored_pin $free_pin
```

### 4.4 扩 AXI 互连（加从设备）

```tcl
set mi_cur [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
set mi_new [expr {$mi_cur + 1}]
set_property CONFIG.NUM_MI $mi_new [get_bd_cells ps7_0_axi_periph]
set mi_idx [format "M%02d" [expr {$mi_new - 1}]]   ;# 注意别再拼一个 M
```

然后必须连 **ACLK / ARESETN**，否则 `validate_bd_design` 会报
`BD 41-758: clock pins not connected` 或 41-759 `input pins tied to 0`：

```tcl
vac_connect_net_if_free [list processing_system7_0/FCLK_CLK0  ps7_0_axi_periph/${mi_idx}_ACLK]
vac_connect_net_if_free [list rst_ps7_0_100M/peripheral_aresetn ps7_0_axi_periph/${mi_idx}_ARESETN]
```

> AXI Interconnect 2.1 在 `NUM_CLKS=1` 时**仍然有** `S00_ARESETN` / `M00_ARESETN` 等每端口复位引脚，
> 只连 `ARESETN` 会得到 41-759（不报 ERROR，但会 tie 到 0）。要么逐口连，要么显式 `CONFIG.HAS_ARESETN {0}`。

### 4.5 地址分配

```tcl
vac_ensure_addr 0x41240000 0x10000 processing_system7_0/Data axi_gpio_user/S_AXI/Reg
# DMA 主口访问 DDR：
assign_bd_address -offset 0x00000000 -range 0x40000000 \
    -target_address_space [get_bd_addr_spaces axi_dma_0/Data_S2MM] \
    [get_bd_addr_segs processing_system7_0/S_AXI_HP0/HP0_DDR_LOWOCM] -force
```

地址冲突/未分配不会让构建失败，但 PYNQ 里 `ip_dict` 会缺项或地址错——用
`scripts/check_handoff.py` 和 `.hwh` 对照检查。

### 4.6 外部端口与 XDC 端口漂移

`make_bd_intf_pins_external` / `make_bd_pins_external` 生成顶层端口后，
XDC 才能约束它们。**BD 大改后端口名可能变**（如 `gpio_io_o_0` → `gpio_io_o_1`），
XDC 找不到端口时 Vivado 只报 CRITICAL WARNING，约束静默失效。

检查：
```tcl
get_bd_ports                       ;# 看当前顶层端口名
report_property [get_bd_ports ...]
```
构建后用 `check_build.py` 兜底（CRITICAL 必须为 0）。

## 5. 版本校验与跨版本

生成的 BD TCL 开头有：

```tcl
set scripts_vivado_version 2020.2
if {[string first $scripts_vivado_version $current_vivado_version] == -1} { ... return 1 }
```

换 Vivado 版本时的正确做法：**用新版本 GUI 打开旧设计 → Report IP Status 升级 → 重新 write_bd_tcl**。
临时绕过校验（不推荐，只用于排查）：

```tcl
# 把 BD TCL 里的版本号改成你的版本，或注释掉那段 if
```

`rebuild.tcl` 已经能识别 `return 1` 并给出明确报错（"BD TCL 版本校验未通过"）。

## 6. 看改动：`bd_diff.py`（BD 语义 diff）

`git diff tcl/design_1.tcl` 在 600~700 行里只告诉你"哪几行变了"。语义 diff 把变化归成 5 类：

```bash
python scripts/bd_diff.py old.tcl new.tcl            # 人读
python scripts/bd_diff.py old.tcl new.tcl --json     # 机读
python scripts/bd_diff.py old.tcl new.tcl --fail-on-change   # CI 门禁（有差异退出 5）
```

输出示例（示例工程加 AXI GPIO 后）：

```
cells added (1):
  + axi_gpio_user
config changed (6):
  ~ ps7_0_axi_periph.NUM_MI: 1 -> 2
  ~ axi_gpio_user.C_GPIO_WIDTH: None -> 16
address changed (1):
  ~ axi_gpio_user/S_AXI/Reg: None -> {'offset': '0x41240000', 'range': '0x00010000'}
connections added (1):
  + axi_gpio_user/S_AXI <-> ps7_0_axi_periph/M01_AXI
```

典型用法：

- **回写真源前**：`bd_export.tcl` 导出后跑一次 diff，确认改动就是你以为的那几处；
- **PR review**：把 `--json` 的摘要贴进 PR 描述；
- **CI 守门**：对"不应该改 BD"的 PR 加 `--fail-on-change`。
