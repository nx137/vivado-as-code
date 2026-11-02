# =============================================================================
# build.ps1 —— 一键构建入口（Windows / PowerShell 5.1+ 与 PowerShell 7+）
# -----------------------------------------------------------------------------
# 用法（在任意目录）：
#   .\scripts\build.ps1 -ProjectRoot D:\myproj                 # 全量构建到 bit
#   .\scripts\build.ps1 -ProjectRoot . -StopAfter bd           # 只重建 BD（3~5 分钟）
#   .\scripts\build.ps1 -ProjectRoot . -StopAfter synth -Jobs 8
#
# 它会：
#   1. 依次探测 Vivado：$env:VIVADO_BIN -> PATH -> 常见安装路径；
#   2. 调用 <ProjectRoot>\vivado\rebuild.tcl（可用 -RebuildScript 覆盖）；
#   3. 把日志落到 <ProjectRoot>\build.log；
#   4. 若本机有 python，自动调用 scripts/check_build.py 做日志门禁（CRITICAL WARNING 也算失败）；
#   5. 把退出码透传出去（0 = 成功）。
# =============================================================================
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Get-Location).Path,
    [ValidateSet('bd', 'synth', 'impl')]
    [string]$StopAfter = 'impl',
    [string]$Part = '',
    [string]$Top = '',
    [int]$Jobs = 0,
    [string]$RebuildScript = '',
    [string]$Vivado = '',
    [switch]$Reuse,
    [switch]$SkipLint
)

$ErrorActionPreference = 'Stop'

function Find-Vivado {
    param([string]$Hint)
    if ($Hint) {
        if (Test-Path $Hint) { return (Resolve-Path $Hint).Path }
        throw "指定的 Vivado 不存在: $Hint"
    }
    if ($env:VIVADO_BIN -and (Test-Path $env:VIVADO_BIN)) { return (Resolve-Path $env:VIVADO_BIN).Path }

    $cmd = Get-Command vivado -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command vivado.bat -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $patterns = @(
        'C:\Xilinx\Vivado\*\bin\vivado.bat',
        'D:\Xilinx\Vivado\*\bin\vivado.bat',
        'E:\Xilinx\Vivado\*\bin\vivado.bat',
        'D:\vivado*\Vivado\*\bin\vivado.bat',
        'C:\Program Files\Xilinx\Vivado\*\bin\vivado.bat',
        '/tools/Xilinx/Vivado/*/bin/vivado'
    )
    foreach ($p in $patterns) {
        $hit = Get-ChildItem -Path $p -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    throw "未找到 Vivado。请设置 VIVADO_BIN 环境变量，或用 -Vivado <路径> 指定。"
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not $RebuildScript) { $RebuildScript = Join-Path $ProjectRoot 'vivado\rebuild.tcl' }
if (-not (Test-Path $RebuildScript)) { throw "找不到构建脚本: $RebuildScript" }

$vivadoExe = Find-Vivado -Hint $Vivado
$log = Join-Path $ProjectRoot 'build.log'
$started = Get-Date

Write-Host "=== vivado-as-code build ===" -ForegroundColor Cyan
Write-Host "  vivado       : $vivadoExe"
Write-Host "  project root : $ProjectRoot"
Write-Host "  rebuild.tcl  : $RebuildScript"
Write-Host "  stop after   : $StopAfter"
Write-Host "  log          : $log"

$env:VAC_STOP_AFTER = $StopAfter
if ($Part) { $env:VAC_PART = $Part }
if ($Top) { $env:VAC_TOP = $Top }
if ($Jobs -gt 0) { $env:VAC_JOBS = "$Jobs" }
if ($Reuse) { $env:VAC_REUSE = '1' }

& $vivadoExe -mode batch -source $RebuildScript -nojournal -log $log
$code = $LASTEXITCODE
$elapsed = (Get-Date) - $started

Write-Host ""
Write-Host ("Vivado 退出码: {0}，耗时 {1:N1} 分钟" -f $code, $elapsed.TotalMinutes)

if (-not $SkipLint -and (Test-Path $log)) {
    $checker = Join-Path $PSScriptRoot 'check_build.py'
    if ((Test-Path $checker) -and (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "--- 日志门禁 (check_build.py) ---"
        & python $checker $log --manifest (Join-Path $ProjectRoot 'outputs\build_manifest.json')
        $lint = $LASTEXITCODE
        if ($lint -ne 0) {
            Write-Host "[BUILD FAILED] 构建日志含 ERROR / CRITICAL WARNING，退出码 $lint" -ForegroundColor Red
            exit $lint
        }
    } elseif (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "（未安装 python，跳过日志门禁；建议手动 grep -i CRITICAL build.log）" -ForegroundColor Yellow
    }
}

if ($code -ne 0) {
    Write-Host "[BUILD FAILED] 见 $log" -ForegroundColor Red
    exit $code
}

$bit = Join-Path $ProjectRoot 'outputs'
Write-Host "[BUILD OK] 产物目录: $bit" -ForegroundColor Green
exit 0
