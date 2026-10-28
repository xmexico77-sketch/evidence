# 把本地仓库推送到 GitHub（含作者信息统一改写）
#
# 用法：
#   pwsh -File scripts/push_github.ps1 -RepoUrl https://github.com/<你的账号>/evidence.git -Email <你的邮箱>
#
# 可选参数：
#   -Name      作者名，默认「彭嘉荣」
#   -NoRewrite 不改写历史作者（默认会改写，让 41 次提交的作者一致）
#   -DryRun    只打印将要执行的命令，不实际执行
#
# 它做五件事：
#   1. 设置仓库级 user.name / user.email
#   2. 把历史提交的作者统一改写成上面两项（哈希会变，内容不变）
#   3. 清掉 filter-branch 留下的备份引用
#   4. 设置 remote 并把分支改名 main
#   5. push，然后打印作者、提交数、状态做核对
#
# 注意：作者改写只影响本地，GitHub 上还没有任何提交，所以不存在冲突。

param(
  [Parameter(Mandatory = $true)][string]$RepoUrl,
  [Parameter(Mandatory = $true)][string]$Email,
  [string]$Name = "彭嘉荣",
  [switch]$NoRewrite,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$gitCandidates = @("git")
$gitCandidates += "D:\deepseek\tools\git\cmd\git.exe"
$git = $null
foreach ($c in $gitCandidates) {
  try { & $c --version > $null 2>&1; $git = $c; break } catch { }
}
if (-not $git) { Write-Host "找不到 git" -ForegroundColor Red; exit 1 }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Run([string[]]$args_, [switch]$AllowFail) {
  $pretty = "$git " + ($args_ -join " ")
  if ($DryRun) { Write-Host "  [dry] $pretty" -ForegroundColor DarkGray; return }
  & $git @args_
  if (-not $AllowFail -and $LASTEXITCODE -ne 0) {
    throw "命令失败：$pretty"
  }
}

Write-Host "仓库：$root" -ForegroundColor Cyan
Write-Host "远程：$RepoUrl" -ForegroundColor Cyan
Write-Host ("作者：" + $Name + " / " + $Email) -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/5] 设置作者信息" -ForegroundColor Cyan
Run @("config", "user.name", $Name)
Run @("config", "user.email", $Email)

if (-not $NoRewrite) {
  Write-Host "[2/5] 统一历史提交的作者（哈希会变）" -ForegroundColor Cyan
  $env:FILTER_BRANCH_SQUELCH_WARNING = "1"
  $env:GIT_AUTHOR_NAME = $Name
  $env:GIT_AUTHOR_EMAIL = $Email
  $env:GIT_COMMITTER_NAME = $Name
  $env:GIT_COMMITTER_EMAIL = $Email
  $filter = "export GIT_AUTHOR_NAME='$Name'; export GIT_AUTHOR_EMAIL='$Email';" +
            " export GIT_COMMITTER_NAME='$Name'; export GIT_COMMITTER_EMAIL='$Email'"
  Run @("filter-branch", "-f", "--env-filter", $filter, "--", "--all") -AllowFail

  Write-Host "[3/5] 清理 filter-branch 备份引用" -ForegroundColor Cyan
  Run @("update-ref", "-d", "refs/original/refs/heads/main") -AllowFail
  Run @("for-each-ref", "--format=%(refname)", "refs/original") -AllowFail | Out-Null
} else {
  Write-Host "[2/5] 跳过作者改写（-NoRewrite）" -ForegroundColor Yellow
  Write-Host "[3/5] 跳过备份清理" -ForegroundColor Yellow
}

Write-Host "[4/5] 配置远程与分支" -ForegroundColor Cyan
$existing = & $git remote 2>$null
if ($existing -contains "origin") {
  Run @("remote", "set-url", "origin", $RepoUrl)
} else {
  Run @("remote", "add", "origin", $RepoUrl)
}
Run @("branch", "-M", "main")

Write-Host "[5/5] 推送" -ForegroundColor Cyan
Write-Host "  提示：首次推送会要求登录。用 Personal Access Token 作为密码，" -ForegroundColor Yellow
Write-Host "        不是 GitHub 账号密码。Token 需要 repo 权限。" -ForegroundColor Yellow
Run @("push", "-u", "origin", "main")

if (-not $DryRun) {
  Write-Host ""
  Write-Host "=== 核对 ===" -ForegroundColor Green
  Write-Host "远程地址："
  & $git remote -v
  Write-Host "提交作者："
  & $git log --format="%an <%ae>" | Sort-Object -Unique
  Write-Host ("提交数：" + (& $git rev-list --count HEAD))
  Write-Host "工作区："
  & $git status --short
  Write-Host ""
  Write-Host "推送完成。请到 GitHub 页面确认：仓库公开、提交历史可见、README 能正常渲染。" -ForegroundColor Green
}
