# Learns a store's own data requests from your own browsing, so the monitor can use the same request the store's page uses.
#
#   powershell -ExecutionPolicy Bypass -File .\learn-traffic.ps1 -Site gamestop -Zip 89436 -ProductId 123456
#
# 1. Start your own Chrome first:  powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
# 2. Run this script, then in that Chrome open the product page and use the store's "check nearby stores"
#    box with your ZIP. It listens for the data requests the page makes (no cookies or headers are kept,
#    token-like values are blanked, and nothing leaves this PC).
# 3. The best replayable requests are saved to data\learned\endpoints.json and the monitor tries them first.
#    The full recording is saved next to it; look it over before sharing it, it can contain your ZIP and store names.
param(
    [string]$Site = "gamestop",
    [string]$Zip = "",
    [string]$ProductId = "",
    [string]$Radius = "",
    [int]$Seconds = 180,
    [int]$Port = 9222
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Run setup.ps1 first." -ForegroundColor Red
    exit 1
}
& $python -m restock.learn --site $Site --zip $Zip --pid $ProductId --radius $Radius --seconds $Seconds --port $Port --save
