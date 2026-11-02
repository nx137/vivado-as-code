# Vivado 版本升级：把旧 BD 迁到新版本

> 场景：工程在 Vivado 2020.2 上开发，现在要用 2022.x / 2024.x 打开并继续维护。
> 直接 `source tcl/design_1.tcl` 会被版本校验拦下（脚本内 `scripts_vivado_version`），
> GUI 里手工"Report IP Status → 升级 → 导出"又容易漏步骤。

## 1. 一条命令

```bash
# 在装了新版本 Vivado 的机器上（VIVADO_BIN 指向新版本）
vivado -mode batch -source scripts/bd_upgrade.tcl -tclargs \
    tcl/design_1.tcl tcl/design_1_<newver>.tcl xc7z020clg400-2
```

MCP 方式：

```json
{"name": "vac_bd_upgrade",
 "arguments": {"bd_in": "tcl/design_1.tcl",
               "bd_out": "tcl/design_1_upgraded.tcl"}}
```

脚本做的事：

1. 把 BD TCL 里的 `set scripts_vivado_version <旧版本>` 替换成当前版本（复制到临时文件，
   原文件不动）；
2. 建临时工程 → `source` 放宽版本校验后的 BD；
3. `upgrade_ip` 升级所有 IP（同版本时是 no-op，不报错）；
4. `validate_bd_design` + `save_bd_design`；
5. `write_bd_tcl -force <out>` 导出新版本真源；
6. 打印升级前后 IP 定义（`IPDEF`，形如 `xilinx.com:ip:axi_dma:7.1`），便于 review；
7. 清理临时工程（`VAC_UPGRADE_KEEP=1` 可保留排查）。

## 2. 升级后必须做的回归

```bash
# 1) 用新真源重建 BD（分钟级）
VAC_BD_TCL=tcl/design_1_<newver>.tcl scripts/build.ps1 -ProjectRoot . -StopAfter bd

# 2) 语义 diff：升级前后到底变了什么
python scripts/bd_diff.py tcl/design_1.tcl tcl/design_1_<newver>.tcl

# 3) 全量构建 + 时序门禁（IP 升级可能改变时序/资源）
scripts/build.ps1 -ProjectRoot .
```

实测（同版本 2020.2 往返）：`bd_diff` 输出 `no semantic changes`，重建 BD PASS、
0 CRITICAL —— 说明升级流程本身不会破坏设计。

## 3. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 升级后 `validate_bd_design` 报错 | IP 升级改变了端口/参数 | 看 `bd_diff` 的 config/connection 变化，按新 IP 文档调整后重新导出 |
| 升级后时序变差 | IP 内部实现变化 | 跑 `check_build.py --explain`，按 `pitfalls.md` C 类处理；必要时锁定旧 IP 版本 |
| `upgrade_ip` 报 "no IPs to upgrade" | 本来就是新版本 | 正常，脚本会继续导出 |
| 导出脚本里仍有旧版本号 | 输入文件被其它脚本覆盖 | 检查 `VAC_BD_TCL` 指向的文件，重新跑升级 |

## 4. 多版本并存建议

同一个仓库里不要提交多份 BD TCL。推荐：

- 仓库保存**目标版本的唯一真源**（如 `tcl/design_1.tcl`）；
- 升级时在分支上跑 `bd_upgrade.tcl`，用 `bd_diff.py` 的结果写 PR 说明；
- 升级完成、回归通过后再合并，旧版本靠 git 历史回溯。

## 5. 边界

- 升级助手只负责"打开旧设计、升级 IP、导出新 TCL"，**不保证**跨大版本（如 2018→2024）
  一次成功；跨大版本建议中途落一个 LTS 版本（如 2020.2 → 2022.2 → 2024.x）。
- 板级约束（XDC）可能因 IP 端口变化需要同步调整，记得跑 `check_build.py`。
- 升级后务必重新做 PYNQ 侧验证（地址/中断可能变化，见 `pynq-handoff.md`）。
