# vivado-as-code

> 把 Xilinx Vivado 工程变成"**工程即代码**"：不提交 `.xpr`，一条命令从零重建 bitstream，
> Block Design 和 Zynq PS 配置全部落在可 diff、可 review 的 TCL 文本里。
> 同时提供 **AI Agent 技能 + MCP 工具层**，让 Claude Code / DeepSeek Harness 能直接
> 调构建、查日志、做 BD 语义 diff、渲染参数化补丁。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/nx137/vivado-as-code/actions/workflows/ci.yml/badge.svg)](https://github.com/nx137/vivado-as-code/actions/workflows/ci.yml)

**English summary** — Vivado as code: one-command full-TCL rebuild of a Xilinx project
(no `.xpr` in VCS), Block Design and Zynq PS7 configuration kept as reviewable Tcl,
idempotent BD patches, semantic BD diff, log gate with fix hints, plus a zero-dependency
MCP server and an AI-agent skill. MIT.

---

## 1. 它解决什么问题

| 传统做法 | 本方案 |
|---|---|
| 提交 `.xpr/.runs/.gen`，二进制不可 review | 只提交 `src/` + `xdc/` + `tcl/<bd>.tcl` + 构建脚本 |
| BD 改了哪里没人知道 | `write_bd_tcl` 导出文本，`git diff` / `bd_diff.py` 看得见 |
| 换台机器/队友 clone 后编不出来 | 一条命令全量重建 |
| PS 时钟/HP 口/中断配置只在 GUI 状态里 | 全部是 `CONFIG.PCW_*` 属性，脚本可配 |
| 参数名写错照样出 bit，硬件是错的 | 日志门禁：0 条 `CRITICAL WARNING` 才算过，并给出修复建议 |
| AI 助手每次都要读文档拼命令 | MCP 工具层 + SKILL.md，工具带参数校验与结构化返回 |

## 2. 版本特性

### v0.3 新增

| 能力 | 用法 | 说明 |
|---|---|---|
| **PS7 声明式配置** | `python scripts/ps7_config.py render ps7.yaml --out tcl/post_bd_ps7.tcl` | 用 `ps7.yaml` 写设计意图（FCLK/HP 口/IRQ/MIO/DDR），生成**带回读断言**的 Tcl；未知键直接报错 |
| **跨版本升级助手** | `vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs 旧.tcl 新.tcl <part>` | 放宽版本校验 → `upgrade_ip` → `validate` → 导出新真源，并打印升级前后 IP 定义 |
| **MCP 扩到 8 工具** | `vac_ps7_render` / `vac_bd_upgrade` | AI 可直接渲染 PS7 配置、执行跨版本升级 |
| **全套英文文档** | [`README.en.md`](README.en.md) / [`SKILL.en.md`](SKILL.en.md) | 英文用户与英文 agent 可直接使用 |

### v0.2 新增

| 能力 | 用法 | 说明 |
|---|---|---|
| **MCP server** | `python mcp/vivado_as_code_server.py` | 8 个工具：`vac_build` / `vac_check_log` / `vac_bd_diff` / `vac_bd_export` / `vac_check_handoff` / `vac_recipe_render` / `vac_ps7_render` / `vac_bd_upgrade`；`.mcp.json` 一份配置同时适用 Claude Code 与 DSH |
| **参数化补丁 recipes** | `python scripts/recipe.py render add_axi_gpio -p name=xxx --out tcl/patch.tcl` | 5 个：`add_axi_gpio` / `add_axi_uartlite` / `add_axi_dma_hp` / `set_fclk` / `open_irq_f2p`，自带幂等与属性回读 |
| **BD 语义 diff** | `python scripts/bd_diff.py old.tcl new.tcl --json` | 新增/删除 cell、CONFIG 变更、地址变更、连线变更；`--fail-on-change` 可做 CI 门禁 |
| **日志诊断** | `python scripts/check_build.py build.log --explain` | 已知错误模式（BD 41-759/758/701、版本锁、Vivado 环境）→ 修复动作 + pitfalls 章节 |
| **测试与 CI** | `python -m unittest discover -s tests -t . -v` | 75 个用例，GitHub Actions 双平台 × Python 3.9/3.12，不需要 Vivado |

## 3. 实测（Vivado 2020.2 / xc7z020clg400-2）

| 验证 | 结果 |
|---|---|
| 从 BD TCL 重建 BD + `.hwh` | ✅ 约 **0.5 分钟**，0 ERROR / 0 CRITICAL |
| 增量补丁幂等性（同轮双跑） | ✅ 导出 BD **哈希完全一致** |
| 全量综合 + 实现 + 生成 bit | ✅ 约 **4.8 分钟**，`.bit` 3.95 MB，**WNS +1.932 ns** |
| PS 时钟菜谱（FCLK0 100→150 MHz） | ✅ 回读 `ACT=150.000000`，分频自动 4/3 |
| recipe 渲染 → 构建 | ✅ `add_axi_gpio` 参数化补丁 0 CRITICAL、幂等 |
| BD 语义 diff | ✅ 精确报出新增 cell、`NUM_MI 1→2`、新增地址 `0x41240000` |
| 日志诊断（注入 41-759） | ✅ 给出修复动作并指向 `pitfalls.md` B3 |
| MCP 端到端 | ✅ 6 工具可列；`vac_build`/`vac_bd_diff`/`vac_check_handoff`/`vac_recipe_render` 返回结构化结果 |
| 干净 clone 端到端 | ✅ 退出码 0，`RESULT: PASS` |
| 新助手仅凭文档完成任务 | ✅ 加 AXI GPIO + 重建 BD，0 CRITICAL |
| PS7 声明式（yaml→Tcl→构建） | ✅ `fclk0: 150` 构建后回读 `ACT=150.000000`，0 CRITICAL |
| 跨版本升级（同版本往返） | ✅ 导出新真源，`bd_diff` 报 `no semantic changes`，重建 BD PASS |
| 测试 | ✅ **75 个用例**（Python 3.9–3.12，CI 双平台） |

> 详细记录：[`docs/verification.md`](docs/verification.md)；可用性测试与修复：[`docs/usability.md`](docs/usability.md)；
> 全量功能审计（v0.3.1）：[`docs/audit-2026-11-02.md`](docs/audit-2026-11-02.md)。

> 依赖：Python ≥ 3.9（脚本与 MCP 全部使用标准库，无需 `pip install`）+ Vivado 2020.2（实跑构建时）。`pytest` 可选，仓库测试用标准库 `unittest`。
## 4. 快速开始

### 4.1 作为技能安装（给 AI 助手用）

```bash
git clone https://github.com/nx137/vivado-as-code ~/.claude/skills/vivado-as-code   # Claude Code
git clone https://github.com/nx137/vivado-as-code ~/.dsh/skills/vivado-as-code      # DeepSeek Harness
```

### 4.2 作为 MCP 工具挂载（推荐，AI 可直接调）

在工程根目录放 `.mcp.json`（Claude Code 与 DSH 通用，DSH 也认 `.dsh/mcp.json`）：

```json
{
  "mcpServers": {
    "vivado-as-code": {
      "command": "python",
      "args": ["D:/vivado-as-code/mcp/vivado_as_code_server.py"]
    }
  }
}
```

详见 [`mcp/README.md`](mcp/README.md)。

### 4.3 直接当模板用（不需要 AI）

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

### 4.4 跑最小示例

```bash
cd examples/zynq7020-min
vivado -mode batch -source tcl/mk_min_bd.tcl     # 生成 tcl/design_1.tcl（只需一次）
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

### 4.5 接入已有工程（不改原布局）

已有工程常把 RTL/XDC 放在 `vivado/` 下、BD 在 `vivado/tcl/`、产物要改名拷到 PYNQ 目录。
写一个 20 行的适配器，用 `-RebuildScript` 切进来即可，原 `build.bat` 保留不动：

```tcl
# vivado/rebuild_vac.tcl
set env(VAC_ROOT)          [file dirname [file dirname [file normalize [info script]]]]
set env(VAC_SRC_DIR)       vivado/src
set env(VAC_XDC_DIR)       vivado/xdc
set env(VAC_BD_TCL)        vivado/tcl/bd_design_1.tcl
set env(VAC_PATCH_TCL)     vivado/tcl/bd_add_fm_modem.tcl
set env(VAC_POST_BD_TCL)   vivado/tcl/post_bd_uart_aclk.tcl
set env(VAC_COPY_TO)       software/pynq/main
set env(VAC_ARTIFACT_NAME) xinhao_uart_kb_adf4351_rf
source [file join $env(VIVADO_AS_CODE) templates rebuild.tcl]
```

```bash
scripts/build.ps1 -ProjectRoot . -RebuildScript vivado/rebuild_vac.tcl -StopAfter bd
```

实测记录与可抄的适配文件：[`examples/real-project-adoption/`](examples/real-project-adoption/)。

## 5. 仓库结构

```
.
├── SKILL.md                 # 技能入口：铁律、决策树、工具表、按需加载 references
├── references/
│   ├── ps7-config.md        # PS7 配置配方（时钟/HP/IRQ/MIO/DDR）+ 验证
│   ├── bd-patterns.md       # BD 即 TCL：回写、幂等补丁、地址、bd_diff、recipe
│   ├── build-pipeline.md    # 九阶段、分级验证、日志门禁、目录约定
│   ├── pitfalls.md          # 症状→根因→检查命令（20+ 条）
│   ├── version-upgrade.md   # 跨 Vivado 版本升级流程
│   └── pynq-handoff.md      # .bit/.hwh、Overlay、FS 校准、一致性检查
├── scripts/
│   ├── build.ps1 / build.sh # 一键构建入口（探测 Vivado、日志门禁）
│   ├── bd_export.tcl        # write_bd_tcl 回写 + 自动存档
│   ├── bd_patch_template.tcl# 幂等增量补丁模板（可跑通、可重复）
│   ├── lib/guards.tcl       # 幂等守卫库
│   ├── recipe.py            # 参数化补丁渲染器
│   ├── recipes/             # 5 个补丁模板
│   ├── bd_diff.py           # BD 语义 diff
│   ├── ps7_config.py        # 声明式 PS7 配置（yaml → Tcl）
│   ├── bd_upgrade.tcl       # 跨 Vivado 版本升级 BD
│   ├── check_build.py       # 日志门禁 + --explain 诊断
│   └── check_handoff.py     # BD ↔ .hwh ↔ .bit 一致性
├── mcp/
│   ├── vivado_as_code_server.py  # 零依赖 stdio MCP server
│   └── README.md            # Claude Code / DSH 接入
├── templates/
│   ├── rebuild.tcl          # 参数化九阶段构建
│   └── project-skeleton/    # 空工程骨架
├── examples/zynq7020-min/   # 可跑通的最小示例（PS7 + DMA 自环，零引脚约束）
├── examples/ps7/            # 声明式 PS7 配置示例
├── examples/real-project-adoption/  # 真实工程接入模板
├── tests/                   # 74 个单元/协议测试（不需要 Vivado）
├── .github/workflows/ci.yml # 双平台 × Python 3.9/3.12
└── docs/                    # 验证记录、可用性测试、自托管 CI 模板
```

## 6. 核心约定（不遵守就会复现老问题）

1. 不提交 `.xpr/.runs/.gen`；BD 真源是 `tcl/<bd>.tcl`。
2. GUI 改完 BD → `bd_export.tcl` 回写 → `bd_diff.py` 确认改动 → 全量重建验证 → commit。
3. 每次验证都**干净重建**，不依赖增量缓存。
4. 构建后必须过日志门禁（`check_build.py`），CRITICAL 数量必须为 0。
5. `.bit` / `.hwh` 同名同目录，且来自同一次构建；交付前用 `check_handoff.py`。

## 7. 适用边界

- **优先 Zynq-7000（PS7）**；纯 7 系列 PL 工程同样适用；
  UltraScale+ MPSoC 需要把 PS 配置段换成 `zynq_ultra_ps_e` 的 `CONFIG.PSU__*`。
- 不处理 Vivado 安装/许可（示例用 WebPACK 覆盖的 xc7z020）。
- 不含任何特定开发板的引脚定义——板级 XDC 由使用者提供。
- 版本：BD TCL 带 Vivado 版本校验（2020.2），跨版本升级方法见 `references/pitfalls.md` A4。

## 8. 出处与许可

这套方法来自 2026 年江苏省大学生电子设计竞赛（TI 杯）G 题参赛工程
（南京理工大学 NJ505 队，Zynq-7020 + PYNQ）。原工程把全部构建流程收敛到
`rebuild.tcl` + `bd_design_1.tcl`，本仓库是其中**可复用部分**的抽象与加固：
去掉板级/赛题专属内容，补上幂等守卫、日志门禁、语义 diff、MCP 工具层与测试。

代码与脚本：[MIT](LICENSE)。
