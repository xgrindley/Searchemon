# Starts your own Edge for the restock monitor, with DevTools open on this PC only.
#
#   powershell -ExecutionPolicy Bypass -File .\start-my-edge.ps1
#
# A second real browser to test beside your own Chrome (see start-my-chrome.ps1). Some stores
# accept one and not the other, and the Methods lab shows which.
# This opens a normal Edge window with its own profile (kept in data\my-edge),
# so your everyday Edge, passwords and history are never touched. Leave the window open
# (minimizing is fine). The monitor notices this Edge by itself within seconds, whether it was
# started before or after the monitor.
param([int]$Port = 9223)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$candidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
)
$edge = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) {
    Write-Host "Edge was not found. It comes with Windows 10 and 11, so check that it is installed, then run this again." -ForegroundColor Red
    exit 1
}

# Already running? Then there is nothing to start.
try {
    $null = Invoke-WebRequest "http://127.0.0.1:$Port/json/version" -UseBasicParsing -TimeoutSec 2
    Write-Host "Your monitor Edge is already running on port $Port." -ForegroundColor Green
    exit 0
} catch { }

$profile = Join-Path $PSScriptRoot "data\my-edge"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
Start-Process -FilePath $edge -ArgumentList @(
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
        Write-Host "Edge is ready on port $Port (this PC only)." -ForegroundColor Green
        Write-Host "Leave it open. The monitor picks it up within seconds (start the monitor with .\run.ps1 if it is not running)."
        exit 0
    } catch { }
}
Write-Host "Edge opened but DevTools did not answer on port $Port. Close that Edge window and run this again." -ForegroundColor Red
exit 1
