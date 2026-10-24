# 证源 Evidence · 本地一键启动（Windows / PowerShell）
#
# 用法：
#   .\scripts\start.ps1            # 启动前后端
#   .\scripts\start.ps1 -Rebuild   # 先重建前端再启动
#
# 前提：已按 README 建好 .venv 与 web/node_modules

param(
    [switch]$Rebuild,
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$node = "node"

if (-not (Test-Path $python)) {
    Write-Error "找不到 $python，请先按 README 创建虚拟环境"
}

if (-not (Test-Path (Join-Path $root "web\node_modules"))) {
    Write-Error "前端依赖未安装，请在 web 目录执行 pnpm install"
}

if ($Rebuild) {
    Write-Host "重建前端..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "web")
    & $node "node_modules\next\dist\bin\next" build
    Pop-Location
}

Write-Host "启动后端 :$ApiPort ..." -ForegroundColor Cyan
$api = Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--app-dir", "$root\backend" `
    -WorkingDirectory $root -PassThru

Start-Sleep -Seconds 8

Write-Host "启动前端 :$WebPort ..." -ForegroundColor Cyan
$web = Start-Process -FilePath $node `
    -ArgumentList "node_modules\next\dist\bin\next", "start", "-p", "$WebPort" `
    -WorkingDirectory (Join-Path $root "web") -PassThru

Start-Sleep -Seconds 6

Write-Host ""
Write-Host "  前端  http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host "  后端  http://127.0.0.1:$ApiPort/docs" -ForegroundColor Green
Write-Host ""
Write-Host "按 Ctrl+C 停止" -ForegroundColor DarkGray

try {
    Wait-Process -Id $api.Id, $web.Id
} finally {
    foreach ($p in @($api, $web)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
}
