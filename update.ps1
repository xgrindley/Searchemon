# Updates the program files from GitHub (https://github.com/xgrindley/Searchemon).
#
#   .\update.ps1                  install the newest STABLE release (the main branch)
#   .\update.ps1 -Channel test    install the newest test build (the test branch)
#   .\update.ps1 -Channel test/ui-redesign   a specific test branch
#   .\update.ps1 -Channel v1.0    an exact release or test tag
#
# Your config.yaml, data folder and .venv are never touched. A snapshot of the current
# files is saved first (see versions.ps1), so .\versions.ps1 restore undoes an update.
param([string]$Channel = "main")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$repo = "xgrindley/Searchemon"
if ($Channel -eq "stable") { $Channel = "main" }

if (Test-Path ".\versions.ps1") {
    & powershell -ExecutionPolicy Bypass -File .\versions.ps1 save "Before updating to $Channel"
}

$tmp = Join-Path $env:TEMP ("searchemon-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"
# A version like v1.2 is looked up as a tag, then as a saved-build branch (build/v1.2 or release/v1.0).
if ($Channel -match '^v\d+(\.\d+)*$') {
    $candidates = @("refs/tags/$Channel", "refs/heads/build/$Channel", "refs/heads/release/$Channel")
} else {
    $candidates = @("refs/heads/$Channel")
}
Write-Host "Downloading $Channel ..."
$ok = $false
foreach ($ref in $candidates) {
    try {
        Invoke-WebRequest -Uri "https://github.com/$repo/archive/$ref.zip" -OutFile $zip -UseBasicParsing
        $ok = $true
        break
    } catch { }
}
if (-not $ok) {
    Write-Host "Could not download '$Channel'. Check the name (try .\update.ps1 -Channel test) and your connection." -ForegroundColor Red
    Remove-Item $tmp -Recurse -Force
    exit 1
}
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
if (-not (Test-Path (Join-Path $src.FullName "app.py"))) {
    Write-Host "'$Channel' has no program files yet, so nothing was changed." -ForegroundColor Red
    if ($Channel -eq "main") {
        Write-Host "No stable release has been published yet. Use  -Channel test  until one is." -ForegroundColor Red
    }
    Remove-Item $tmp -Recurse -Force
    exit 1
}

$items = @("app.py", "restock", "tests", "requirements.txt", "config.example.yaml", "README.md",
           "VERSION", "CHANGELOG.md", "NOTES.md", "RESOURCES.md", "RELEASING.md",
           "setup.ps1", "run.ps1", "versions.ps1", "update.ps1", "add-to-startup.ps1", "build-exe.ps1", "start-my-chrome.ps1")
foreach ($i in $items) {
    $from = Join-Path $src.FullName $i
    if (-not (Test-Path $from)) { continue }
    if ((Test-Path $i -PathType Container)) { Remove-Item $i -Recurse -Force }
    Copy-Item $from -Destination . -Recurse -Force
}
Remove-Item $tmp -Recurse -Force
$v = (Get-Content VERSION -Raw).Trim()
Write-Host "Now on v$v ($Channel). Your settings and data were not touched." -ForegroundColor Green
Write-Host "Run  powershell -ExecutionPolicy Bypass -File .\setup.ps1  once, then  .\run.ps1"
