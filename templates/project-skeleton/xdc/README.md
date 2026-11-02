# xdc/ —— 约束文件

把 `.xdc` 放在这里，Phase 4 会全部加入。

注意：
- BD 改动后**顶层端口名可能漂移**（`gpio_io_o_0` → `_1`），XDC 找不到端口时
  Vivado 只报 CRITICAL WARNING，约束静默失效 —— 构建后必须过 `check_build.py`；
- 时钟约束建议按端口/网络命名分开写（`adc_pins.xdc`、`da_pins.xdc`…），便于 diff。
