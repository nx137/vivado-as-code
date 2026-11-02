# 可用性测试（V6）：新助手只靠文档能否完成任务

## 测试方式

启动一个**全新上下文**的 AI 助手，只告诉它仓库位置与任务，不给任何额外提示：

> 读 `SKILL.md`，按文档把 `examples/zynq7020-min` 复制到临时目录，
> 用文档里的"幂等增量补丁"路线加一个 AXI GPIO（`axi_gpio_user`，8 bit，双通道，全输出），
> 然后只做 BD 阶段构建并验证。

## 结果：任务完成 ✅

| 检查项 | 结果 |
|---|---|
| 构建退出码 | 0 |
| 日志 CRITICAL WARNING | **0** |
| 导出的 BD 里出现 `axi_gpio_user` | ✅（`create_bd_cell ... axi_gpio_user`） |
| `.hwh` 里出现该 IP | ✅（57 处引用） |
| 幂等性（补丁跑 1 次 vs 2 次的导出 BD） | ✅ **哈希一致** |
| 助手是否需要"猜"关键步骤 | 基本不需要：它直接复制 `bd_patch_template.tcl` 改 IP 参数 |

## 暴露的文档缺口（已修复）

### 1. 补丁复制到工程 `tcl/` 后找不到 `guards.tcl`（已修复）

助手把 `bd_patch_template.tcl` 复制成 `<proj>/tcl/patch_add_gpio.tcl` 后，
模板只按"补丁脚本同级 `lib/guards.tcl`"查找，于是它不得不手工把
`scripts/lib/guards.tcl` 再复制到 `<proj>/tcl/lib/`。
文档没写这一步。

**修复**：模板的守卫库查找顺序扩展为
`$env:VAC_GUARDS_TCL` → `./lib/guards.tcl` → `./guards.tcl` →
`../scripts/lib/guards.tcl` → `../../scripts/lib/guards.tcl` → `$pwd/scripts/lib/guards.tcl`，
并在全部失败时打印已尝试路径与解决办法。

### 2. 快速上手的 `cp` 目标目录不存在（已修复）

`cp templates/rebuild.tcl myproj/vivado/rebuild.tcl` 在 `myproj/vivado/` 不存在时会失败。
**修复**：所有文档的快速上手都先 `mkdir -p myproj/vivado`，并补上"把 `scripts/` 一起复制进工程"的可选步骤。

### 3. `check_handoff.py` 对 `.hwh` 的解析过严（已修复）

`.hwh` 的 `<MODULE>` 属性顺序不固定（`COREREVISION` 在前），原正则要求 `FULLNAME` 紧跟 `<MODULE`，
导致正例被误判为"0 个 MODULE"。**修复**：改为 `<MODULE\b[^>]*?\bFULLNAME="/([^"]+)"`，
并用真实 `.hwh` 做了正例/负例验证。

## 结论

- 文档的"决策树 + 模板 + 守卫库"路径是有效的：新助手在**没有口头提示**的情况下完成了任务；
- 最需要的不是更多说明，而是**更聪明的路径解析**和**可执行的检查器**——
  这正是本次修掉的三处；
- 剩余改进空间：把 `patch_add_gpio` 这类高频补丁做成 `scripts/recipes/` 预设，
  让助手"选一个 + 改参数"而不是"抄模板再改"。
