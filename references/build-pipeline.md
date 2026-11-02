# 构建流水线：九阶段与门禁

## 1. 全流程

```
Phase 1  清理（删工程目录）      ← 除非 VAC_REUSE=1
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
