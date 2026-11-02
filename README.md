# vivado-as-code

> 把 Xilinx Vivado 工程变成"**工程即代码**"：不提交 `.xpr`，一条命令从零重建 bitstream，
> Block Design 和 Zynq PS 配置全部落在可 diff、可 review 的 TCL 文本里。
> 同时打包成一个 **AI Agent 技能（Skill）**，让 Claude Code / DeepSeek Harness 等助手
> 能按同一套方法论帮你改 PS 时钟、加 AXI 外设、定位构建问题。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 1. 它解决什么问题

| 传统做法 | 本方案 |
|---|---|
| 提交 `.xpr/.runs/.gen`，二进制不可 review | 只提交 `src/` + `xdc/` + `tcl/<bd>.tcl` + 构建脚本 |
| BD 改了哪里没人知道 | `write_bd_tcl` 导出文本，`git diff` 看得见 |
| 换台机器/队友 clone 后编不出来 | 一条命令全量重建 |
| PS 时钟/HP 口/中断配置只在 GUI 状态里 | 全部是 `CONFIG.PCW_*` 属性，脚本可配 |
| 参数名写错照样出 bit，硬件是错的 | 日志门禁：0 条 `CRITICAL WARNING` 才算过 |

## 2. 本机实测结果（Vivado 2020.2 / xc7z020clg400-2）

| 验证 | 结果 |
|---|---|
| 从 BD TCL 全量重建 BD + `.hwh` | ✅ 约 **0.5 分钟**，0 ERROR / 0 CRITICAL |
| 增量补丁幂等性（连跑 2 次 vs 1 次） | ✅ 导出的 BD TCL **哈希完全一致** |
| 全量综合 + 实现 + 生成 bit | ✅ 约 **4.8 分钟**，`design_1_wrapper.bit` 3.95 MB，**WNS +1.932 ns** |
| PS 时钟菜谱（FCLK0 100→150 MHz） | ✅ 回读 `ACT_FPGA0=150.000000`，分频自动变 4/3 |
| 日志门禁负例（注入 CRITICAL） | ✅ 退出码 2，正确拦截 |
| 产物一致性检查 | ✅ BD/`.hwh`/`.bit` 一致 |

> 完整记录见 [`docs/verification.md`](docs/verification.md)（含命令与原始输出摘要）。

## 3. 快速开始

### 3.1 作为技能安装（给 AI 助手用）

```bash
# Claude Code
git clone https://github.com/nx137/vivado-as-code ~/.claude/skills/vivado-as-code
# DeepSeek Harness
git clone https://github.com/nx137/vivado-as-code ~/.dsh/skills/vivado-as-code
```

装好后对助手说"用 vivado-as-code 把 FCLK0 改成 150MHz 并重建"即可，
助手会读 `SKILL.md`，按需加载 `references/` 里的细则。

### 3.2 直接当模板用（不需要 AI）

```bash
mkdir -p myproj/vivado
cp -r templates/project-skeleton/. myproj/
cp templates/rebuild.tcl myproj/vivado/rebuild.tcl
cp -r scripts myproj/scripts            # 可选：工程自带工具链

# 已有工程：把 BD 导出成真源
vivado -mode batch -source scripts/bd_export.tcl -tclargs \
    old_project.xpr design_1 myproj/tcl/design_1.tcl

# 构建（脚本在仓库里，或已复制进工程）
./scripts/build.ps1 -ProjectRoot myproj -StopAfter bd   # 只验 BD（约 1 分钟）
./scripts/build.ps1 -ProjectRoot myproj                  # 全量出 bit
```

Linux/macOS：`scripts/build.sh -p myproj -s bd`。

### 3.3 跑最小示例

```bash
cd examples/zynq7020-min
vivado -mode batch -source tcl/mk_min_bd.tcl     # 生成 tcl/design_1.tcl（只需一次）
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

## 4. 仓库结构

```
.
├── SKILL.md                 # 技能入口：铁律、决策树、脚本表、按需加载 references
├── references/
│   ├── ps7-config.md        # PS7 配置配方（时钟/HP/IRQ/MIO/DDR）+ 验证
│   ├── bd-patterns.md       # BD 即 TCL：回写、幂等补丁、扩互连、地址
│   ├── build-pipeline.md    # 九阶段、分级验证、日志门禁、目录约定
│   ├── pitfalls.md          # 症状→根因→检查命令（20+ 条）
│   └── pynq-handoff.md      # .bit/.hwh、Overlay、FS 校准、一致性检查
├── scripts/
│   ├── build.ps1 / build.sh # 一键构建入口（探测 Vivado、日志门禁）
│   ├── bd_export.tcl        # write_bd_tcl 回写 + 自动存档
│   ├── bd_patch_template.tcl# 幂等增量补丁模板（可跑通、可重复）
│   ├── lib/guards.tcl       # 幂等守卫库
│   ├── check_build.py       # 日志门禁（ERROR/CRITICAL/WNS）
│   └── check_handoff.py     # BD ↔ .hwh ↔ .bit 一致性
├── templates/
│   ├── rebuild.tcl          # 参数化九阶段构建
│   └── project-skeleton/    # 空工程骨架
└── examples/zynq7020-min/   # 可跑通的最小示例（PS7 + DMA 自环，零引脚约束）
```

## 5. 核心约定（不遵守就会复现老问题）

1. 不提交 `.xpr/.runs/.gen`；BD 真源是 `tcl/<bd>.tcl`。
2. GUI 改完 BD → `bd_export.tcl` 回写 → 全量重建验证 → commit。
3. 每次验证都**干净重建**，不依赖增量缓存。
4. 构建后必须过日志门禁（`check_build.py`），CRITICAL 数量必须为 0。
5. `.bit` / `.hwh` 同名同目录，且来自同一次构建。

## 6. 适用边界

- **优先 Zynq-7000（PS7）**；纯 7 系列 PL 工程同样适用；
  UltraScale+ MPSoC 需要把 PS 配置段换成 `zynq_ultra_ps_e` 的 `CONFIG.PSU__*`。
- 不处理 Vivado 安装/许可（示例用 WebPACK 覆盖的 xc7z020）。
- 不含任何特定开发板的引脚定义——板级 XDC 由使用者提供。
- 版本：BD TCL 带 Vivado 版本校验，跨版本升级方法见 `references/pitfalls.md` A4。

## 7. 出处与许可

这套方法来自 2026 年江苏省大学生电子设计竞赛（TI 杯）G 题参赛工程
（南京理工大学 NJ505 队，Zynq-7020 + PYNQ）。原工程把全部构建流程收敛到
`rebuild.tcl` + `bd_design_1.tcl`，本仓库是其中**可复用部分**的抽象与加固：
去掉板级/赛题专属内容，补上幂等守卫、日志门禁、一致性检查与最小示例。

代码与脚本：[MIT](LICENSE)。
