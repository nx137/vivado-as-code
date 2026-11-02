# tcl/ —— Block Design 真源

| 文件 | 说明 |
|---|---|
| `design_1.tcl` | 由 `scripts/bd_export.tcl` 从 GUI 导出的**全量 BD**，是唯一真源（可空，首次生成） |
| `post_bd.tcl` | 可选：BD 构建之后的属性覆盖（如改 PS 时钟），由 `VAC_POST_BD_TCL` 指定 |
| `archive/` | 每次构建自动存档的旧 BD（`.gitignore` 已排除） |

改 BD 的两条路：
- **大改**：GUI 改 → `bd_export.tcl` 回写 → 全量重建验证 → commit；
- **小改/加外设**：写幂等补丁脚本（参考 `references/bd-patterns.md` §4 的补丁骨架），挂到 `VAC_PATCH_TCL`。
