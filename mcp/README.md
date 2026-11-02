# MCP 接入：把 vivado-as-code 变成 AI 可直接调用的工具

本目录的 `vivado_as_code_server.py` 是一个**零依赖**（只用 Python 标准库）的
MCP server，通过 stdio 提供 6 个工具：

| 工具 | 作用 | 会写文件？ | 典型耗时 |
|---|---|---|---|
| `vac_build` | 跑构建（`bd`/`synth`/`impl`），返回 manifest + 日志摘要 | ✅ 工程目录 | bd ≈ 1 min，impl 30–60 min |
| `vac_check_log` | 日志门禁 + 已知问题建议 | ❌ | 秒级 |
| `vac_bd_diff` | 两份 BD TCL 的语义 diff | ❌ | 秒级 |
| `vac_bd_export` | `write_bd_tcl` 回写 BD 真源 | ✅ 输出文件 | 1–2 min |
| `vac_check_handoff` | BD ↔ `.hwh` ↔ `.bit` 一致性 | ❌ | 秒级 |
| `vac_ps7_render` | `ps7.yaml` → 带回读断言的 Tcl | ✅ 输出文件 | 秒级 |

## 通用：项目级 `.mcp.json`

Claude Code 与 DeepSeek Harness 都支持在**会话工作区**放 `.mcp.json`（DSH 同时识别 `.dsh/mcp.json`），
schema 一致：

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

把 `args` 换成你 clone 后的实际路径即可。Windows 上也可以写 `python.exe`；
Linux/macOS 用 `python3`。若 `python` 不在 PATH，写绝对路径。

## Claude Code

```bash
# 方式 1：命令行注册（project scope 会写 .mcp.json）
claude mcp add vivado-as-code -- python /path/to/vivado-as-code/mcp/vivado_as_code_server.py

# 方式 2：直接用上面的 .mcp.json
claude mcp list          # 确认已加载
```

## DeepSeek Harness（DSH）

DSH 的 `dsh-workspace-mcp` 会从工作区读取 `.dsh/mcp.json`（或 `.mcp.json`）并把其中的
server 挂载给 agent。把上面的 `.mcp.json` 放到你的工程根目录即可，无需改 profile。

## 自测（不经过宿主）

```bash
# 工具注册与 Vivado 探测
python mcp/vivado_as_code_server.py --self-test

# 协议级自测（仓库测试套件里的 test_mcp_protocol.py 就是这么做的）
python -m unittest tests.test_mcp_protocol -v
```

手工验证一次 `initialize`：

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0"}}}' |
  python mcp/vivado_as_code_server.py
```

## 安全与边界

- 工具以**当前用户权限**执行，`vac_build` 会删除并重建工程目录里的 `vivado_project/`
  （与 CLI 行为一致）；不要在含手工改动工程文件的目录里跑。
- server 不联网，只调用本地 Vivado / 本地脚本。
- `vac_build` 的 `timeout_sec` 默认 3600；宿主可能在工具返回前超时，长构建建议
  先用 `stop_after=bd` 验证，再用 CLI 跑全量。
- stdout 只输出协议 JSON；调试信息都在 stderr（宿主日志里可见）。
