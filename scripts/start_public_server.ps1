param(
  [switch]$SkipDeploy
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$workDir = Join-Path $env:LOCALAPPDATA 'rural-broadcast'
if (-not (Test-Path $workDir)) {
  New-Item -ItemType Directory -Path $workDir | Out-Null
}

$cloudflared = Join-Path $workDir 'cloudflared.exe'
if (-not (Test-Path $cloudflared)) {
  Write-Host '下載 cloudflared…'
  Invoke-WebRequest `
    -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' `
    -OutFile $cloudflared
}

$backendOut = Join-Path $workDir 'backend.out.log'
$backendErr = Join-Path $workDir 'backend.err.log'
$listen = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $listen) {
  Write-Host '啟動本機後端 http://127.0.0.1:8000 …'
  Start-Process `
    -FilePath 'python' `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--app-dir', 'backend') `
    -WorkingDirectory $root `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru | Out-Null
  Start-Sleep -Seconds 6
} else {
  Write-Host '本機後端已在執行。'
}

$tunnelOut = Join-Path $workDir 'tunnel.out.log'
$tunnelErr = Join-Path $workDir 'tunnel.err.log'
Write-Host '啟動 Cloudflare Tunnel…'
$tunnel = Start-Process `
  -FilePath $cloudflared `
  -ArgumentList @('tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8000') `
  -RedirectStandardOutput $tunnelOut `
  -RedirectStandardError $tunnelErr `
  -PassThru

$url = $null
for ($i = 0; $i -lt 60; $i++) {
  $logs = @()
  foreach ($file in @($tunnelOut, $tunnelErr)) {
    if (Test-Path $file) {
      $logs += Get-Content $file -Raw -ErrorAction SilentlyContinue
    }
  }
  $match = [regex]::Match(($logs -join "`n"), 'https://[a-z0-9-]+\.trycloudflare\.com')
  if ($match.Success) {
    $url = $match.Value
    break
  }
  Start-Sleep -Seconds 1
}

if (-not $url) {
  throw '找不到 Tunnel 網址，請檢查 tunnel.err.log。'
}

Write-Host ''
Write-Host "公開 API 網址：$url"
Write-Host "Cloudflare 進程 ID：$($tunnel.Id)"

if (-not $SkipDeploy) {
  gh variable set API_BASE --repo ZYZ17/rural-sustainability-broadcast --body $url
  gh workflow run deploy-pages.yml --repo ZYZ17/rural-sustainability-broadcast
  Write-Host '已更新 GitHub Pages 設定並觸發部署。'
}

Write-Host ''
Write-Host '請保持此電腦、後端與 tunnel 進程开启；關閉後公開網址會失效。'
