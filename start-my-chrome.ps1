# Starts your own Chrome for the restock monitor, with DevTools open on this PC only.
#
#   powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
#
# Stores like CVS and Dick's refuse the monitor's own automated browsers but usually accept an
# ordinary Chrome. This opens a normal Chrome window with its own profile (kept in data\my-chrome),
# so your everyday Chrome, passwords and history are never touched. Leave the window open
# (minimizing is fine), then start or restart the monitor. It notices this Chrome by itself.
param([int]$Port = 9222)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Host "Chrome was not found. Install it from google.com/chrome, then run this again." -ForegroundColor Red
    exit 1
}

# Already running? Then there is nothing to start.
try {
    $null = Invoke-WebRequest "http://127.0.0.1:$Port/json/version" -UseBasicParsing -TimeoutSec 2
    Write-Host "Your monitor Chrome is already running on port $Port." -ForegroundColor Green
    Write-Host "If the monitor was started before it, restart the monitor so it picks it up."
    exit 0
} catch { }

$profile = Join-Path $PSScriptRoot "data\my-chrome"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=`"$profile`"",
    "--no-first-run",
    "--no-default-browser-check"
)

for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-WebRequest "http://127.0.0.1:$Port/json/version" -UseBasicParsing -TimeoutSec 2
        Write-Host "Chrome is ready on port $Port (this PC only)." -ForegroundColor Green
        Write-Host "Leave it open, then start the monitor:  powershell -ExecutionPolicy Bypass -File .\run.ps1"
        exit 0
    } catch { }
}
Write-Host "Chrome opened but DevTools did not answer on port $Port. Close that Chrome window and run this again." -ForegroundColor Red
exit 1
