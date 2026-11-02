# 用 CI 跑真实 Vivado 构建（可选）

GitHub 托管的 runner **没有 Vivado**（许可 + 安装体积），所以：

- **托管 CI（默认，见 `.github/workflows/ci.yml`）**：只跑纯 Python 测试，
  保证脚本/解析器/协议不回归，秒级完成；
- **自托管 runner（本文档）**：在装有 Vivado 的机器上跑真实构建，用于夜晚回归或发版前验证。

---

## 1. 自托管 runner 上的最小 workflow

在仓库建 `.github/workflows/vivado.yml`（**不要**默认启用，按需手动触发）：

```yaml
name: vivado-build

on:
  workflow_dispatch:
  schedule:
    - cron: "0 18 * * *"      # 每天 UTC 18:00（北京时间 02:00）

jobs:
  bd:
    runs-on: [self-hosted, windows, vivado]
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4

      - name: Detect Vivado
        shell: pwsh
        run: |
          if (-not $env:VIVADO_BIN) { throw "runner 需要设置 VIVADO_BIN 环境变量" }
          & $env:VIVADO_BIN -version

      - name: Build Block Design (fast gate)
        shell: pwsh
        run: ./scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter bd

      - name: Full build (bitstream)
        shell: pwsh
        run: ./scripts/build.ps1 -ProjectRoot examples/zynq7020-min -StopAfter impl

      - name: Artifacts
        uses: actions/upload-artifact@v4
        with:
          name: bitstream
          path: |
            examples/zynq7020-min/outputs/*.bit
            examples/zynq7020-min/outputs/*.hwh
            examples/zynq7020-min/outputs/build_manifest.json
            examples/zynq7020-min/outputs/timing_summary.txt
```

关键点：

- `runs-on` 用自定义标签（如 `[self-hosted, windows, vivado]`），把这台机器注册成 runner；
- runner 上设置 `VIVADO_BIN`（例如 `E:\Xilinx\Vivado\2020.2\bin\vivado.bat`）；
- `build.ps1` 自己会做日志门禁（CRITICAL WARNING 也算失败），不需要额外步骤；
- 全量构建 30–60 分钟，`timeout-minutes` 要给够。

## 2. 在自己的工程上跑

把 workflow 里的 `examples/zynq7020-min` 换成你的工程根目录即可：

```yaml
run: ./scripts/build.ps1 -ProjectRoot path/to/your/project -StopAfter bd
```

## 3. 只验证"脚本没坏"的极速方案

不想维护 runner 的话，本地一条命令即可：

```bash
python -m unittest discover -s tests -t . -v      # 秒级，不需要 Vivado
```

配合 `scripts/check_build.py --explain` 在本地构建后做门禁。

## 4. 许可提醒

- Vivado 许可不可分发，镜像/缓存里不要包含 `~/.Xilinx` 的 license 文件；
- 若用 WebPACK，确认目标器件在免费范围内（示例 `xc7z020clg400-2` 属于 WebPACK 覆盖范围）；
- 自托管 runner 的磁盘要预留 Vivado 安装 + 工程缓存（通常 40–80 GB）。
