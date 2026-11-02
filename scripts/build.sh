#!/usr/bin/env bash
# =============================================================================
# build.sh —— 一键构建入口（Linux / macOS / WSL / Git Bash）
# -----------------------------------------------------------------------------
# 用法：
#   ./scripts/build.sh -p /path/to/project           # 全量构建到 bit
#   ./scripts/build.sh -p . -s bd                    # 只重建 BD
#   VIVADO_BIN=/opt/Xilinx/Vivado/2020.2/bin/vivado ./scripts/build.sh -p .
#
# 退出码：0 成功；非 0 失败（可直接用于 CI）
# 注意：本脚本在 Linux 上仍属 beta，欢迎提 issue 反馈。
# =============================================================================
set -u

PROJECT_ROOT="$(pwd)"
STOP_AFTER="impl"
PART=""
TOP=""
JOBS=""
REBUILD=""
VIVADO_HINT=""

usage() {
    cat <<'EOF'
用法: build.sh [-p 项目根目录] [-s bd|synth|impl] [--part 器件] [--top 顶层]
               [--jobs N] [--rebuild 脚本] [--vivado 路径]
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -p|--project)  PROJECT_ROOT="$2"; shift 2 ;;
        -s|--stop)     STOP_AFTER="$2"; shift 2 ;;
        --part)        PART="$2"; shift 2 ;;
        --top)         TOP="$2"; shift 2 ;;
        --jobs)        JOBS="$2"; shift 2 ;;
        --rebuild)     REBUILD="$2"; shift 2 ;;
        --vivado)      VIVADO_HINT="$2"; shift 2 ;;
        -h|--help)     usage; exit 0 ;;
        *) echo "未知参数: $1"; usage; exit 1 ;;
    esac
done

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
[ -n "$REBUILD" ] || REBUILD="$PROJECT_ROOT/vivado/rebuild.tcl"
[ -f "$REBUILD" ] || { echo "找不到构建脚本: $REBUILD"; exit 1; }

find_vivado() {
    if [ -n "$VIVADO_HINT" ] && [ -x "$VIVADO_HINT" ]; then echo "$VIVADO_HINT"; return; fi
    if [ -n "${VIVADO_BIN:-}" ] && [ -x "${VIVADO_BIN}" ]; then echo "$VIVADO_BIN"; return; fi
    if command -v vivado >/dev/null 2>&1; then command -v vivado; return; fi
    for p in /tools/Xilinx/Vivado/*/bin/vivado /opt/Xilinx/Vivado/*/bin/vivado "$HOME"/Xilinx/Vivado/*/bin/vivado; do
        [ -x "$p" ] && { echo "$p"; return; }
    done
    echo ""
}

VIVADO_EXE="$(find_vivado)"
[ -n "$VIVADO_EXE" ] || { echo "未找到 Vivado，请设置 VIVADO_BIN 或用 --vivado 指定"; exit 1; }

LOG="$PROJECT_ROOT/build.log"
echo "=== vivado-as-code build ==="
echo "  vivado       : $VIVADO_EXE"
echo "  project root : $PROJECT_ROOT"
echo "  rebuild.tcl  : $REBUILD"
echo "  stop after   : $STOP_AFTER"
echo "  log          : $LOG"

export VAC_STOP_AFTER="$STOP_AFTER"
[ -n "$PART" ] && export VAC_PART="$PART"
[ -n "$TOP" ] && export VAC_TOP="$TOP"
[ -n "$JOBS" ] && export VAC_JOBS="$JOBS"

START=$(date +%s)
"$VIVADO_EXE" -mode batch -source "$REBUILD" -nojournal -log "$LOG"
CODE=$?
ELAPSED=$(( $(date +%s) - START ))
echo ""
echo "Vivado 退出码: $CODE，耗时 $(( ELAPSED / 60 )) 分 $(( ELAPSED % 60 )) 秒"

if [ "$CODE" -eq 0 ]; then
    # 日志门禁需要 Python：优先 python3，回退 python。
    # 注意：要实际执行一次，排除 Windows Store 的 python3 存根（存在但调用即失败）。
    PYTHON_BIN=""
    for _cand in python3 python; do
        if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c 'import sys' >/dev/null 2>&1; then
            PYTHON_BIN="$(command -v "$_cand")"
            break
        fi
    done
    CHECKER="$(cd "$(dirname "$0")" && pwd)/check_build.py"
    if [ -n "$PYTHON_BIN" ] && [ -f "$CHECKER" ]; then
        echo "--- 日志门禁 (check_build.py) ---"
        ALLOW_ARGS=()
        if [ -n "${VAC_CHECK_ALLOW:-}" ]; then
            IFS=';,' read -ra _pats <<< "$VAC_CHECK_ALLOW"
            for _pat in "${_pats[@]}"; do
                [ -n "$_pat" ] && ALLOW_ARGS+=(--allow "$_pat")
            done
        fi
        if [ -f "$PROJECT_ROOT/.vac-lint-allow" ]; then
            while IFS= read -r _line || [ -n "$_line" ]; do
                _pat="$(printf '%s' "$_line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
                case "$_pat" in ''|'#'*) continue ;; esac
                ALLOW_ARGS+=(--allow "$_pat")
            done < "$PROJECT_ROOT/.vac-lint-allow"
        fi
        "$PYTHON_BIN" "$CHECKER" "$LOG" --manifest "$PROJECT_ROOT/outputs/build_manifest.json" "${ALLOW_ARGS[@]}"
        LINT=$?
        if [ "$LINT" -ne 0 ]; then
            echo "[BUILD FAILED] 日志含 ERROR / CRITICAL WARNING（退出码 $LINT）"
            exit "$LINT"
        fi
    else
        echo "（未找到 python3/python，跳过日志门禁；建议手动 grep -i CRITICAL $LOG）"
    fi
fi

[ "$CODE" -eq 0 ] || { echo "[BUILD FAILED] 见 $LOG"; exit "$CODE"; }
echo "[BUILD OK] 产物目录: $PROJECT_ROOT/outputs"
exit 0
