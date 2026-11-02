# 工程骨架：从这里开始

复制本目录到你的工程根目录，然后：

```bash
cp -r templates/project-skeleton myproj
cp templates/rebuild.tcl myproj/vivado/rebuild.tcl
```

## 目录约定

```
myproj/
├── src/                  # RTL 源文件（*.v / *.sv / *.vh）
├── xdc/                  # 约束文件（*.xdc）
├── tcl/
│   ├── design_1.tcl      # Block Design 真源（write_bd_tcl 导出；首次可空）
│   └── archive/          # 构建时自动存档旧 BD（勿提交）
├── vivado/
│   └── rebuild.tcl       # 构建入口（从 ../../templates/rebuild.tcl 复制）
├── outputs/              # .bit/.hwh/报告（勿提交）
└── .gitignore
```

## 三条路，按情况选

### A. 已有 Vivado 工程，想转成全量 TCL

```bash
# 1) 把已有工程的 BD 导出成文本真源
vivado -mode batch -source ../../scripts/bd_export.tcl -tclargs \
    <old_project.xpr> design_1 tcl/design_1.tcl

# 2) 把 RTL / XDC 拷进 src/ 与 xdc/（保持原相对路径无所谓，rebuild 会 glob）
# 3) 全量重建验证
../../scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

### B. 从零新建

在 Vivado GUI 里 `create_project` + `create_bd_design`，配好 PS（或纯 PL），
然后按 A 的第 1、3 步导出真源并验证。之后所有改动优先用补丁脚本。

### C. 纯 RTL 工程（无 BD）

删掉 `tcl/design_1.tcl`，把 `rebuild.tcl` 里 Phase 5/6 的 BD 相关段落注释掉，
并在 Phase 4 之后加：

```tcl
set_property top <你的顶层> [current_fileset]
```

再跑 `build.ps1 -StopAfter synth` 验证。

## 首次提交前

- [ ] `git status` 里没有 `vivado_project/`、`outputs/`、`*.log`
- [ ] `tcl/design_1.tcl` 是最新的（`bd_export.tcl` 回写过）
- [ ] `build.ps1 -StopAfter bd` 通过且 0 CRITICAL
- [ ] `build.ps1` 全量通过且 WNS ≥ 0
- [ ] `.bit` / `.hwh` 同名同目录（如果要提交产物到 release）
