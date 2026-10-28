# 一键启动"公网演示"环境
#
# 做三件事：起后端（启用认证）→ 起前端 → 开 Cloudflare 快速隧道
# 结束后终端会打印 trycloudflare.com 的公网地址。
#
# 用法（在项目根目录）：
#   pwsh -File scripts/start_public.ps1
#
# 凭据从 .cache/deploy-creds.txt 读取（该文件不入库）：
#   reviewer=<密码>
#   secret=<会话密钥>
#
# 注意：快速隧道**不需要 Cloudflare 账号**，但地址每次重启都会变，
# 且没有可用性保证。评审期长期使用请改用命名隧道（见 docs/部署手册.md）。

param(
  [int]$ApiPort = 8000,
  [int]$WebPort = 3001,
  [string]$CredFile = ".cache/deploy-creds.txt"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path $CredFile)) {
  Write-Host "缺少凭据文件 $CredFile" -ForegroundColor Red
  Write-Host "请先创建，内容两行：`n  reviewer=<密码>`n  secret=<会话密钥>" -ForegroundColor Yellow
  exit 1
}

$cred = @{}
Get-Content $CredFile | ForEach-Object {
  if ($_ -match "^\s*([^=]+)=(.*)$") { $cred[$matches[1].Trim()] = $matches[2].Trim() }
}
$pwd_ = $cred["reviewer"]
$secret = $cred["secret"]
if (-not $pwd_ -or -not $secret) {
  Write-Host "凭据文件格式不对，应为 reviewer=... 与 secret=..." -ForegroundColor Red
  exit 1
}

Write-Host "[1/3] 启动后端（启用认证，端口 $ApiPort）" -ForegroundColor Cyan
$env:AUTH_ENABLED = "1"
$env:EVIDENCE_USERS = "reviewer:$pwd_,demo:$pwd_"
$env:EVIDENCE_SECRET = $secret
Start-Process -WindowStyle Hidden -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$ApiPort","--app-dir","$root\backend" `
  -WorkingDirectory $root
Start-Sleep -Seconds 18

Write-Host "[2/3] 启动前端（端口 $WebPort）" -ForegroundColor Cyan
$node = "D:\deepseek\github工具使用与下载\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
if (-not (Test-Path $node)) {
  $node = (Get-Command node -ErrorAction SilentlyContinue).Source
}
Start-Process -WindowStyle Hidden -FilePath $node `
  -ArgumentList "node_modules\next\dist\bin\next","start","-p","$WebPort" `
  -WorkingDirectory "$root\web"
Start-Sleep -Seconds 12

Write-Host "[3/3] 打开 Cloudflare 快速隧道（公网地址见下）" -ForegroundColor Cyan
$cf = "$root\.cache\cf\cloudflared.exe"
if (-not (Test-Path $cf)) {
  Write-Host "缺少 cloudflared：$cf" -ForegroundColor Red
  Write-Host "下载：https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -ForegroundColor Yellow
  exit 1
}

Write-Host ""
Write-Host "评审账号：reviewer / $pwd_" -ForegroundColor Green
Write-Host "本机地址：http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host "公网地址：见下面输出中的 https://*.trycloudflare.com" -ForegroundColor Green
Write-Host "验证：.venv\Scripts\python.exe scripts\check_deploy.py <公网地址> --user reviewer --password '$pwd_'" -ForegroundColor Green
Write-Host ""

& $cf tunnel --url "http://localhost:$WebPort" --no-autoupdate
