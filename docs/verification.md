# 验证记录

环境：Windows 10/11 · Vivado **2020.2** · 器件 `xc7z020clg400-2` · 2026-11-02。

## V1 — 只重建 BD（`StopAfter=bd`）

```bash
scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter bd
```

结果：✅ Vivado 退出码 0，耗时 **0.5 分钟**；
产物 `outputs/design_1_wrapper.hwh`（约 300 KB）+ `build_manifest.json`；
`check_build.py`：ERROR 0 / CRITICAL WARNING 0 / `RESULT: PASS`。

## V2 — 增量补丁幂等性

验证必须让**同一次构建**把补丁跑两遍（只跑两次 build 不算：每次都是干净重建）：

```bash
VAC_PATCH_TCL="patch_add_gpio.tcl,patch_add_gpio.tcl" \
VAC_EXPORT_BD=bd_exported.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

| 运行 | 补丁执行次数 | 导出 BD |
|---|---|---|
| A | 1 次 | 16,304 bytes |
| B | 2 次（第二次走"已连接，跳过"分支） | 16,304 bytes |

结果：✅ 两次导出的 `bd_exported.tcl` **SHA256 完全一致**（幂等成立）。

第一版补丁并不幂等：`NUM_MI` 从 1→2→3，第二次运行把 AXI 互连多扩了一个口。
修复方式：整段"扩互连 + 接线 + 分地址"用"S_AXI 是否已连接"统一判断。

## V3 — 全量构建出 bit

```bash
scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter impl
```

结果：✅ 退出码 0，耗时 **4.8 分钟**（287 s）

| 产物 | 大小 |
|---|---|
| `design_1_wrapper.bit` | 3,950.9 KB |
| `design_1_wrapper.hwh` | 296 KB |
| `build_manifest.json` | `status=ok`, `wns=1.932`, `elapsed_sec=287` |
| `timing_summary.txt` / `utilization.txt` | 已生成 |

时序：**WNS = +1.932 ns**（满足），日志门禁 PASS。

## V4 — 日志门禁负例

构造只含一条 `CRITICAL WARNING: [BD 41-759] ...` 的假日志：

```bash
python scripts/check_build.py fake_vivado.log
# ERROR 0 / CRITICAL WARNING 1 / RESULT: FAIL
# exit code = 2
```

结果：✅ 正确拦截（退出码 2）。

## V4b — 产物一致性检查（`check_handoff.py`）

- 正例：`BD(5 IP) ↔ .hwh(5 MODULE)` → `RESULT: PASS`，退出码 0；
- 负例：`.bit` 不存在 → 明确报错，退出码 4。

（首版正则过严，`<MODULE>` 属性顺序不固定导致误报 0 个 MODULE，已修复。）

## V5 — PS7 时钟配方（FCLK0 100 → 150 MHz）

```tcl
set ps [get_bd_cells processing_system7_0]
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150} $ps
```

回读结果：

```
ACT_FPGA0 = 150.000000
CLK0_FREQ = 150000000
DIV0 = 4  DIV1 = 3        # 1800 / 4 / 3 = 150 MHz
```

导出的 BD TCL 中对应行：

```tcl
CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ {150.000000}
CONFIG.PCW_CLK0_FREQ {150000000}
CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR0 {4}
CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR1 {3}
```

结果：✅ 只改一个"用户意图"属性，Vivado 自动重算分频。

## V6 — 新助手可用性测试

由全新上下文的 AI 助手只依据 `SKILL.md` 完成"给示例加 AXI GPIO 并重建 BD"：

| 检查 | 结果 |
|---|---|
| 构建退出码 | 0 |
| 日志 CRITICAL WARNING | **0** |
| 导出的 BD / `.hwh` 中出现 `axi_gpio_user` | ✅ / ✅ |
| 补丁幂等性（同轮 1 次 vs 2 次） | ✅ 导出 BD 哈希一致 |
| 是否需要口头提示 | ❌ 不需要，仅靠文档完成 |

暴露并已修复的 6 处问题（详见 `docs/usability.md`）：
守卫库路径解析、`VAC_PATCH_TCL` 相对路径、模板回读不全、幂等验证写法、
BD 阶段 `.hwh` 说明、示例文件名不一致。

## V7 — 技能加载

`git clone --depth 1` 到 `~/.claude/skills/vivado-as-code` 与 `~/.dsh/skills/vivado-as-code`，
两个目录均含 `SKILL.md`（根级）+ `references/`（5 篇）。

结果：✅ 宿主在下一次会话刷新时**自动把 `vivado-as-code` 加入可用技能列表**，
说明目录结构与 frontmatter（`name` / `description` / `license`）符合两套技能系统的约定。

## V8 — 干净 clone 端到端验收

```bash
git clone --depth 1 https://github.com/nx137/vivado-as-code.git /tmp/vac
cd /tmp/vac
scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter bd
```

结果：✅ 退出码 0，`RESULT: PASS`，生成 `design_1_wrapper.hwh` 与 `build_manifest.json`。
即"clone 即可重建"成立（本机 Vivado 自动探测到 `E:\Xilinx\Vivado\2020.2`）。
