# 构建流水线：九阶段与门禁

## 1. 全流程

```
Phase 1  清理（删工程目录，每次全量干净重建）
Phase 2  create_project -part   ← 器件一致性检查
Phase 3  add RTL (src/*.v,*.sv)
Phase 4  add XDC (xdc/*.xdc)
Phase 5  重建 BD                ← 存档旧 BD TCL → source → 补丁 → 后处理 → validate/save
Phase 6  wrapper + IP 产物       ← make_wrapper / generate_target
Phase 7  synth_1                 ← status 必须 *Complete*
Phase 8  impl_1                  ← status 必须 *Complete*
Phase 9  write_bitstream + 报告 + 收集产物 + manifest
```

每阶段失败立即 `exit 1`，不吞错误。

## 2. 分级验证（`VAC_STOP_AFTER`）

| 值 | 做到哪 | 实测耗时（最小示例 xc7z020） | 用途 |
|---|---|---|---|
| `bd` | BD + wrapper + `.hwh` | **约 0.5 分钟** | 改 BD 后立刻验证 Tcl 是否正确 |
| `synth` | + 综合 | 约 2–3 分钟 | 查 RTL/约束引起的综合问题 |
| `impl` | + 实现 + 比特流 | **约 4.8 分钟** | 出可上板的 bit，查时序 |

> 真实项目（多 IP + 大 RTL）会明显更久：综合/实现常到 10–40 分钟。日常开发用 `bd`，
> 只在提交前跑 `impl`。

## 3. 产物约定

| 文件 | 说明 |
|---|---|
| `outputs/<top>.bit` | 比特流 |
| `outputs/<top>.hwh` | 硬件手递（地址/中断/参数），PYNQ 必需 |
| `outputs/build_manifest.json` | 机器可读的构建结果（status/vivado/part/wns/耗时） |
| `outputs/timing_summary.txt` | `report_timing_summary` |
| `outputs/utilization.txt` | `report_utilization` |

`.bit`/`.hwh` **不进 git**（`.gitignore` 已排除 `outputs/`），作为 release 附件分发；
PYNQ 部署时两个文件必须同名同目录。

## 4. 日志门禁（关键）

```bash
python scripts/check_build.py build.log --manifest outputs/build_manifest.json
```

| 退出码 | 含义 |
|---|---|
| 0 | 通过（0 ERROR / 0 CRITICAL WARNING / WNS ≥ 0） |
| 2 | 有 ERROR 或 CRITICAL WARNING |
| 3 | 时序未收敛（WNS < 0） |
| 1 | 参数/文件问题 |

**为什么必须扫日志**：Vivado 的退出码不可靠——
- IP 参数名写错 → 只报 `CRITICAL WARNING`，综合实现照跑，bit 照出，硬件行为错；
- 时序违例 → `write_bitstream` 仍可能成功；
- 部分 DRC 只在日志里。

推荐 CI 写法：

```bash
./scripts/build.sh -p . -s impl || exit 1
python3 scripts/check_build.py build.log --manifest outputs/build_manifest.json || exit 1
python3 scripts/check_handoff.py --bd tcl/design_1.tcl \
        --hwh outputs/design_1_wrapper.hwh --bit outputs/design_1_wrapper.bit || exit 1
```

## 5. 偶发失败与重试

Vivado batch 有已知偶发问题（IP init 时 `init.tcl/utils.tcl` 找不到、run 卡在
`Running` 但无进展、GUI 与 batch 同时持有 BD）。处理顺序：

1. 关掉所有 Vivado GUI（batch 与 GUI 抢同一工程会互相覆盖）；
2. 重跑一次（干净重建，很多问题是缓存引起的）；
3. 仍失败 → `reset_target all` 后重跑；
4. 看日志里的 `init.tcl` / `ipgen_iptclns` 关键字，必要时换机器/换 Vivado 小版本。

## 6. 目录约定

```
myproj/
├── src/                  # RTL（*.v/*.sv）
├── xdc/                  # 约束（*.xdc）
├── tcl/
│   ├── design_1.tcl      # BD 真源（write_bd_tcl 导出）
│   ├── post_bd.tcl       # 可选：BD 后处理（改 PS 时钟等）
│   └── archive/          # 自动存档，gitignore
├── vivado/rebuild.tcl    # 构建入口（从 templates/ 复制）
└── outputs/              # 产物，gitignore
```

`.gitignore` 至少要包含：`vivado_project/`、`outputs/`、`*.jou`、`*.log`、`*.str`、
`.Xil/`、`tcl/archive/`。

## 7. 接入已有工程（不改原布局）

已有工程通常是这样：`vivado/src`、`vivado/xdc`、`vivado/tcl/<bd>.tcl`，构建后还要把
`.bit/.hwh` 改名复制到 PYNQ 目录。**不用搬家**，写一个适配器脚本把路径翻译成环境变量：

```tcl
# vivado/rebuild_vac.tcl
set _here  [file normalize [info script]]
set _root  [file dirname [file dirname $_here]]
set env(VAC_ROOT)          $_root
set env(VAC_SRC_DIR)       vivado/src
set env(VAC_XDC_DIR)       vivado/xdc
set env(VAC_BD_TCL)        vivado/tcl/bd_design_1.tcl
set env(VAC_PATCH_TCL)     "vivado/tcl/bd_add_fm_modem.tcl,vivado/tcl/patch_fix_bd_issues.tcl"
set env(VAC_POST_BD_TCL)   vivado/tcl/post_bd_uart_aclk.tcl
set env(VAC_COPY_TO)       software/pynq/main
set env(VAC_ARTIFACT_NAME) xinhao_uart_kb_adf4351_rf
source [file join "D:/vivado-as-code" templates rebuild.tcl]
```

然后：

```bash
scripts/build.ps1 -ProjectRoot . -RebuildScript vivado/rebuild_vac.tcl -StopAfter bd
```

要点：
- 原来的 `build.bat` / `rebuild.tcl` **保留不动**，两套入口并存；
- 原来 `rebuild.tcl` 里"source BD 之后"的 `set_property` 收到 `VAC_POST_BD_TCL`；
- 原来"复制并改名到 PYNQ 目录"的动作由 `VAC_COPY_TO` + `VAC_ARTIFACT_NAME` 完成；
- 先跑 `-StopAfter bd`（分钟级），确认 BD 与补丁都正确，再跑全量。

### 7.1 第一次接入通常会被门禁拦下

原流程多半没检查过 CRITICAL WARNING。实测一个真实竞赛工程，第一次接入就抓到 3 类问题：
一个从未连接的多余 AXI 主口（`NUM_SI=3` 但 `S02_AXI` 空）、一个只建了网名却没接驱动的中断
（`axi_dma_0/s2mm_introut` 没接进 `xlconcat`）、以及一组预留通道的未连接 `tvalid`。
前两个是真 bug，第三个显式接常量 0 即可。

处理原则：
1. **能修的在 BD 里修**（写成幂等补丁，挂到 `VAC_PATCH_TCL`）；
2. 只有"确认无害且无法消除"的才进白名单 `<root>/.vac-lint-allow`，并写明原因；
3. 修完必须验证"补丁之后不再出现该 CRITICAL"（`grep` 日志的行号顺序即可判断）。

完整可抄的适配文件见 `examples/real-project-adoption/`。