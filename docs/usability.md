# 可用性测试（V6）：新助手只靠文档能否完成任务

## 测试方式

启动一个**全新上下文**的 AI 助手，只告诉它仓库位置与任务，不给任何额外提示：

> 读 `SKILL.md`，按文档把 `examples/zynq7020-min` 复制到临时目录，
> 用文档里的"幂等增量补丁"路线加一个 AXI GPIO（`axi_gpio_user`，8 bit，双通道，全输出），
> 然后只做 BD 阶段构建并验证。

## 结果：任务完成 ✅

| 检查项 | 结果 |
|---|---|
| 构建退出码 | 0（耗时 0.5 分钟） |
| 日志 CRITICAL WARNING | **0** |
| 导出的 BD 里出现 `axi_gpio_user` | ✅（`create_bd_cell ... axi_gpio_user` + 地址 `0x41240000`） |
| `.hwh` 里出现该 IP | ✅（57 行命中 `INSTANCE="axi_gpio_user"`） |
| 幂等性（同一次构建内补丁跑 1 次 vs 2 次） | ✅ **导出 BD 哈希一致** |
| 是否需要"猜"关键步骤 | 需要 4 处（见下），已全部修复 |

## 暴露的问题与修复

### 1. 补丁复制到工程 `tcl/` 后找不到 `guards.tcl`（已修复）

> v0.3.2 起改为共享 `scripts/lib/guard_loader.tcl`：补丁只需找到它，候选路径与错误提示集中在一处。

现象：按 `references/bd-patterns.md` §4.1 把补丁放进 `<proj>/tcl/`，直接报
`invalid command name "vac_ensure_ip"`（Vivado 退出码 1 / 脚本 2，提示指不到根因）。
测试助手只能自己把 `scripts/lib/guards.tcl` 复制到 `tcl/lib/` 才跑通。

修复：
- `bd_patch_template.tcl` 的守卫库查找顺序扩展为 6 个位置：
  `$env:VAC_GUARDS_TCL` → `./lib/guards.tcl` → `./guards.tcl` →
  `../scripts/lib/guards.tcl` → `../../scripts/lib/guards.tcl` → `$pwd/scripts/lib/guards.tcl`；
- 全部失败时打印"已尝试路径 + 解决办法"；
- `SKILL.md` 决策树与 `bd-patterns.md` §4.1 写明放置约定。

### 2. `VAC_PATCH_TCL` 的相对路径按 Vivado 当前目录解析（已修复）

现象：`build.ps1` 不改变工作目录，`rebuild.tcl` 用 `file normalize` 相对 Vivado 的 cwd 解析，
于是 `VAC_PATCH_TCL=tcl/patch_add_gpio.tcl` 找不到文件。

修复：`rebuild.tcl` 对 `VAC_PATCH_TCL` / `VAC_POST_BD_TCL` / `VAC_BD_TCL` 的
**相对路径统一按项目根目录解析**；文档同步说明。

### 3. 模板的"双通道全输出"少一半，且回读不足（已修复）

现象：`bd_patch_template.tcl` 只设了 `C_ALL_OUTPUTS`，漏了 `C_ALL_OUTPUTS_2`
（第二通道仍是双向）；`vac_verify_prop` 只回读 `C_GPIO_WIDTH`，违反自家铁律"重要属性必须回读"。

修复：补上 `C_ALL_OUTPUTS_2 {1}`，并回读 5 个属性
（`C_GPIO_WIDTH` / `C_GPIO2_WIDTH` / `C_IS_DUAL` / `C_ALL_OUTPUTS` / `C_ALL_OUTPUTS_2`）。

### 4. 幂等性验证的写法不成立（已修复文档）

现象：文档写"连跑两次 build，对比导出的 BD"。但默认每次都是**干净重建**，
补丁永远打在干净 BD 上，两次结果天然一致——这个写法验证不了幂等。

修复：正确写法是让**同一次构建**把补丁跑两遍：

```bash
VAC_PATCH_TCL="tcl/patch_add_gpio.tcl,tcl/patch_add_gpio.tcl" \
VAC_EXPORT_BD=bd_exported.tcl ./scripts/build.ps1 -ProjectRoot . -StopAfter bd
```

`V2` 与示例 README 都已改成这个写法。

### 5. `StopAfter=bd` 也会生成 `.hwh`（已补充说明）

文档原来只列全量产物，容易误以为 BD 阶段没有 `.hwh`。实际上
`generate_target all` 会在 `.gen/.../hw_handoff/` 生成 `.hwh` 并复制到 `outputs/`，
可用于 PYNQ 地址验证。`SKILL.md` 已注明。

### 6. 示例 BD 文件名不一致（已统一）

`scripts/bd_export.tcl`、`bd_patch_template.tcl` 的注释里写 `tcl/bd_design_1.tcl`，
而默认约定是 `tcl/design_1.tcl`。已统一；`README.md` 里提到原竞赛工程历史文件名的地方保留（那是事实）。

## 其它已知显示问题（非阻塞）

- **PowerShell 5.1 控制台看中文日志会乱码**：Vivado 输出 UTF-8 字节，PS 5.1 控制台按 GBK 解码。
  日志**文件**本身是 UTF-8，`check_build.py` 读取正常；关键结论看
  `outputs/build_manifest.json`、`build.log` 与退出码，不要依赖控制台回显。

## 结论

- 文档的"决策树 + 模板 + 守卫库"路径有效：新助手在无口头提示下完成了任务；
- 最有价值的改进不是增加说明，而是**更聪明的路径解析**、**更完整的回读**、
  以及**能真正证伪的验证写法**（同轮双跑补丁）。
