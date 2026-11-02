# 最小示例：Zynq-7020 + AXI DMA 自环

这个示例证明"**TCL 建 BD → 导出真源 → 全量重建 → 出 bit**"这条链路可用，
故意不依赖任何开发板的引脚定义，因此在任意 `xc7z020clg400-2` 板子上都能跑完。

## 设计内容

```
processing_system7_0
  ├─ FCLK_CLK0 100MHz ── 全设计单一时钟
  ├─ M_AXI_GP0 ──→ ps7_0_axi_periph ──→ axi_dma_0/S_AXI_LITE
  └─ S_AXI_HP0 ──→ axi_mem_intercon ←── axi_dma_0/M_AXI_MM2S
                                     ←── axi_dma_0/M_AXI_S2MM

axi_dma_0: MM2S → (AXI-Stream 自环) → S2MM
DDR / FIXED_IO: PS 固定引脚，不需要额外 XDC
```

为什么用自环：外部 AXI-Stream 引脚需要板级 XDC 才能布局布线。
自环让示例零引脚约束即可出 bit，验证的是构建链路本身。

## 跑法

```bash
# 1) 生成 BD 真源（只需一次，之后 tcl/design_1.tcl 就是唯一真源）
vivado -mode batch -source tcl/mk_min_bd.tcl

# 2) 只验证 BD（约 0.5 分钟）
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
#    Linux: ../../scripts/build.sh -p . -s bd

# 3) 全量出 bit（约 5 分钟）
../../scripts/build.ps1 -ProjectRoot .
```

## 预期输出

```
outputs/
├── design_1_wrapper.bit      ~3.95 MB
├── design_1_wrapper.hwh      ~300 KB
├── build_manifest.json       status=ok, wns≈+1.932ns
├── timing_summary.txt
└── utilization.txt
```

## 在示例上练手

```bash
# 改 PS 时钟 100 → 150 MHz，然后只重建 BD
cat > tcl/post_fclk150.tcl <<'EOF'
set ps [get_bd_cells processing_system7_0]
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150} $ps
puts "ACT = [get_property CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ $ps]"
EOF

$env:VAC_POST_BD_TCL = (Resolve-Path tcl/post_fclk150.tcl)
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
# 日志里应出现 ACT = 150.000000
```

```bash
# 加一个 AXI GPIO（幂等补丁，可重复执行）
$env:VAC_PATCH_TCL = (Resolve-Path ../../scripts/bd_patch_template.tcl)
$env:VAC_EXPORT_BD = "bd_exported.tcl"     # 导出补丁后的 BD，便于 diff
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
# 连跑两次，outputs/bd_exported.tcl 应完全一致（幂等性验证）
```
