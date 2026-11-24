param(
  [string]$ApiBase = ''
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$site = Join-Path $env:TEMP 'rural-broadcast-gh-pages'
if (Test-Path $site) {
  Remove-Item -Recurse -Force $site
}
New-Item -ItemType Directory -Path $site | Out-Null

Copy-Item (Join-Path $root 'frontend/index.html') (Join-Path $site 'index.html')
Copy-Item (Join-Path $root 'frontend/src') (Join-Path $site 'src') -Recurse
Get-ChildItem (Join-Path $root 'frontend/public') -Force | Copy-Item -Destination $site -Recurse -Force

$indexPath = Join-Path $site 'index.html'
$html = Get-Content $indexPath -Raw -Encoding UTF8
$apiBase = $ApiBase.TrimEnd('/')
$html = $html.Replace('__API_BASE__', $apiBase)
Set-Content -Path $indexPath -Value $html -Encoding UTF8 -NoNewline

if ($apiBase) {
  $configPath = Join-Path $site 'data/api_config.json'
  @{ api_base = $apiBase } | ConvertTo-Json -Compress | Set-Content -Path $configPath -Encoding UTF8 -NoNewline
}

Push-Location $site
try {
  git init -q
  git checkout -q -b gh-pages
  git remote add origin 'https://github.com/ZYZ17/rural-sustainability-broadcast.git'
  git add -A
  git -c user.name='rural-broadcast-bot' -c user.email='bot@users.noreply.github.com' commit -q -m 'Deploy site with live API'
  git push -q --force origin gh-pages
} finally {
  Pop-Location
}

Write-Host "已部署到 GitHub Pages 分支： gh-pages (API_BASE=$ApiBase)"
