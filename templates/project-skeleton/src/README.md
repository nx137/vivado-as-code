# src/ —— RTL 源文件

把 `.v` / `.sv` / `.vh` 放在这里。`rebuild.tcl` 的 Phase 3 会 `glob` 本目录并全部加入工程。

约定：
- 一个模块一个文件，文件名 = 模块名（便于 BD 里 `create_bd_cell -type module -reference <模块名>`）；
- 改端口/参数时，如果综合结果"没变化"，见 `references/pitfalls.md` A5（模块名缓存），必要时改名 `_v2`。
