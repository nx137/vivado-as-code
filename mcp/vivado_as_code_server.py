#!/usr/bin/env python3
"""vivado_as_code_server.py —— vivado-as-code 的 MCP server（零依赖，stdio）。

目的：
    让 Claude Code / DeepSeek Harness 等支持 MCP 的宿主**直接调用**构建、检查、
    语义 diff、recipe 渲染，而不是每次会话都靠读文档拼命令。

协议：
    JSON-RPC 2.0 over stdio，MCP 2024-11-05 子集：
    initialize / notifications/initialized / tools/list / tools/call / ping

约束（重要）：
    - **stdout 只输出协议 JSON**；所有日志/错误信息走 stderr；
    - 工具会读写工程目录（vac_build / vac_bd_export / vac_recipe_render）；
    - 全量构建可能 30–60 分钟，vac_build 默认超时 3600s。

用法：
    python mcp/vivado_as_code_server.py
    # Claude Code: claude mcp add vivado-as-code -- python <repo>/mcp/vivado_as_code_server.py
    # DSH: 在 MCP 连接配置里加同样的 command/args

自测：
    python mcp/vivado_as_code_server.py --self-test
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_NAME = "vivado-as-code"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[vivado-as-code-mcp] {msg}", file=sys.stderr, flush=True)


def ascii_safe(text: str, limit: int = 4000) -> str:
    return text[:limit].encode("ascii", "replace").decode("ascii")


def run_python(script: str, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def find_vivado() -> str:
    env = os.environ.get("VIVADO_BIN", "")
    if env and Path(env).exists():
        return env
    for name in ("vivado", "vivado.bat"):
        hit = shutil.which(name)
        if hit:
            return hit
    patterns = [
        r"C:\Xilinx\Vivado\*\bin\vivado.bat",
        r"D:\Xilinx\Vivado\*\bin\vivado.bat",
        r"E:\Xilinx\Vivado\*\bin\vivado.bat",
        r"D:\vivado*\Vivado\*\bin\vivado.bat",
        r"C:\Program Files\Xilinx\Vivado\*\bin\vivado.bat",
        "/tools/Xilinx/Vivado/*/bin/vivado",
        "/opt/Xilinx/Vivado/*/bin/vivado",
        str(Path.home() / "Xilinx/Vivado/*/bin/vivado"),
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    raise FileNotFoundError("未找到 Vivado：请设置 VIVADO_BIN，或把 vivado 加入 PATH")


def read_manifest(project_root: str) -> dict | None:
    path = Path(project_root) / "outputs" / "build_manifest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# 工具实现（全部转发到已测脚本）
# ---------------------------------------------------------------------------
def tool_vac_build(args: dict) -> dict:
    project_root = str(args.get("project_root", "")).strip()
    if not project_root or not Path(project_root).is_dir():
        raise ValueError("project_root 不存在或未提供")
    stop_after = str(args.get("stop_after", "bd"))
    if stop_after not in ("bd", "synth", "impl"):
        raise ValueError("stop_after 必须是 bd / synth / impl")
    jobs = int(args.get("jobs", 8))
    patch_files = args.get("patch_files") or []
    export_bd = str(args.get("export_bd", "") or "")
    timeout = int(args.get("timeout_sec", 3600))

    env = dict(os.environ)
    env["VAC_STOP_AFTER"] = stop_after
    env["VAC_JOBS"] = str(jobs)
    env["VAC_PATCH_TCL"] = ",".join(patch_files)
    env["VAC_EXPORT_BD"] = export_bd

    build_ps1 = SCRIPTS / "build.ps1"
    build_sh = SCRIPTS / "build.sh"
    if os.name == "nt":
        shell = shutil.which("pwsh") or "powershell"
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(build_ps1),
               "-ProjectRoot", project_root, "-StopAfter", stop_after, "-Jobs", str(jobs)]
    else:
        cmd = ["bash", str(build_sh), "-p", project_root, "-s", stop_after, "--jobs", str(jobs)]

    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)

    log_path = str(Path(project_root) / "build.log")
    critical = errors = None
    if Path(log_path).is_file():
        code, out, _ = run_python("check_build.py", [log_path, "--json"])
        try:
            summary = json.loads(out)
            critical = summary.get("critical_warnings")
            errors = summary.get("errors")
        except json.JSONDecodeError:
            pass

    tail = ""
    if Path(log_path).is_file():
        try:
            lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-40:])
        except OSError:
            tail = ""

    return {
        "exit_code": proc.returncode,
        "stop_after": stop_after,
        "manifest": read_manifest(project_root),
        "critical_warnings": critical,
        "errors": errors,
        "log_path": log_path,
        "log_tail": ascii_safe(tail),
        "stdout_tail": ascii_safe(proc.stdout[-2000:]),
    }


def tool_vac_check_log(args: dict) -> dict:
    log_path = str(args.get("log_path", "")).strip()
    if not log_path or not Path(log_path).is_file():
        raise ValueError(f"日志不存在：{log_path}")
    extra = ["--json", "--explain"]
    manifest = str(args.get("manifest_path", "") or "")
    if manifest:
        extra += ["--manifest", manifest]
    code, out, err = run_python("check_build.py", [log_path, *extra])
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = {"raw": out, "stderr": err}
    data["exit_code"] = code
    return data


def tool_vac_bd_diff(args: dict) -> dict:
    a, b = str(args.get("bd_a", "")), str(args.get("bd_b", ""))
    if not a or not b:
        raise ValueError("需要 bd_a 与 bd_b")
    sys.path.insert(0, str(SCRIPTS))
    import bd_diff  # noqa: E402

    result = bd_diff.diff(bd_diff.parse_bd(bd_diff.load(Path(a))), bd_diff.parse_bd(bd_diff.load(Path(b))))
    result["has_changes"] = bd_diff.has_changes(result)
    return result


def tool_vac_bd_export(args: dict) -> dict:
    project_xpr = str(args.get("project_xpr", "")).strip()
    bd_name = str(args.get("bd_name", "design_1"))
    out_path = str(args.get("out_path", "")).strip()
    if not project_xpr or not Path(project_xpr).is_file():
        raise ValueError(f"工程文件不存在：{project_xpr}")
    if not out_path:
        raise ValueError("需要 out_path")
    vivado = find_vivado()
    cmd = [vivado, "-mode", "batch", "-source", str(SCRIPTS / "bd_export.tcl"),
           "-nojournal", "-log", str(Path(out_path).parent / "bd_export.log"),
           "-tclargs", project_xpr, bd_name, out_path]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1800)
    return {
        "ok": proc.returncode == 0 and Path(out_path).is_file(),
        "exit_code": proc.returncode,
        "path": out_path,
        "stdout_tail": ascii_safe(proc.stdout[-2000:]),
        "stderr_tail": ascii_safe(proc.stderr[-2000:]),
    }


def tool_vac_check_handoff(args: dict) -> dict:
    bd = str(args.get("bd", ""))
    hwh = str(args.get("hwh", ""))
    bit = str(args.get("bit", "") or "")
    cmd_args = ["--bd", bd, "--hwh", hwh, "--json"]
    if bit:
        cmd_args += ["--bit", bit]
    code, out, err = run_python("check_handoff.py", cmd_args)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = {"raw": out, "stderr": err}
    data["exit_code"] = code
    return data


def tool_vac_recipe_render(args: dict) -> dict:
    name = str(args.get("recipe", "")).strip()
    params = args.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    sys.path.insert(0, str(SCRIPTS))
    import recipe  # noqa: E402

    text = recipe.render(name, {k: str(v) for k, v in params.items()})
    out_path = str(args.get("out_path", "") or "")
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
    return {
        "ok": True,
        "recipe": name,
        "out_path": out_path or None,
        "bytes": len(text.encode("utf-8")),
        "preview": ascii_safe(text[:1500]),
    }


# ---------------------------------------------------------------------------
# 工具声明
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "vac_build",
        "description": "Run a vivado-as-code build (writes into the project directory). "
                       "stop_after=bd is fast (~1 min) and validates Block Design; impl produces the bitstream "
                       "and may take 30-60 minutes. Returns exit code, build manifest, CRITICAL/ERROR counts and log tail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {"type": "string", "description": "工程根目录（含 vivado/rebuild.tcl、src/、xdc/、tcl/）"},
                "stop_after": {"type": "string", "enum": ["bd", "synth", "impl"], "default": "bd"},
                "jobs": {"type": "integer", "default": 8},
                "patch_files": {"type": "array", "items": {"type": "string"},
                                "description": "BD 增量补丁路径（相对项目根或绝对）"},
                "export_bd": {"type": "string", "description": "导出打补丁后的 BD 到 outputs/<name>"},
                "timeout_sec": {"type": "integer", "default": 3600},
            },
            "required": ["project_root"],
        },
    },
    {
        "name": "vac_check_log",
        "description": "Check a Vivado build log: counts ERROR/CRITICAL WARNING, checks WNS from the manifest, "
                       "and returns known-issue suggestions. Exit code 0=pass, 2=errors/criticals, 3=timing not met.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_path": {"type": "string"},
                "manifest_path": {"type": "string"},
            },
            "required": ["log_path"],
        },
    },
    {
        "name": "vac_bd_diff",
        "description": "Semantic diff of two Block Design TCL files: added/removed cells, CONFIG changes, "
                       "address changes and connection changes. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bd_a": {"type": "string", "description": "旧 BD TCL"},
                "bd_b": {"type": "string", "description": "新 BD TCL"},
            },
            "required": ["bd_a", "bd_b"],
        },
    },
    {
        "name": "vac_bd_export",
        "description": "Export the current Block Design of a Vivado project to a full TCL file "
                       "(write_bd_tcl). Writes the output file and runs Vivado in batch mode.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_xpr": {"type": "string"},
                "bd_name": {"type": "string", "default": "design_1"},
                "out_path": {"type": "string"},
            },
            "required": ["project_xpr", "out_path"],
        },
    },
    {
        "name": "vac_check_handoff",
        "description": "Check consistency between BD TCL, .hwh and .bit (stale hwh, basename pairing). "
                       "Exit code 0=pass, 4=mismatch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bd": {"type": "string"},
                "hwh": {"type": "string"},
                "bit": {"type": "string"},
            },
            "required": ["bd", "hwh"],
        },
    },
    {
        "name": "vac_recipe_render",
        "description": "Render a parameterized BD patch recipe (add_axi_gpio / add_axi_uartlite / "
                       "add_axi_dma_hp / set_fclk / open_irq_f2p). Writes the generated Tcl file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipe": {"type": "string"},
                "params": {"type": "object", "additionalProperties": {"type": ["string", "number"]}},
                "out_path": {"type": "string"},
            },
            "required": ["recipe"],
        },
    },
]

HANDLERS = {
    "vac_build": tool_vac_build,
    "vac_check_log": tool_vac_check_log,
    "vac_bd_diff": tool_vac_bd_diff,
    "vac_bd_export": tool_vac_bd_export,
    "vac_check_handoff": tool_vac_check_handoff,
    "vac_recipe_render": tool_vac_recipe_render,
}


# ---------------------------------------------------------------------------
# JSON-RPC / MCP
# ---------------------------------------------------------------------------
def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def error_response(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method in ("notifications/initialized", "initialized"):
        return None  # 通知，无响应

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return error_response(req_id, -32602, f"unknown tool: {name}")
        try:
            payload = handler(arguments)
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:  # 工具错误返回给调用方，而不是让服务崩溃
            log(f"tool {name} failed: {exc}")
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True,
                },
            }

    return error_response(req_id, -32601, f"method not found: {method}")


def serve() -> int:
    log(f"server ready: {SERVER_NAME} {SERVER_VERSION} (repo={REPO_ROOT})")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            send(error_response(None, -32700, f"parse error: {exc}"))
            continue
        if not isinstance(msg, dict):
            send(error_response(None, -32600, "invalid request"))
            continue
        response = handle(msg)
        if response is not None:
            send(response)
    return 0


def self_test() -> int:
    """不经过 stdio，直接验证工具注册与实现可导入。"""
    ok = True
    for tool in TOOLS:
        name = tool["name"]
        if name not in HANDLERS:
            print(f"missing handler: {name}", file=sys.stderr)
            ok = False
    try:
        find_vivado()
        print("vivado: found", file=sys.stderr)
    except FileNotFoundError as exc:
        print(f"vivado: {exc}", file=sys.stderr)
    print(f"tools={len(TOOLS)} ok={ok}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(serve())
